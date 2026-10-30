---
name: psx-scanner
description: "Chart Scanner for the Pakistan Stock Exchange. Scans PSX charts for setups: opening-range breakouts on 5-minute candles during the session, and before the open a daily scan for 20-day closing-high breakouts, bull flags, a reclaimed 20-day average, oversold and oversold bounces. Knows PSX hours in Pakistan time and writes trader/psx_watchlist.json for /psx-news and /psx-entry. Use when the user says \"scan the PSX\", \"find me setups\", \"what is breaking out\", \"opening range breakouts\", \"pre-market scan\", \"build my watchlist\", \"what should I look at today\", or at the start of a PSX trading day before /psx-news."
---

# psx-scanner

The first step of a PSX day trade, and it needs no ticker. It lists charts that match a rule. That
is all it does. A scan is a list of charts that match a rule, not a list of stocks to buy.

`psx.py` below means `"${CLAUDE_SKILL_DIR}/../psx-core/psx.py"`, the engine all the psx-* skills
share. Run it from the user's project folder: `trader/` is written to the current folder.
This step needs a pyPSX key in `PYPSX_API_KEY_ID` and `PYPSX_API_SECRET_KEY`. If it says the
key is missing, put `source ~/.zshrc >/dev/null 2>&1;` before the command. Never ask for a key in
the chat and never print one. pyPSX's docs state no delay figure, so say how old the newest candle is.


```bash
python3 psx.py clock                      # open or closed, Pakistan time
python3 psx.py universe                   # about once a week: every PSX symbol from pyPSX
python3 psx.py scan --show 30             # before the open or after the close, Yahoo daily bars
python3 psx.py orb                        # during the session, 5-minute candles
python3 psx.py orb --at 10:15
python3 psx.py orb --watchlist            # only today's daily-scan hits, faster
```

Flags: `--symbols OGDC,HBL`, `--min-price`, `--min-volume`, `--or-minutes 15`, `--show N`,
`--now "2026-10-30 10:15"` (Pakistan time), `--no-write`, `--json`. Exit 0 when it found something.

Both write `trader/psx_watchlist.json`: `hits[].symbol` is what the next skills read.
`trader/psx_universe.txt` is used when it exists, else a short shipped list of 60 symbols. The full
list means one Yahoo request per symbol, so `scan` takes minutes: run it in the background.

## Steps

1. Run `clock`. It decides which scan applies, so do not ask the user.
2. Before the open or after the close: `scan`. During the session, from the first completed candle
   after the opening range (9:50 AM Monday to Thursday, 9:35 AM Friday): `orb`. In the first minutes,
   use the `scan` watchlist and say when `orb` will work.
3. Say what was scanned: how many symbols, how many charts came back, how many were usable and the
   date or time of the data.
4. Hand on: `/psx-news`, then `/psx-entry`. The user picks one chart. Never pick for them.

## Rules

- Say "matched a rule", never "a buy", "a winner" or "a good trade".
- Daily scans use closes only, so they say nothing about today. Say the date.
- A hit goes stale once the price moves. Re-run before acting on it.

## Safety

- Education and tooling, not financial advice. A PASS is a rules check, not a recommendation.
- Nothing in this pack can place an order. The user types every order into their own broker's
  app, after /psx-risk passes that exact order and they give their own explicit yes.
- No options, margin or short selling. Most people who day trade lose money.
