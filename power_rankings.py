#!/usr/bin/env python3
"""Position power rankings for the NFL Player Stats Hub.

Scores every qualified player at each position (QB, RB, WR, TE, OL, EDGE, IDL, LB, CB, S) with a composite built from
the hub's own stats (data/players_<season>.json), then rolls a weekly history so the site can show movement arrows.

Method (per position):
  1. Pool = players who pass the position's playing-time qualifier (see QUAL below).
  2. Every input stat becomes a z-score within that pool (direction-corrected, clipped to +/-3). Missing values count as
     average (z = 0). ESPN win rates use list standing: (list size + 1 - rank) / list size if published, else 0.
  3. Rate stats are shrunk toward average for small samples: z * n / (n + k) (n = dropbacks, carries, targets, ...).
  4. Stats are averaged into components (efficiency, production, ...) and components are summed with the weights below.
  5. The composite is shrunk once more for games played (x g / (g + 1.5)), standardized within the pool and mapped to a
     0-100 score: 50 = an average qualified player, each standard deviation = 16 points.

History: data/rankings_history.json = {season: {through_week: {group: {player_id: [rank, score]}}}}. Each run stores the
week it covers (re-running a week overwrites that week) and compares with the latest earlier week on file.

CLI:
  python power_rankings.py                       # roll data/players_2026.json into the history + data/rankings_2026.json
  python power_rankings.py --baseline raw/wk7/players_2026.json   # store an earlier-week snapshot without writing output
"""
import argparse, json, math, os, statistics as stt

# stat spec: (key, weight, lower_is_better, shrink_volume, k). key may be "x/g" (per game played), "avail", "ss",
# "<metric>_pts" (ESPN list standing) or "team:<stat>" (team offense context from meta.team_off).
DB, CAR, TGT, DSN, TKL, CVT = "dropbacks", "carries", "targets", "def_snaps", "tackles", "tgt_allowed"
AV = ("Availability & role", 10, [("avail", 1, 0, None, 0), ("ss", 1, 0, None, 0)])
SPEC = {
  "QB": [("Efficiency", 45, [("epa_db", 3, 0, DB, 120), ("anya", 1.5, 0, DB, 120), ("succ_db", 1, 0, DB, 120), ("cpoe", 1, 0, DB, 120)]),
         ("Passing production", 25, [("pass_ypg", 2, 0, None, 0), ("pass_td/g", 1, 0, None, 0)]),
         ("Rushing", 10, [("rush_ypg", 1, 0, None, 0), ("epa_rush", 1, 0, CAR, 30)]),
         ("Ball security & sacks", 10, [("int_rate", 1, 1, DB, 150), ("sack_pct", 1, 1, DB, 150)]),
         AV],
  "RB": [("Rushing production", 25, [("rush_ypg", 2, 0, None, 0), ("rush_td/g", 1, 0, None, 0)]),
         ("Rushing efficiency", 25, [("epa_rush", 1.2, 0, CAR, 60), ("ryoe_att", 1.2, 0, CAR, 60), ("succ_rush", 1, 0, CAR, 60), ("ypc", 0.6, 0, CAR, 60)]),
         ("Receiving", 20, [("rec_ypg", 1.5, 0, None, 0), ("epa_tgt", 0.8, 0, TGT, 15), ("ypt", 0.5, 0, TGT, 15)]),
         ("Scrimmage total", 15, [("scrim_ypg", 1.5, 0, None, 0), ("total_td/g", 1, 0, None, 0)]),
         ("Availability & role", 15, AV[2])],
  "WR": [("Production", 30, [("rec_ypg", 2, 0, None, 0), ("rec_td/g", 0.7, 0, None, 0)]),
         ("Efficiency", 30, [("ypdb", 2, 0, TGT, 30), ("epa_tgt", 1.2, 0, TGT, 30), ("ypt", 1, 0, TGT, 30), ("catch_pct", 0.4, 0, TGT, 30)]),
         ("Earning targets", 20, [("tgt_share", 2, 0, None, 0), ("air_yds/g", 0.7, 0, None, 0)]),
         ("Tracking (NGS)", 8, [("sep", 1, 0, TGT, 30), ("yacoe", 1, 0, TGT, 30)]),
         ("Availability & role", 12, AV[2])],
  "TE": [("Production", 28, [("rec_ypg", 2, 0, None, 0), ("rec_td/g", 0.7, 0, None, 0)]),
         ("Efficiency", 25, [("ypdb", 2, 0, TGT, 20), ("epa_tgt", 1.2, 0, TGT, 20), ("ypt", 1, 0, TGT, 20), ("catch_pct", 0.4, 0, TGT, 20)]),
         ("Earning targets", 17, [("tgt_share", 2, 0, None, 0)]),
         ("Tracking (NGS)", 5, [("sep", 1, 0, TGT, 20), ("yacoe", 1, 0, TGT, 20)]),
         ("Snap share (blocking role)", 15, [("ss", 1, 0, None, 0)]),
         ("Availability", 10, [("avail", 1, 0, None, 0)])],
  "OL": [("ESPN pass block win rate", 30, [("pbwr_pts", 1, 0, None, 0)]),
         ("ESPN run block win rate", 20, [("rbwr_pts", 1, 0, None, 0)]),
         ("Playing time", 25, AV[2]),
         ("Team pass protection", 12.5, [("team:sack_rate", 1, 1, None, 0)]),
         ("Team run blocking", 12.5, [("team:rush_epa", 1, 0, None, 0), ("team:rush_succ", 1, 0, None, 0)])],
  "EDGE": [("Pass rush", 45, [("prs_100", 2, 0, DSN, 150), ("prs_pg", 1.5, 0, None, 0), ("sacks/g", 1.5, 0, None, 0), ("qb_hits/g", 0.5, 0, None, 0), ("prwr_pts", 1.5, 0, None, 0)]),
           ("Run defense", 20, [("rswr_pts", 1, 0, None, 0), ("tfl/g", 1, 0, None, 0), ("tpg", 0.7, 0, None, 0)]),
           ("Playmaking", 10, [("ff/g", 1, 0, None, 0), ("pd/g", 0.3, 0, None, 0)]),
           ("Tackling", 10, [("missed_tkl_pct", 1, 1, TKL, 20)]),
           ("Availability & role", 15, AV[2])],
  "IDL": [("Pass rush", 40, [("prs_100", 2, 0, DSN, 150), ("prs_pg", 1.5, 0, None, 0), ("sacks/g", 1.5, 0, None, 0), ("qb_hits/g", 0.5, 0, None, 0), ("prwr_pts", 1.5, 0, None, 0)]),
          ("Run defense", 30, [("rswr_pts", 1.2, 0, None, 0), ("tfl/g", 1, 0, None, 0), ("tpg", 0.8, 0, None, 0)]),
          ("Playmaking", 5, [("ff/g", 1, 0, None, 0), ("pd/g", 0.5, 0, None, 0)]),
          ("Tackling", 10, [("missed_tkl_pct", 1, 1, TKL, 20)]),
          ("Availability & role", 15, AV[2])],
  "LB": [("Tackling & run defense", 35, [("tpg", 1.5, 0, None, 0), ("tfl/g", 1, 0, None, 0), ("missed_tkl_pct", 1, 1, TKL, 30)]),
         ("Coverage", 25, [("rating_allowed", 1.2, 1, CVT, 20), ("yds_allowed_tgt", 1, 1, CVT, 20), ("pd/g", 0.8, 0, None, 0), ("ints/g", 0.8, 0, None, 0)]),
         ("Pass rush", 15, [("prs_pg", 1, 0, None, 0), ("sacks/g", 1, 0, None, 0)]),
         ("Playmaking", 5, [("ff/g", 1, 0, None, 0)]),
         ("Availability & role", 20, AV[2])],
  "CB": [("Coverage", 55, [("rating_allowed", 1.5, 1, CVT, 25), ("yds_allowed_tgt", 1.2, 1, CVT, 25), ("cmp_allowed_pct", 0.8, 1, CVT, 25),
                            ("tgt_rate", 0.5, 1, DSN, 150), ("pd/g", 1, 0, None, 0), ("ints/g", 1, 0, None, 0)]),
         ("Tackling & run support", 15, [("missed_tkl_pct", 1, 1, TKL, 25), ("tpg", 0.6, 0, None, 0), ("tfl/g", 0.4, 0, None, 0)]),
         ("Playmaking", 10, [("ff/g", 1, 0, None, 0), ("def_td/g", 1, 0, None, 0)]),
         ("Availability & role", 20, AV[2])],
  "S": [("Coverage", 40, [("rating_allowed", 1, 1, CVT, 20), ("yds_allowed_tgt", 0.8, 1, CVT, 20), ("pd/g", 1, 0, None, 0), ("ints/g", 1.2, 0, None, 0)]),
        ("Tackling & run support", 30, [("tpg", 1, 0, None, 0), ("tfl/g", 0.6, 0, None, 0), ("missed_tkl_pct", 1, 1, TKL, 25)]),
        ("Playmaking", 10, [("ff/g", 1, 0, None, 0), ("sacks/g", 0.5, 0, None, 0), ("def_td/g", 0.5, 0, None, 0)]),
        ("Availability & role", 20, AV[2])],
}
KEYS = {"QB": ["epa_db", "anya", "pass_ypg", "cpoe"], "RB": ["scrim_ypg", "rush_ypg", "epa_rush", "ryoe_att"],
        "WR": ["rec_ypg", "ypdb", "epa_tgt", "tgt_share"], "TE": ["rec_ypg", "ypdb", "epa_tgt", "tgt_share"],
        "OL": ["pbwr", "rbwr", "off_snaps", "ss"], "EDGE": ["sacks", "pressures", "prs_100", "prwr"], "IDL": ["sacks", "pressures", "tfl", "rswr"],
        "LB": ["tackles", "tfl", "pressures", "rating_allowed"], "CB": ["rating_allowed", "yds_allowed_tgt", "pd", "ints"],
        "S": ["ints", "pd", "tackles", "rating_allowed"]}
# playing-time qualifier: (min snap share %, min share of team games played, extra test, description)
QUAL = {
  "QB": (0, 0.5, lambda p: "pass" in p["q"], "≥ 14 pass attempts per team game and ≥ half his team's games"),
  "RB": (25, 0.5, lambda p: (p["s"].get("carries", 0) + p["s"].get("targets", 0)) >= 8 * (p.get("tg") or 1), "≥ 8 carries + targets per team game, ≥ 25% snaps, ≥ half his team's games"),
  "WR": (35, 0.5, lambda p: p["s"].get("targets", 0) >= 3 * (p.get("tg") or 1), "≥ 3 targets per team game, ≥ 35% snaps, ≥ half his team's games"),
  "TE": (35, 0.5, lambda p: p["s"].get("targets", 0) >= 1.5 * (p.get("tg") or 1), "≥ 1.5 targets per team game, ≥ 35% snaps, ≥ half his team's games"),
  "OL": (50, 0.5, None, "≥ 50% of offensive snaps and ≥ half his team's games"),
  "EDGE": (35, 0.5, None, "≥ 35% of defensive snaps and ≥ half his team's games"),
  "IDL": (35, 0.5, None, "≥ 35% of defensive snaps and ≥ half his team's games"),
  "LB": (40, 0.5, None, "≥ 40% of defensive snaps and ≥ half his team's games"),
  "CB": (45, 0.5, None, "≥ 45% of defensive snaps and ≥ half his team's games"),
  "S": (45, 0.5, None, "≥ 45% of defensive snaps and ≥ half his team's games"),
}
GROUPS = list(SPEC)
LABELS = {"avail": "Games played / team games", "ss": "Snap share", "int_rate": "INT per attempt", "tgt_rate": "Targets per def. snap",
          "pbwr_pts": "ESPN PBWR list standing", "rbwr_pts": "ESPN RBWR list standing", "prwr_pts": "ESPN PRWR list standing",
          "rswr_pts": "ESPN RSWR list standing", "team:sack_rate": "Team sack rate allowed", "team:rush_epa": "Team EPA/designed rush",
          "team:rush_succ": "Team designed-rush success rate"}

def value(p, key, team_off):
    s = p["s"]; g = max(p.get("g") or 0, 1)
    if key == "avail": return min(1.0, (p.get("g") or 0) / (p.get("tg") or 1))
    if key == "ss": return (p.get("ss") or 0) / 100
    if key == "dropbacks": return s.get("pass_att", 0) + s.get("sacks_taken", 0)
    if key == "int_rate": return s["int"] / s["pass_att"] * 100 if s.get("pass_att") else None
    if key == "tgt_rate": return s.get("tgt_allowed", 0) / s["def_snaps"] * 100 if s.get("def_snaps") else None
    if key.endswith("_pts"):
        w = (p.get("wr") or {}).get(key[:-4]); return (w["n"] + 1 - w["rank"]) / w["n"] if w else 0.0
    if key.startswith("team:"): return (team_off.get(p.get("t")) or {}).get(key[5:])
    if key.endswith("/g"):
        v = s.get(key[:-2]); return None if v is None else v / g
    return s.get(key)

def qualified(p):
    ms, mg, extra, _ = QUAL[p["gr"]]
    if not p.get("g") or not p.get("tg"): return False
    if (p.get("ss") or 0) < ms or p["g"] < mg * p["tg"]: return False
    return extra(p) if extra else True

def compute(D, extra_spec=None):
    """Return {group: [entry, ...] sorted best first}. extra_spec (optional) = {group: (weight 0-1, [stat spec])} blends a
    second standardized composite in (used by forks that add more data)."""
    team_off = D["meta"].get("team_off") or {}
    out = {}
    for grp in GROUPS:
        pool = [p for p in D["players"] if p["gr"] == grp and qualified(p)]
        if len(pool) < 5: out[grp] = []; continue
        def zcols(spec):
            comps = []
            for label, w, stats in spec:
                tot = [0.0] * len(pool); sw = 0
                for key, sw_, lower, vol, k in stats:
                    vals = [value(p, key, team_off) for p in pool]
                    have = [v for v in vals if v is not None and math.isfinite(v)]
                    if len(have) < 3: continue
                    mu = stt.fmean(have); sd = stt.pstdev(have) or 1
                    for i, (p, v) in enumerate(zip(pool, vals)):
                        if v is None or not math.isfinite(v): continue
                        z = max(-3, min(3, (v - mu) / sd)) * (-1 if lower else 1)
                        if vol: n = value(p, vol, team_off) or 0; z *= n / (n + k)
                        tot[i] += sw_ * z
                    sw += sw_
                comps.append((label, w, [t / sw if sw else 0 for t in tot]))
            return comps
        comps = zcols(SPEC[grp])
        W = sum(w for _, w, _ in comps)
        comp = [sum(w * c[i] for _, w, c in comps) / W for i in range(len(pool))]
        def standardize(x):
            sd = stt.pstdev(x) or 1; mu = stt.fmean(x); return [(v - mu) / sd for v in x]
        comp = standardize(comp)
        if extra_spec and grp in extra_spec:
            wp, sp = extra_spec[grp]; c2 = zcols([("x", 1, sp)])[0][2]
            comp = [(1 - wp) * a + wp * b for a, b in zip(comp, standardize(c2))]
        comp = [c * p["g"] / (p["g"] + 1.5) for c, p in zip(comp, pool)]
        comp = standardize(comp)
        rows = []
        for i, p in enumerate(pool):
            csd = {}
            for label, w, c in comps:
                sd = stt.pstdev(c) or 1; csd[label] = round(max(0, min(100, 50 + 16 * c[i] / sd)))
            rows.append(dict(id=p["id"], sc=round(max(0.0, min(100.0, 50 + 16 * comp[i])), 1), z=comp[i], c=csd))
        rows.sort(key=lambda r: -r["z"])
        for i, r in enumerate(rows): r["rk"] = i + 1; r.pop("z")
        out[grp] = rows
    return out

def method_meta():
    return {g: dict(qual=QUAL[g][3], keys=KEYS[g], comps=[dict(l=l, w=w, stats=[dict(k=k, w=sw, lower=bool(lo), shrink=(f"{v}, k={kk}" if v else None),
                    label=LABELS.get(k)) for k, sw, lo, v, kk in st]) for l, w, st in SPEC[g]]) for g in GROUPS}

def snapshot(R): return {g: {r["id"]: [r["rk"], r["sc"]] for r in rows} for g, rows in R.items()}

def store(history_path, season, week, R):
    H = json.load(open(history_path)) if os.path.exists(history_path) else {}
    H.setdefault(str(season), {})[str(week)] = snapshot(R)
    json.dump(H, open(history_path, "w"), separators=(",", ":"))
    return H

def roll(players_path, history_path, out_path, extra_spec=None, edition="free"):
    D = json.load(open(players_path)); m = D["meta"]; season, week = m["season"], m["through_week"]
    R = compute(D, extra_spec)
    H = store(history_path, season, week, R)
    prev_weeks = sorted(int(w) for w in H[str(season)] if int(w) < week)
    pw = prev_weeks[-1] if prev_weeks else None; prev = H[str(season)][str(pw)] if pw else {}
    for g, rows in R.items():
        pg = prev.get(g, {}) if pw else None
        for r in rows:
            if pg is None: r["mv"] = None; continue
            o = pg.get(r["id"]); r["pr"] = o[0] if o else None; r["mv"] = (o[0] - r["rk"]) if o else "new"
    meta = dict(season=season, through_week=week, prev_week=pw, built=m.get("built"), edition=edition,
                history_weeks=sorted(int(w) for w in H[str(season)]), method=method_meta(),
                scale="50 = average qualified player at the position; ±16 points per standard deviation; clipped to 0–100",
                pools={g: len(r) for g, r in R.items()})
    json.dump(dict(meta=meta, groups=R), open(out_path, "w"), separators=(",", ":"))
    print(f"power rankings: {out_path} through week {week} vs week {pw}; pools {meta['pools']}")
    return R

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", type=int, default=2026)
    ap.add_argument("--players"); ap.add_argument("--history", default="data/rankings_history.json"); ap.add_argument("--out")
    ap.add_argument("--baseline", help="players JSON for an earlier week: store its snapshot in the history only")
    a = ap.parse_args()
    if a.baseline:
        D = json.load(open(a.baseline)); store(a.history, D["meta"]["season"], D["meta"]["through_week"], compute(D))
        print(f"stored baseline week {D['meta']['through_week']} in {a.history}")
    else:
        roll(a.players or f"data/players_{a.season}.json", a.history, a.out or f"data/rankings_{a.season}.json")
