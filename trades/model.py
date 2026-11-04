#!/usr/bin/env python3
"""Fit the trade-value model on trades/trades.csv and score current players.

Model (transparent, weighted ridge regression on log draft-pick value, Over The Cap / Fitzgerald-Spielberger points):
  log(points) = b0 + position effect (shrunk toward 0) + b_q * quality + b_age * (age-27) + b_cap * APY as % of cap (clipped at 16%)
               + b_rookie * rookie deal + b_ctl * years of control (1-4) + b_exp * expiring + b_ped * young-player draft pedigree
(Tested and dropped: a "market minus actual APY" surplus term and guarantee share; both lost to raw cap % in leave-one-out CV,
 because in real trades bigger contracts signal players the league values more.)
Recency weighting: each trade weighted 0.5 ** (years before the newest trade / 2.5)  (half-life 2.5 years).
Star premium (added Nov 2026): a separate, transparent multiplier exp(k * tier) on top of the regression.
  tier (0-1) = quality factor clip((Q-55)/20) x market-esteem factor clip((APY% of cap - 7%)/3%) (rookie deals: veteran market
  rate for his quality) x prime-age factor clip((31-age)/2) x position weight (QB/EDGE/IDL/WR/CB/OL 1.0, TE/S/LB 0.6, RB 0.4).
  k is fitted on the regression's residuals for tier players, weighted toward recent prices (half-life 0.75 years, i.e. 2025-26
  star trades dominate) and shrunk toward 0 by n_eff/(n_eff+1); capped at log(2.2). Depth players have tier 0 -> no change.
  (Tested and dropped: a convex quality-only term; it overpriced high-quality stars who sold cheaply, e.g. Adams, Sweat, Metcalf.)
Writes trades/model.json (coefficients, fit stats, backtests) and data/trade_values_<season>.json.
"""
import json, os, sys, math, datetime as dt
import pandas as pd, numpy as np
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from trades.common import ROOT, chart, quality_from_season, load_season, CONTRACT_GROUP

GROUPS = ["QB", "RB", "WR", "TE", "OL", "EDGE", "IDL", "LB", "CB", "S"]
STARTERS = dict(QB=32, RB=32, WR=80, TE=32, OL=150, EDGE=56, IDL=56, LB=56, CB=80, S=56)
STRETCH_EXP = 0.5
HALF_LIFE = 2.5; RIDGE_POS = 4.0; RIDGE = 0.5
STAR = dict(q_lo=55, q_hi=75, cap_lo=0.07, cap_hi=0.10, prime_age=29, half_life=0.75, prior=1.0, k_max=math.log(2.2),
            posw=dict(QB=1, EDGE=1, IDL=1, WR=1, CB=1, OL=1, TE=.6, S=.6, LB=.6, RB=.4))
FEATS = ["quality", "age_dev", "cap", "rookie", "control", "expiring", "pedigree"]


def market_curve():
    """APY (% of cap) of starter-level contracts by position group, Over The Cap active contracts; index = quality 0-100."""
    c = pd.read_parquet(f"{ROOT}/raw/historical_contracts.parquet")
    c = c[c.is_active & c.apy_cap_pct.notna()].copy(); c["grp"] = c.position.map(CONTRACT_GROUP)
    curve = {}
    for g in GROUPS:
        v = np.sort(c[c.grp == g].apy_cap_pct.values)[::-1][:STARTERS[g]][::-1]
        curve[g] = [float(np.quantile(v, q / 100)) for q in range(0, 101)]
    return curve

def pedigree(draft_pick, seasons_in_league):
    if draft_pick is None or pd.isna(draft_pick) or seasons_in_league is None or seasons_in_league > 3: return 0.0
    ch = chart(); return math.log(ch[int(min(max(draft_pick, 1), 256))] / ch[64])   # vs. a late-2nd-round pick

CAP_CLIP = 0.16   # cap% beyond the range seen in traded players is not extrapolated
def features(df, curve):
    """Contract term: APY as % of cap. Rookie-scale deals say nothing about how the league values a player, so for them
    we use the market APY a veteran of the same position and quality gets (and flag the rookie deal separately)."""
    X = pd.DataFrame(index=df.index)
    rk = df.rookie_deal.fillna(False).astype(bool).values
    mkt = np.array([curve[g][int(round(min(100, max(0, q))))] for g, q in zip(df.group, df.quality.astype(float))])
    X["quality"] = (df.quality.astype(float) - 50) / 25
    X["age_dev"] = df.age.astype(float) - 27
    X["cap"] = np.clip(np.where(rk, mkt, df.apy_cap_pct.astype(float).values), 0, CAP_CLIP) * 10
    X["rookie"] = rk.astype(float)
    X["control"] = df.years_left.astype(float).clip(lower=1, upper=4)
    X["expiring"] = (df.years_left.fillna(1) <= 1).astype(float)
    X["pedigree"] = [pedigree(p, s) for p, s in zip(df.draft_pick, df.seasons_in_league)]
    for g in GROUPS: X["pos_" + g] = (df.group == g).astype(float)
    return X

def star_tier(X, df):
    """0-1 star tier from the same inputs the model uses (quality, contract esteem, age, position)."""
    q = np.clip((df.quality.astype(float).values - STAR["q_lo"]) / (STAR["q_hi"] - STAR["q_lo"]), 0, 1)
    c = np.clip((X.cap.values / 10 - STAR["cap_lo"]) / (STAR["cap_hi"] - STAR["cap_lo"]), 0, 1)
    a = np.clip((STAR["prime_age"] + 2 - df.age.astype(float).values) / 2, 0, 1)
    pw = np.array([STAR["posw"].get(g, 0.5) for g in df.group])
    return q * c * a * pw

def fit_star(res, tier, yrs):
    ws = tier * 0.5 ** (yrs / STAR["half_life"])
    if ws.sum() <= 0: return dict(k=0.0, n_eff=0.0)
    k = float(np.sum(ws * res) / np.sum(ws * tier)); neff = float(ws.sum() ** 2 / np.sum(ws ** 2))
    return dict(k=float(min(max(k * neff / (neff + STAR["prior"]), 0.0), STAR["k_max"])), n_eff=round(neff, 2), k_raw=round(k, 4))

def fit_full(X, y, w, tier, yrs, star=True):
    b = fit_cal(X, y, w)
    b["_star"] = fit_star(y - predict(b, X), tier, yrs) if star else dict(k=0.0)
    return b

def predict_full(b, X, tier):
    return predict(b, X) + b.get("_star", {}).get("k", 0.0) * tier

def fit(X, y, w):
    cols = list(X.columns); A = np.column_stack([np.ones(len(X)), X.values]); W = np.diag(w)
    pen = np.diag([0.0] + [RIDGE_POS if c.startswith("pos_") else RIDGE for c in cols])
    beta = np.linalg.solve(A.T @ W @ A + pen, A.T @ W @ y)
    return dict(zip(["const"] + cols, beta))

def predict(b, X):
    raw = b["const"] + sum(b[c] * X[c].values for c in X.columns if c in b)
    st = b.get("_stretch")
    return raw if st is None else st["mu"] + (raw - st["mu"]) * st["s"]

def fit_cal(X, y, w):
    """Ridge fit, then a variance calibration: regression shrinks the extremes (stars come out too cheap), so predictions are
    stretched around their weighted mean by s = (sd(actual)/sd(predicted)) ** 0.5, capped at 1.6 ** 0.5."""
    b = fit(X, y, w); p = predict(b, X)
    mu = float(np.sum(w * p) / np.sum(w)); my = float(np.sum(w * y) / np.sum(w))
    ratio = math.sqrt(np.sum(w * (y - my) ** 2) / np.sum(w * (p - mu) ** 2))
    b["_stretch"] = dict(mu=mu, s=min(ratio, 1.6) ** STRETCH_EXP); return b

def wstats(res, w):
    return float(np.sqrt(np.sum(w * res ** 2) / np.sum(w)))

PALETTE = [("early 1st", 5), ("mid 1st", 16), ("late 1st", 28), ("early 2nd", 40), ("late 2nd", 56), ("3rd", 80), ("4th", 112),
           ("5th", 144), ("6th", 176), ("7th", 208)]

def describe(v):
    """Express a point value as the simplest combination of 1-3 standard picks (OTC chart)."""
    ch = chart(); pal = [(n, ch[p]) for n, p in PALETTE]
    if v < ch[240]: return "≈ late-round flier (less than a 7th)"
    best = None
    def consider(names, tot, k):
        nonlocal best
        err = abs(tot - v) / v + 0.08 * (k - 1)
        if best is None or err < best[0]: best = (err, names)
    for i, (a, va) in enumerate(pal):
        consider([a], va, 1)
        for j in range(i, len(pal)):
            b, vb = pal[j]; consider([a, b], va + vb, 2)
            for k in range(j, len(pal)):
                c, vc = pal[k]; consider([a, b, c], va + vb + vc, 3)
    names = best[1]; out = []
    for n in names:
        if out and out[-1][0] == n: out[-1][1] += 1
        else: out.append([n, 1])
    word = {2: "two", 3: "three"}
    return "≈ " + " + ".join((f"{word[c]} {n}s" if c > 1 else n) for n, c in out)

def main(season=2026):
    curve = market_curve()
    tr = pd.read_csv(f"{ROOT}/trades/trades.csv")
    pl = pd.read_parquet(f"{ROOT}/raw/players.parquet").set_index("gsis_id")
    tr["seasons_in_league"] = [ (dt.date.fromisoformat(d).year - (1 if dt.date.fromisoformat(d).month < 9 else 0)) - pl.rookie_season.get(g, np.nan) + 1
                                if g in pl.index and pd.notna(pl.rookie_season.get(g)) else None for d, g in zip(tr.date, tr.gsis_id)]
    use = tr[tr.quality.notna() & tr.age.notna() & tr.apy_cap_pct.notna() & tr.years_left.notna()].copy()
    X = features(use, curve); y = np.log(use.net_value.values.astype(float))
    newest = pd.to_datetime(use.date).max()
    yrs_ago = (newest - pd.to_datetime(use.date)).dt.days.values / 365.25
    w = 0.5 ** (yrs_ago / HALF_LIFE)
    tier = star_tier(X, use)
    def backtests(star):
        b = fit_full(X, y, w, tier, yrs_ago, star); res = y - predict_full(b, X, tier); sigma = wstats(res, w)
        loo = []
        for i in range(len(use)):
            m = np.ones(len(use), bool); m[i] = False
            bi = fit_full(X[m], y[m], w[m], tier[m], yrs_ago[m], star); loo.append(float(predict_full(bi, X.iloc[[i]], tier[[i]])[0]))
        loo = np.array(loo)
        tmask = (pd.to_datetime(use.date) < "2025-03-01").values
        bt = fit_full(X[tmask], y[tmask], w[tmask], tier[tmask], yrs_ago[tmask], star); pt = predict_full(bt, X[~tmask], tier[~tmask])
        sig_t = wstats(y[tmask] - predict_full(bt, X[tmask], tier[tmask]), w[tmask])
        return b, res, sigma, loo, pt, tmask, sig_t
    b0, _, _, loo0, pt0, _, sig_t0 = backtests(False)
    b, res, sigma, loo, pt, tmask, sig_t = backtests(True)
    ybar = np.sum(w * y) / np.sum(w); r2 = 1 - np.sum(w * res ** 2) / np.sum(w * (y - ybar) ** 2)
    loo_err = y - loo; et = y[~tmask] - pt
    def summ(err, sig, pred_, actual):
        ae = np.abs(err)
        return dict(n=int(len(err)), median_abs_log=float(np.median(ae)), median_ratio=float(np.exp(np.median(ae))),
                    within_x1_5=float(np.mean(ae <= math.log(1.5))), within_x2=float(np.mean(ae <= math.log(2))),
                    within_range=float(np.mean(ae <= sig)), spearman=float(pd.Series(actual).rank().corr(pd.Series(pred_).rank())))
    s_loo = summ(loo_err, sigma, loo, y); s_t = summ(et, sig_t, pt, y[~tmask])
    # before/after star premium, overall and on star subsets (leave-one-out, each trade held out of the fit and of k)
    def subset(err, mask):
        e = err[mask]; return dict(n=int(mask.sum()), median_ratio_actual_over_pred=round(float(np.exp(np.median(e))), 3),
                                   median_miss=round(float(np.exp(np.median(np.abs(e)))), 3), within_x2=round(float(np.mean(np.abs(e) <= math.log(2))), 3))
    big = use.net_value.values >= 1500; inp = ((use.quality >= 80) & (use.age <= 30.5)).values; depth = use.net_value.values < 300
    e0 = y - loo0; et0 = y[~tmask] - pt0
    compare = {}
    for lab, e_, et_ in (("before", e0, et0), ("after", loo_err, et)):
        compare[lab] = dict(loo=dict(median_miss=round(float(np.exp(np.median(np.abs(e_)))), 3), within_x2=round(float(np.mean(np.abs(e_) <= math.log(2))), 3)),
                            time_split=dict(median_miss=round(float(np.exp(np.median(np.abs(et_)))), 3), within_x2=round(float(np.mean(np.abs(et_) <= math.log(2))), 3)),
                            big_trades_1500plus=subset(e_, big), high_quality_prime=subset(e_, inp), star_tier_over_half=subset(e_, tier > 0.5),
                            depth_under_300=subset(e_, depth), recent_2025plus=subset(e_, (pd.to_datetime(use.date) >= "2025-01-01").values))
    spot = []
    for i in np.where(big | (tier > 0.5) & (pd.to_datetime(use.date) >= "2025-01-01").values)[0]:
        spot.append(dict(date=use.date.iloc[i], player=use.player.iloc[i], group=use.group.iloc[i], actual=int(use.net_value.iloc[i]),
                         before=int(round(math.exp(loo0[i]))), after=int(round(math.exp(loo[i]))), tier=round(float(tier[i]), 2)))
    spot.sort(key=lambda r: r["date"], reverse=True)
    # baseline: always predict the weighted mean (how much the model helps)
    base_err = y - ybar
    use["pred"] = np.exp(loo).round(); use["pred_no_star"] = np.exp(loo0).round(); use["fit"] = np.exp(predict_full(b, X, tier)).round(); use["star_tier"] = tier.round(3)
    use[["date", "player", "group", "age", "quality", "star_tier", "net_value", "pred_no_star", "pred"]].to_csv(f"{ROOT}/raw/loo_predictions.csv", index=False)
    # baseline contributions use a typical traded player (weighted means)
    xbar = {c: float(np.sum(w * X[c].values) / np.sum(w)) for c in FEATS}
    model = dict(chart="Over The Cap (Fitzgerald-Spielberger) draft value chart, via nflverse draft_values.csv",
                 target="log(net pick value received, OTC points)", half_life_years=HALF_LIFE, ridge=dict(position=RIDGE_POS, other=RIDGE),
                 n_trades=int(len(use)), n_dataset=int(len(tr)), date_range=[str(tr.date.min()), str(tr.date.max())],
                 coef={k: round(float(v), 4) for k, v in b.items() if not k.startswith("_")}, star=dict(STAR, k=round(b["_star"]["k"], 4), n_eff=b["_star"].get("n_eff"), k_raw=b["_star"].get("k_raw"), max_multiplier=round(math.exp(b["_star"]["k"]), 3)),
                 star_backtest=compare, star_spot_check=spot, stretch={k: round(v, 4) for k, v in b["_stretch"].items()}, sigma_log=round(sigma, 4), weighted_r2=round(float(r2), 3),
                 loo=s_loo, time_split=dict(train="before 2025-03-01", test="2025-03-01 onward", **s_t),
                 baseline_median_abs_log=float(np.median(np.abs(base_err))), xbar=xbar)
    json.dump(model, open(f"{ROOT}/trades/model.json", "w"), indent=1)
    print(json.dumps({k: model[k] for k in ("n_trades", "coef", "stretch", "star", "star_backtest", "sigma_log", "weighted_r2", "loo", "time_split", "baseline_median_abs_log")}, indent=1))
    score_players(season, b, sigma, curve, use, X, w, xbar, tier)

def confidence(n_seasons, qual_seasons, grp, games, contract_ok):
    pts = 0
    pts += 2 if qual_seasons >= 2 else 1 if qual_seasons == 1 else 0
    pts += 1 if games >= 10 else 0
    pts += 1 if contract_ok else 0
    pts -= 1 if grp in ("QB", "OL") else 0
    return "High" if pts >= 4 else "Medium" if pts >= 2 else "Low"

def score_players(season, b, sigma, curve, tr, Xtr, wtr, xbar, tier_tr=None):
    cur = json.load(open(f"{ROOT}/data/players_{season}.json")); prev = load_season(season - 1) or {}
    pl = pd.read_parquet(f"{ROOT}/raw/players.parquet").drop_duplicates("gsis_id").set_index("gsis_id")
    c = pd.read_parquet(f"{ROOT}/raw/historical_contracts.parquet"); c = c[c.is_active].sort_values("year_signed")
    act = c.drop_duplicates("gsis_id", keep="last").set_index("gsis_id")
    # Over The Cap 2026 cap data from the NFL Salary Cap Lab (cap hit by year, guarantees)
    cap_path = next((x for x in ("/workspace/nfl-salary-cap/data.json", f"{ROOT}/raw/otc_cap.json") if os.path.exists(x)), None)
    cap = json.load(open(cap_path)) if cap_path else None
    otc = {}
    if cap:
        for t in cap["teams"]:
            for p in t["players"]: otc[str(p["pid"])] = dict(team=t["abbr"], **p)
    caps = {int(k): v["value"] for k, v in cap["caps"].items()} if cap else {}
    today = dt.date.today(); L = today.year if today.month >= 3 else today.year - 1
    meanw = np.sum(wtr)
    tr_feat = Xtr[FEATS].copy(); scale = tr_feat.std().replace(0, 1); ptr = np.log(tr.net_value.values.astype(float))
    out = {}
    for p in cur["players"]:
        gid = p["id"]; grp = p["gr"]
        if grp not in GROUPS: continue
        q_now, _ = quality_from_season(p) if p.get("g") else (None, grp)
        pp = prev.get(gid); q_prev, _ = quality_from_season(pp) if pp else (None, None)
        g_now = p.get("g") or 0; g_prev = (pp or {}).get("g") or 0
        qs = [(0.55, q_now)] if q_now is not None and g_now >= 3 else []
        if q_prev is not None and g_prev >= 4: qs.append((0.45, q_prev))
        r = pl.loc[gid] if gid in pl.index else None
        bd = pd.to_datetime(r.birth_date) if r is not None and pd.notna(r.birth_date) else None
        age = (pd.Timestamp(today) - bd).days / 365.25 if bd is not None else None
        ct = act.loc[gid] if gid in act.index else None
        reasons = []
        if not qs: reasons.append("fewer than 3 games this season and 4 last season")
        if age is None: reasons.append("no birth date")
        if ct is None or pd.isna(ct.apy_cap_pct): reasons.append("no Over The Cap contract on file")
        if reasons:
            if g_now or g_prev: out[gid] = dict(status="insufficient", why="; ".join(reasons))
            continue
        Q = sum(wq * q for wq, q in qs) / sum(wq for wq, _ in qs)
        qual_seasons = sum(1 for (_, q), g in zip(qs, [g_now, g_prev]) if q is not None and q >= 25)
        apy_pct = float(ct.apy_cap_pct); years_left = int(ct.year_signed + (ct.years or 1) - L)
        # Over The Cap current cap detail (cap hit, years, remaining guarantees) from the Salary Cap Lab
        o = otc.get(str(int(ct.otc_id))) if pd.notna(ct.otc_id) else None
        cap_hit = gtd = None; yrs_otc = None
        if o:
            ys = sorted(int(y) for y in o["years"])
            fut = [y for y in ys if y >= L and not o["years"][str(y)][6]]
            if fut: yrs_otc = len(fut); years_left = yrs_otc
            if str(L) in o["years"]: cap_hit = o["years"][str(L)][0]
            gtd = sum((o["years"][str(y)][5] or 0) for y in ys if y >= L)
            cap_by_year = {y: o["years"][str(y)][0] for y in fut}
        rookie = bool(pd.notna(ct.draft_year) and int(ct.draft_year) == int(ct.year_signed))
        seasons_in = (L - r.rookie_season + 1) if r is not None and pd.notna(r.rookie_season) else None
        row = pd.DataFrame([dict(quality=Q, age=age, apy_cap_pct=apy_pct, years_left=years_left, group=grp, rookie_deal=rookie,
                                 draft_pick=r.draft_pick if r is not None and pd.notna(r.draft_pick) else None, seasons_in_league=seasons_in)])
        X = features(row, curve)
        tier = float(star_tier(X, row)[0]); prem = b["_star"]["k"] * tier
        lv = float(predict(b, X)[0]) + prem; v = math.exp(lv)
        lo, hi = math.exp(lv - sigma), math.exp(lv + sigma)
        # drivers: contribution vs a typical traded player, in % of value
        contrib = {}
        for f in FEATS: contrib[f] = b[f] * (X[f].iloc[0] - xbar[f]) * b["_stretch"]["s"]
        pos_mean = sum(b["pos_" + g] * float(np.sum(wtr * Xtr["pos_" + g].values) / np.sum(wtr)) for g in GROUPS)
        contrib["position"] = (b["pos_" + grp] - pos_mean) * b["_stretch"]["s"]
        if prem > 0: contrib["star"] = prem
        # comparables: nearest trades in feature space (same position group weighted), recent trades preferred
        f0 = X[FEATS].iloc[0]
        d = 0.5 * (((tr_feat - f0) / scale) ** 2).sum(axis=1) ** 0.5 + (tr.group.values != grp) * 4.0 + (1 - wtr) * 0.75 + np.abs(ptr - lv) * 1.5
        comps = []
        for i in d.nsmallest(3).index:
            t = tr.loc[i]; comps.append(dict(d=t.date, n=t.player, g=t.group, a=round(float(t.age), 1), ft=t.from_team, tt=t.to_team,
                                            ret=t.picks_received + (f" (sent back {t.picks_sent_with_player})" if isinstance(t.picks_sent_with_player, str) and t.picks_sent_with_player else ""),
                                            v=int(t.net_value), q=round(float(t.quality))))
        conf = confidence(len(qs), qual_seasons, grp, g_now + g_prev, o is not None)
        notes = []
        if grp == "QB": notes.append("QB market is special: starting QBs rarely move for picks alone, so this is a rough guide (few comparable trades).")
        if grp == "OL": notes.append("OL quality uses playing time plus ESPN block win rates when listed; no box-score stats exist for linemen.")
        if g_now < 3: notes.append(f"Played {g_now} games in {season}; estimate leans on {season-1}.")
        if apy_pct < 0.02 and seasons_in and seasons_in <= 4: notes.append("Cheap rookie contract: lots of surplus value.")
        if tier > 0 and rookie: notes.append("Star premium uses the veteran market rate for his quality, since he is on a rookie deal; rookie-contract stars rarely move for picks alone.")
        out[gid] = dict(status="ok", v=round(v), st=round(tier, 2), sp=round(math.exp(prem), 3), lo=round(lo), hi=round(hi), desc=describe(v), conf=conf,
                        Q=round(Q, 1), age=round(age, 1), apy=round(float(ct.apy), 2), apy_pct=round(apy_pct * 100, 2), yl=years_left,
                        cap=cap_hit, gtd=gtd, rk=rookie, ped=bool(abs(float(X.pedigree.iloc[0])) > 0), otc=bool(o), gtd_total=float(ct.guaranteed) if pd.notna(ct.guaranteed) else None,
                        drv={k: round(float(v_), 3) for k, v_ in contrib.items()}, comps=comps, notes=notes,
                        qs=dict(now=None if q_now is None else round(q_now, 1), prev=None if q_prev is None else round(q_prev, 1)))
    meta = dict(season=season, built=dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                model=json.load(open(f"{ROOT}/trades/model.json")) , as_of=str(today))
    ok = [k for k, v in out.items() if v["status"] == "ok"]; vals = sorted((out[k]["v"] for k in ok), reverse=True)
    meta["n_ok"] = len(ok); meta["n_insufficient"] = len(out) - len(ok)
    json.dump(dict(meta=meta, players=out), open(f"{ROOT}/data/trade_values_{season}.json", "w"), separators=(",", ":"), allow_nan=False)
    print(f"scored {len(ok)} players, insufficient {len(out)-len(ok)}")

if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 2026)
