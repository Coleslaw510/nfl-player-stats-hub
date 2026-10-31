# NFL Player Stats Hub

A fast, mobile-friendly static dashboard covering individual NFL **players**: leader charts, typeahead player search with league ranks and percentiles, a 2–4 player comparison tool with shareable links, full sortable leaderboards, a **trade value estimator** (what a player is worth in draft picks, calibrated on real trades), and a stat glossary. Covers the 2026 season (updated weekly) plus 2025 for context.

**Live:** https://coleslaw510.github.io/nfl-player-stats-hub/
**Example compare:** https://coleslaw510.github.io/nfl-player-stats-hub/#compare=micah-parsons,montez-sweat&season=2025

## Files
- `index.html`, `style.css`, `app.js`: front end (Chart.js via CDN, no build step).
- `data/players_<season>.json`: one data file per season (stats, ranks, percentiles, ESPN win rates, metadata).
- `update_data.py`: refresh script. It downloads the sources into `raw/` (gitignored) and rebuilds the JSON.
- `data/trade_values_<season>.json`: trade-value estimate for every player with enough data (value, range, confidence, drivers, 3 comparable trades).
- `trades/trades.csv`: the calibration dataset of real veteran player-for-picks trades (committed).
- `trades/manual_trades_2026.csv`: 2026 trades made after the nflverse trade log's last entry, each row with a source URL.
- `trades/build_trades.py`, `trades/model.py`, `trades/common.py`: build the dataset, fit the model, score players.
- `trades/model.json`: fitted coefficients, accuracy and backtests.
- `preview.png`, `compare-preview.png`, `trade-preview.png`: screenshots.

## Refresh (weekly, e.g. Tuesday after Monday Night Football)

    python3 -m venv .venv && .venv/bin/pip install pandas pyarrow beautifulsoup4 lxml
    .venv/bin/python update_data.py --season 2026        # auto-detects last fully completed week
    .venv/bin/python update_data.py --season 2026 --through-week 8   # or pin a week
    git add data && git commit -m "Data through week N" && git push

If ESPN can't be reached, the script keeps the previous build's win rates and marks them stale.

`update_data.py` also refreshes the trade-value step for the season it builds: it re-downloads the nflverse trade log, draft value chart and Over The Cap contracts, builds any missing prior seasons into `raw/hist/` (2018 onward, first run only, a few minutes), then runs `trades/build_trades.py` and `trades/model.py`. Skip it with `--no-trade-values`. New trades after the nflverse log's last entry go in `trades/manual_trades_2026.csv` with a source URL.

## Trade value estimator
- **Units:** Over The Cap (Fitzgerald-Spielberger) draft-value points from nflverse `draft_values.csv` (pick #1 = 3,000, #16 = 1,540, #32 = 1,175, #64 = 810, #96 = 596, #224 = 150). The card also shows the simplest 1–3 pick combination with about the same points (e.g. "≈ late 1st + 3rd").
- **Dataset (`trades/trades.csv`):** 302 real trades from 2019-03-13 to 2026-10-29 where one veteran (at least one prior NFL season, plus a real role: ≥25% snaps or a contract ≥2% of the cap) moved for draft picks. Source: the [nflverse trade log](https://github.com/nflverse/nfldata/blob/master/data/trades.csv) through 2026-04-17, then 2026 deals cited to [Pro Football Rumors](https://www.profootballrumors.com/2026/08/2026-nfl-trades), the [NFL.com deadline tracker](https://www.nfl.com/news/nfl-trade-deadline-track-every-move-since-start-of-2026-regular-season) and ESPN's trade trackers. Player-for-player swaps (e.g. Garrett for Verse + picks, Parsons for Clark + picks) are excluded. 121 of the trades returned ≥300 points (about a 5th-round pick or more); the rest are depth deals.
- **Pick valuation:** upcoming-draft picks with a known slot (trades from January to April) use the slot. Other picks use the middle of the round, and future picks move back one round (32 slots) per year.
- **Features at trade time:** quality 0–100 (from the hub's own season builds; see the glossary), age, Over The Cap contract (APY as % of cap, years left, rookie deal), draft pedigree for players in years 1–3, and position group.
- **Model:** weighted ridge regression on log(points). Recency weight has a 2.5-year half-life. Predictions are then stretched by √(sd ratio) so stars aren't shrunk to the middle. Fit on 299 trades with complete inputs. Leave-one-out median miss ×1.60, with 69% of trades within 2×. Out-of-time test (fit before 2025-03-01, scored on 77 later trades): median miss ×1.59, 68% within 2×. An always-average baseline misses by ×1.86.
- **Contract:** in real trades, higher-paid players fetched more picks because pay signals league esteem. A "market minus actual pay" surplus term and guarantee share were tested and lost in cross-validation, so cap hit and guarantees are displayed but not used in the formula. Rookie-scale deals are entered at the veteran market rate for the player's quality, and their extra years of control add value.
- **Confidence / insufficient data:** see the in-app glossary section "How trade value works".

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
- `#leaders`, `#table`, `#trade` (trade value leaderboard), `#glossary` (`#glossary=trade` for the trade-value explainer)
- `#player=<gsis id or name-slug>`
- `#compare=name-1,name-2[,name-3,name-4]`
- Add `&season=2025` to any route for 2025.
