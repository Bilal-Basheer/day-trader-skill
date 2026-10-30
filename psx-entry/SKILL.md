---
name: psx-entry
description: "Entry Timer for the Pakistan Stock Exchange. Watches a setup bar by bar and says the moment to get in: builds the opening range from 5-minute candles and calls the entry on the first completed candle that CLOSES above the range high. Says waiting, triggered, expired or forming, for one symbol or the whole watchlist, and writes trader/psx_entry.json for /psx-exit. Long side only, and it never places an order. Use when the user says \"tell me when to get in\", \"watch OGDC\", \"has it broken out\", \"time my entry\", \"check my watchlist\", or after /psx-scanner and /psx-news, before /psx-exit."
---

# psx-entry

The opening range is the first 15 minutes of the session, on the 5-minute grid: 09:30, 09:35 and 09:40
Monday to Thursday, 09:15, 09:20 and 09:25 on Friday. The entry is the first completed candle to CLOSE
above its high. Post-close candles and the Friday break do not count.

`psx.py` below means `"${CLAUDE_SKILL_DIR}/../psx-core/psx.py"`, the engine all the psx-* skills
share. Run it from the user's project folder: `trader/` is written to the current folder.
This step needs a pyPSX key in `PYPSX_API_KEY_ID` and `PYPSX_API_SECRET_KEY`. If it says the
key is missing, put `source ~/.zshrc >/dev/null 2>&1;` before the command. Never ask for a key in
the chat and never print one. pyPSX's docs state no delay figure, so say how old the newest candle is.


```bash
python3 psx.py entry --watchlist          # every watchlist symbol, no ticker needed
python3 psx.py entry OGDC                 # one symbol -> trader/psx_entry.json
python3 psx.py watch OGDC --every 60      # keep checking until it triggers
python3 psx.py intraday OGDC              # the candles, and how old they are
```

Flags: `--at 10:15`, `--or-minutes 15`, `--now`, `--json`. Exit 0 when triggered.

## Steps

1. With no ticker, run `entry --watchlist`. List what triggered, when, and how far the last close has
   moved past the trigger.
2. For anything triggered, offer `python3 psx.py history SYMBOL --days 60` so the user sees how the rule
   went on past sessions. Counts only, with no costs or slippage.
3. **The user picks one, and may say "the first one". Never pick for them.** Run `entry SYMBOL` to save it.
4. Hand on: `/psx-exit`.

## Rules

- TRIGGERED reports when the rule fired, and that can be hours ago. Always say the time and how old
  the candle is. An old trigger is not an entry.
- Never call a candle live. The price to act on comes from the user's broker's screen.

## Safety

- Education and tooling, not financial advice. A PASS is a rules check, not a recommendation.
- Nothing in this pack can place an order. The user types every order into their own broker's
  app, after /psx-risk passes that exact order and they give their own explicit yes.
- No options, margin or short selling. Most people who day trade lose money.
