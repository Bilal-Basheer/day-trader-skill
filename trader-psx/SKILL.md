---
name: trader-psx
description: Pakistan Stock Exchange (PSX) workflow on free data. Scans daily setups from Yahoo's daily bars for Karachi symbols, reads Pakistani business RSS feeds (Business Recorder, Dawn, Express Tribune, ProPakistani), knows PSX sessions in Pakistan time including the split Friday, sets a stop and target in rupees inside the daily price band, sizes whole shares to your PKR limits, checks PASS or BLOCK, and prints a ticket you type into your own broker's app. With your own pyPSX key it adds 5-minute candles: opening-range breakouts, an entry check and a replay on past sessions. It never places an order. Use when the user says "PSX", "KSE", "Pakistan stocks", "scan the PSX", "is the PSX open", "OGDC", "HBL", "LUCK", "size this PSX trade", or asks to trade a Pakistani stock.
---

# trader-psx

The eleven US skills in this pack do not work on the Pakistan Stock Exchange:
their calendar, symbol list, filings and broker are all American. This skill is
the PSX version of the same path, built only on data that is free and open to a
tool. That has one large consequence:

**Without a key this works from yesterday's close.** Yahoo answers a 5-minute
request for a Karachi symbol with daily bars. **With your own pyPSX key** it reads
5-minute candles for opening-range breakouts, an entry check and a replay on past
sessions. Either way you supply the live price from your broker's screen: pyPSX's
docs state no delay figure, so the tool prints how old each candle is. Check that
against your broker before trusting it.

Most people who day trade lose money. A scan is a list of charts that match a
rule, not a list of stocks to buy.

`psx.py` below means the full path to the script in this skill's folder. Run it from
the user's project folder, never from the skill's folder: `trader/` is written to the
current folder.

```bash
python3 psx.py clock                                 # open? Pakistan time, next open
python3 psx.py scan                                  # -> trader/psx_watchlist.json
python3 psx.py scan --symbols OGDC,HBL,LUCK --show 10
python3 psx.py news --tickers OGDC,HBL --hours 24    # Pakistani RSS, new items only
python3 psx.py plan OGDC --entry 306.50 --stop pct:2 --target 1R --write
python3 psx.py size --write                          # -> trader/psx_orders.json
python3 psx.py check                                 # PASS / BLOCK
python3 psx.py ticket                                # type this into your broker's app
python3 psx.py record                                # after you have placed it

# these need a pyPSX key
python3 psx.py intraday OGDC                         # today's 5-minute candles and their age
python3 psx.py orb --symbols OGDC,HBL --at 10:15     # -> trader/psx_orb.json
python3 psx.py entry OGDC                            # waiting / triggered / expired
python3 psx.py history OGDC --days 60 --target 1R    # the same rule on past sessions
```

Key setup: sign up at markets.pypsx.com, open the Dashboard and click Generate New
Keys, then set `PYPSX_API_KEY_ID` and `PYPSX_API_SECRET_KEY` in the environment.
Never ask for a key in the chat, and never print one.

Flags: `--now "2026-10-30 10:15"` (Pakistan time) pins the clock, `--offline DIR`
reads saved files, `--json`, `--config PATH`. Exit code 0 on a result, 1 on nothing
found or a BLOCK.

## Where the data comes from

| source | used for | limits |
| --- | --- | --- |
| Yahoo chart JSON, `SYMBOL.KA` | daily open, high, low, close, volume | Unofficial, can lag. Today's bar is empty until after the close. The meta price is years old, so only the bars are read. |
| Business Recorder, Dawn, Express Tribune, ProPakistani RSS | headlines | Matched on company name or ticker, so a story can be missed or matched wrongly. |
| pyPSX API (`paper-api.pypsx.com`), your key | 5-minute candles from 20 Oct 2025, read only | Proprietary third party, not affiliated with PSX. Its docs state no terms, no delay figure and no PSX licence, and sandbox keys can return synthetic data. Check candles against your broker first. |
| `psx_universe.txt` | the 60 symbols to scan | A hand-checked list, not an index. Add your own. Yahoo had no chart for HUBC, ENGRO, ENGROH, AVN or PSMC. |

**The PSX Data Portal (`dps.psx.com.pk`) is not read, on purpose.** Its terms ban
"spiders, robots, avatars, agents, tools" without PSX's written permission, and
licences for market data go through `marketdatarequest@psx.com.pk`. Do not add a
scraper for it. Read company announcements there yourself. For intraday data use
a licensed vendor from PSX's vendor list, or get PSX's permission.

## The PSX rules it uses

| rule | value | source and status |
| --- | --- | --- |
| Regular market, Monday to Thursday | 09:32 to 15:30 | psx.com.pk trading-hours page, read 2026-10-30 |
| Regular market, Friday | 09:17 to 12:00 and 14:32 to 16:30 | same page |
| Time zone | UTC+5, no daylight saving | |
| Lot size | 1 share | PSX change from 22 April 2024, ETFs and some others excluded |
| Settlement | T+1 | SECP, from 9 February 2026. Not used in the arithmetic |
| Price band | 10 % around the previous close | **Config.** kasb.com, June 2025, varies by category. Check your stock |
| Costs | 0 % until you set it | **Config.** Set `roundtrip_cost_pct` to your broker's commission and levies |
| Holidays | closures with a notice found | **Incomplete.** Nothing recorded after 2026-08-26. Add the rest in the config |
| Ramadan hours | not built in | **Config.** Add them under `session_overrides` |

Not confirmed anywhere: blank-sale rules, how each broker treats same-day
selling, and whether your broker offers stop orders. Ask your broker.

## Steps

1. Copy `psx_config.example.json` to `trader/psx_config.json` and set your limits,
   your costs and any holidays. Remove the 2099 examples.
2. `psx.py clock`, then `psx.py scan`. Say what was scanned: the symbols, how many
   charts came back, and the date of the last close.
3. `psx.py news` for what the user is looking at. Open a story before saying that
   something happened. Say so if it could not be read.
4. The user picks a chart and reads the live price off their broker's screen. Never
   pick for them. Then `psx.py plan SYMBOL --entry PRICE --write`.
5. `psx.py size --write`, then `psx.py check`. A plan without `--entry` is blocked,
   because yesterday's close is not a price you can buy at.
   With a key, `psx.py entry SYMBOL` says when the breakout rule fires and
   `psx.py history SYMBOL` counts how it went on past sessions. Neither replaces the
   live price: still plan with `--entry` from the broker's screen.
6. On PASS, `psx.py ticket`. The user places it themselves, then `psx.py record`.
   Daily limits only count what is recorded.

## Rules

- Say "matched a rule", never "a buy", "a winner" or "a good trade".
- Say the date of the data every time. These are closes, not live prices.
- Never call a Yahoo price or a pyPSX candle live, and never print a P&L or a return.
- `history` counts past sessions with no costs or slippage: it is not a prediction.
- A band can lock a stock: a stop order may not fill at all, and a position may not
  be sellable that day. Say so.

## What it never does

It never places, sends or routes an order, has no broker connection, does not sell
short, does not use margin, does not read the PSX Data Portal, and only reads from
pyPSX: it does not use pyPSX's trading endpoints.

## Safety

- Education and tooling, not financial advice. A PASS is a rules check, not a recommendation.
- No order reaches a broker from this skill. The user types it, after a PASS and their own explicit yes.
- Check prices against your broker before you act. Free data can be wrong or late.
- Trading rules change. Check PSX and SECP notices, and talk to a licensed professional if you need advice.
