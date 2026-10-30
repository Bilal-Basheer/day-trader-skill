---
name: psx-risk
description: "Risk Manager for the Pakistan Stock Exchange. Checks every trade against your limits and stops anything over them: a stop is required, the loss at the stop must fit your max loss, reward to risk after costs must meet your minimum, the day's risk must fit your daily limit, no more than your trades per day, no entries outside the PSX entry window, inside the price band, and the entry must be a live price from your broker. Prints PASS or BLOCK with the reason. Use when the user says \"check my order\", \"is this safe\", \"risk check\", \"can I take this trade\", or before /psx-broker, always."
---

# psx-risk

The last check before a ticket exists. /psx-broker shows nothing that has not passed here today.

`psx.py` below means `"${CLAUDE_SKILL_DIR}/../psx-core/psx.py"`, the engine all the psx-* skills
share. Run it from the user's project folder: `trader/` is written to the current folder.


```bash
python3 psx.py check                      # PASS or BLOCK, exit 1 on BLOCK
python3 psx.py check --json
```

Verdicts are saved in `trader/state/psx_risk.json`.

## What blocks an order

Not a buy, or not matching the plan. A plan from another day. An entry that is an estimate rather than
the broker's live price. A blocked ticker. No stop, or stop, entry and target out of order. A quantity
that is not whole shares. An entry outside the price band. A loss over your max, or today's risk over
your daily limit. Too many trades today. Reward to risk after costs under your minimum. A position over
your cap. The same order already logged today. Outside the entry window, or the market closed.

It warns when costs are 0 and when no PSX holiday is recorded for the date.

## Steps

1. Run it. Say PASS or BLOCK and every reason. Never argue around a BLOCK.
2. On PASS, hand on: `/psx-broker`. On BLOCK, stop, or change the plan with `/psx-exit`.

Getting out is never blocked: /psx-broker prints a closing ticket at any time.

## Safety

- Education and tooling, not financial advice. A PASS is a rules check, not a recommendation.
- Nothing in this pack can place an order. The user types every order into their own broker's
  app, after /psx-risk passes that exact order and they give their own explicit yes.
- No options, margin or short selling. Most people who day trade lose money.
