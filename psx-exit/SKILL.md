---
name: psx-exit
description: "Exit Planner for the Pakistan Stock Exchange. Sets the stop and target before you enter, so you know when to get out. Reads the entry from /psx-entry, puts the stop at the opening-range midpoint (or a percent, an ATR multiple or your price) and the target at 2R (or 1R, or your price), checks them against the daily price band, shows reward to risk after costs and writes trader/psx_plan.json. Use when the user says \"where is my stop\", \"set my stop and target\", \"plan the exit\", \"what is my R\", \"risk reward\", or right after /psx-entry triggers, before /psx-timemachine."
---

# psx-exit

Sets the plan before the money. It reads the symbol and the opening range from today's
`trader/psx_entry.json`, so no ticker is needed after /psx-entry.

`psx.py` below means `"${CLAUDE_SKILL_DIR}/../psx-core/psx.py"`, the engine all the psx-* skills
share. Run it from the user's project folder: `trader/` is written to the current folder.


```bash
python3 psx.py plan --entry 306.80 --write          # today's entry, stop at the range midpoint, 2R target
python3 psx.py plan OGDC --entry 306.80 --stop pct:2 --target 1R --write
```

Stop: `or-mid` (the default after a triggered entry), `atr`, `atr:1.5`, `pct:2`, `price:295.50`.
Target: `2R` (the default), `1R`, `1.5R`, `price:310`.

## Steps

1. Ask the user for the live price on their broker's screen. No free source here gives a live price.
2. Run `plan --entry PRICE --write`. Without `--entry` it uses the breakout candle or yesterday's close
   as an estimate, and /psx-risk will block it.
3. Say the entry, stop, target, risk per share, reward to risk after costs, the band and the flat-by time.
4. Hand on: `/psx-timemachine`.

## Rules

- It refuses a stop at or above the entry, a target at or below it, and an entry outside the band.
- Costs count: a tight stop can fail the reward-to-risk minimum even at 2R, so say so.
- A stop is a plan, not a guarantee. A stock locked at its band may not fill a stop at all, and a
  position may not be sellable that day.

## Safety

- Education and tooling, not financial advice. A PASS is a rules check, not a recommendation.
- Nothing in this pack can place an order. The user types every order into their own broker's
  app, after /psx-risk passes that exact order and they give their own explicit yes.
- No options, margin or short selling. Most people who day trade lose money.
