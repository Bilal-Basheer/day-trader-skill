---
name: psx-timemachine
description: "Time Machine for the Pakistan Stock Exchange. Replays every possible outcome of a trade before you risk a rupee: 10,000 simulated sessions built from the stock's own 5-minute candles over the last 59 full sessions, plus every past time the setup fired. Reads the plan from /psx-exit and prints the odds of target first, stop first or neither, where the price sits at the end, the average R, the history and one honest verdict after costs. Use when the user says \"run the time machine\", \"replay this trade\", \"what are the odds\", \"simulate this trade\", \"monte carlo\", \"backtest this setup\", \"is this a coin flip\", or after /psx-exit writes a plan, before /psx-budget."
---

# psx-timemachine

Sits between the plan and the money. If today plays out like the stock's own recent sessions, how often
does this plan hit the target first, the stop first, or neither? It is a simulation, not a prediction.

`psx.py` below means `"${CLAUDE_SKILL_DIR}/../psx-core/psx.py"`, the engine all the psx-* skills
share. Run it from the user's project folder: `trader/` is written to the current folder.
This step needs a pyPSX key in `PYPSX_API_KEY_ID` and `PYPSX_API_SECRET_KEY`. If it says the
key is missing, put `source ~/.zshrc >/dev/null 2>&1;` before the command. Never ask for a key in
the chat and never print one. pyPSX's docs state no delay figure, so say how old the newest candle is.


```bash
python3 psx.py timemachine                # trader/psx_plan.json, 10,000 replays, seed 19
python3 psx.py timemachine --write        # also save trader/psx_timemachine.json
python3 psx.py timemachine --until 15:25
```

Flags: `--replays N`, `--seed N`, `--window N` (default 2 candles), `--at 10:15`, `--now`, `--json`.

## How it works

1. **The pool.** Full sessions only, up to the last 59 before the plan's day. Candles at each time of
   day become ratios to the close before. Sessions with missing candles are left out.
2. **One replay.** From the entry, for each candle left until the flat-by time, draw a past candle from
   about that time of day (plus or minus 2 candles) and scale it. A candle touching both counts as the stop.
3. **10,000 replays** give the odds, the price range at the end and the average R before costs.
4. **The history** re-runs the breakout rule on those sessions, with the stop at the range midpoint.
5. **The verdict** compares how often the target came first with the break-even share after your costs.

It refuses with fewer than 20 full sessions. pyPSX's candles start on 20 October 2025.

## Steps

1. Run it, and report the odds, the history and the verdict as printed.
2. Hand on: `/psx-budget`, whatever the verdict. The user decides.

## Limits

- It cannot see results, a halt, a locked stock or a headline, and a real stop can fill worse.
- PSX Friday hours differ, so a Friday plan draws its later candles from fewer sessions.
- Never present the odds as a promise.

## Safety

- Education and tooling, not financial advice. A PASS is a rules check, not a recommendation.
- Nothing in this pack can place an order. The user types every order into their own broker's
  app, after /psx-risk passes that exact order and they give their own explicit yes.
- No options, margin or short selling. Most people who day trade lose money.
