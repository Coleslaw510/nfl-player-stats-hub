# NFL Player Stats Hub

A fast, mobile-friendly static dashboard covering individual NFL **players**: leader charts, typeahead player search with league ranks and percentiles, a 2–4 player comparison tool with shareable links, full sortable leaderboards, and a stat glossary. Covers the 2026 season (updated weekly) plus 2025 for context.

**Live:** https://coleslaw510.github.io/nfl-player-stats-hub/
**Example compare:** https://coleslaw510.github.io/nfl-player-stats-hub/#compare=micah-parsons,montez-sweat&season=2025

## Files
- `index.html`, `style.css`, `app.js`: front end (Chart.js via CDN, no build step).
- `data/players_<season>.json`: one data file per season (stats, ranks, percentiles, ESPN win rates, metadata).
- `update_data.py`: refresh script. It downloads the sources into `raw/` (gitignored) and rebuilds the JSON.
- `preview.png`, `compare-preview.png`: screenshots.

## Refresh (weekly, e.g. Tuesday after Monday Night Football)

    python3 -m venv .venv && .venv/bin/pip install pandas pyarrow beautifulsoup4 lxml
    .venv/bin/python update_data.py --season 2026        # auto-detects last fully completed week
    .venv/bin/python update_data.py --season 2026 --through-week 8   # or pin a week
    git add data && git commit -m "Data through week N" && git push

If ESPN can't be reached, the script keeps the previous build's win rates and marks them stale.

## Sources
- **nflverse-data** (github.com/nflverse/nflverse-data releases): play-by-play with EPA, CPOE and success models; weekly player stats; rosters and headshots; snap counts; Next Gen Stats (time to throw, separation, YAC over expected, rush yards over expected); Pro Football Reference advanced defense (pressures, hurries, blitzes, coverage, missed tackles).
- **nflverse/nfldata** `games.csv`: schedule and results, used to find the last completed week and each team's games played.
- **ESPN Analytics win rates**, from ESPN's season article "<season> NFL pass rush, run stop, blocking win rate rankings":
  - Pass Rush and Run Stop win rates for Edge and DT.
  - Pass Block and Run Block win rates for OT and IOL.
  - ESPN publishes only the top 20 (pass rush, pass block) or top 10 (run stop, run block) per list. Everyone else shows "not published"; nothing is estimated.

## What's real vs proxied
- **EPA/dropback, EPA/rush, EPA/target, CPOE, success rate:** computed from nflverse play-by-play.
- **YPRR is not available.** Route counts for 2026 aren't public (PFF is paywalled, and nflverse participation data isn't published for current seasons). The site shows **receiving yards per team dropback in games played**, labeled as a *proxy*, along with yards per target and yards per offensive snap.
- **Win rates:** ESPN's published values and ranks only.

## Qualifiers
Ranks and percentiles compare a player only with qualified players in his own position group: QB, RB, WR, TE, OL, EDGE (DE/OLB), IDL, LB, CB, S.

| Stat type | Qualifier |
|---|---|
| Counting stats | ≥ 25% of team offensive/defensive snaps |
| Passing rates | ≥ 14 attempts per team game |
| Rushing rates | ≥ 6.25 carries per team game |
| Receiving rates | ≥ 1.875 receptions per team game |
| Coverage rates | ≥ 2 targets per team game |
| Missed tackle % | ≥ 2 tackle attempts per team game |

## URL routes
- `#leaders`, `#table`, `#glossary`
- `#player=<gsis id or name-slug>`
- `#compare=name-1,name-2[,name-3,name-4]`
- Add `&season=2025` to any route for 2025.
