---
name: psx-analyst
description: "Earnings Analyst for the Pakistan Stock Exchange. Sums up what changed in a PSX company's results from Pakistani business news and any report or filing the user provides: profit, EPS, revenue, margins and dividend, against the same period a year earlier. Use when the user says \"how did OGDC's results look\", \"analyze the earnings\", \"what changed this quarter\", \"sum up this report\", \"does it report this week\", or before trading a stock around its results."
---

# psx-analyst

The original reads SEC filings, which PSX companies do not file. PSX announcements are on the PSX Data
Portal, whose terms ban automated tools, so this works from the news feeds and from what the user gives it.

`psx.py` below means `"${CLAUDE_SKILL_DIR}/../psx-core/psx.py"`, the engine all the psx-* skills
share. Run it from the user's project folder: `trader/` is written to the current folder.


```bash
python3 psx.py news --tickers OGDC --hours 720 --no-market --all --dry-run
```

## Steps

1. Find the results stories with that command, and open each one.
2. Ask the user for the company's report or PSX notice if the stories are thin, as a PDF or pasted text.
   They can download it from the PSX Data Portal themselves.
3. Report the period, revenue, profit, EPS, margins and dividend, each against the same period a year
   earlier, with the source for every number. Say which numbers came from a news story and which from
   the company.
4. Say whether results are due inside the trade. Say so plainly if the date could not be confirmed.

## Rules

- Never invent or estimate a number. A missing figure is reported as missing.
- No predictions, and never a buy or sell call from results.
- Education and tooling, not financial advice.
