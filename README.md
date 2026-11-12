# NFL Player Stats Hub

A fast, mobile-friendly static dashboard covering individual NFL **players**: leader charts, typeahead player search with league ranks and percentiles, a 2–4 player comparison tool with shareable links, full sortable leaderboards, **position power rankings** with week-to-week movement arrows, a **trade value estimator** (what a player is worth in draft picks, calibrated on real trades), and a stat glossary. Covers the 2026 season (updated weekly) plus 2025 for context.

**Live:** https://coleslaw510.github.io/nfl-player-stats-hub/
**Example compare:** https://coleslaw510.github.io/nfl-player-stats-hub/#compare=micah-parsons,montez-sweat&season=2025

## Files
- `index.html`, `style.css`, `app.js`: front end (Chart.js via CDN, no build step).
- `data/players_<season>.json`: one data file per season (stats, ranks, percentiles, ESPN win rates, metadata).
- `update_data.py`: refresh script. It downloads the sources into `raw/` (gitignored) and rebuilds the JSON.
- `power_rankings.py`: position power rankings (composite score per position) and the weekly history roll.
- `data/rankings_<season>.json`: current rankings with movement vs the previous week; `data/rankings_history.json`: every week's full rankings, `{season: {through_week: {group: {player_id: [rank, score]}}}}`.
- `data/trade_values_<season>.json`: trade-value estimate for every player with enough data (value, range, confidence, drivers, 3 comparable trades).
- `trades/trades.csv`: the calibration dataset of real veteran player-for-picks trades (committed).
- `trades/manual_trades_2026.csv`: 2026 trades made after the nflverse trade log's last entry, each row with a source URL.
- `trades/build_trades.py`, `trades/model.py`, `trades/common.py`: build the dataset, fit the model, score players.
- `trades/model.json`: fitted coefficients, accuracy and backtests.
- `preview.png`, `compare-preview.png`, `trade-preview.png`: screenshots.

## Refresh (weekly, e.g. Tuesday after Monday Night Football)

    python3 -m venv .venv && .venv/bin/pip install pandas pyarrow beautifulsoup4 lxml
    .venv/bin/python update_data.py --season 2026        # auto-detects last fully completed week
    .venv/bin/python update_data.py --season 2026 --through-week 9   # or pin a week
    git add data && git commit -m "Data through week N" && git push

Each refresh also runs `power_rankings.py`: it scores the week, stores it in `data/rankings_history.json` (re-running the same week overwrites that week only) and compares it with the latest earlier week, which drives the ▲/▼ arrows. Commit `data/rankings_*.json` with the rest of `data/`. Skip with `--no-rankings`.

If ESPN can't be reached, the script keeps the previous build's win rates and marks them stale.

`update_data.py` also refreshes the trade-value step for the season it builds: it re-downloads the nflverse trade log, draft value chart and Over The Cap contracts, builds any missing prior seasons into `raw/hist/` (2018 onward, first run only, a few minutes), then runs `trades/build_trades.py` and `trades/model.py`. Skip it with `--no-trade-values`. New trades after the nflverse log's last entry go in `trades/manual_trades_2026.csv` with a source URL.

## Power rankings
- **Tab:** `#rankings` (top 5 at every position) and `#rankings=<QB|RB|WR|TE|OL|EDGE|IDL|LB|CB|S>` (full list, sortable by rank, with key stats and component scores). Each player card shows his power ranking.
- **Score (0–100):** within each position's qualified pool, every input stat becomes a z-score (direction-corrected, capped at ±3, missing = average). Rate stats are shrunk toward average for small samples, z × n/(n+k), where n is dropbacks, carries, targets, coverage targets or defensive snaps. Stats are averaged into weighted components, the total is shrunk for games played (× g/(g+1.5)), then standardized: 50 = average qualified player, 16 points per SD.
- **Components (weights):**
  - QB: efficiency 45 (EPA/dropback, ANY/A, success rate, CPOE), passing production 25, rushing 10, ball security & sacks 10, availability 10.
  - RB: rushing production 25, rushing efficiency 25 (EPA/rush, RYOE/att, success, YPC), receiving 20, scrimmage total 15, availability & role 15.
  - WR: production 30, efficiency 30 (YPRR proxy, EPA/target, yds/target, catch %), earning targets 20, NGS separation/YACOE 8, availability & role 12.
  - TE: production 28, efficiency 25, targets 17, NGS 5, snap share 15, availability 10.
  - OL: ESPN pass block win rate 30, ESPN run block win rate 20, playing time 25, team sack rate 12.5, team designed-run EPA/success 12.5.
  - EDGE: pass rush 45 (pressures/100 snaps, pressures/g, sacks/g, hits, ESPN PRWR), run defense 20 (ESPN RSWR, TFL, tackles), playmaking 10, tackling 10, availability 15.
  - IDL: pass rush 40, run defense 30, playmaking 5, tackling 10, availability 15.
  - LB: tackling & run defense 35, coverage 25, pass rush 15, playmaking 5, availability 20.
  - CB: coverage 55 (rating/yds/cmp% allowed, targets per snap, PD, INT), tackling 15, playmaking 10, availability 20.
  - S: coverage 40, tackling & run support 30, playmaking 10, availability 20.
  - Exact stat weights and shrink constants are in `power_rankings.py` (`SPEC`) and on the page.
- **ESPN win rates** count by list standing, (size + 1 − rank)/size, and 0 if he isn't on ESPN's published top-N list.
- **Qualifiers:** QB ≥ 14 att per team game; RB ≥ 8 carries+targets per team game and ≥ 25% snaps; WR ≥ 3 targets per team game and ≥ 35% snaps; TE ≥ 1.5 targets per team game and ≥ 35% snaps; OL ≥ 50% snaps; EDGE/IDL ≥ 35%; LB ≥ 40%; CB/S ≥ 45%; everyone ≥ half his team's games.
- **Movement:** ▲n / ▼n = spots gained or lost vs the previous stored week, – = same spot, NEW = not ranked at that position that week. The Week 7 baseline was rebuilt with the same method (`update_data.py --through-week 7 --out-dir raw/wk7 --no-trade-values --espn-html <ESPN's Week 7 article from the Internet Archive>`, then `power_rankings.py --baseline raw/wk7/players_2026.json`). Use the same recipe to backfill any missed week.
- **Caveats:** OL has no public individual box-score stats, so its list leans on ESPN's top-N lists, snaps and team context. Coverage stats are PFR charting and noisy over half a season.

## Trade value estimator
- **Units:** Over The Cap (Fitzgerald-Spielberger) draft-value points from nflverse `draft_values.csv` (pick #1 = 3,000, #16 = 1,540, #32 = 1,175, #64 = 810, #96 = 596, #224 = 150). The card also shows the simplest 1–3 pick combination with about the same points (e.g. "≈ late 1st + 3rd").
- **Dataset (`trades/trades.csv`):** 312 real trades from 2019-03-13 to 2026-11-10 where one veteran (at least one prior NFL season, plus a real role: ≥25% snaps or a contract ≥2% of the cap) moved for draft picks. Source: the [nflverse trade log](https://github.com/nflverse/nfldata/blob/master/data/trades.csv) through 2026-04-17, then 2026 deals cited to [Pro Football Rumors](https://www.profootballrumors.com/2026/08/2026-nfl-trades), the [NFL.com deadline tracker](https://www.nfl.com/news/nfl-trade-deadline-track-every-move-since-start-of-2026-regular-season) and ESPN's trade trackers. Player-for-player swaps (e.g. Garrett for Verse + picks, Parsons for Clark + picks) are excluded. 127 of the trades returned ≥300 points (about a 5th-round pick or more); the rest are depth deals.
- **Pick valuation:** upcoming-draft picks with a known slot (trades from January to April) use the slot. Other picks use the middle of the round, and future picks move back one round (32 slots) per year.
- **Features at trade time:** quality 0–100 (from the hub's own season builds; see the glossary), age, Over The Cap contract (APY as % of cap, years left, rookie deal), draft pedigree for players in years 1–3, and position group.
- **Model:** weighted ridge regression on log(points). Recency weight has a 2.5-year half-life. Predictions are then stretched by √(sd ratio) so stars aren't shrunk to the middle. Fit on 309 trades with complete inputs. Leave-one-out median miss ×1.64, with 67% of trades within 2×. Out-of-time test (fit before 2025-03-01, scored on 87 later trades): median miss ×1.67, 66% within 2×. An always-average baseline misses by ×1.87.
- **Star premium:** a separate multiplier ×e^(k·tier). Tier (0–1) = quality factor (0 at 55, 1 at 75+) × market-esteem factor (APY 0 at 7% of cap, 1 at 10%+; rookie deals use the veteran market rate for his quality) × prime-age factor (1 through 29, 0 by 31) × position weight (QB/EDGE/IDL/WR/CB/OL 1.0, TE/S/LB 0.6, RB 0.4). k is fitted on the regression's residuals for tier players, weighted toward 2025–26 prices (0.75-year half-life) and shrunk toward 0: k = 0.258 (full-tier star ×1.29). Tier-0 players (most mid-tier and depth) are unchanged. Leave-one-out before → after: biggest 17 trades actual/predicted ×1.73 → ×1.61 (within 2×: 59% → 71%); overall median miss ×1.63 → ×1.64; depth trades unchanged. Full numbers and the spot-check table are in `trades/model.json` (`star_backtest`, `star_spot_check`). A convex quality-only boost was tested and dropped (it overpriced high-quality stars who sold cheaply).
- **Contract:** in real trades, higher-paid players fetched more picks because pay signals league esteem. A "market minus actual pay" surplus term and guarantee share were tested and lost in cross-validation, so cap hit and guarantees are displayed but not used in the formula. Rookie-scale deals are entered at the veteran market rate for the player's quality, and their extra years of control add value.
- **Confidence / insufficient data:** see the in-app glossary section "How trade value works".

## Current teams
Each player's team is his **current** team: ESPN's live team rosters (fetched at build time) win, then the latest nflverse weekly roster (released players marked CUT and on no ESPN roster show as free agents), then `trades/team_overrides.csv` (manual, cited) overrides everything. Season stats stay with the player; earlier 2026 teams are shown as "(prev. XXX)". Usage denominators (team dropbacks, team snaps, team games) use the games he was on each team. Every change vs the stats-only team is logged in `meta.team_changes` of `data/players_2026.json`.

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
- `#rankings`, `#rankings=WR` (power rankings)
- `#leaders`, `#table`, `#trade` (trade value leaderboard), `#glossary` (`#glossary=trade` for the trade-value explainer)
- `#player=<gsis id or name-slug>`
- `#compare=name-1,name-2[,name-3,name-4]`
- Add `&season=2025` to any route for 2025.
