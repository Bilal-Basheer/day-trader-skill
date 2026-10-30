---
name: psx-broker
description: "Order ticket for the Pakistan Stock Exchange. Shows each order that passed /psx-risk as a plain ticket to type into your own broker's app, such as AKD. It has no broker connection and cannot place an order. Records your order so the daily limits count it, and prints the ticket to close by your flat-by time. Use when the user says \"place the order\", \"buy it\", \"execute\", \"give me the ticket\", \"close my position\", \"flatten\", \"get me out\", or after /psx-risk passes."
---

# psx-broker

The original pack sends orders through a broker connector. No PSX broker connection is available here,
so this prints the ticket and the user types it into their broker's app.

`psx.py` below means `"${CLAUDE_SKILL_DIR}/../psx-core/psx.py"`, the engine all the psx-* skills
share. Run it from the user's project folder: `trader/` is written to the current folder.


```bash
python3 psx.py ticket                     # READY only with a PASS from today for this exact order
python3 psx.py record                     # after the user says they placed it
python3 psx.py close                      # the ticket to get out
```

## Steps

1. Run `ticket`. Show it in plain words. NOT READY means run `/psx-risk` first.
2. Ask the user for an explicit yes for that exact order, then tell them to place it themselves.
3. When they say it is placed, run `record`. Daily limits only count what is recorded. In paper practice,
   skip `record` unless they want it counted.
4. Hand on: `/psx-alerts`.
5. When they want out, run `close`. Getting out is never blocked.

## Rules

- Never claim an order was placed. Only the user can do that.
- Not every PSX broker offers stop or bracket orders. If theirs does not, they watch the levels themselves.
- Ask the broker how same-day selling is charged and treated. It was not confirmed anywhere.

## Safety

- Education and tooling, not financial advice. A PASS is a rules check, not a recommendation.
- Nothing in this pack can place an order. The user types every order into their own broker's
  app, after /psx-risk passes that exact order and they give their own explicit yes.
- No options, margin or short selling. Most people who day trade lose money.
