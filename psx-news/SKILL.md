---
name: psx-news
description: "News Monitor for the Pakistan Stock Exchange. Tracks news on every stock on the PSX watchlist from Business Recorder, Dawn, Express Tribune and ProPakistani RSS feeds, shows only what is new, newest first in Pakistan time, tags each item (earnings, macro, regulatory, deal, capital, halt, legal, people) and never repeats one. Use when the user says \"any news on OGDC\", \"why is this moving\", \"what is the news on my watchlist\", \"morning briefing\", \"PSX news\", \"did anything break\", or after /psx-scanner finds setups."
---

# psx-news

A chart can look perfect and still be about to gap on results, a halt or a court order. This reads
Pakistani business feeds for the watchlist and reports only what is new. No ticker is needed.

`psx.py` below means `"${CLAUDE_SKILL_DIR}/../psx-core/psx.py"`, the engine all the psx-* skills
share. Run it from the user's project folder: `trader/` is written to the current folder.


```bash
python3 psx.py news                        # the plan and the watchlist
python3 psx.py news --tickers OGDC,HBL --hours 24
python3 psx.py news --all --dry-run        # include items already seen, change nothing
```

`--no-market` leaves out market-wide items. Seen items are kept in `trader/state/psx_news.json`.
Exit 1 means nothing new.

## Steps

1. Run it. With no `--tickers` it reads `trader/psx_plan.json` and `trader/psx_watchlist.json`.
2. Open every item that matters before saying something happened: earnings, halt, legal, regulatory,
   and anything naming a watchlist stock. Quote the source and link it. If a story could not be read,
   say so.
3. Write a short brief per ticker: what happened, the source, and one line on why it matters to the
   setup, like "results are due: an overnight gap can jump past any stop".
4. If a story changes the picture, say so before `/psx-entry`. When a ticker has no news, say that.

## Limits

- Matching is on the headline's ticker or company name, so a story inside a market report can be
  missed. Read the market reports too.
- PSX company announcements are not included, because the PSX Data Portal's terms ban automated
  tools. The user reads those on the portal.
- Headlines are leads, not facts. No predictions, and never trade on a headline alone.

## Safety

- Education and tooling, not financial advice. A PASS is a rules check, not a recommendation.
- Nothing in this pack can place an order. The user types every order into their own broker's
  app, after /psx-risk passes that exact order and they give their own explicit yes.
- No options, margin or short selling. Most people who day trade lose money.
