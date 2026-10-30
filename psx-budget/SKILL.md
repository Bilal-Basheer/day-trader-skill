---
name: psx-budget
description: "Budget Manager for the Pakistan Stock Exchange. Sizes every position to your budget and your max loss per trade, in rupees. Reads the plan from /psx-exit, finds the whole shares that fit inside your max loss, the position cap and the cash after your buffer, says which limit decided it, and writes one order to trader/psx_orders.json. Nothing is placed. Use when the user says \"how many shares\", \"size this trade\", \"how much should I buy\", \"set my rules\", \"set my budget\", or after /psx-timemachine, before /psx-risk."
---

# psx-budget

Turns the plan into one order, and refuses plainly when not even one share fits.

`psx.py` below means `"${CLAUDE_SKILL_DIR}/../psx-core/psx.py"`, the engine all the psx-* skills
share. Run it from the user's project folder: `trader/` is written to the current folder.


```bash
python3 psx.py size                       # show it
python3 psx.py size --write               # -> trader/psx_orders.json
```

## Settings

Limits live in `trader/psx_config.json`. If it is missing, copy `psx-core/psx_config.example.json`
there and ask the user for their numbers: the built-in defaults are placeholders.

`budget_pkr`, `cash_buffer_pct`, `max_position_pct`, `max_loss_per_trade_pkr`, `max_daily_loss_pkr`,
`max_trades_per_day`, `min_reward_risk`, `price_band_pct`, `roundtrip_cost_pct`,
`no_entries_first_minutes`, `no_entries_last_minutes`, `flat_by_minutes`, `blocked`, `holidays`,
`session_overrides`.

## Steps

1. Run `size --write`. Say the shares, the rupees, the max loss at the stop and which limit decided it.
2. Hand on: `/psx-risk`.

## Rules

- Whole shares only. PSX regular-market symbols trade in lots of one since 22 April 2024.
- The max loss is the loss at the stop price plus costs. A gap can make it worse.
- Set `roundtrip_cost_pct` to the broker's real commission and levies. It changes which trades pass.

## Safety

- Education and tooling, not financial advice. A PASS is a rules check, not a recommendation.
- Nothing in this pack can place an order. The user types every order into their own broker's
  app, after /psx-risk passes that exact order and they give their own explicit yes.
- No options, margin or short selling. Most people who day trade lose money.
