---
name: psx-alerts
description: "Price Alerts for the Pakistan Stock Exchange. Rings when a price, a stop, a target, a time or the opening bell hits. Turns the plan into three alerts in one go (stop, target, flat by), plus above and below levels and reminders, each ringing once. Knows PSX hours and works in Pakistan time. Use when the user says \"alert me when\", \"tell me if OGDC hits\", \"watch my stop\", \"watch my trade\", \"remind me to close\", \"is the PSX open\", \"when does the market open\", or right after /psx-broker."
---

# psx-alerts

Watches the numbers so the user does not have to stare at a chart. An alert is information, never an
order: when a stop alert rings, nothing is sold.

`psx.py` below means `"${CLAUDE_SKILL_DIR}/../psx-core/psx.py"`, the engine all the psx-* skills
share. Run it from the user's project folder: `trader/` is written to the current folder.
This step needs a pyPSX key in `PYPSX_API_KEY_ID` and `PYPSX_API_SECRET_KEY`. If it says the
key is missing, put `source ~/.zshrc >/dev/null 2>&1;` before the command. Never ask for a key in
the chat and never print one. pyPSX's docs state no delay figure, so say how old the newest candle is.


```bash
python3 psx.py clock                                # open or closed, next open
python3 psx.py alert-add --from-plan                # stop, target, flat by
python3 psx.py alert-add --symbol OGDC --above 320
python3 psx.py alert-add --symbol OGDC --below 300
python3 psx.py alert-add --at 15:25 --label "flat by close"
python3 psx.py alert-add --opening-bell
python3 psx.py alert-check                          # exit 0 means something rang
python3 psx.py alert-list
python3 psx.py alert-reset ogdc-stop-300.64
```

Alerts are kept in `trader/psx_alerts.json`. Plan alerts only ring on the plan's day.

## Steps

1. Right after a plan: `alert-add --from-plan`.
2. While the trade is open, run `alert-check`, or `/loop 5m /psx-alerts`. New candles only come every
   5 minutes.
3. When one rings, say what hit and when, and that nothing was sold. Point to `/psx-broker` for the
   closing ticket.

## Limits

Alerts are as late as the candles, and the delay has not been measured. Price levels are checked on
regular-market candle highs and lows. Never rely on an alert as your only stop.

## Safety

- Education and tooling, not financial advice. A PASS is a rules check, not a recommendation.
- Nothing in this pack can place an order. The user types every order into their own broker's
  app, after /psx-risk passes that exact order and they give their own explicit yes.
- No options, margin or short selling. Most people who day trade lose money.
