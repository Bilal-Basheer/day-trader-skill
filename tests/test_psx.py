"""trader-psx. Every price here is made up: real PSX data is licensed, so none is committed."""

import contextlib
import datetime
import io
import json
import os
import tempfile
import unittest

from _load import ROOT, load

psx = load("trader-psx", "psx")
CFG = dict(psx.DEFAULTS)


def utc(text):
    return psx.parse_now(text)


def chart(days, closes, meta=None, volume=500000, null_last=False):
    """A Yahoo-shaped daily chart. days are dates, stamped 09:30 PKT as Yahoo does."""
    ts = [int((datetime.datetime.combine(d, datetime.time(4, 30)) - datetime.datetime(1970, 1, 1)).total_seconds()) for d in days]
    o = [c - 1 for c in closes]
    h = [c + 2 for c in closes]
    lo = [c - 2 for c in closes]
    v = [volume] * len(closes)
    c = list(closes)
    if null_last:
        o[-1] = h[-1] = lo[-1] = c[-1] = v[-1] = None
    return {"chart": {"result": [{"meta": dict({"dataGranularity": "1d"}, **(meta or {})), "timestamp": ts,
                                  "indicators": {"quote": [{"open": o, "high": h, "low": lo, "close": c, "volume": v}]}}]}}


def weekdays(end, n):
    out, d = [], end
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d -= datetime.timedelta(days=1)
    return out[::-1]


END = datetime.date(2026, 10, 29)  # a Thursday
NOW = "2026-10-30 10:00"           # the Friday after it, in the first session


def bars(closes, end=END, now=NOW):
    return psx.parse_bars(chart(weekdays(end, len(closes)), closes), utc(now), CFG, "TEST")


class Clock(unittest.TestCase):
    def status(self, now, cfg=CFG):
        return psx.market_status(utc(now), cfg)

    def test_monday_to_thursday(self):
        self.assertEqual(self.status("2026-10-29 09:20")["reason"], "before the open")
        self.assertEqual(self.status("2026-10-29 09:32")["state"], "open")
        self.assertEqual(self.status("2026-10-29 15:29")["state"], "open")
        self.assertEqual(self.status("2026-10-29 15:30")["reason"], "after the close")

    def test_friday_has_two_sessions_and_a_break(self):
        self.assertEqual(self.status("2026-10-30 09:17")["state"], "open")
        st = self.status("2026-10-30 13:00")
        self.assertEqual((st["state"], st["reason"]), ("closed", "midday break"))
        self.assertEqual(st["next_open"], "2026-10-30 14:32")
        self.assertEqual(self.status("2026-10-30 16:00")["state"], "open")

    def test_weekend_rolls_to_monday(self):
        st = self.status("2026-10-31 11:00")
        self.assertEqual((st["state"], st["reason"]), ("closed", "weekend"))
        self.assertEqual(st["next_open"], "2026-11-02 09:32")

    def test_a_noticed_holiday_and_one_from_the_config(self):
        self.assertIn("Independence", self.status("2026-08-14 10:00")["reason"])
        cfg = dict(CFG, holidays={"2026-11-09": "Iqbal Day"})
        self.assertEqual(self.status("2026-11-09 10:00", cfg)["state"], "closed")
        self.assertEqual(self.status("2026-11-09 10:00")["state"], "open")

    def test_session_override_for_ramadan_hours(self):
        cfg = dict(CFG, session_overrides={"2026-11-03": [["09:17", "13:30"]]})
        self.assertEqual(self.status("2026-11-03 09:20", cfg)["state"], "open")
        self.assertEqual(self.status("2026-11-03 14:00", cfg)["state"], "closed")

    def test_the_calendar_says_when_it_runs_out(self):
        self.assertIsNone(psx.calendar_gap(datetime.date(2026, 3, 1), CFG))
        self.assertIn("No PSX holiday", psx.calendar_gap(datetime.date(2026, 11, 2), CFG))

    def test_entry_window_on_both_friday_sessions(self):
        self.assertIsNotNone(psx.entry_window_block(utc("2026-10-30 09:20"), CFG))
        self.assertIsNone(psx.entry_window_block(utc("2026-10-30 09:32"), CFG))
        self.assertIsNotNone(psx.entry_window_block(utc("2026-10-30 11:45"), CFG))
        self.assertIsNotNone(psx.entry_window_block(utc("2026-10-30 13:00"), CFG))
        self.assertIsNone(psx.entry_window_block(utc("2026-10-30 15:00"), CFG))
        self.assertIn("closed", psx.entry_window_block(utc("2026-10-31 11:00"), CFG))

    def test_flat_by(self):
        self.assertEqual(psx.flat_by(datetime.date(2026, 10, 29), CFG), "15:25")
        self.assertEqual(psx.flat_by(datetime.date(2026, 10, 30), CFG), "16:25")
        self.assertIsNone(psx.flat_by(datetime.date(2026, 10, 31), CFG))


class Bars(unittest.TestCase):
    def test_the_stale_meta_price_is_ignored(self):
        doc = chart(weekdays(END, 3), [300, 301, 306.21], meta={"regularMarketPrice": 131.87})
        got = psx.parse_bars(doc, utc(NOW), CFG, "OGDC")
        self.assertEqual(got[-1]["close"], 306.21)

    def test_todays_empty_bar_is_dropped(self):
        doc = chart(weekdays(datetime.date(2026, 10, 30), 3), [300, 301, 302], null_last=True)
        got = psx.parse_bars(doc, utc(NOW), CFG, "OGDC")
        self.assertEqual(got[-1]["date"], "2026-10-29")

    def test_todays_bar_waits_for_the_last_session_to_end(self):
        doc = chart(weekdays(datetime.date(2026, 10, 30), 3), [300, 301, 302])
        self.assertEqual(psx.parse_bars(doc, utc("2026-10-30 15:00"), CFG)[-1]["date"], "2026-10-29")
        self.assertEqual(psx.parse_bars(doc, utc("2026-10-30 17:00"), CFG)[-1]["date"], "2026-10-30")

    def test_intraday_data_is_refused_rather_than_read_as_daily(self):
        doc = chart(weekdays(END, 3), [1, 2, 3], meta={"dataGranularity": "5m"})
        with self.assertRaises(psx.PsxError):
            psx.parse_bars(doc, utc(NOW), CFG, "OGDC")

    def test_no_result_is_one_plain_error(self):
        with self.assertRaises(psx.PsxError):
            psx.parse_bars({"chart": {"result": None}}, utc(NOW), CFG, "NOPE")

    def test_symbols(self):
        self.assertEqual(psx.clean_symbol(" ogdc.ka "), "OGDC")
        with self.assertRaises(psx.PsxError):
            psx.clean_symbol("OG/DC")
        self.assertEqual(psx.symbol_list("OGDC, hbl LUCK"), ["OGDC", "HBL", "LUCK"])

    def test_the_universe_file(self):
        rows = psx.read_universe()
        self.assertEqual(len(rows), 60)
        self.assertIn(("HBL", "Habib Bank Limited"), rows)
        self.assertNotIn("HUBC", dict(rows))


class Scan(unittest.TestCase):
    def run_scan(self, closes, volume=500000, end=END, min_volume=100000):
        doc = chart(weekdays(end, len(closes)), closes, volume=volume)
        fetch = lambda s: psx.parse_bars(doc, utc(NOW), CFG, s)
        return psx.scan(["TEST"], fetch, utc(NOW), 1.0, min_volume)

    def test_a_breakout(self):
        hits, c, last = self.run_scan([100.0 + (i % 3) for i in range(40)] + [120.0])
        self.assertEqual(hits[0]["symbol"], "TEST")
        self.assertIn("breakout_20d", hits[0]["setups"])
        self.assertEqual((c["scanned"], last), (1, "2026-10-29"))

    def test_oversold(self):
        hits, _, _ = self.run_scan([200.0 - 2 * i for i in range(40)])
        self.assertIn("oversold", hits[0]["setups"])

    def test_filters_and_failures_are_counted(self):
        self.assertEqual(self.run_scan([100.0] * 40, volume=10)[1]["illiquid"], 1)
        self.assertEqual(self.run_scan([100.0] * 10)[1]["short"], 1)
        self.assertEqual(self.run_scan([100.0] * 40, end=datetime.date(2026, 10, 1))[1]["stale"], 1)

        def boom(s):
            raise psx.PsxError("no chart")
        self.assertEqual(psx.scan(["X"], boom, utc(NOW), 1.0, 0)[1]["failed"], 1)

    def test_same_rules_as_the_us_scanner(self):
        scanner = load("trader-scanner", "scan")
        for closes in ([100.0 + (i % 3) for i in range(40)] + [120.0], [200.0 - 2 * i for i in range(40)],
                       [100 + i * 1.5 for i in range(25)] + [137.0, 138.0, 137.5, 138.5, 138.0]):
            self.assertEqual(psx.find_setups(closes)[0], scanner.find_setups(closes)[0])


RSS = b"""<?xml version="1.0"?><rss version="2.0"><channel><title>Feed</title>
<item><title>Habib Bank posts higher profit &amp; dividend</title><link>https://x.test/1</link><pubDate>Fri, 30 Oct 26 09:51:17 +0500</pubDate></item>
<item><title>KSE-100 gains 1,130 points</title><link>https://x.test/2</link><pubDate>Fri, 30 Oct 2026 04:00:00 +0000</pubDate></item>
<item><title>Palm oil gains on bargain buying</title><link>https://x.test/3</link><pubDate>Fri, 30 Oct 2026 03:00:00 +0000</pubDate></item>
<item><title>OGDC finds gas in Sindh</title><link>https://x.test/4</link><pubDate>Mon, 19 Oct 2026 03:00:00 +0000</pubDate></item>
<item><title>Pol Pot history</title><link>https://x.test/5</link><pubDate>Fri, 30 Oct 2026 03:00:00 +0000</pubDate></item>
</channel></rss>"""


class News(unittest.TestCase):
    def pick(self, tickers=("HBL", "OGDC", "POL"), seen=None, market=True, hours=24):
        items = psx.parse_feed(RSS, "Test")
        match = psx.matchers(psx.read_universe(), list(tickers))
        return psx.select_news(items, match, utc("2026-10-30 12:00"), hours, seen, market)

    def test_parse_reads_a_two_digit_year_and_entities(self):
        items = psx.parse_feed(RSS, "Test")
        self.assertEqual(items[0]["title"], "Habib Bank posts higher profit & dividend")
        self.assertEqual(items[0]["utc"], datetime.datetime(2026, 10, 30, 4, 51, 17))

    def test_name_match_and_market_items_only(self):
        titles = [i["title"] for i in self.pick()]
        self.assertEqual(titles, ["Habib Bank posts higher profit & dividend", "KSE-100 gains 1,130 points"])

    def test_tags_and_tickers(self):
        first = self.pick()[0]
        self.assertEqual(first["tickers"], ["HBL"])
        self.assertIn("earnings", first["tags"])

    def test_seen_items_do_not_repeat_and_old_ones_fall_away(self):
        self.assertEqual(len(self.pick(seen={"https://x.test/1": "t"})), 1)
        self.assertEqual(len(self.pick(hours=24 * 30)), 3)

    def test_an_ambiguous_ticker_matches_only_its_name(self):
        match = psx.matchers(psx.read_universe(), ["POL"])
        self.assertFalse(match[0][1].search("POL rises"))
        self.assertTrue(match[0][1].search("Pakistan Oilfields rises"))

    def test_generic_words_do_not_match_a_company(self):
        match = dict(psx.matchers(psx.read_universe(), ["PPL", "SYS", "NBP", "TRG"]))
        self.assertFalse(match["PPL"].search("Petroleum prices rise"))
        self.assertTrue(match["PPL"].search("Pakistan Petroleum finds gas"))
        self.assertFalse(match["SYS"].search("New payment systems launched"))
        self.assertTrue(match["SYS"].search("Systems Limited posts profit"))
        self.assertTrue(match["NBP"].search("National Bank raises profit"))
        self.assertTrue(match["TRG"].search("TRG rises on stake sale"))

    def test_a_broken_feed_is_no_items(self):
        self.assertEqual(psx.parse_feed(b"<not xml", "Test"), [])


PRICES = [300.0 + (i % 5) for i in range(30)]


class Plan(unittest.TestCase):
    def plan(self, stop="pct:2", target="1R", entry=306.5, cfg=CFG, now=NOW):
        return psx.build_plan("OGDC", bars(PRICES), psx.parse_stop(stop), psx.parse_target(target), entry, cfg, utc(now))

    def test_a_percent_stop_and_1r_target(self):
        p = self.plan()
        self.assertEqual((p["entry"], p["stop"], p["target"]), (306.5, 300.37, 312.63))
        self.assertEqual(p["reward_risk"], 1.0)
        self.assertFalse(p["entry_is_estimate"])
        self.assertEqual(p["flat_by"], "16:25")

    def test_no_entry_is_flagged_an_estimate(self):
        p = self.plan(entry=None)
        self.assertTrue(p["entry_is_estimate"])
        self.assertEqual(p["entry"], PRICES[-1])
        self.assertTrue(any("estimate" in n for n in p["notes"]))

    def test_refusals(self):
        with self.assertRaises(psx.PsxError):
            self.plan(stop="price:310")
        with self.assertRaises(psx.PsxError):
            self.plan(target="price:300")
        with self.assertRaises(psx.PsxError):
            self.plan(entry=500.0)  # outside the band
        for bad in ("foo", "pct", "atr:x"):
            with self.assertRaises(psx.PsxError):
                psx.parse_stop(bad)
        with self.assertRaises(psx.PsxError):
            psx.parse_target("big")

    def test_a_target_past_the_band_is_said_out_loud(self):
        p = self.plan(target="price:400")
        self.assertTrue(any("cannot trade today" in n for n in p["notes"]))

    def test_costs_lower_the_reward_to_risk(self):
        p = self.plan(cfg=dict(CFG, roundtrip_cost_pct=0.5))
        self.assertLess(p["reward_risk_after_costs"], 1.0)

    def test_atr(self):
        self.assertIsNone(psx.atr(bars(PRICES[:5])))
        self.assertGreater(psx.atr(bars(PRICES)), 0)


class Size(unittest.TestCase):
    def setUp(self):
        self.p = psx.build_plan("OGDC", bars(PRICES), ("pct", 2.0), ("r", 1.0), 306.5, CFG, utc(NOW))

    def test_max_loss_decides(self):
        p = psx.build_plan("OGDC", bars(PRICES), ("pct", 4.0), ("r", 1.0), 306.5, CFG, utc(NOW))
        o = psx.size_order(p, CFG)
        self.assertEqual(o["qty"], 407)  # 5000 / 12.27
        self.assertEqual(o["decided_by"], "max loss per trade")
        self.assertLessEqual(o["max_loss_at_stop"], 5000)

    def test_the_position_cap_decides(self):
        o = psx.size_order(self.p, dict(CFG, max_loss_per_trade_pkr=500000))
        self.assertEqual(o["decided_by"], "position cap")
        self.assertEqual(o["qty"], 815)  # 250000 / 306.5

    def test_costs_shrink_the_order(self):
        self.assertLess(psx.size_order(self.p, dict(CFG, roundtrip_cost_pct=0.5))["qty"], 815)

    def test_nothing_fits_is_a_refusal(self):
        with self.assertRaises(psx.PsxError):
            psx.size_order(self.p, dict(CFG, max_loss_per_trade_pkr=1))


class Check(unittest.TestCase):
    def setUp(self):
        self.p = psx.build_plan("OGDC", bars(PRICES), ("pct", 2.0), ("r", 1.0), 306.5, CFG, utc(NOW))
        self.o = psx.size_order(self.p, CFG)

    def blocks(self, order=None, plan=None, cfg=CFG, trades=(), now=NOW):
        return psx.check_order(order or self.o, plan or self.p, cfg, list(trades), utc(now))[0]

    def has(self, word, **kw):
        self.assertTrue(any(word in b for b in self.blocks(**kw)), self.blocks(**kw))

    def test_a_clean_order_passes(self):
        self.assertEqual(self.blocks(), [])

    def test_a_missing_cost_setting_is_a_warning(self):
        self.assertTrue(any("roundtrip_cost_pct" in w for w in psx.check_order(self.o, self.p, CFG, [], utc(NOW))[1]))

    def test_yesterdays_close_as_an_entry_is_blocked(self):
        self.has("yesterday's close", plan=dict(self.p, entry_is_estimate=True))

    def test_outside_the_session(self):
        self.has("outside the entry window", now="2026-10-30 13:00")
        self.has("closed today", now="2026-10-31 11:00")

    def test_a_plan_from_another_day(self):
        self.has("not today", now="2026-11-02 10:00")

    def test_limits(self):
        self.has("over your max", cfg=dict(CFG, max_loss_per_trade_pkr=100))
        self.has("over your daily limit", cfg=dict(CFG, max_daily_loss_pkr=100))
        self.has("trades today", trades=[{"day": "2026-10-30"}] * 3)
        self.has("blocked list", cfg=dict(CFG, blocked=["OGDC"]))
        self.has("reward to risk", cfg=dict(CFG, min_reward_risk=2.0))
        self.has("% cap", cfg=dict(CFG, max_position_pct=1))

    def test_yesterdays_trades_do_not_count(self):
        self.assertEqual(self.blocks(trades=[{"day": "2026-10-29", "max_loss_at_stop": 99999}] * 3), [])

    def test_shape(self):
        self.has("only buys", order=dict(self.o, side="sell"))
        self.has("a stop is required", order=dict(self.o, stop_price=None))
        self.has("does not match the plan", order=dict(self.o, limit_price=306.0))
        self.has("outside the band", plan=dict(self.p, band=[1.0, 2.0]))
        self.has("already logged", trades=[{"day": "2026-10-30", "fingerprint": psx.fingerprint(self.o)}])


class Cli(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cwd = os.getcwd()
        os.chdir(self.tmp.name)
        self.addCleanup(os.chdir, self.cwd)
        os.mkdir("charts")
        with open(os.path.join("charts", "OGDC.json"), "w") as fh:
            json.dump(chart(weekdays(END, 30), PRICES), fh)
        os.mkdir("feeds")
        with open(os.path.join("feeds", "dawn.xml"), "wb") as fh:
            fh.write(RSS)

    def run_cli(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = psx.main(list(args))
        return code, out.getvalue() + err.getvalue()

    def test_the_whole_path(self):
        now = ["--now", NOW]
        self.assertEqual(self.run_cli("plan", "OGDC", "--entry", "306.5", "--stop", "pct:2", "--offline", "charts", "--write", *now)[0], 0)
        code, text = self.run_cli("ticket", *now)
        self.assertEqual(code, 1)  # no order yet
        self.assertEqual(self.run_cli("size", "--write", *now)[0], 0)
        code, text = self.run_cli("ticket", *now)
        self.assertEqual(code, 1)
        self.assertIn("NOT READY", text)
        code, text = self.run_cli("check", *now)
        self.assertEqual(code, 0, text)
        self.assertIn("PASS", text)
        code, text = self.run_cli("ticket", *now)
        self.assertEqual(code, 0)
        self.assertIn("BUY 815 OGDC", text)
        self.assertIn("Nothing is sent", text)
        self.assertEqual(self.run_cli("record", *now)[0], 0)
        code, text = self.run_cli("record", *now)
        self.assertEqual(code, 1)  # once only
        code, text = self.run_cli("check", *now)
        self.assertEqual(code, 1)
        self.assertIn("already logged", text)

    def test_a_plan_with_no_entry_cannot_reach_a_ticket(self):
        now = ["--now", NOW]
        self.run_cli("plan", "OGDC", "--offline", "charts", "--write", *now)
        self.run_cli("size", "--write", *now)
        code, text = self.run_cli("check", *now)
        self.assertEqual(code, 1)
        self.assertIn("yesterday's close", text)
        self.assertEqual(self.run_cli("ticket", *now)[0], 1)

    def test_scan_writes_its_own_watchlist_not_the_us_one(self):
        code, text = self.run_cli("scan", "--symbols", "OGDC,NOPE", "--offline", "charts", "--min-volume", "0", "--now", NOW)
        self.assertIn("1 failed", text)
        self.assertFalse(os.path.exists(os.path.join("trader", "watchlist.json")))
        self.assertTrue(os.path.exists(psx.WATCHLIST))

    def test_news_shows_an_item_once(self):
        args = ["news", "--tickers", "HBL", "--offline", "feeds", "--now", "2026-10-30 12:00"]
        code, text = self.run_cli(*args)
        self.assertEqual(code, 0)
        self.assertIn("Habib Bank", text)
        self.assertEqual(self.run_cli(*args)[0], 1)
        self.assertEqual(self.run_cli(*(args + ["--all"]))[0], 0)

    def test_clock_and_errors_are_plain_lines(self):
        self.assertIn("MIDDAY", self.run_cli("clock", "--now", "2026-10-30 13:00")[1].upper())
        code, text = self.run_cli("plan", "NOPE", "--offline", "charts", "--now", NOW)
        self.assertEqual(code, 1)
        self.assertNotIn("Traceback", text)
        code, text = self.run_cli("clock", "--now", "soon")
        self.assertEqual(code, 1)


def candle_doc(sym, days, make):
    """pyPSX's documented shape. make(day) -> [(HH:MM, o, h, l, c)]."""
    rows = []
    for d in days:
        for hm_, o, h, lo, c in make(d):
            rows.append(["%sT%s:00+05:00" % (d.isoformat(), hm_), o, h, lo, c, 1000])
    return {"results": [{"symbol": sym, "interval": "5m", "candles": rows, "gaps": [], "note": None}]}


THU = datetime.date(2026, 10, 29)
FRI = datetime.date(2026, 10, 30)
OPENING = [("09:30", 100, 101, 99, 100), ("09:35", 100, 102, 99.5, 101), ("09:40", 101, 102, 100, 101)]  # high 102, low 99


def bars_of(rows, day=THU):
    return psx.parse_candles(candle_doc("OGDC", [day], lambda d: rows))["OGDC"]["bars"]


def at(day, text):
    return datetime.datetime.combine(day, datetime.datetime.strptime(text, "%H:%M").time())


class Intraday(unittest.TestCase):
    def st(self, rows, when, day=THU, cfg=CFG):
        return psx.orb_status(bars_of(rows, day), at(day, when), 15, cfg)

    def test_times_become_pakistan_time(self):
        doc = {"results": [{"symbol": "X", "candles": [["2026-10-29T04:30:00Z", 1, 2, 0.5, 1.5, 9]]}]}
        self.assertEqual(psx.parse_candles(doc)["X"]["bars"][0]["t"], at(THU, "09:30"))

    def test_a_changed_shape_is_one_plain_error(self):
        with self.assertRaises(psx.PsxError):
            psx.parse_candles({"candles": []})

    def test_forming_waiting_triggered(self):
        self.assertEqual(self.st(OPENING, "09:40")["status"], "forming")
        rows = OPENING + [("09:45", 101, 101.5, 100, 101.2)]
        self.assertEqual(self.st(rows, "09:50")["status"], "waiting")
        rows = rows + [("09:50", 101, 104, 101, 103)]
        got = self.st(rows, "09:55")
        self.assertEqual((got["status"], got["price"], got["at"], got["or_high"], got["or_low"]), ("triggered", 103.0, "09:55", 102.0, 99.0))

    def test_a_high_above_the_range_is_not_a_close_above_it(self):
        rows = OPENING + [("09:45", 101, 105, 100, 101.9)]
        self.assertEqual(self.st(rows, "09:50")["status"], "waiting")

    def test_a_candle_still_forming_does_not_count(self):
        rows = OPENING + [("09:45", 101, 104, 101, 103)]
        self.assertEqual(self.st(rows, "09:49")["status"], "waiting")
        self.assertEqual(self.st(rows, "09:50")["status"], "triggered")

    def test_a_missing_opening_candle_is_unusable(self):
        self.assertEqual(self.st(OPENING[:2], "10:00")["status"], "unusable")

    def test_friday_opens_earlier(self):
        rows = [("09:15", 100, 101, 99, 100), ("09:20", 100, 102, 99.5, 101), ("09:25", 101, 102, 100, 101), ("09:30", 101, 104, 101, 103)]
        got = self.st(rows, "09:35", day=FRI)
        self.assertEqual((got["status"], got["at"]), ("triggered", "09:35"))

    def test_expired_and_closed(self):
        self.assertEqual(self.st(OPENING, "15:00")["status"], "expired")
        self.assertEqual(psx.orb_status([], at(datetime.date(2026, 10, 31), "10:00"), 15, CFG)["status"], "closed")

    def test_post_close_candles_cannot_fire_the_rule(self):
        rows = OPENING + [("15:25", 101, 101.5, 100, 101), ("15:30", 103, 103, 103, 103), ("15:35", 103, 103, 103, 103)]
        self.assertEqual(self.st(rows, "15:45")["status"], "expired")

    def test_the_friday_break_is_not_trading(self):
        rows = [("09:15", 100, 101, 99, 100), ("09:20", 100, 102, 99.5, 101), ("09:25", 101, 102, 100, 101),
                ("12:30", 103, 103, 103, 103), ("14:30", 101, 101, 101, 101)]
        self.assertEqual(self.st(rows, "13:00", day=FRI)["status"], "waiting")
        rows.append(("14:35", 101, 104, 101, 103))
        self.assertEqual(self.st(rows, "14:40", day=FRI)["at"], "14:40")

    def test_post_close_prices_do_not_reach_a_stop_or_target(self):
        rows = OPENING + [("09:45", 101, 104, 101, 103), ("15:35", 103, 110, 90, 103)]
        self.assertEqual(psx.replay_day(bars_of(rows), THU, 15, 1.0, CFG), "neither")

    def test_or_minutes_must_fit_the_grid(self):
        with self.assertRaises(psx.PsxError):
            psx.orb_status([], at(THU, "10:00"), 7, CFG)

    def test_replay_counts_only(self):
        win = OPENING + [("09:45", 101, 104, 101, 103), ("09:50", 103, 106, 103, 105.5)]     # entry 103, stop 100.5, target 105.5
        lose = OPENING + [("09:45", 101, 104, 101, 103), ("09:50", 103, 103, 100, 100.2)]
        both = OPENING + [("09:45", 101, 104, 101, 103), ("09:50", 103, 106, 100, 103)]
        quiet = OPENING + [("09:45", 101, 101.5, 100, 101)]
        idle = OPENING + [("09:45", 101, 104, 101, 103), ("09:50", 103, 103.5, 102.5, 103)]
        days = {datetime.date(2026, 10, 26): win, datetime.date(2026, 10, 27): lose, datetime.date(2026, 10, 28): both,
                datetime.date(2026, 10, 29): quiet, datetime.date(2026, 10, 22): idle}
        doc = candle_doc("OGDC", sorted(days), lambda d: days[d])
        c = psx.replay(psx.parse_candles(doc)["OGDC"]["bars"], 15, 1.0, CFG)
        self.assertEqual(c, {"sessions": 5, "fired": 4, "target": 1, "stop": 2, "neither": 1})

    def test_no_key_is_one_plain_line(self):
        saved = {k: os.environ.pop(k, None) for k in ("PYPSX_API_KEY_ID", "PYPSX_API_SECRET_KEY")}
        try:
            with self.assertRaises(psx.PsxError) as e:
                psx.pypsx_get("/x", {})
            self.assertIn("markets.pypsx.com", str(e.exception))
        finally:
            for k, v in saved.items():
                if v is not None:
                    os.environ[k] = v


class IntradayCli(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cwd = os.getcwd()
        os.chdir(self.tmp.name)
        self.addCleanup(os.chdir, self.cwd)
        with open("c.json", "w") as fh:
            json.dump(candle_doc("OGDC", [THU], lambda d: OPENING + [("09:45", 101, 104, 101, 103)]), fh)

    def run_cli(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = psx.main(list(args))
        return code, out.getvalue() + err.getvalue()

    def test_entry_and_orb_and_intraday(self):
        now = ["--now", "2026-10-29 10:00", "--offline", "c.json"]
        code, text = self.run_cli("entry", "OGDC", *now)
        self.assertEqual(code, 0)
        self.assertIn("TRIGGERED at 09:50", text)
        self.assertIn("--stop price:100.50", text)
        code, text = self.run_cli("orb", "--symbols", "OGDC,NOPE", *now)
        self.assertEqual(code, 0)
        self.assertIn("1 of 2 charts usable (1 no data", text)
        self.assertTrue(os.path.exists(psx.ORB_FILE))
        code, text = self.run_cli("intraday", "OGDC", *now)
        self.assertIn("newest candle closed 09:50, 10 minutes before", text)

    def test_at_cuts_the_clock(self):
        code, text = self.run_cli("entry", "OGDC", "--now", "2026-10-29 15:00", "--at", "09:48", "--offline", "c.json")
        self.assertEqual(code, 1)
        self.assertIn("waiting", text)

    def test_history_prints_no_profit_figure(self):
        code, text = self.run_cli("history", "OGDC", "--now", "2026-10-30 10:00", "--offline", "c.json")
        self.assertIn("fired 1 times", text)
        for word in ("profit", "P&L", "return"):
            self.assertNotIn(word, text)


class Limits(unittest.TestCase):
    def test_it_cannot_place_an_order_or_read_the_portal(self):
        with open(os.path.join(ROOT, "trader-psx", "psx.py"), encoding="utf-8") as fh:
            src = fh.read()
        code = src.split('"""', 2)[2]  # past the docstring, which names the portal to say why not
        self.assertNotIn("place_stock_order", code)
        self.assertNotIn("data=", code)
        self.assertNotIn("dps.psx.com.pk", code)
        self.assertNotIn("/orders", code)
        self.assertNotIn("api.pypsx.com/v", code)
        self.assertNotIn("POST", code)

    def test_no_real_market_data_is_committed(self):
        self.assertFalse(os.path.exists(os.path.join(ROOT, "tests", "fixtures", "trader-psx")))


if __name__ == "__main__":
    unittest.main()
