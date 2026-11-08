#!/usr/bin/env python3
"""Rebuild data/players_<season>.json for the NFL Player Stats Hub.

Sources
* nflverse-data releases (github.com/nflverse/nflverse-data): play-by-play, weekly player stats, rosters,
  snap counts, Next Gen Stats, PFR advanced defense; schedule from nflverse/nfldata games.csv.
* ESPN Analytics player win rates (PRWR / RSWR / PBWR / RBWR) from ESPN's season win-rate article.

Usage:  python3 update_data.py --season 2026 [--through-week N] [--offline]
Without --through-week it uses the last regular-season week in which every game is final.
"""
import argparse, json, math, os, re, sys, time, unicodedata, datetime as dt
import urllib.request
import pandas as pd, numpy as np
from bs4 import BeautifulSoup

REL = "https://github.com/nflverse/nflverse-data/releases/download"
FILES = {  # local name -> release path
    "pbp": "pbp/play_by_play_{s}.parquet",
    "week": "stats_player/stats_player_week_{s}.parquet",
    "roster": "rosters/roster_{s}.parquet",
    "snaps": "snap_counts/snap_counts_{s}.parquet",
    "pfrdef": "pfr_advstats/advstats_week_def_{s}.parquet",
    "ngs_passing": "nextgen_stats/ngs_passing.parquet",
    "ngs_receiving": "nextgen_stats/ngs_receiving.parquet",
    "ngs_rushing": "nextgen_stats/ngs_rushing.parquet",
    "players": "players/players.parquet",
}
GAMES_URL = "https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv"
ESPN_WR = {2026: "https://www.espn.com/nfl/story/_/id/49742016/2026-win-rates-team-player-rankings-pass-rush-run-stop-blocking",
           2025: "https://www.espn.com/nfl/story/_/id/46138675/2025-nfl-win-rates-top-teams-players-rankings-pass-run-block"}
ESPN_SEARCH = "https://site.web.api.espn.com/apis/search/v2"
HEAD_PREFIX = "https://static.www.nfl.com/image/upload/f_auto,q_auto/league/"
UA = {"User-Agent": "Mozilla/5.0 nfl-player-stats-hub"}

def fetch(url, path, offline=False, max_age_h=6):
    if os.path.exists(path) and (offline or time.time() - os.path.getmtime(path) < max_age_h * 3600):
        return path
    for i in range(4):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=120) as r:
                data = r.read()
            open(path, "wb").write(data); return path
        except Exception as e:
            print(f"  retry {url}: {e}", file=sys.stderr); time.sleep(3 * (i + 1))
    if os.path.exists(path): return path
    raise RuntimeError(f"download failed: {url}")

def raw(name, season, offline):
    rel = FILES[name].format(s=season)
    return fetch(f"{REL}/{rel}", f"raw/{os.path.basename(rel)}", offline)

def norm(s):
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"\b(jr|sr|ii|iii|iv|v)\b\.?", "", s)
    return re.sub(r"[^a-z]", "", s)

ESPN_TEAM = {"AZ": "ARI", "WSH": "WAS", "LAR": "LA", "JAC": "JAX", "LV": "LV"}

def find_espn_article(season):
    try:
        q = urllib.parse.urlencode({"query": f"{season} NFL pass rush run stop blocking win rate rankings", "limit": 10, "type": "article"})
        with urllib.request.urlopen(urllib.request.Request(f"{ESPN_SEARCH}?{q}", headers=UA), timeout=30) as r:
            sj = json.load(r)
        want = f"{season} nfl pass rush, run stop, blocking win rate rankings"
        for res in sj.get("results", []):
            for c in res.get("contents", []):
                head = (c.get("displayName") or c.get("headline") or "").strip().lower()
                link = (c.get("link") or {}).get("web") if isinstance(c.get("link"), dict) else None
                if link and head == want: return link
    except Exception as e:
        print(f"  ESPN search failed ({e}); using known URL", file=sys.stderr)
    return ESPN_WR.get(season)

def espn_win_rates(season, offline, html=None):
    """html: optional saved copy of the article (e.g. an archived earlier-week version, used for ranking baselines)."""
    url = ESPN_WR.get(season) if html else find_espn_article(season)
    if not url: return None, []
    path = html or fetch(url, f"raw/espn_wr_{season}.html", offline)
    soup = BeautifulSoup(open(path, encoding="utf-8").read(), "lxml")
    hs = [h.get_text(" ", strip=True) for h in soup.find_all("h1")] + [soup.title.get_text(" ", strip=True) if soup.title else ""]
    headline = next((h for h in hs if "win rate" in h.lower()), hs[0] if hs else "").replace(" - ESPN", "")
    if str(season) not in headline: raise RuntimeError(f"ESPN article headline {headline!r} is not {season}")
    txt = soup.get_text(" ", strip=True)
    m = re.search(r"Last updated:\s*(.{5,80}?(?:a\.m\.|p\.m\.)(?: ET)?)", txt)
    upd = m.group(1).strip() if m else None
    wk = re.search(r"Week (\d+)", upd or "")
    rows = []
    for t in soup.find_all("table"):
        h = t.find_previous(["h2", "h3", "h4"]); title = h.get_text(" ", strip=True) if h else ""
        mm = re.match(r"(Edge|DT|OT|IOL) (pass rush|run stop|pass block|run block) win rate", title, re.I)
        if not mm: continue
        metric = {"pass rush": "prwr", "run stop": "rswr", "pass block": "pbwr", "run block": "rbwr"}[mm.group(2).lower()]
        trs = t.find_all("tr")
        for tr in trs[1:]:
            c = [x.get_text(" ", strip=True) for x in tr.find_all(["td", "th"])]
            if len(c) < 6 or not c[0].strip().isdigit(): continue
            rows.append(dict(metric=metric, list=mm.group(1), rank=int(c[0]), name=re.sub(r"\s+\.", ".", c[1]), team=ESPN_TEAM.get(c[2], c[2]),
                             wins=int(c[3]), plays=int(c[4]), rate=float(c[5].rstrip("%")), list_size=len(trs) - 1))
    meta = dict(url=url, headline=headline, updated=upd, through_week=int(wk.group(1)) if wk else None,
                fetched=dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), rows=len(rows))
    return meta, rows

ESPN_ROSTER = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/teams/{id}/roster"
def espn_rosters(offline):
    """Current ESPN team rosters (all 32 teams): espn_id -> team, and normalized name -> {teams}."""
    os.makedirs("raw/espn_rosters", exist_ok=True)
    tl = json.load(open(fetch("https://site.api.espn.com/apis/site/v2/sports/football/nfl/teams", "raw/espn_rosters/_teams.json", offline)))
    by_id, by_name = {}, {}
    for t in tl["sports"][0]["leagues"][0]["teams"]:
        t = t["team"]; ab = ESPN_TEAM.get(t["abbreviation"], {"LAR": "LA"}.get(t["abbreviation"], t["abbreviation"]))
        j = json.load(open(fetch(ESPN_ROSTER.format(id=t["id"]), f"raw/espn_rosters/{t['abbreviation']}.json", offline)))
        for g in j.get("athletes", []):
            for a_ in g.get("items", []):
                by_id[str(a_["id"])] = ab; by_name.setdefault(norm(a_["fullName"]), set()).add(ab)
    return by_id, by_name

def load_overrides():
    """trades/team_overrides.csv: manual current-team fixes (gsis_id, name, team, date, source). Empty team = free agent."""
    f = "trades/team_overrides.csv"
    if not os.path.exists(f): return {}
    o = pd.read_csv(f, dtype=str).fillna("")
    return {r.gsis_id: dict(team=r.team or None, date=r.date, source=r.source, name=r.name) for r in o.itertuples()}

GROUP = {"QB": "QB", "RB": "RB", "FB": "RB", "WR": "WR", "TE": "TE", "T": "OL", "G": "OL", "C": "OL", "OT": "OL", "OG": "OL", "OL": "OL",
         "DE": "EDGE", "OLB": "EDGE", "DT": "IDL", "NT": "IDL", "DL": "IDL", "ILB": "LB", "MLB": "LB", "LB": "LB",
         "CB": "CB", "FS": "S", "SS": "S", "S": "S", "DB": "S", "SAF": "S", "K": "ST", "P": "ST", "LS": "ST"}
OFF = {"QB", "RB", "WR", "TE", "OL"}; DEF = {"EDGE", "IDL", "LB", "CB", "S"}

# key, label, category, higher_is_better, fmt, qualifier, groups
S = []
def st(k, label, cat, hb, fmt, q, groups, desc=""):
    S.append(dict(k=k, label=label, cat=cat, hb=hb, fmt=fmt, q=q, groups=groups, desc=desc))
P = ["QB"]; RU = ["QB", "RB", "WR", "TE"]; RE = ["RB", "WR", "TE"]; D = sorted(DEF); FRONT = ["EDGE", "IDL", "LB"]
st("pass_att", "Pass attempts", "Passing", 1, "int", "snap", P)
st("cmp", "Completions", "Passing", 1, "int", "snap", P)
st("cmp_pct", "Completion %", "Passing", 1, "pct1", "pass", P)
st("pass_yds", "Passing yards", "Passing", 1, "int", "snap", P)
st("pass_ypg", "Passing yards / game", "Passing", 1, "f1", "pass", P)
st("pass_td", "Passing TD", "Passing", 1, "int", "snap", P)
st("int", "Interceptions thrown", "Passing", 0, "int", "pass", P)
st("ypa", "Yards / attempt", "Passing", 1, "f2", "pass", P)
st("anya", "ANY/A", "Passing", 1, "f2", "pass", P, "(pass yds + 20·TD − 45·INT − sack yds) / (att + sacks)")
st("rating", "Passer rating", "Passing", 1, "f1", "pass", P)
st("epa_db", "EPA / dropback", "Passing", 1, "f3", "pass", P, "nflverse qb_epa averaged over dropbacks (passes, sacks, scrambles)")
st("cpoe", "CPOE", "Passing", 1, "f1", "pass", P, "Completion % over expected (nflverse model)")
st("succ_db", "Success rate (dropbacks)", "Passing", 1, "pct1", "pass", P)
st("adot", "Avg depth of target", "Passing", 1, "f1", "pass", P)
st("sacks_taken", "Sacks taken", "Passing", 0, "int", "pass", P)
st("sack_pct", "Sack rate", "Passing", 0, "pct1", "pass", P)
st("ttt", "Time to throw (s)", "Passing", None, "f2", "pass", P, "NGS avg time to throw (no better/worse direction)")
st("carries", "Carries", "Rushing", 1, "int", "snap", RU)
st("rush_yds", "Rushing yards", "Rushing", 1, "int", "snap", RU)
st("rush_ypg", "Rushing yards / game", "Rushing", 1, "f1", "rush", RU)
st("ypc", "Yards / carry", "Rushing", 1, "f2", "rush", RU)
st("rush_td", "Rushing TD", "Rushing", 1, "int", "snap", RU)
st("epa_rush", "EPA / rush", "Rushing", 1, "f3", "rush", RU, "Designed runs (scrambles count as dropbacks)")
st("succ_rush", "Rush success rate", "Rushing", 1, "pct1", "rush", RU)
st("ryoe_att", "Rush yds over expected / att", "Rushing", 1, "f2", "rush", RU, "NGS")
st("targets", "Targets", "Receiving", 1, "int", "snap", RE)
st("rec", "Receptions", "Receiving", 1, "int", "snap", RE)
st("rec_yds", "Receiving yards", "Receiving", 1, "int", "snap", RE)
st("rec_ypg", "Receiving yards / game", "Receiving", 1, "f1", "recv", RE)
st("rec_td", "Receiving TD", "Receiving", 1, "int", "snap", RE)
st("catch_pct", "Catch %", "Receiving", 1, "pct1", "recv", RE)
st("ypt", "Yards / target", "Receiving", 1, "f2", "recv", RE)
st("ypr", "Yards / reception", "Receiving", 1, "f1", "recv", RE)
st("ypdb", "Rec yds / team dropback (YPRR proxy)", "Receiving", 1, "f2", "recv", RE,
   "PROXY, not YPRR: receiving yards ÷ team dropbacks in games he played. Routes run aren't public for 2026.")
st("yps", "Rec yds / offensive snap", "Receiving", 1, "f2", "recv", RE)
st("tgt_share", "Target share", "Receiving", 1, "pct1", "recv", RE)
st("air_yds", "Air yards (targeted)", "Receiving", 1, "int", "snap", RE)
st("yac", "Yards after catch", "Receiving", 1, "int", "snap", RE)
st("adot_rec", "aDOT", "Receiving", None, "f1", "recv", RE)
st("epa_tgt", "EPA / target", "Receiving", 1, "f3", "recv", RE)
st("sep", "Avg separation (yds)", "Receiving", 1, "f2", "recv", ["WR", "TE"], "NGS")
st("yacoe", "YAC over expected / rec", "Receiving", 1, "f2", "recv", RE, "NGS")
st("scrim_yds", "Scrimmage yards", "Scrimmage", 1, "int", "snap", RU)
st("scrim_ypg", "Scrimmage yards / game", "Scrimmage", 1, "f1", "snap", RU)
st("total_td", "Total TD (rush+rec)", "Scrimmage", 1, "int", "snap", RU)
st("tackles", "Tackles", "Defense", 1, "int", "snap", D)
st("solo", "Solo tackles", "Defense", 1, "int", "snap", D)
st("ast", "Assisted tackles", "Defense", 1, "int", "snap", D)
st("tpg", "Tackles / game", "Defense", 1, "f1", "snap", D)
st("tfl", "Tackles for loss", "Defense", 1, "int", "snap", D)
st("sacks", "Sacks", "Pass rush", 1, "f1", "snap", D)
st("qb_hits", "QB hits", "Pass rush", 1, "int", "snap", D)
st("pressures", "Pressures (PFR)", "Pass rush", 1, "int", "snap", D, "Pro Football Reference charting: hurries + QB knockdowns + sacks")
st("hurries", "Hurries (PFR)", "Pass rush", 1, "int", "snap", D)
st("prs_pg", "Pressures / game", "Pass rush", 1, "f2", "snap", D)
st("prs_100", "Pressures / 100 def. snaps", "Pass rush", 1, "f1", "snap", FRONT, "Uses all defensive snaps (pass-rush snaps aren't public)")
st("blitzes", "Times blitzed (PFR)", "Pass rush", None, "int", "snap", ["LB", "CB", "S"])
st("ints", "Interceptions", "Coverage", 1, "int", "snap", D)
st("pd", "Passes defended", "Coverage", 1, "int", "snap", D)
st("tgt_allowed", "Targets in coverage (PFR)", "Coverage", None, "int", "snap", ["LB", "CB", "S"])
st("cmp_allowed_pct", "Completion % allowed (PFR)", "Coverage", 0, "pct1", "cov", ["LB", "CB", "S"])
st("yds_allowed_tgt", "Yards allowed / target (PFR)", "Coverage", 0, "f1", "cov", ["LB", "CB", "S"])
st("rating_allowed", "Passer rating allowed (PFR)", "Coverage", 0, "f1", "cov", ["LB", "CB", "S"])
st("ff", "Forced fumbles", "Defense", 1, "int", "snap", D)
st("fr", "Fumble recoveries", "Defense", 1, "int", "snap", D)
st("def_td", "Defensive TD", "Defense", 1, "int", "snap", D)
st("missed_tkl_pct", "Missed tackle % (PFR)", "Defense", 0, "pct1", "tkl", D)
for m, lab, grp in (("prwr", "Pass Rush Win Rate", ["EDGE", "IDL"]), ("rswr", "Run Stop Win Rate", ["EDGE", "IDL"]),
                    ("pbwr", "Pass Block Win Rate", ["OL"]), ("rbwr", "Run Block Win Rate", ["OL"])):
    st(m, lab + " (ESPN)", "Win rates", 1, "pct0", "espn", grp, "ESPN Analytics / NGS tracking. ESPN publishes only its top players per list; others show 'not published'.")
st("off_snaps", "Offensive snaps", "Usage", 1, "int", "none", sorted(OFF))
st("def_snaps", "Defensive snaps", "Usage", 1, "int", "none", D)
STAT = {s["k"]: s for s in S}

QUAL_TEXT = {
    "snap": "played ≥ 25% of his team's offensive/defensive snaps through the data week",
    "pass": "≥ 14 pass attempts per team game (PFR standard)",
    "rush": "≥ 6.25 carries per team game (PFR standard)",
    "recv": "≥ 1.875 receptions per team game (PFR standard)",
    "cov": "≥ 2 coverage targets per team game and ≥ 25% def. snaps",
    "tkl": "≥ 2 tackle attempts per team game",
    "espn": "ESPN's published top-N list for that position (rank shown is ESPN's)",
    "none": "all players",
}

def rating(c, a, y, td, i):
    if not a: return None
    cl = lambda x: max(0, min(2.375, x))
    return (cl((c / a - .3) * 5) + cl((y / a - 3) * .25) + cl(td / a * 20) + cl(2.375 - i / a * 25)) / 6 * 100

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--season", type=int, default=2026)
    ap.add_argument("--through-week", type=int); ap.add_argument("--offline", action="store_true")
    ap.add_argument("--out-dir", default="data"); ap.add_argument("--no-espn", action="store_true")
    ap.add_argument("--no-trade-values", action="store_true", help="skip the trade-value model step")
    ap.add_argument("--espn-html", help="parse this saved ESPN win-rate article instead of fetching the live one")
    ap.add_argument("--no-rankings", action="store_true", help="skip the power-rankings step")
    a = ap.parse_args(); SEA = a.season
    os.makedirs("raw", exist_ok=True); os.makedirs(a.out_dir, exist_ok=True)
    games = pd.read_csv(fetch(GAMES_URL, "raw/games.csv", a.offline))
    g = games[(games.season == SEA) & (games.game_type == "REG")]
    done = g.groupby("week").apply(lambda x: x.result.notna().all(), include_groups=False)
    W = a.through_week or int(max([w for w, ok in done.items() if ok]))
    gw = g[(g.week <= W) & g.result.notna()]
    last_date = str(gw.gameday.max())
    tg = pd.concat([gw.home_team, gw.away_team]).value_counts().to_dict()  # team games through W
    print(f"season {SEA} through week {W} (last game {last_date})")

    wk = pd.read_parquet(raw("week", SEA, a.offline)); wk = wk[(wk.season_type == "REG") & (wk.week <= W)]
    ros = pd.read_parquet(raw("roster", SEA, a.offline))
    pl = pd.read_parquet(raw("players", SEA, a.offline))
    pbp = pd.read_parquet(raw("pbp", SEA, a.offline)); pbp = pbp[(pbp.season_type == "REG") & (pbp.week <= W)]
    snaps = pd.read_parquet(raw("snaps", SEA, a.offline)); snaps = snaps[(snaps.game_type == "REG") & (snaps.week <= W)]
    try:
        pfr = pd.read_parquet(raw("pfrdef", SEA, a.offline)); pfr = pfr[(pfr.game_type == "REG") & (pfr.week <= W)]
    except Exception as e:
        print("PFR defense unavailable", e); pfr = pd.DataFrame()
    ngs = {}
    for k in ("ngs_passing", "ngs_receiving", "ngs_rushing"):
        d = pd.read_parquet(raw(k, SEA, a.offline)); ngs[k] = d[(d.season == SEA) & (d.season_type == "REG") & (d.week >= 1) & (d.week <= W)]
    pfr2gsis = pl.dropna(subset=["pfr_id", "gsis_id"]).set_index("pfr_id").gsis_id.to_dict()
    pfr2gsis.update(ros.dropna(subset=["pfr_id", "gsis_id"]).set_index("pfr_id").gsis_id.to_dict())

    # ---------- base counting stats ----------
    num = wk.select_dtypes("number").columns.difference(["season", "week"])
    agg = wk.groupby("player_id")[list(num)].sum()
    agg["games"] = wk.groupby("player_id").game_id.nunique()
    last = wk.sort_values("week").groupby("player_id").tail(1).set_index("player_id")
    gp = wk.groupby("player_id").game_id.apply(set).to_dict()

    # snaps (by gsis)
    snaps["gsis"] = snaps.pfr_player_id.map(pfr2gsis)
    sn = snaps.dropna(subset=["gsis"]).groupby("gsis")[["offense_snaps", "defense_snaps"]].sum()
    for gs, games_ in snaps.dropna(subset=["gsis"]).groupby("gsis").game_id.apply(set).items():
        gp.setdefault(gs, set()).update(games_)
    team_snaps = snaps.groupby(["game_id", "team"]).apply(lambda x: pd.Series({"o": (x.offense_snaps / x.offense_pct.replace(0, np.nan)).median(),
                                                                                 "d": (x.defense_snaps / x.defense_pct.replace(0, np.nan)).median()}), include_groups=False)
    tsn = team_snaps.groupby(level="team").sum()
    # player team-snap denominators over his team's games
    # ---------- play-by-play ----------
    db = pbp[(pbp["pass"] == 1) & pbp.passer_id.notna()]
    dbs = db.groupby("passer_id").agg(dropbacks=("qb_epa", "size"), epa_db=("qb_epa", "mean"), succ_db=("success", "mean"),
                                      cpoe=("cpoe", "mean"))
    att = pbp[(pbp.pass_attempt == 1) & (pbp.sack == 0) & pbp.passer_id.notna()]
    dbs["adot"] = att.groupby("passer_id").air_yards.mean()
    ru = pbp[(pbp.rush == 1) & pbp.rusher_id.notna()]
    rus = ru.groupby("rusher_id").agg(epa_rush=("epa", "mean"), succ_rush=("success", "mean"))
    tg_ = pbp[(pbp.pass_attempt == 1) & (pbp.sack == 0) & pbp.receiver_id.notna()]
    rcv = tg_.groupby("receiver_id").agg(epa_tgt=("epa", "mean"), adot_rec=("air_yards", "mean"))
    _dbk = pbp[pbp.qb_dropback == 1]; _rr = pbp[(pbp.rush == 1) & (pbp.qb_scramble == 0)]
    team_off = pd.DataFrame({"sack_rate": _dbk.groupby("posteam").sack.mean() * 100,
                             "rush_epa": _rr.groupby("posteam").epa.mean(), "rush_succ": _rr.groupby("posteam").success.mean() * 100})
    team_off = {t_: {k_: round(float(v_), 4) for k_, v_ in r_.items()} for t_, r_ in team_off.iterrows()}
    team_db = pbp[pbp.qb_dropback == 1].groupby(["game_id", "posteam"]).size().to_dict()
    team_att = pbp[(pbp.pass_attempt == 1) & (pbp.sack == 0)].groupby(["game_id", "posteam"]).size().to_dict()
    # NGS weighted
    def wavg(d, key, val, w):
        d = d.dropna(subset=[val, w]); d = d[d[w] > 0]
        return (d[val] * d[w]).groupby(d[key]).sum() / d[w].groupby(d[key]).sum()
    ttt = wavg(ngs["ngs_passing"], "player_gsis_id", "avg_time_to_throw", "attempts")
    sep = wavg(ngs["ngs_receiving"], "player_gsis_id", "avg_separation", "targets")
    yacoe = wavg(ngs["ngs_receiving"], "player_gsis_id", "avg_yac_above_expectation", "receptions")
    nr = ngs["ngs_rushing"]; ryoe = nr.groupby("player_gsis_id").rush_yards_over_expected.sum() / nr.groupby("player_gsis_id").rush_attempts.sum()
    # PFR defense
    pf = pd.DataFrame()
    if len(pfr):
        pfr["gsis"] = pfr.pfr_player_id.map(pfr2gsis)
        cols = ["def_pressures", "def_times_hurried", "def_times_hitqb", "def_times_blitzed", "def_targets", "def_completions_allowed",
                "def_yards_allowed", "def_missed_tackles", "def_tackles_combined", "def_receiving_td_allowed", "def_ints"]
        pf = pfr.dropna(subset=["gsis"]).groupby("gsis")[cols].sum()
    # ESPN
    wr_meta, wr_rows = None, []
    try:
        if not a.no_espn: wr_meta, wr_rows = espn_win_rates(SEA, a.offline, a.espn_html)
    except Exception as e:
        print("ESPN win rates failed:", e, file=sys.stderr)

    # ---------- player universe ----------
    ros_l = ros.sort_values("week").groupby("gsis_id").tail(1).set_index("gsis_id") if "week" in ros else ros.set_index("gsis_id")
    ids = set(agg.index) | set(sn.index) | set(ros_l[ros_l.status.isin(["ACT", "RES", "INA", "DEV", "EXE"])].index)
    plx = pl.set_index("gsis_id")
    # ---------- current team ----------
    # priority: manual override (cited) > ESPN's live team roster > latest nflverse weekly roster (unless CUT) > last team with stats
    cur_rosters = None
    if a.out_dir == "data" and not a.no_espn:
        try: cur_rosters = espn_rosters(a.offline)
        except Exception as e: print("ESPN rosters unavailable:", e, file=sys.stderr)
    overrides = load_overrides() if a.out_dir == "data" else {}
    team_changes = []
    # per-game team for each player (weekly stats + snap counts), to credit traded players' team totals correctly
    pg_team = {(r_.player_id, r_.game_id): r_.team for r_ in wk[["player_id", "game_id", "team"]].itertuples()}
    for r_ in snaps.dropna(subset=["gsis"])[["gsis", "game_id", "team"]].itertuples(): pg_team.setdefault((r_.gsis, r_.game_id), r_.team)
    pteams = {}
    for (pid_, gid_), t_ in pg_team.items(): pteams.setdefault(pid_, {}).setdefault(t_, []).append(gid_)
    gweek = dict(zip(gw.game_id, gw.week))
    team_games_w = {}
    for r_ in gw.itertuples():
        for t_ in (r_.home_team, r_.away_team): team_games_w.setdefault(t_, []).append((r_.week, r_.game_id))
    def team_spans(pid_):
        """[(team, [game_ids the player was on that team for])]: earlier team(s) from week 1 to their last appearance, the
        latest team from its first appearance on (a traded player's denominators are the games he was on each roster)."""
        tm = pteams.get(pid_)
        if not tm: return []
        order = sorted(tm, key=lambda t_: max(gweek.get(g_, 0) for g_ in tm[t_]))
        out_, start = [], 1
        for i_, t_ in enumerate(order):
            wks = [gweek.get(g_, 0) for g_ in tm[t_]]
            lo_ = min(wks) if i_ else 1; hi_ = W if i_ == len(order) - 1 else max(wks)
            if i_ and i_ == len(order) - 1: lo_ = min(wks)
            out_.append((t_, [g_ for w_, g_ in team_games_w.get(t_, []) if lo_ <= w_ <= hi_]))
        return out_
    out = []
    for pid in ids:
        if not isinstance(pid, str) or not pid: continue
        r = ros_l.loc[pid] if pid in ros_l.index else None
        x = plx.loc[pid] if pid in plx.index else None
        name = (r.full_name if r is not None else None) or (last.loc[pid].player_display_name if pid in last.index else None) or (x.display_name if x is not None else None)
        if not name: continue
        pos = (r.depth_chart_position if r is not None and isinstance(r.depth_chart_position, str) else None) or \
              (r.position if r is not None else None) or (last.loc[pid].position if pid in last.index else None) or (x.position if x is not None else None)
        grp = GROUP.get(pos)
        if grp in (None, "ST"): continue
        stat_team = last.loc[pid].team if pid in last.index else None
        team = r.team if r is not None and r.status != "CUT" else (None if r is not None else stat_team)
        old_logic = stat_team or (r.team if r is not None else None)
        why = "nflverse weekly roster (week %s)" % (int(r.week) if r is not None and "week" in r else "?") if team else None
        if cur_rosters:
            eid = str(int(r.espn_id)) if r is not None and pd.notna(r.espn_id) else None
            et = cur_rosters[0].get(eid) if eid else None
            if et is None:
                nm = cur_rosters[1].get(norm(name), set())
                if len(nm) == 1: et = next(iter(nm))
            if et: team, why = et, "ESPN team roster (fetched %s)" % dt.date.today()
            elif r is not None and r.status == "CUT": team, why = None, "released (nflverse status CUT; on no ESPN roster)"
        if pid in overrides: team, why = overrides[pid]["team"], "manual override: " + overrides[pid]["source"]
        spans = team_spans(pid)
        prev_teams = [t_ for t_, _ in spans if t_ != team]
        if team != old_logic and (G_ := len(gp.get(pid, set()))) >= 0:
            team_changes.append(dict(id=pid, n=name, pos=pos, old=old_logic, new=team, why=why, prev=prev_teams, g=G_))
        head = (last.loc[pid].headshot_url if pid in last.index else None) or (r.headshot_url if r is not None else None) or (x.headshot if x is not None else None)
        status = r.status if r is not None else None
        s = {}
        A = agg.loc[pid] if pid in agg.index else None
        games_set = gp.get(pid, set()); G = len(games_set)
        span_games = [g_ for _, gl in spans for g_ in gl] if spans else [g_ for _, g_ in team_games_w.get(team, [])]
        team_g = len(set(span_games)) or None
        v = lambda k: float(A[k]) if A is not None and k in A and pd.notna(A[k]) else 0.0
        if A is not None:
            pa, cmp_, py, ptd, pint = v("attempts"), v("completions"), v("passing_yards"), v("passing_tds"), v("passing_interceptions")
            sk, sky = v("sacks_suffered"), v("sack_yards_lost")
            if pa > 0:
                s.update(pass_att=pa, cmp=cmp_, cmp_pct=cmp_ / pa * 100, pass_yds=py, pass_ypg=py / max(G, 1), pass_td=ptd, int=pint, ypa=py / pa,
                         anya=(py + 20 * ptd - 45 * pint - sky) / (pa + sk), rating=rating(cmp_, pa, py, ptd, pint), sacks_taken=sk, sack_pct=sk / (pa + sk) * 100)
            car, ryd = v("carries"), v("rushing_yards")
            if car > 0: s.update(carries=car, rush_yds=ryd, rush_ypg=ryd / max(G, 1), ypc=ryd / car, rush_td=v("rushing_tds"))
            tgt, rec, ryds = v("targets"), v("receptions"), v("receiving_yards")
            if tgt > 0:
                s.update(targets=tgt, rec=rec, rec_yds=ryds, rec_ypg=ryds / max(G, 1), rec_td=v("receiving_tds"), catch_pct=rec / tgt * 100,
                         ypt=ryds / tgt, air_yds=v("receiving_air_yards"), yac=v("receiving_yards_after_catch"))
                if rec: s["ypr"] = ryds / rec
                tdb = sum(team_db.get((gid, pg_team.get((pid, gid), team)), 0) for gid in games_set)
                tat = sum(team_att.get((gid, pg_team.get((pid, gid), team)), 0) for gid in games_set)
                if tdb: s["ypdb"] = ryds / tdb
                if tat: s["tgt_share"] = tgt / tat * 100
            if car > 0 or tgt > 0:
                s.update(scrim_yds=ryd + ryds, scrim_ypg=(ryd + ryds) / max(G, 1), total_td=v("rushing_tds") + v("receiving_tds"))
            solo, asst = v("def_tackles_solo"), v("def_tackle_assists")
            if grp in DEF:
                s.update(tackles=solo + asst, solo=solo, ast=asst, tpg=(solo + asst) / max(G, 1), tfl=v("def_tackles_for_loss"), sacks=v("def_sacks"),
                         qb_hits=v("def_qb_hits"), ints=v("def_interceptions"), pd=v("def_pass_defended"), ff=v("def_fumbles_forced"),
                         fr=v("fumble_recovery_opp"), def_td=v("def_tds"))
        elif grp in DEF and G:
            s.update(tackles=0, solo=0, ast=0, tpg=0, tfl=0, sacks=0, qb_hits=0, ints=0, pd=0, ff=0, fr=0, def_td=0)
        if pid in dbs.index and "pass_att" in s:
            d_ = dbs.loc[pid]; s.update(epa_db=d_.epa_db, succ_db=d_.succ_db * 100, cpoe=d_.cpoe, adot=d_.adot)
        if pid in ttt.index and "pass_att" in s: s["ttt"] = ttt[pid]
        if pid in rus.index and "carries" in s: s.update(epa_rush=rus.loc[pid].epa_rush, succ_rush=rus.loc[pid].succ_rush * 100)
        if pid in ryoe.index and "carries" in s and np.isfinite(ryoe[pid]): s["ryoe_att"] = ryoe[pid]
        if pid in rcv.index and "targets" in s: s.update(epa_tgt=rcv.loc[pid].epa_tgt, adot_rec=rcv.loc[pid].adot_rec)
        if pid in sep.index and "targets" in s: s["sep"] = sep[pid]
        if pid in yacoe.index and "targets" in s: s["yacoe"] = yacoe[pid]
        osn = float(sn.loc[pid].offense_snaps) if pid in sn.index else 0.0
        dsn = float(sn.loc[pid].defense_snaps) if pid in sn.index else 0.0
        if grp in OFF and osn: s["off_snaps"] = osn
        if grp in DEF and dsn: s["def_snaps"] = dsn
        if "targets" in s and osn: s["yps"] = s["rec_yds"] / osn
        if grp in DEF and pid in pf.index:
            f = pf.loc[pid]
            s.update(pressures=f.def_pressures, hurries=f.def_times_hurried, blitzes=f.def_times_blitzed, prs_pg=f.def_pressures / max(G, 1))
            if dsn: s["prs_100"] = f.def_pressures / dsn * 100
            if f.def_targets > 0:
                s.update(tgt_allowed=f.def_targets, cmp_allowed_pct=f.def_completions_allowed / f.def_targets * 100,
                         yds_allowed_tgt=f.def_yards_allowed / f.def_targets,
                         rating_allowed=rating(f.def_completions_allowed, f.def_targets, f.def_yards_allowed, f.def_receiving_td_allowed, f.def_ints))
            tk_att = f.def_tackles_combined + f.def_missed_tackles
            if tk_att > 0: s["missed_tkl_pct"] = f.def_missed_tackles / tk_att * 100
            s["_tkatt"] = tk_att
        # qualifiers
        side_snaps = osn if grp in OFF else dsn
        col_ = "o" if grp in OFF else "d"
        span_pairs = [(g_, t_) for t_, gl in spans for g_ in gl] if spans else [(g_, team) for _, g_ in team_games_w.get(team, [])]
        team_side = float(sum(team_snaps[col_].get((g_, t_), 0) or 0 for g_, t_ in span_pairs)) if span_pairs else 0
        q = {"snap": bool(team_side and side_snaps >= .25 * team_side) or (not team_side and team_g and G >= team_g / 2), "none": True}
        tgames = team_g or max(G, 1)
        q["pass"] = s.get("pass_att", 0) >= 14 * tgames
        q["rush"] = s.get("carries", 0) >= 6.25 * tgames
        q["recv"] = s.get("rec", 0) >= 1.875 * tgames
        q["cov"] = s.get("tgt_allowed", 0) >= 2 * tgames and q["snap"]
        q["tkl"] = s.pop("_tkatt", 0) >= 2 * tgames
        out.append(dict(id=pid, name=name, team=team, prev=prev_teams, pos=pos, grp=grp, head=head, status=status, g=G, tg=team_g,
                        snap_share=round(side_snaps / team_side * 100, 1) if team_side else None, s=s, q=q,
                        espn_id=(str(int(r.espn_id)) if r is not None and pd.notna(r.espn_id) else None)))
    # ---------- ESPN join (carry forward last good win rates if ESPN can't be reached) ----------
    old_path = f"{a.out_dir}/players_{SEA}.json"
    if not wr_rows and os.path.exists(old_path):
        old = json.load(open(old_path)); om = old["meta"]["espn"].get("meta")
        if om:
            wr_meta = dict(om, stale=True, note="ESPN fetch failed; carried forward from previous build")
            for op in old["players"]:
                for m_, w_ in (op.get("wr") or {}).items():
                    wr_rows.append(dict(metric=m_, list=w_["list"], rank=w_["rank"], name=op["n"], team=op["t"], wins=w_["wins"],
                                        plays=w_["plays"], rate=op["s"][m_], list_size=w_["n"]))
            print("ESPN win rates carried forward from previous build", file=sys.stderr)
    byname = {}
    for p in out: byname.setdefault(norm(p["name"]), []).append(p)
    wr_matched = 0; wr_unmatched = []
    for w in wr_rows:
        cands = byname.get(norm(w["name"]), [])
        c2 = [p for p in cands if p["team"] == w["team"]] or cands
        if len(c2) >= 1:
            p = c2[0]; p["s"][w["metric"]] = w["rate"]
            p.setdefault("wr", {})[w["metric"]] = dict(rank=w["rank"], list=w["list"], n=w["list_size"], wins=w["wins"], plays=w["plays"])
            wr_matched += 1
        else: wr_unmatched.append(f'{w["name"]} ({w["team"]})')
    # ---------- ranks / percentiles ----------
    counts = {}
    for k, d in STAT.items():
        for grp in d["groups"]:
            pool = [p for p in out if p["grp"] == grp and k in p["s"] and p["s"][k] is not None and np.isfinite(p["s"][k])]
            if d["q"] == "espn":
                for p in pool:
                    p.setdefault("r", {})[k] = [p["wr"][k]["rank"], None, p["wr"][k]["n"]]
                counts[f"{grp}|{k}"] = len(pool); continue
            qual = [p for p in pool if p["q"][d["q"]] and (d["q"] == "snap" or p["q"]["snap"] or d["q"] in ("pass", "rush", "recv"))]
            n = len(qual); counts[f"{grp}|{k}"] = n
            if not n or d["hb"] is None:
                continue
            vals = np.array([p["s"][k] for p in qual], dtype=float)
            sgn = 1 if d["hb"] else -1
            for p in qual:
                x = p["s"][k] * sgn; better = int(((vals * sgn) > x + 1e-9).sum()); worse = int(((vals * sgn) < x - 1e-9).sum())
                tie = n - better - worse
                pct = round(100 * (worse + 0.5 * (tie - 1)) / (n - 1)) if n > 1 else 100
                p.setdefault("r", {})[k] = [better + 1, pct, n]
    # ---------- write ----------
    def rnd(v):
        if v is None or (isinstance(v, float) and not np.isfinite(v)): return None
        v = float(v); return int(v) if v.is_integer() else round(v, 4)
    cl = lambda x: x if isinstance(x, str) and x else None
    def clean(o):
        if isinstance(o, dict): return {k: clean(v) for k, v in o.items()}
        if isinstance(o, list): return [clean(v) for v in o]
        if isinstance(o, (float, np.floating)): return None if not np.isfinite(o) else float(o)
        if isinstance(o, np.integer): return int(o)
        return o
    players = []
    for p in sorted(out, key=lambda p: p["name"]):
        h = p["head"]
        if isinstance(h, str) and h.startswith(HEAD_PREFIX): h = "~" + h[len(HEAD_PREFIX):]
        players.append(dict(id=p["id"], n=p["name"], t=cl(p["team"]), p=cl(p["pos"]), gr=p["grp"], h=cl(h), st=cl(p["status"]), g=p["g"], tg=p["tg"],
                            ss=p["snap_share"], q=[k for k, v in p["q"].items() if v and k != "none"], s={k: rnd(v) for k, v in p["s"].items()},
                            r=p.get("r", {}), wr=p.get("wr"), e=p["espn_id"], **({"pt": p["prev"]} if p["prev"] else {})))
    meta = dict(season=SEA, through_week=W, last_game=last_date, built=dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                team_games=tg, players=len(players), team_source="Current team: ESPN team rosters (fetched at build) > nflverse weekly roster > trades/team_overrides.csv overrides win; 'pt' = earlier 2026 teams",
                team_changes=team_changes, with_stats=sum(1 for p in players if p["g"]), qualifiers=QUAL_TEXT,
                espn=dict(meta=wr_meta, matched=wr_matched, total=len(wr_rows), unmatched=wr_unmatched),
                team_off=team_off, pfr_def_weeks=sorted(int(w) for w in pfr.week.unique()) if len(pfr) else [], counts=counts)
    json.dump(clean(dict(meta=meta, stats=S, players=players)), open(f"{a.out_dir}/players_{SEA}.json", "w"), separators=(",", ":"), allow_nan=False)
    print(f"wrote {a.out_dir}/players_{SEA}.json: {len(players)} players ({meta['with_stats']} with stats); ESPN rows matched {wr_matched}/{len(wr_rows)}",
          ("unmatched: " + ", ".join(wr_unmatched)) if wr_unmatched else "")

    if a.out_dir == "data" and not a.no_trade_values and not a.no_espn:
        trade_values(SEA, a.offline)
    if a.out_dir == "data" and not a.no_rankings:
        import power_rankings
        power_rankings.roll(f"{a.out_dir}/players_{SEA}.json", "data/rankings_history.json", f"data/rankings_{SEA}.json")

NFLDATA = "https://raw.githubusercontent.com/nflverse/nfldata/master/data"
CAP_LAB = "https://coleslaw510.github.io/nfl-salary-cap/data.json"
def trade_values(season, offline):
    """Refresh the trade dataset and model, then score current players (data/trade_values_<season>.json).
    Needs: nflverse trades + draft value chart, Over The Cap contracts (nflverse release), the NFL Salary Cap Lab's
    Over The Cap 2026 cap data, and prior-season builds in raw/hist/ (built here if missing)."""
    import subprocess
    print("trade values: refreshing inputs")
    fetch(f"{NFLDATA}/trades.csv", "raw/trades.csv", offline, max_age_h=12)
    fetch(f"{NFLDATA}/draft_values.csv", "raw/draft_values.csv", offline, max_age_h=24 * 30)
    fetch(f"{REL}/contracts/historical_contracts.parquet", "raw/historical_contracts.parquet", offline, max_age_h=24)
    if not os.path.exists("/workspace/nfl-salary-cap/data.json"):
        fetch(CAP_LAB, "raw/otc_cap.json", offline, max_age_h=24)
    for y in range(2018, season - 1):
        if not os.path.exists(f"raw/hist/players_{y}.json"):
            subprocess.run([sys.executable, __file__, "--season", str(y), "--out-dir", "raw/hist", "--no-espn"], check=True)
    subprocess.run([sys.executable, "trades/build_trades.py"], check=True)
    subprocess.run([sys.executable, "trades/model.py", str(season)], check=True)

if __name__ == "__main__":
    import urllib.parse
    main()
