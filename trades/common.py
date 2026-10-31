"""Shared helpers for the trade-value dataset and model."""
import json, os, datetime as dt
import pandas as pd, numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DV = None
def chart():
    """Over The Cap (Fitzgerald-Spielberger) draft value chart, via nflverse/nfldata draft_values.csv."""
    global _DV
    if _DV is None:
        dv = pd.read_csv(os.path.join(ROOT, "raw", "draft_values.csv"))
        _DV = dict(zip(dv.pick.astype(int), dv.otc.astype(float)))
    return _DV

def next_draft(d):
    return d.year if d.month < 5 else d.year + 1

def pick_value(season, rnd, number, d):
    """Value of a pick at trade date d. Known slot if it is in the upcoming draft and the order is set (Jan-Apr);
    otherwise the middle of the round; future drafts are discounted one round (32 slots) per year."""
    D = next_draft(d); yrs = max(0, season - D); ch = chart()
    if yrs == 0 and pd.notna(number) and d.month <= 4: n = int(number)
    else: n = (rnd - 1) * 32 + 16 + 32 * yrs
    n = max(1, min(n, max(ch)))
    return ch[n], n

def pick_label(season, rnd, number, d, cond=False):
    known = season == next_draft(d) and pd.notna(number) and d.month <= 4
    s = f"{season} R{rnd}" + (f" #{int(number)}" if known else "")
    return s + (" (cond.)" if cond else "")

GROUP_OF_POS = {"QB": "QB", "RB": "RB", "FB": "RB", "WR": "WR", "TE": "TE", "T": "OL", "G": "OL", "C": "OL", "OT": "OL", "OG": "OL", "OL": "OL",
                "DE": "EDGE", "DT": "IDL", "NT": "IDL", "DL": "IDL", "OLB": "EDGE", "ILB": "LB", "MLB": "LB", "LB": "LB", "CB": "CB", "DB": "CB",
                "S": "S", "FS": "S", "SS": "S", "SAF": "S"}
CONTRACT_GROUP = {"QB": "QB", "RB": "RB", "FB": "RB", "WR": "WR", "TE": "TE", "LT": "OL", "RT": "OL", "LG": "OL", "RG": "OL", "C": "OL",
                  "ED": "EDGE", "IDL": "IDL", "LB": "LB", "CB": "CB", "S": "S"}

# stats that define "how good" per position group (percentiles within the group among qualified players)
KEY = {"QB": ["epa_db", "cpoe", "anya", "pass_ypg", "succ_db", "rating"],
       "RB": ["rush_ypg", "epa_rush", "ryoe_att", "succ_rush", "scrim_ypg", "total_td"],
       "WR": ["rec_ypg", "ypdb", "epa_tgt", "tgt_share", "ypt", "rec_td"],
       "TE": ["rec_ypg", "ypdb", "epa_tgt", "tgt_share", "ypt", "rec_td"],
       "EDGE": ["pressures", "prs_100", "sacks", "qb_hits", "tfl", "prwr", "rswr"],
       "IDL": ["pressures", "prs_100", "sacks", "qb_hits", "tfl", "prwr", "rswr"],
       "LB": ["tackles", "tfl", "pressures", "pd", "missed_tkl_pct"],
       "CB": ["rating_allowed", "yds_allowed_tgt", "pd", "ints", "cmp_allowed_pct"],
       "S": ["tackles", "pd", "ints", "rating_allowed", "yds_allowed_tgt"],
       "OL": []}

def espn_pct(p, k):
    w = (p.get("wr") or {}).get(k)
    if not w: return None
    return 80 + 20 * (1 - (w["rank"] - 1) / max(1, w["n"] - 1))   # making ESPN's top-N list = 80th-100th pct

def quality_from_season(p):
    """0-100 quality score for one player-season, plus group. Production percentiles (65%) + playing time (35%).
    OL have no box-score stats: 70% of snap share, raised to 80-100 if on an ESPN pass/run-block win-rate list."""
    grp = p.get("gr"); ss = p.get("ss") or 0
    if not grp or not p.get("g"): return None, grp
    play = min(100.0, ss * 1.1)
    if grp == "OL":
        q = 0.7 * play
        e = [v for v in (espn_pct(p, "pbwr"), espn_pct(p, "rbwr")) if v is not None]
        return (max(q, max(e)) if e else q), grp
    pcts = []
    for k in KEY.get(grp, []):
        if k in ("prwr", "rswr", "pbwr", "rbwr"):
            v = espn_pct(p, k)
            if v is not None: pcts.append(v)
            continue
        r = (p.get("r") or {}).get(k)
        if r and r[1] is not None: pcts.append(r[1])
    if len(pcts) >= 2: return 0.65 * float(np.mean(pcts)) + 0.35 * play, grp
    return 0.5 * play * 0.6, grp   # not qualified for the stat pools: part-time player

def load_season(s):
    for path in (f"{ROOT}/data/players_{s}.json", f"{ROOT}/raw/hist/players_{s}.json"):
        if os.path.exists(path):
            return {p["id"]: p for p in json.load(open(path))["players"]}
    return None

def contract_at(contracts, gsis, d):
    """Contract in force at date d (Over The Cap historical contracts via nflverse)."""
    L = d.year if d.month >= 3 else d.year - 1   # league year starts in March
    c0 = contracts[(contracts.gsis_id == gsis) & (contracts.year_signed <= L)].sort_values("year_signed")
    c = c0[c0.year_signed + c0.years.fillna(1) - 1 >= L]
    if c.empty and len(c0) and int(c0.iloc[-1].year_signed + (c0.iloc[-1].years or 1)) >= L - 1:
        c = c0.tail(1)   # extensions are often listed from the signing year; treat the latest deal as in force (final year)
    out = dict(apy_m=None, apy_cap_pct=None, years_left=None, gtd_m=None, rookie_deal=None, cap_pct_now=None)
    if c.empty: return out
    r = c.iloc[-1]
    out.update(apy_m=round(float(r.apy), 3), apy_cap_pct=float(r.apy_cap_pct) if pd.notna(r.apy_cap_pct) else None,
               years_left=max(1, int(r.year_signed + (r.years or 1) - L)), gtd_m=float(r.guaranteed) if pd.notna(r.guaranteed) else None,
               rookie_deal=bool(pd.notna(r.draft_year) and int(r.draft_year) == int(r.year_signed)))
    for h in (r.season_history if r.season_history is not None else []):
        if str(h.get("year")) == str(L) and h.get("cap_percent") is not None: out["cap_pct_now"] = float(h["cap_percent"])
    return out
