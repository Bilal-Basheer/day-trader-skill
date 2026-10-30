#!/usr/bin/env python3
"""The Pakistan Stock Exchange tool for trader-psx. Standard library only.

    python3 psx.py clock                                  # is the PSX open? (Pakistan time)
    python3 psx.py scan                                   # daily setups -> trader/psx_watchlist.json
    python3 psx.py scan --symbols OGDC,HBL --show 10
    python3 psx.py news --tickers OGDC,HBL --hours 24     # Pakistani business RSS feeds
    python3 psx.py plan OGDC --entry 306.50 --stop pct:2 --target 1R --write
    python3 psx.py size --write                           # -> trader/psx_orders.json
    python3 psx.py check                                  # PASS / BLOCK
    python3 psx.py ticket                                 # the ticket to type into your broker's app
    python3 psx.py record                                 # log it once you have placed it

  Intraday, these need a pyPSX key (see SKILL.md):
    python3 psx.py intraday OGDC                          # today's 5-minute candles and how old they are
    python3 psx.py orb --symbols OGDC,HBL --at 10:15      # opening-range breakouts so far
    python3 psx.py entry OGDC                             # waiting / triggered / expired
    python3 psx.py history OGDC --days 60 --target 1R     # the same rule on past sessions

Data, and why these and no others:

  Yahoo chart JSON (SYMBOL.KA)  daily bars only. Yahoo answers a 5-minute request for
                                a Karachi symbol with daily bars, so nothing here is
                                intraday. Yahoo's meta price for these symbols is years
                                old (regularMarketTime 2024-07-24 for OGDC when this was
                                written), so prices come from the bars, never the meta.
  RSS feeds                     Business Recorder, Dawn, Express Tribune, ProPakistani.
  pyPSX API, with your own key  5-minute candles, read only (GET). Its docs state no delay
                                figure and no PSX licence, so every candle's age is printed.

  dps.psx.com.pk is deliberately not read. Its terms ban "spiders, robots, avatars,
  agents, tools" without PSX's written permission, and market data licences go through
  marketdatarequest@psx.com.pk.

It never places an order. Every "order" here is a ticket a person types into a broker's
app. Rules that could not be confirmed against a current PSX notice live in the config
so you can correct them: see psx_config.example.json and SKILL.md.
"""

import argparse
import datetime
import email.utils
import html
import json
import math
import os
import re
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

UA = "Mozilla/5.0 (compatible; day-trader-skill-psx/1.0; personal research tool)"
HOSTS = ("https://query2.finance.yahoo.com", "https://query1.finance.yahoo.com")
PAUSE = 0.3          # seconds between requests: be polite to free endpoints
BACKOFF = 5.0        # seconds to wait before the one retry after a 429
SLEEP = time.sleep   # tests swap this out
MAX_BYTES = 8 * 1024 * 1024
PKT = datetime.timedelta(hours=5)  # Pakistan keeps UTC+5 all year
MIN_BARS = 30
STALE_DAYS = 7       # a last bar older than this is a dead or suspended chart
ATR_BARS = 14
NOTE = "A scan is a list of charts that match a rule, not a list of stocks to buy."

HERE = os.path.dirname(os.path.abspath(__file__))
UNIVERSE = os.path.join(HERE, "psx_universe.txt")
CONFIG = "trader/psx_config.json"
WATCHLIST = "trader/psx_watchlist.json"
PLAN = "trader/psx_plan.json"
ORDERS = "trader/psx_orders.json"
NEWS_STATE = "trader/state/psx_news.json"
RISK_STATE = "trader/state/psx_risk.json"
TRADES_STATE = "trader/state/psx_trades.json"
ORB_FILE = "trader/psx_orb.json"
ENTRY_FILE = "trader/psx_entry.json"

# Sandbox host on purpose: this tool only reads market data and has no use for live accounts.
PYPSX_BASE = "https://paper-api.pypsx.com"
PYPSX_PAUSE = 1.1    # the docs allow bursts of 20, then 1 request a second per key
PYPSX_BATCH = 20
BAR_MINUTES = 5

# psx.com.pk/psx/exchange/general/trading-hours, regular market, read 2026-10-30.
# Ramadan and other changes go in the config as session_overrides.
MON_THU = (("09:32", "15:30"),)
FRIDAY = (("09:17", "12:00"), ("14:32", "16:30"))

# Only closures with a notice found on 2026-10-30. Moon-dependent dates are announced
# late, so add yours under "holidays" in the config. Nothing confirmed yet past this list.
HOLIDAYS = {
    "2026-02-05": "Kashmir Solidarity Day",
    "2026-05-01": "Labour Day",
    "2026-05-26": "Eid-ul-Azha",
    "2026-05-27": "Eid-ul-Azha",
    "2026-05-28": "Eid-ul-Azha",
    "2026-06-25": "Ashura",
    "2026-06-26": "Ashura",
    "2026-08-14": "Independence Day",
    "2026-08-26": "Eid Milad-un-Nabi",
}

DEFAULTS = {
    "budget_pkr": 500000,
    "cash_buffer_pct": 10,
    "max_position_pct": 50,
    "max_loss_per_trade_pkr": 5000,
    "max_daily_loss_pkr": 15000,
    "max_trades_per_day": 3,
    "min_reward_risk": 1.0,
    "price_band_pct": 10,        # most stocks, per kasb.com (June 2025): check your stock's band
    "roundtrip_cost_pct": 0.0,   # your broker's commission and levies, both ways: set this
    "no_entries_first_minutes": 15,
    "no_entries_last_minutes": 30,
    "flat_by_minutes": 5,
    "blocked": [],
    "holidays": {},
    "session_overrides": {},
}

SETUPS = [
    ("breakout_20d", "20-day closing-high breakout"),
    ("bull_flag", "bull flag"),
    ("reclaim_ma20", "reclaimed the 20-day average"),
    ("oversold", "oversold (RSI under 30)"),
    ("oversold_bounce", "oversold bounce"),
]
LABEL = dict(SETUPS)

FEEDS = (
    ("Business Recorder", "https://www.brecorder.com/feeds/markets"),
    ("Dawn", "https://www.dawn.com/feeds/business"),
    ("Express Tribune", "https://tribune.com.pk/feed/business"),
    ("ProPakistani", "https://propakistani.pk/category/business/feed/"),
)
MARKET_WORDS = re.compile(r"\b(PSX|KSE[- ]?(?:100|30)|SECP|SBP|State Bank|policy rate|bourse|stock exchange|IMF)\b", re.I)
# short tickers that are also ordinary words or other things in headlines
AMBIGUOUS = {"POL", "PTC", "MTL", "UNITY", "AGP", "ILP", "NCL", "NML", "TGL", "SYS", "BOP", "ABL", "SEARL"}
TRAILING = {"limited", "ltd", "ltd.", "company", "co", "co.", "pakistan", "pk"}
# names too generic to match on once the suffix is gone
ALIASES = {"SYS": "Systems Limited", "NBP": "National Bank", "PTC": "PTCL", "AGP": "AGP Limited", "TRG": "TRG Pakistan"}
TAGS = (
    ("earnings", r"\b(earnings|profit|loss|EPS|results?|dividend|payout|bonus)\b"),
    ("macro", r"\b(SBP|State Bank|policy rate|inflation|IMF|rupee|budget|current account|remittances?)\b"),
    ("regulatory", r"\b(SECP|regulator|OGRA|NEPRA|PTA|licen[cs]e)\b"),
    ("deal", r"\b(merger|acquisition|acquires?|stake|takeover|privati[sz]ation)\b"),
    ("capital", r"\b(rights? issue|IPO|offering|sukuk|bond)\b"),
    ("halt", r"\b(halt(?:ed)?|suspend(?:ed)?|circuit breaker|defaulter)\b"),
    ("legal", r"\b(court|lawsuit|fine[ds]?|penalty|NAB|FIA)\b"),
    ("people", r"\b(CEO|chairman|resign(?:s|ed)?|appoint(?:s|ed)?)\b"),
)


class PsxError(Exception):
    """One plain line for the user, no traceback."""


# ---------------------------------------------------------------- the clock

def utc_now():
    return datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None, microsecond=0)


def to_pkt(utc):
    return utc + PKT


def parse_now(text):
    """--now in Pakistan time -> naive UTC."""
    if not text:
        return utc_now()
    try:
        return datetime.datetime.strptime(text, "%Y-%m-%d %H:%M") - PKT
    except ValueError:
        raise PsxError('--now must look like "2026-10-30 10:15" (Pakistan time)')


def hm(text):
    return datetime.datetime.strptime(text, "%H:%M").time()


def holiday_name(d, cfg):
    key = d.isoformat()
    return cfg.get("holidays", {}).get(key) or HOLIDAYS.get(key)


def sessions_for(d, cfg):
    """[(open, close), ...] as times, empty on a closed day."""
    if d.weekday() >= 5 or holiday_name(d, cfg):
        return []
    override = cfg.get("session_overrides", {}).get(d.isoformat())
    spans = override if override else (FRIDAY if d.weekday() == 4 else MON_THU)
    return [(hm(a), hm(b)) for a, b in spans]


def calendar_gap(d, cfg):
    """A warning when the date is past the last holiday anyone has recorded."""
    known = list(HOLIDAYS) + list(cfg.get("holidays", {}))
    if d.isoformat() > max(known):
        return ("No PSX holiday is recorded after %s, so an unannounced closure would not show here. "
                "Add closures under \"holidays\" in %s." % (max(known), CONFIG))
    return None


def market_status(now_utc, cfg):
    now = to_pkt(now_utc)
    today, t = now.date(), now.time()
    spans = sessions_for(today, cfg)
    state, reason = "closed", ""
    if today.weekday() >= 5:
        reason = "weekend"
    elif holiday_name(today, cfg):
        reason = "holiday: " + holiday_name(today, cfg)
    elif t < spans[0][0]:
        reason = "before the open"
    elif t >= spans[-1][1]:
        reason = "after the close"
    else:
        for a, b in spans:
            if a <= t < b:
                state, reason = "open", "regular market"
        if state == "closed":
            reason = "midday break"
    nxt = None
    d = today
    for _ in range(15):
        for a, _b in sessions_for(d, cfg):
            if d > today or a > t:
                nxt = "%s %s" % (d.isoformat(), a.strftime("%H:%M"))
                break
        if nxt:
            break
        d += datetime.timedelta(days=1)
    return {"now_pkt": now.strftime("%Y-%m-%d %H:%M"), "weekday": now.strftime("%A"), "state": state,
            "reason": reason, "next_open": nxt,
            "today": ["%s to %s" % (a.strftime("%H:%M"), b.strftime("%H:%M")) for a, b in spans]}


def entry_window_block(now_utc, cfg):
    """A reason no new entry is allowed right now, or None."""
    now = to_pkt(now_utc)
    spans = sessions_for(now.date(), cfg)
    if not spans:
        return "the PSX is closed today (%s)" % (holiday_name(now.date(), cfg) or "weekend")
    first = datetime.timedelta(minutes=cfg["no_entries_first_minutes"])
    last = datetime.timedelta(minutes=cfg["no_entries_last_minutes"])
    for a, b in spans:
        start = datetime.datetime.combine(now.date(), a)
        stop = datetime.datetime.combine(now.date(), b)
        if start + first <= now < stop - last:
            return None
    return "%s is outside the entry window (%d minutes after each open to %d minutes before each close)" % (
        now.strftime("%H:%M"), cfg["no_entries_first_minutes"], cfg["no_entries_last_minutes"])


def flat_by(d, cfg):
    """The last moment to be out, the last session's close less a few minutes."""
    spans = sessions_for(d, cfg)
    if not spans:
        return None
    end = datetime.datetime.combine(d, spans[-1][1]) - datetime.timedelta(minutes=cfg["flat_by_minutes"])
    return end.strftime("%H:%M")


# ---------------------------------------------------------------- files

def read_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        if default is not None:
            return default
        raise PsxError("%s is missing" % path)
    except ValueError:
        raise PsxError("%s is not valid JSON" % path)


def write_json(path, doc):
    folder = os.path.dirname(path)
    if folder:
        os.makedirs(folder, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=2)
        fh.write("\n")
    os.replace(tmp, path)


def load_config(path=CONFIG):
    cfg = dict(DEFAULTS)
    cfg.update(read_json(path, {}))
    return cfg


def read_universe(path=UNIVERSE):
    """[(symbol, name)] from SYMBOL|Name lines."""
    out = []
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line and not line.startswith("#"):
                    sym, _, name = line.partition("|")
                    out.append((clean_symbol(sym), name.strip()))
    except FileNotFoundError:
        raise PsxError("%s is missing" % path)
    return out


def clean_symbol(sym):
    s = sym.strip().upper()
    if s.endswith(".KA"):
        s = s[:-3]
    if not re.match(r"^[A-Z0-9]{1,10}$", s):
        raise PsxError("%r does not look like a PSX symbol" % sym)
    return s


def symbol_list(text):
    return [clean_symbol(s) for s in re.split(r"[,\s]+", text) if s.strip()]


# ---------------------------------------------------------------- the network

def ssl_context():
    """Verified TLS always. python.org builds on macOS ship with no CA store until
    "Install Certificates.command" is run, so fall back to the system bundle."""
    ctx = ssl.create_default_context()
    if not ctx.cert_store_stats().get("x509_ca") and os.path.exists("/etc/ssl/cert.pem"):
        ctx.load_verify_locations("/etc/ssl/cert.pem")
    return ctx


def http_get(url, timeout=25):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout, context=ssl_context()) as resp:
        return resp.read(MAX_BYTES)


def yahoo_get(path):
    """query2, then query1 on a 429 or 5xx, one retry after a wait on a 429."""
    last = "no answer"
    waited = False
    hosts = list(HOSTS)
    while hosts:
        host = hosts.pop(0)
        try:
            return http_get(host + path)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                raise PsxError("Yahoo has no chart for this symbol (404)")
            last = "HTTP %d" % e.code
            if e.code == 429 and not waited:
                waited = True
                SLEEP(BACKOFF)
                hosts.insert(0, host)
            elif e.code != 429 and e.code < 500:
                break
        except (urllib.error.URLError, OSError) as e:
            last = str(getattr(e, "reason", e))
    raise PsxError("could not read Yahoo: %s" % last)


def parse_bars(text_or_doc, now_utc, cfg, sym=""):
    """Yahoo chart JSON -> complete daily bars, oldest first. The meta block is ignored
    on purpose: its price for Karachi symbols is stale, the bars are not."""
    doc = json.loads(text_or_doc) if isinstance(text_or_doc, (str, bytes)) else text_or_doc
    chart = (doc or {}).get("chart") or {}
    results = chart.get("result") or []
    if not results:
        raise PsxError("Yahoo has no data for %s" % sym)
    res = results[0]
    granularity = (res.get("meta") or {}).get("dataGranularity")
    if granularity not in (None, "1d"):
        raise PsxError("expected daily bars for %s, got %s" % (sym, granularity))
    quotes = ((res.get("indicators") or {}).get("quote") or [{}])[0]
    now = to_pkt(now_utc)
    spans = sessions_for(now.date(), cfg)
    today_done = not spans or now.time() >= spans[-1][1]
    out = {}
    for i, ts in enumerate(res.get("timestamp") or []):
        vals = [(quotes.get(k) or [None] * (i + 1))[i] for k in ("open", "high", "low", "close", "volume")]
        if None in vals[:4]:
            continue
        d = (datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).replace(tzinfo=None) + PKT).date()
        if d > now.date() or (d == now.date() and not today_done):
            continue
        out[d] = {"date": d.isoformat(), "open": float(vals[0]), "high": float(vals[1]), "low": float(vals[2]),
                  "close": float(vals[3]), "volume": int(vals[4] or 0)}
    return [out[d] for d in sorted(out)]


def get_bars(sym, now_utc, cfg, offline=None, rng="6mo"):
    if offline:
        path = os.path.join(offline, sym + ".json")
        try:
            with open(path, encoding="utf-8") as fh:
                return parse_bars(fh.read(), now_utc, cfg, sym)
        except FileNotFoundError:
            raise PsxError("no offline file for %s" % sym)
    text = yahoo_get("/v8/finance/chart/%s.KA?range=%s&interval=1d" % (sym, rng))
    return parse_bars(text, now_utc, cfg, sym)


# ---------------------------------------------------------------- setups (the rules in trader-scanner)

def rsi(closes, n=14):
    if len(closes) < n + 1:
        return None
    g = [max(0.0, closes[i] - closes[i - 1]) for i in range(1, len(closes))]
    lo = [max(0.0, closes[i - 1] - closes[i]) for i in range(1, len(closes))]
    ag, al = sum(g[:n]) / n, sum(lo[:n]) / n
    for i in range(n, len(g)):
        ag = (ag * (n - 1) + g[i]) / n
        al = (al * (n - 1) + lo[i]) / n
    return 100 - 100 / (1 + ag / al) if al else 100.0


def find_setups(closes):
    """closes (oldest first, >= 30) -> (setup keys, rsi)."""
    c = closes
    last = c[-1]
    hi20 = max(c[-21:-1])
    ma20 = sum(c[-20:]) / 20.0
    ma20_prev = sum(c[-21:-1]) / 20.0
    run = c[-6] / c[-16] - 1
    rng5 = (max(c[-5:]) - min(c[-5:])) / last
    r = rsi(c)
    r_prev = rsi(c[:-1])
    tags = []
    if last > hi20:
        tags.append("breakout_20d")
    if run > 0.10 and rng5 < 0.05:
        tags.append("bull_flag")
    if c[-2] < ma20_prev and last > ma20:
        tags.append("reclaim_ma20")
    if r is not None and r < 30:
        tags.append("oversold")
    if r_prev is not None and r_prev < 30 and last > c[-2]:
        tags.append("oversold_bounce")
    return tags, r


def atr(bars, n=ATR_BARS):
    """Average true range, from daily bars."""
    if len(bars) < n + 1:
        return None
    trs = []
    for prev, b in zip(bars[-n - 1:-1], bars[-n:]):
        trs.append(max(b["high"] - b["low"], abs(b["high"] - prev["close"]), abs(b["low"] - prev["close"])))
    return sum(trs) / n


def scan(symbols, fetch, now_utc, min_price, min_volume):
    """Pure but for fetch(sym) -> bars. Returns (hits, counts, last_date)."""
    today = to_pkt(now_utc).date()
    hits, dates = [], {}
    counts = {"requested": len(symbols), "fetched": 0, "failed": 0, "stale": 0, "illiquid": 0, "short": 0, "scanned": 0}
    for sym in symbols:
        try:
            bars = fetch(sym)
        except PsxError:
            counts["failed"] += 1
            continue
        if not bars:
            counts["failed"] += 1
            continue
        counts["fetched"] += 1
        last = bars[-1]
        if (today - datetime.date.fromisoformat(last["date"])).days > STALE_DAYS:
            counts["stale"] += 1
            continue
        if last["close"] < min_price or last["volume"] < min_volume:
            counts["illiquid"] += 1
            continue
        if len(bars) < MIN_BARS:
            counts["short"] += 1
            continue
        counts["scanned"] += 1
        dates[last["date"]] = dates.get(last["date"], 0) + 1
        tags, r = find_setups([b["close"] for b in bars])
        if tags:
            hits.append({"symbol": sym, "setups": tags, "price": round(last["close"], 2), "close_date": last["date"],
                         "rsi": round(r, 1) if r is not None else None, "volume": last["volume"]})
    hits.sort(key=lambda h: (-(h["price"] * h["volume"]), h["symbol"]))  # most rupees traded first
    counts["hits"] = len(hits)
    last_date = max(dates, key=lambda d: (dates[d], d)) if dates else None
    return hits, counts, last_date


# ---------------------------------------------------------------- news

def local(tag):
    return tag.split("}")[-1]


def parse_feed(data, source):
    """RSS or Atom bytes -> [{source, title, link, utc}]. ElementTree does not fetch
    external entities, and a broken feed is simply no items."""
    try:
        root = ET.fromstring(data)
    except ET.ParseError:
        return []
    items = []
    for node in root.iter():
        if local(node.tag) not in ("item", "entry"):
            continue
        title = link = stamp = None
        for child in node:
            name = local(child.tag)
            if name == "title":
                title = html.unescape((child.text or "").strip())
            elif name == "link":
                link = (child.text or child.get("href") or "").strip()
            elif name in ("pubDate", "published") or (name == "updated" and not stamp):
                stamp = (child.text or "").strip()
        if not title or not link:
            continue
        items.append({"source": source, "title": title, "link": link, "utc": parse_stamp(stamp)})
    return items


def parse_stamp(text):
    if not text:
        return None
    try:
        dt = email.utils.parsedate_to_datetime(text)
    except (TypeError, ValueError):
        try:
            dt = datetime.datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
    if dt.tzinfo is None:
        return dt
    return (dt - dt.utcoffset()).replace(tzinfo=None)


def name_key(name):
    """'Habib Bank Limited' -> 'Habib Bank'. A leading 'Pakistan' stays: 'Petroleum' alone
    would match every oil story."""
    words = name.split()
    if words and words[0].lower() == "the":
        words = words[1:]
    while words and words[-1].lower() in TRAILING:
        words = words[:-1]
    return " ".join(words)


def matchers(universe, tickers):
    """[(symbol, compiled)] for the tickers asked about."""
    names = dict(universe)
    out = []
    for sym in tickers:
        parts = []
        if len(sym) >= 3 and sym not in AMBIGUOUS:
            parts.append(r"(?-i:\b%s\b)" % re.escape(sym))
        key = ALIASES.get(sym) or name_key(names.get(sym, ""))
        if len(key) >= 4:
            parts.append(r"\b%s\b" % re.escape(key))
        if parts:
            out.append((sym, re.compile("|".join(parts), re.I)))
    return out


def tag_item(title):
    return [t for t, rx in TAGS if re.search(rx, title, re.I)]


def select_news(items, match, now_utc, hours, seen=None, market=True):
    """Newest first: items touching a ticker, plus market-wide ones, not seen before."""
    seen = seen or {}
    cutoff = now_utc - datetime.timedelta(hours=hours)
    out, links = [], set()
    for it in items:
        if it["link"] in seen or it["link"] in links:
            continue
        if it["utc"] is None or it["utc"] < cutoff or it["utc"] > now_utc + datetime.timedelta(hours=1):
            continue
        touches = [s for s, rx in match if rx.search(it["title"])]
        is_market = bool(MARKET_WORDS.search(it["title"]))
        if not touches and not (market and is_market):
            continue
        links.add(it["link"])
        out.append(dict(it, tickers=touches, market=is_market, tags=tag_item(it["title"])))
    out.sort(key=lambda i: i["utc"], reverse=True)
    return out


# ---------------------------------------------------------------- plan and size

def cents(x):
    return round(float(x) + 1e-9, 2)


def floor_cents(x):
    return math.floor(float(x) * 100 + 1e-6) / 100.0


def money(x):
    return "PKR {:,.2f}".format(x)


def band(prev_close, pct):
    return cents(prev_close * (1 - pct / 100.0)), cents(prev_close * (1 + pct / 100.0))


def parse_stop(text):
    m = re.match(r"^(atr|pct|price)(?::([0-9.]+))?$", text.lower())
    if not m or (m.group(1) != "atr" and not m.group(2)):
        raise PsxError('--stop must be atr, atr:1.5, pct:2 or price:295.50')
    return m.group(1), float(m.group(2)) if m.group(2) else 1.0


def parse_target(text):
    m = re.match(r"^([0-9.]+)r$", text.lower())
    if m:
        return "r", float(m.group(1))
    m = re.match(r"^price:([0-9.]+)$", text.lower())
    if m:
        return "price", float(m.group(1))
    raise PsxError("--target must be 1R, 1.5R, 2R or price:310")


def build_plan(sym, bars, stop_spec, target_spec, entry, cfg, now_utc):
    """Pure. Refuses anything that does not hold together."""
    if not bars:
        raise PsxError("no daily bars for %s" % sym)
    prev = bars[-1]
    estimate = entry is None
    entry = cents(prev["close"] if estimate else entry)
    if entry <= 0:
        raise PsxError("the entry must be above zero")
    low, high = band(prev["close"], cfg["price_band_pct"])
    if not low <= entry <= high:
        raise PsxError("entry %.2f is outside %s's %g%% band (%.2f to %.2f around the %s close of %.2f)" % (
            entry, sym, cfg["price_band_pct"], low, high, prev["date"], prev["close"]))
    rule, param = stop_spec
    if rule == "atr":
        a = atr(bars)
        if a is None:
            raise PsxError("not enough bars for an ATR on %s" % sym)
        stop = floor_cents(entry - a * param)
    elif rule == "pct":
        stop = floor_cents(entry * (1 - param / 100.0))
    else:
        stop = cents(param)
    if stop <= 0 or stop >= entry:
        raise PsxError("the stop %.2f must be below the entry %.2f" % (stop, entry))
    risk = entry - stop
    kind, value = target_spec
    target = cents(entry + risk * value) if kind == "r" else cents(value)
    if target <= entry:
        raise PsxError("the target %.2f must be above the entry %.2f" % (target, entry))
    cost = entry * cfg["roundtrip_cost_pct"] / 100.0
    net_rr = (target - entry - cost) / (risk + cost)
    today = to_pkt(now_utc).date()
    notes = []
    if estimate:
        notes.append("Entry is yesterday's close, an estimate: there is no free live PSX price here. "
                     "Pass --entry with the price on your broker's screen before /trader-psx check.")
    if target > high:
        notes.append("The target %.2f is above the %g%% band top %.2f, so it cannot trade today." % (
            target, cfg["price_band_pct"], high))
    if stop < low:
        notes.append("The stop %.2f is below the band floor %.2f, so a stop order there cannot fill today." % (stop, low))
    return {"market": "psx", "currency": "PKR", "symbol": sym, "side": "buy", "entry": entry,
            "entry_is_estimate": estimate, "stop": cents(stop), "target": target, "risk_per_share": cents(risk),
            "reward_risk": round((target - entry) / risk, 2), "reward_risk_after_costs": round(net_rr, 2),
            "prev_close": cents(prev["close"]), "prev_close_date": prev["date"], "band": [low, high],
            "flat_by": flat_by(today, cfg), "created_pkt": to_pkt(now_utc).strftime("%Y-%m-%d %H:%M"),
            "day": today.isoformat(), "notes": notes}


def size_order(plan, cfg):
    """Whole shares inside the max loss, the position cap and the cash after the buffer.
    PSX regular-market symbols trade in lots of one since 22 April 2024."""
    entry = plan["entry"]
    cost = entry * cfg["roundtrip_cost_pct"] / 100.0
    per_share = plan["entry"] - plan["stop"] + cost
    limits = {
        "max loss per trade": cfg["max_loss_per_trade_pkr"] / per_share,
        "position cap": cfg["budget_pkr"] * cfg["max_position_pct"] / 100.0 / entry,
        "cash after the buffer": cfg["budget_pkr"] * (1 - cfg["cash_buffer_pct"] / 100.0) / entry,
    }
    decided = min(limits, key=lambda k: limits[k])
    qty = int(math.floor(limits[decided] + 1e-9))
    if qty < 1:
        raise PsxError("not even one share fits: %s allows %.2f shares of %s at %.2f" % (
            decided, limits[decided], plan["symbol"], entry))
    return {"market": "psx", "symbol": plan["symbol"], "side": "buy", "qty": qty, "type": "limit",
            "limit_price": entry, "stop_price": plan["stop"], "target_price": plan["target"],
            "notional": cents(qty * entry), "max_loss_at_stop": cents(qty * per_share),
            "decided_by": decided, "day": plan["day"], "flat_by": plan["flat_by"]}


def fingerprint(order):
    return "|".join(str(order.get(k)) for k in ("symbol", "side", "qty", "limit_price", "stop_price", "target_price"))


def check_order(order, plan, cfg, trades, now_utc):
    """(blocks, warnings). Pure. Only buys come through here: getting out is never blocked."""
    blocks, warns = [], []
    today = to_pkt(now_utc).date()
    day = today.isoformat()
    todays = [t for t in trades if t.get("day") == day]
    if order.get("side") != "buy":
        blocks.append("only buys are checked here: no short selling in this tool")
    if order.get("symbol") != plan.get("symbol") or fingerprint(order) != fingerprint(
            {"symbol": plan.get("symbol"), "side": plan.get("side"), "qty": order.get("qty"),
             "limit_price": plan.get("entry"), "stop_price": plan.get("stop"), "target_price": plan.get("target")}):
        blocks.append("the order does not match the plan: run size again")
    if plan.get("day") != day:
        blocks.append("the plan is from %s, not today: plan again" % plan.get("day"))
    if plan.get("entry_is_estimate"):
        blocks.append("the entry is yesterday's close: plan again with --entry and your broker's live price")
    if order.get("symbol") in cfg["blocked"]:
        blocks.append("%s is on your blocked list" % order.get("symbol"))
    stop, target, entry = order.get("stop_price"), order.get("target_price"), order.get("limit_price")
    if not stop:
        blocks.append("a stop is required")
    elif not stop < entry < target:
        blocks.append("stop, entry and target are out of order")
    if not isinstance(order.get("qty"), int) or order["qty"] < 1:
        blocks.append("the quantity must be a whole number of shares")
    low, high = plan.get("band") or (0, float("inf"))
    if entry is not None and not low <= entry <= high:
        blocks.append("entry %.2f is outside the band %.2f to %.2f" % (entry, low, high))
    loss = order.get("max_loss_at_stop") or 0
    if loss > cfg["max_loss_per_trade_pkr"] + 0.005:
        blocks.append("loss at the stop %s is over your max %s" % (money(loss), money(cfg["max_loss_per_trade_pkr"])))
    risked = sum(t.get("max_loss_at_stop", 0) for t in todays)
    if risked + loss > cfg["max_daily_loss_pkr"] + 0.005:
        blocks.append("today's risk would be %s, over your daily limit %s" % (money(risked + loss), money(cfg["max_daily_loss_pkr"])))
    if len(todays) >= cfg["max_trades_per_day"]:
        blocks.append("you have logged %d trades today, your limit is %d" % (len(todays), cfg["max_trades_per_day"]))
    if plan.get("reward_risk_after_costs", 0) < cfg["min_reward_risk"]:
        blocks.append("reward to risk after costs is %.2f, your minimum is %.2f" % (
            plan.get("reward_risk_after_costs", 0), cfg["min_reward_risk"]))
    if (order.get("notional") or 0) > cfg["budget_pkr"] * cfg["max_position_pct"] / 100.0 + 0.005:
        blocks.append("the position is over your %g%% cap" % cfg["max_position_pct"])
    if any(t.get("fingerprint") == fingerprint(order) for t in todays):
        blocks.append("this exact order is already logged today")
    window = entry_window_block(now_utc, cfg)
    if window:
        blocks.append(window)
    if cfg["roundtrip_cost_pct"] == 0:
        warns.append("roundtrip_cost_pct is 0: set your broker's commission and levies in the config, they count on PSX.")
    gap = calendar_gap(today, cfg)
    if gap:
        warns.append(gap)
    if plan.get("target", 0) > high:
        warns.append("the target is above today's band top %.2f" % high)
    return blocks, warns


# ---------------------------------------------------------------- commands

def cmd_clock(a, cfg):
    st = market_status(parse_now(a.now), cfg)
    if a.json:
        print(json.dumps(st, indent=2))
        return 0
    print("Pakistan %s (%s): PSX %s, %s." % (st["now_pkt"], st["weekday"], st["state"].upper(), st["reason"]))
    if st["today"]:
        print("Regular market today: " + ", ".join(st["today"]) + ".")
    if st["next_open"]:
        print("Next open: %s." % st["next_open"])
    gap = calendar_gap(to_pkt(parse_now(a.now)).date(), cfg)
    if gap:
        print("note: " + gap)
    return 0


def cmd_scan(a, cfg):
    now_utc = parse_now(a.now)
    symbols = symbol_list(a.symbols) if a.symbols else [s for s, _ in read_universe(a.universe)]
    first = {"done": False}

    def fetch(sym):
        if first["done"] and not a.offline:
            SLEEP(PAUSE)
        first["done"] = True
        return get_bars(sym, now_utc, cfg, a.offline)

    print("Fetching daily bars for %d PSX symbols (one request each)..." % len(symbols), file=sys.stderr)
    hits, c, last_date = scan(symbols, fetch, now_utc, a.min_price, a.min_volume)
    doc = {"created_by": "trader-psx", "market": "psx", "currency": "PKR", "mode": "daily",
           "as_of": "%s close" % last_date, "universe": c["requested"], "scanned": c["scanned"],
           "failed": c["failed"], "source": "yahoo daily bars", "note": NOTE, "hits": hits}
    if a.json:
        print(json.dumps(doc, indent=2))
    else:
        print("PSX daily scan, %s Pakistan time, closes through %s (Yahoo daily bars, not intraday)." % (
            to_pkt(now_utc).strftime("%a %Y-%m-%d %H:%M"), last_date or "nothing"))
        print("Fetched %d of %d charts (%d failed or had no data, %d stale). %d passed PKR %g+ and %s+ shares; %d scanned." % (
            c["fetched"], c["requested"], c["failed"], c["stale"], c["fetched"] - c["stale"] - c["illiquid"],
            a.min_price, format(a.min_volume, ","), c["scanned"]))
        print("%d charts matched a setup." % c["hits"])
        for h in hits[:a.show]:
            rsi_text = "%5.1f" % h["rsi"] if h["rsi"] is not None else "  n/a"
            print("  %-8s %10s  RSI %s  %s" % (h["symbol"], "{:,.2f}".format(h["price"]), rsi_text,
                                               ", ".join(LABEL[t] for t in h["setups"])))
        if len(hits) > a.show:
            print("  ... and %d more (--show N for more)." % (len(hits) - a.show))
        print(NOTE)
    if not a.no_write and (hits or c["scanned"]):
        write_json(WATCHLIST, doc)
        if not a.json:
            print("Wrote %s." % WATCHLIST)
    return 0 if hits else 1


def news_tickers(a):
    if a.tickers:
        return symbol_list(a.tickers)
    syms = []
    plan = read_json(PLAN, {})
    if plan.get("symbol"):
        syms.append(plan["symbol"])
    for h in read_json(WATCHLIST, {}).get("hits", []):
        if h["symbol"] not in syms:
            syms.append(h["symbol"])
    return syms


def read_feeds(a):
    items, errors = [], []
    for i, (name, url) in enumerate(FEEDS):
        if a.offline:
            path = os.path.join(a.offline, re.sub(r"\W+", "_", name.lower()) + ".xml")
            if os.path.exists(path):
                with open(path, "rb") as fh:
                    items.extend(parse_feed(fh.read(), name))
            continue
        if i:
            SLEEP(PAUSE)
        try:
            items.extend(parse_feed(http_get(url), name))
        except (urllib.error.URLError, OSError) as e:
            errors.append("%s: %s" % (name, getattr(e, "reason", e)))
    return items, errors


def cmd_news(a, cfg):
    now_utc = parse_now(a.now)
    tickers = news_tickers(a)
    match = matchers(read_universe(a.universe), tickers)
    state = read_json(NEWS_STATE, {"seen": {}})
    seen = {} if a.all else state.get("seen", {})
    items, errors = read_feeds(a)
    picked = select_news(items, match, now_utc, a.hours, seen, market=not a.no_market)
    if a.json:
        print(json.dumps({"items": [dict(i, utc=i["utc"].isoformat()) for i in picked], "errors": errors}, indent=2))
    else:
        for it in picked:
            when = to_pkt(it["utc"]).strftime("%Y-%m-%d %H:%M")
            touched = ",".join(it["tickers"]) or "market"
            print("  %s PKT  %-12s %-17s %s" % (when, touched, it["source"], it["title"]))
            print("      %s%s" % ("tags: %s  " % ",".join(it["tags"]) if it["tags"] else "", it["link"]))
        if not picked:
            print("Nothing new.")
        for e in errors:
            print("note: feed skipped: " + e)
        print("Read %d items from %d feeds. PSX company announcements are not included: read them on the PSX Data "
              "Portal yourself. Headlines are leads, not facts. Not financial advice." % (
                  len(items), len(FEEDS) - len(errors)))
    if not a.dry_run:
        kept = {k: v for k, v in state.get("seen", {}).items()
                if v >= (now_utc - datetime.timedelta(days=30)).isoformat()}
        kept.update({i["link"]: now_utc.isoformat() for i in picked})
        write_json(NEWS_STATE, {"seen": kept})
    return 0 if picked else 1


def cmd_plan(a, cfg):
    now_utc = parse_now(a.now)
    sym = clean_symbol(a.symbol)
    bars = get_bars(sym, now_utc, cfg, a.offline)
    plan = build_plan(sym, bars, parse_stop(a.stop), parse_target(a.target), a.entry, cfg, now_utc)
    if a.json:
        print(json.dumps(plan, indent=2))
    else:
        print("%s plan: entry %.2f%s, stop %.2f, target %.2f (risk %.2f a share, reward:risk %.2f, %.2f after costs)." % (
            sym, plan["entry"], " (estimate)" if plan["entry_is_estimate"] else "", plan["stop"], plan["target"],
            plan["risk_per_share"], plan["reward_risk"], plan["reward_risk_after_costs"]))
        print("Band %.2f to %.2f around the %s close of %.2f. Flat by %s." % (
            plan["band"][0], plan["band"][1], plan["prev_close_date"], plan["prev_close"], plan["flat_by"] or "n/a (closed today)"))
        for n in plan["notes"]:
            print("note: " + n)
        print("A stop is a plan, not a guarantee: a gap or a locked stock can fill past it, or not at all.")
    if a.write:
        write_json(PLAN, plan)
        if not a.json:
            print("Wrote %s." % PLAN)
    return 0


def cmd_size(a, cfg):
    order = size_order(read_json(PLAN), cfg)
    if a.json:
        print(json.dumps(order, indent=2))
    else:
        print("Buy %d %s at %.2f = %s. Max loss at the stop %s (%s decided it)." % (
            order["qty"], order["symbol"], order["limit_price"], money(order["notional"]),
            money(order["max_loss_at_stop"]), order["decided_by"]))
    if a.write:
        write_json(ORDERS, order)
        if not a.json:
            print("Wrote %s. Nothing is placed." % ORDERS)
    return 0


def cmd_check(a, cfg):
    now_utc = parse_now(a.now)
    order, plan = read_json(ORDERS), read_json(PLAN)
    trades = read_json(TRADES_STATE, {"trades": []})["trades"]
    blocks, warns = check_order(order, plan, cfg, trades, now_utc)
    verdict = {"fingerprint": fingerprint(order), "pass": not blocks, "blocks": blocks, "warnings": warns,
               "day": to_pkt(now_utc).date().isoformat(), "at_pkt": to_pkt(now_utc).strftime("%Y-%m-%d %H:%M")}
    if a.json:
        print(json.dumps(verdict, indent=2))
    else:
        print("%s: buy %s %s at %.2f." % ("BLOCK" if blocks else "PASS", order["qty"], order["symbol"], order["limit_price"]))
        for b in blocks:
            print("  blocked: " + b)
        for w in warns:
            print("  warning: " + w)
    write_json(RISK_STATE, verdict)
    return 1 if blocks else 0


def cmd_ticket(a, cfg):
    now_utc = parse_now(a.now)
    order = read_json(ORDERS)
    verdict = read_json(RISK_STATE, {})
    ready = (verdict.get("pass") and verdict.get("fingerprint") == fingerprint(order)
             and verdict.get("day") == to_pkt(now_utc).date().isoformat())
    if not ready:
        print("NOT READY: this exact order has no PASS from today. Run /trader-psx check first.")
        return 1
    print("TICKET, READY. Nothing is sent: this tool cannot place an order. Type it into your broker's app yourself.")
    print("  BUY %d %s, limit %.2f (%s)" % (order["qty"], order["symbol"], order["limit_price"], money(order["notional"])))
    print("  Stop %.2f, target %.2f, max loss at the stop %s." % (order["stop_price"], order["target_price"], money(order["max_loss_at_stop"])))
    print("  Flat by %s Pakistan time." % (order["flat_by"] or "the close"))
    print("  Enter the stop and the target as separate orders if your broker has them, or watch them yourself:")
    print("  not every PSX broker offers stop or bracket orders. Ask yours, and ask how same-day selling is treated.")
    print("Then run /trader-psx record so the daily limits count it.")
    return 0


def cmd_record(a, cfg):
    now_utc = parse_now(a.now)
    order = read_json(ORDERS)
    verdict = read_json(RISK_STATE, {})
    today = to_pkt(now_utc).date().isoformat()
    if not verdict.get("pass") or verdict.get("fingerprint") != fingerprint(order) or verdict.get("day") != today:
        raise PsxError("this exact order has no PASS from today, so there is nothing to record")
    doc = read_json(TRADES_STATE, {"trades": []})
    if any(t.get("fingerprint") == fingerprint(order) and t.get("day") == today for t in doc["trades"]):
        raise PsxError("this order is already logged today")
    doc["trades"].append({"day": today, "fingerprint": fingerprint(order), "symbol": order["symbol"], "qty": order["qty"],
                          "max_loss_at_stop": order["max_loss_at_stop"], "at_pkt": to_pkt(now_utc).strftime("%Y-%m-%d %H:%M")})
    write_json(TRADES_STATE, doc)
    print("Logged %d %s. %d trades today." % (order["qty"], order["symbol"], sum(t["day"] == today for t in doc["trades"])))
    return 0


# ---------------------------------------------------------------- intraday, from pyPSX

def pypsx_get(path, params):
    """One authenticated GET. Keys come from the environment and are never printed."""
    key, secret = os.environ.get("PYPSX_API_KEY_ID"), os.environ.get("PYPSX_API_SECRET_KEY")
    if not key or not secret:
        raise PsxError("intraday data needs a pyPSX key: create one at markets.pypsx.com, then set "
                       "PYPSX_API_KEY_ID and PYPSX_API_SECRET_KEY in your environment (never in the chat)")
    base = os.environ.get("PYPSX_BASE", PYPSX_BASE).rstrip("/")
    req = urllib.request.Request(base + path + "?" + urllib.parse.urlencode(params), headers={
        "User-Agent": UA, "PYPSX-API-KEY-ID": key, "PYPSX-API-SECRET-KEY": secret})
    for attempt in (1, 2):
        try:
            with urllib.request.urlopen(req, timeout=30, context=ssl_context()) as resp:
                return resp.read(MAX_BYTES)
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt == 1:
                SLEEP(BACKOFF)
                continue
            if e.code in (401, 403):
                raise PsxError("pyPSX refused the key (HTTP %d): check it, or whether your plan allows this data" % e.code)
            raise PsxError("pyPSX answered HTTP %d" % e.code)
        except (urllib.error.URLError, OSError) as e:
            raise PsxError("could not reach pyPSX: %s" % getattr(e, "reason", e))
    raise PsxError("pyPSX is rate limiting this key")


def parse_stamp_pkt(text):
    """An ISO candle time -> naive Pakistan time."""
    dt = datetime.datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        return dt
    return dt.replace(tzinfo=None) - dt.utcoffset() + PKT


def parse_candles(text_or_doc):
    """{results: [{symbol, candles: [[time, o, h, l, c, v]], gaps, note}]} -> {SYM: {bars, gaps, note}}."""
    try:
        doc = json.loads(text_or_doc) if isinstance(text_or_doc, (str, bytes)) else text_or_doc
        out = {}
        for row in doc["results"]:
            bars = {}
            for c in row.get("candles") or []:
                if None in c[:5]:
                    continue
                t = parse_stamp_pkt(c[0])
                bars[t] = {"t": t, "open": float(c[1]), "high": float(c[2]), "low": float(c[3]), "close": float(c[4]),
                           "volume": int(c[5] or 0)}
            out[row["symbol"]] = {"bars": [bars[t] for t in sorted(bars)], "gaps": row.get("gaps") or [],
                                  "note": row.get("note")}
        return out
    except (KeyError, TypeError, ValueError, IndexError):
        raise PsxError("pyPSX's answer was not in the documented shape: it may have changed")


def get_candles(symbols, start, end, offline=None):
    """5-minute candles for symbols between two Pakistan times, batched to the rate limit."""
    if offline:
        with open(offline, encoding="utf-8") as fh:
            return parse_candles(fh.read())
    out = {}
    for i in range(0, len(symbols), PYPSX_BATCH):
        if i:
            SLEEP(PYPSX_PAUSE)
        text = pypsx_get("/api/v1/market/historical-intraday", {
            "symbol": ",".join(symbols[i:i + PYPSX_BATCH]), "interval": "%dm" % BAR_MINUTES,
            "from": start.isoformat() + "+05:00", "to": end.isoformat() + "+05:00"})
        out.update(parse_candles(text))
    return out


def complete_bars(bars, day, now):
    """One day's candles that have finished by now (Pakistan time)."""
    width = datetime.timedelta(minutes=BAR_MINUTES)
    return [b for b in bars if b["t"].date() == day and b["t"] + width <= now]


def range_start(day, cfg):
    """The first candle of the session on the 5-minute grid: 09:32 -> 09:30, 09:17 -> 09:15."""
    spans = sessions_for(day, cfg)
    if not spans:
        return None
    t = datetime.datetime.combine(day, spans[0][0])
    return t.replace(minute=t.minute - t.minute % BAR_MINUTES)


def orb_status(bars, now, or_minutes, cfg):
    """Pure. The first completed candle after the opening range to CLOSE above its high.
    status: closed, forming, unusable, waiting, triggered or expired."""
    day = now.date()
    start = range_start(day, cfg)
    if start is None:
        return {"status": "closed"}
    if or_minutes % BAR_MINUTES or or_minutes <= 0:
        raise PsxError("--or-minutes must be a multiple of %d" % BAR_MINUTES)
    range_end = start + datetime.timedelta(minutes=or_minutes)
    done = complete_bars(bars, day, now)
    in_range = [b for b in done if start <= b["t"] < range_end]
    if now < range_end:
        return {"status": "forming", "range_ends": range_end.strftime("%H:%M")}
    if len(in_range) < or_minutes // BAR_MINUTES:
        return {"status": "unusable", "reason": "%d of %d opening-range candles are there" % (
            len(in_range), or_minutes // BAR_MINUTES)}
    high, low = max(b["high"] for b in in_range), min(b["low"] for b in in_range)
    out = {"or_high": round(high, 2), "or_low": round(low, 2)}
    after = [b for b in done if b["t"] >= range_end]
    out["last"] = round((after or in_range)[-1]["close"], 2)
    out["last_bar"] = (after or in_range)[-1]["t"].strftime("%H:%M")
    for b in after:
        if b["close"] > high:
            closed = b["t"] + datetime.timedelta(minutes=BAR_MINUTES)
            out.update(status="triggered", price=round(b["close"], 2), at=closed.strftime("%H:%M"),
                       over_pct=round((b["close"] / high - 1) * 100, 2))
            return out
    spans = sessions_for(day, cfg)
    last_entry = datetime.datetime.combine(day, spans[-1][1]) - datetime.timedelta(minutes=cfg["no_entries_last_minutes"])
    out["status"] = "expired" if now >= last_entry else "waiting"
    return out


def replay_day(bars, day, or_minutes, target_r, cfg):
    """One past session: did the rule fire, and which came first? Stop at the range midpoint.
    A candle that touches both counts as the stop, the cautious reading."""
    end = datetime.datetime.combine(day, datetime.time(23, 59))
    st = orb_status(bars, end, or_minutes, cfg)
    if st.get("status") != "triggered":
        return None
    closed = datetime.datetime.combine(day, datetime.datetime.strptime(st["at"], "%H:%M").time())
    entry = st["price"]
    stop = (st["or_high"] + st["or_low"]) / 2.0
    if stop >= entry:
        return None
    target = entry + (entry - stop) * target_r
    for b in complete_bars(bars, day, end):
        if b["t"] < closed:
            continue
        if b["low"] <= stop:
            return "stop"
        if b["high"] >= target:
            return "target"
    return "neither"


def replay(bars, or_minutes, target_r, cfg):
    """Pure. Counts only, never a profit figure."""
    counts = {"sessions": 0, "fired": 0, "target": 0, "stop": 0, "neither": 0}
    for day in sorted({b["t"].date() for b in bars}):
        if not sessions_for(day, cfg):
            continue
        counts["sessions"] += 1
        got = replay_day(bars, day, or_minutes, target_r, cfg)
        if got:
            counts["fired"] += 1
            counts[got] += 1
    return counts


def age_line(bars, now):
    """How old the newest finished candle is: the docs state no delay, so measure it."""
    if not bars:
        return "no candles today"
    end = bars[-1]["t"] + datetime.timedelta(minutes=BAR_MINUTES)
    return "newest candle closed %s, %d minutes before this check" % (end.strftime("%H:%M"), (now - end).total_seconds() // 60)


def pkt_now(a):
    """--at cuts the clock to a time today, --now pins it."""
    now = to_pkt(parse_now(a.now))
    if getattr(a, "at", None):
        try:
            now = datetime.datetime.combine(now.date(), hm(a.at))
        except ValueError:
            raise PsxError("--at must look like 10:15")
    return now


def day_span(now):
    midnight = datetime.datetime.combine(now.date(), datetime.time(0, 0))
    return midnight, midnight + datetime.timedelta(days=1)


def cmd_intraday(a, cfg):
    now = pkt_now(a)
    sym = clean_symbol(a.symbol)
    got = get_candles([sym], *day_span(now), offline=a.offline).get(sym) or {"bars": []}
    bars = complete_bars(got["bars"], now.date(), now)
    if a.json:
        print(json.dumps([dict(b, t=b["t"].isoformat()) for b in bars], indent=2))
        return 0 if bars else 1
    for b in bars[-a.show:]:
        print("  %s  O %.2f  H %.2f  L %.2f  C %.2f  V %s" % (b["t"].strftime("%H:%M"), b["open"], b["high"], b["low"], b["close"], format(b["volume"], ",")))
    print("%s: %s. Confirm against your broker's screen." % (sym, age_line(bars, now)))
    return 0 if bars else 1


def cmd_orb(a, cfg):
    now = pkt_now(a)
    if not sessions_for(now.date(), cfg):
        print("The PSX is closed on %s (%s)." % (now.date(), holiday_name(now.date(), cfg) or "weekend"))
        return 1
    symbols = symbol_list(a.symbols) if a.symbols else [s for s, _ in read_universe(a.universe)]
    data = get_candles(symbols, *day_span(now), offline=a.offline)
    hits, counts = [], {"requested": len(symbols), "no_data": 0, "unusable": 0, "usable": 0}
    newest = None
    for sym in symbols:
        got = data.get(sym)
        if not got or not got["bars"]:
            counts["no_data"] += 1
            continue
        st = orb_status(got["bars"], now, a.or_minutes, cfg)
        if st["status"] == "forming":
            print("The %d-minute opening range ends at %s. Run this again after that." % (a.or_minutes, st["range_ends"]))
            return 1
        if st["status"] == "unusable":
            counts["unusable"] += 1
            continue
        counts["usable"] += 1
        done = complete_bars(got["bars"], now.date(), now)
        if done and (newest is None or done[-1]["t"] > newest):
            newest = done[-1]["t"]
        if st["status"] == "triggered":
            hits.append(dict(st, symbol=sym))
    hits.sort(key=lambda h: (h["at"], h["symbol"]))
    doc = {"created_by": "trader-psx", "market": "psx", "mode": "orb", "as_of_pkt": now.strftime("%Y-%m-%d %H:%M"),
           "or_minutes": a.or_minutes, "counts": counts, "hits": hits, "source": "pyPSX 5-minute candles", "note": NOTE}
    if a.json:
        print(json.dumps(doc, indent=2))
    else:
        print("PSX opening-range scan at %s Pakistan time: %d of %d charts usable (%d no data, %d with missing candles)." % (
            now.strftime("%H:%M"), counts["usable"], counts["requested"], counts["no_data"], counts["unusable"]))
        print("%d of %d closed above their %d-minute opening-range high:" % (len(hits), counts["usable"], a.or_minutes))
        for h in hits[:a.show]:
            print("  %s  %-8s %10s  range %.2f to %.2f  +%.2f%% over" % (h["at"], h["symbol"], "{:,.2f}".format(h["price"]), h["or_low"], h["or_high"], h["over_pct"]))
        if newest:
            print("Newest candle starts %s: check how far that is behind your broker's screen." % newest.strftime("%H:%M"))
        print("A later hit is closer to the price now, and a hit goes stale as the price moves. " + NOTE)
    if not a.no_write and counts["usable"]:
        write_json(ORB_FILE, doc)
    return 0 if hits else 1


def cmd_entry(a, cfg):
    now = pkt_now(a)
    sym = clean_symbol(a.symbol)
    got = get_candles([sym], *day_span(now), offline=a.offline).get(sym) or {"bars": []}
    st = orb_status(got["bars"], now, a.or_minutes, cfg)
    st.update(symbol=sym, as_of_pkt=now.strftime("%Y-%m-%d %H:%M"))
    done = complete_bars(got["bars"], now.date(), now)
    if a.json:
        print(json.dumps(st, indent=2))
    else:
        s = st["status"]
        if s == "triggered":
            print("%s TRIGGERED at %s: closed %.2f, %.2f%% over the range high %.2f." % (sym, st["at"], st["price"], st["over_pct"], st["or_high"]))
            print("Read the live price off your broker's screen, then: plan %s --entry PRICE --stop price:%.2f --write" % (
                sym, (st["or_high"] + st["or_low"]) / 2.0))
        elif s == "waiting":
            print("%s waiting: last close %.2f, range high %.2f (%.2f away)." % (sym, st["last"], st["or_high"], st["or_high"] - st["last"]))
        elif s == "expired":
            print("%s expired: no close above %.2f before the entry window ended." % (sym, st["or_high"]))
        elif s == "forming":
            print("%s: the opening range ends at %s." % (sym, st["range_ends"]))
        elif s == "unusable":
            print("%s: not usable, %s (a halt, a thin stock or a feed gap)." % (sym, st["reason"]))
        else:
            print("%s: the PSX is closed today." % sym)
        print("%s. It never places an order." % age_line(done, now).capitalize())
    write_json(ENTRY_FILE, st)
    return 0 if st["status"] == "triggered" else 1


def cmd_history(a, cfg):
    now = pkt_now(a)
    sym = clean_symbol(a.symbol)
    kind, target_r = parse_target(a.target)
    if kind != "r":
        raise PsxError("--target must be a multiple of the risk here, like 1R")
    end = datetime.datetime.combine(now.date(), datetime.time(0, 0))
    got = get_candles([sym], end - datetime.timedelta(days=a.days), end, offline=a.offline).get(sym) or {"bars": [], "gaps": []}
    bars = [b for b in got["bars"] if b["t"] < end]
    c = replay(bars, a.or_minutes, target_r, cfg)
    if a.json:
        print(json.dumps(dict(c, symbol=sym, gaps=got.get("gaps"), note=got.get("note")), indent=2))
    else:
        print("%s, %d sessions with candles in the last %d days: the %d-minute breakout fired %d times." % (sym, c["sessions"], a.days, a.or_minutes, c["fired"]))
        print("Target %s first %d, stop at the range midpoint first %d, neither by the close %d." % (a.target.upper(), c["target"], c["stop"], c["neither"]))
        for g in got.get("gaps") or []:
            print("note: data gap: %s" % (g,))
        if got.get("note"):
            print("note: %s" % got["note"])
        print("Past sessions, not a prediction. No costs, slippage or locked stocks are counted, and a candle touching both counts as the stop.")
    return 0 if c["fired"] else 1


def main(argv=None):
    ap = argparse.ArgumentParser(description="Pakistan Stock Exchange tools (trader-psx). Never places an order.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p):
        p.add_argument("--now", help='pretend it is this Pakistan time, e.g. "2026-10-30 10:15"')
        p.add_argument("--config", default=CONFIG)
        p.add_argument("--json", action="store_true")
        return p

    common(sub.add_parser("clock", help="is the PSX open?"))
    p = common(sub.add_parser("scan", help="daily setups from Yahoo's daily bars"))
    p.add_argument("--symbols", help="OGDC,HBL,LUCK instead of the universe file")
    p.add_argument("--universe", default=UNIVERSE)
    p.add_argument("--min-price", type=float, default=1.0)
    p.add_argument("--min-volume", type=int, default=100000)
    p.add_argument("--show", type=int, default=15)
    p.add_argument("--offline", metavar="DIR", help="a folder of SYMBOL.json chart files")
    p.add_argument("--no-write", action="store_true")
    p = common(sub.add_parser("news", help="Pakistani business RSS feeds"))
    p.add_argument("--tickers", help="OGDC,HBL. Default: the plan and the watchlist")
    p.add_argument("--hours", type=float, default=24)
    p.add_argument("--universe", default=UNIVERSE)
    p.add_argument("--all", action="store_true", help="show items already seen")
    p.add_argument("--no-market", action="store_true", help="only items naming a ticker")
    p.add_argument("--dry-run", action="store_true", help="leave the seen list alone")
    p.add_argument("--offline", metavar="DIR", help="a folder of saved feeds")
    p = common(sub.add_parser("plan", help="set the stop and target"))
    p.add_argument("symbol")
    p.add_argument("--entry", type=float, help="the live price on your broker's screen")
    p.add_argument("--stop", default="atr", help="atr, atr:1.5, pct:2 or price:295.50")
    p.add_argument("--target", default="1R", help="1R, 2R or price:310")
    p.add_argument("--offline", metavar="DIR")
    p.add_argument("--write", action="store_true")
    p = common(sub.add_parser("size", help="whole shares inside your limits"))
    p.add_argument("--write", action="store_true")
    common(sub.add_parser("check", help="PASS or BLOCK against your limits"))
    common(sub.add_parser("ticket", help="the ticket to type into your broker's app"))
    common(sub.add_parser("record", help="log the order after you have placed it"))
    p = common(sub.add_parser("intraday", help="today's 5-minute candles (needs a pyPSX key)"))
    p.add_argument("symbol")
    p.add_argument("--at", help="cut the clock at this time today, like 10:15")
    p.add_argument("--show", type=int, default=12)
    p.add_argument("--offline", metavar="FILE", help="saved candles JSON")
    p = common(sub.add_parser("orb", help="opening-range breakouts so far (needs a pyPSX key)"))
    p.add_argument("--symbols", help="OGDC,HBL. Default: the universe file")
    p.add_argument("--universe", default=UNIVERSE)
    p.add_argument("--at", help="cut the clock at this time today, like 10:15")
    p.add_argument("--or-minutes", type=int, default=15)
    p.add_argument("--show", type=int, default=20)
    p.add_argument("--offline", metavar="FILE", help="saved candles JSON")
    p.add_argument("--no-write", action="store_true")
    p = common(sub.add_parser("entry", help="waiting, triggered or expired (needs a pyPSX key)"))
    p.add_argument("symbol")
    p.add_argument("--at", help="cut the clock at this time today, like 10:15")
    p.add_argument("--or-minutes", type=int, default=15)
    p.add_argument("--offline", metavar="FILE", help="saved candles JSON")
    p = common(sub.add_parser("history", help="the breakout rule on past sessions (needs a pyPSX key)"))
    p.add_argument("symbol")
    p.add_argument("--days", type=int, default=60)
    p.add_argument("--target", default="1R")
    p.add_argument("--or-minutes", type=int, default=15)
    p.add_argument("--offline", metavar="FILE", help="saved candles JSON")

    a = ap.parse_args(argv)
    commands = {"clock": cmd_clock, "scan": cmd_scan, "news": cmd_news, "plan": cmd_plan,
                "size": cmd_size, "check": cmd_check, "ticket": cmd_ticket, "record": cmd_record,
                "intraday": cmd_intraday, "orb": cmd_orb, "entry": cmd_entry, "history": cmd_history}
    try:
        return commands[a.cmd](a, load_config(a.config))
    except PsxError as e:
        print("psx.py: %s" % e, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
