#!/usr/bin/env python3
"""Build trades/trades.csv: veteran player-for-draft-pick trades, 2019 to now, with pick values and player features.

Sources
* nflverse/nfldata trades.csv (every NFL trade since 2002, compiled from Pro Football Reference / league transactions)
  https://github.com/nflverse/nfldata/blob/master/data/trades.csv
* trades/manual_trades_2026.csv: trades after nflverse's last entry (2026-04-17), each row cited
  (Pro Football Rumors 2026 trade log, NFL.com deadline tracker, ESPN trade trackers).
* Pick values: Over The Cap / Fitzgerald-Spielberger chart, from nflverse/nfldata draft_values.csv (column `otc`).
* Player features: nflverse players.parquet (birth date, draft slot), Over The Cap historical contracts
  (via nflverse contracts release), and the hub's own season builds (raw/hist/players_<season>.json).
"""
import json, os, sys, math, datetime as dt
import pandas as pd, numpy as np
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from trades.common import (pick_value, pick_label, quality_from_season, load_season, GROUP_OF_POS, contract_at, ROOT)

NFLV = "https://raw.githubusercontent.com/nflverse/nfldata/master/data/trades.csv"

def main():
    t = pd.read_csv(f"{ROOT}/raw/trades.csv", dtype={"trade_id": str})
    t["source"] = NFLV
    m = pd.read_csv(f"{ROOT}/trades/manual_trades_2026.csv", dtype={"trade_id": str})
    pl = pd.read_parquet(f"{ROOT}/raw/players.parquet")
    by_pfr = pl.dropna(subset=["pfr_id"]).drop_duplicates("pfr_id").set_index("pfr_id")
    name_ix = {}
    for _, r in pl.iterrows():
        name_ix.setdefault(str(r.display_name).lower(), []).append(r)
    m["pfr_id"] = None
    for i, r in m.iterrows():
        if isinstance(r.player_name, str):
            c = name_ix.get(r.player_name.lower(), [])
            c = sorted(c, key=lambda x: -(x.last_season or 0))
            if c: m.at[i, "pfr_id"] = c[0].pfr_id if isinstance(c[0].pfr_id, str) else "GSIS:" + c[0].gsis_id
    m = m.rename(columns={"player_name": "pfr_name"}); m["season"] = m.trade_date.str[:4].astype(int)
    t = pd.concat([t[t.trade_date >= "2019-01-01"], m], ignore_index=True)
    contracts = pd.read_parquet(f"{ROOT}/raw/historical_contracts.parquet")
    seasons = {}
    rows, skipped = [], {}
    def skip(why): skipped[why] = skipped.get(why, 0) + 1
    for tid, x in t.groupby("trade_id", sort=False):
        date = x.trade_date.iloc[0]; d = dt.date.fromisoformat(date)
        players = x[x.pick_round.isna() & (x.pfr_id.notna() | x.pfr_name.notna())]
        picks = x[x.pick_round.notna()]
        if len(players) != 1 or picks.empty: skip("not exactly one player + picks"); continue
        pr = players.iloc[0]; old, new = pr.gave, pr.received
        if set(x.gave) - {old, new} or set(x.received) - {old, new}: skip("3-team"); continue
        pid = pr.pfr_id
        if isinstance(pid, str) and pid.startswith("GSIS:"): prow = pl[pl.gsis_id == pid[5:]].iloc[0]
        elif pid in by_pfr.index: prow = by_pfr.loc[pid]; prow = prow.copy(); prow["pfr_id"] = pid
        else: skip("player not found"); continue
        gsis = prow.gsis_id
        draft_year_at_trade = d.year if d.month < 5 else d.year + 1   # the next draft at trade time
        rookie_season = prow.rookie_season if pd.notna(prow.rookie_season) else prow.draft_year
        if pd.isna(rookie_season) or rookie_season >= draft_year_at_trade: skip("no prior NFL season (rookie/draft-day)"); continue
        val_in = val_out = 0.0; got, sent = [], []
        for _, k in picks.iterrows():
            v, n_used = pick_value(int(k.pick_season), int(k.pick_round), k.pick_number, d)
            lab = pick_label(int(k.pick_season), int(k.pick_round), k.pick_number, d, bool(k.conditional == 1)) + f" ({v:.0f})"
            if k.gave == new: val_in += v; got.append(lab)
            else: val_out += v; sent.append(lab)
        net = val_in - val_out
        # season context: in-season trades (Sep-Dec) use that season + the previous; offseason trades use the two prior seasons
        S = d.year if d.month >= 9 else d.year - 1
        qinfo = []
        for s_, w in ((S, 0.6), (S - 1, 0.4)):
            if s_ not in seasons: seasons[s_] = load_season(s_)
            sp = seasons[s_].get(gsis) if seasons[s_] else None
            q, grp = quality_from_season(sp) if sp else (None, None)
            qinfo.append((s_, w, q, grp, sp))
        grp = next((g for *_, g, _ in qinfo if g), None) or GROUP_OF_POS.get(prow.position)
        if not grp: skip("no position group"); continue
        qs = [(w, q) for _, w, q, _, _ in qinfo if q is not None]
        Q = sum(w * q for w, q in qs) / sum(w for w, _ in qs) if qs else None
        snap = max([sp["ss"] or 0 for *_, sp in qinfo if sp] or [0])
        bd = pd.to_datetime(prow.birth_date) if pd.notna(prow.birth_date) else None
        age = (pd.Timestamp(d) - bd).days / 365.25 if bd is not None else None
        ct = contract_at(contracts, gsis, d)
        rows.append(dict(trade_id=tid, date=date, player=pr.pfr_name if isinstance(pr.pfr_name, str) else prow.display_name, gsis_id=gsis,
                         pfr_id=prow.pfr_id if isinstance(prow.pfr_id, str) else None, pos=prow.position, group=grp, from_team=old, to_team=new,
                         age=round(age, 1) if age else None, draft_pick=prow.draft_pick if pd.notna(prow.draft_pick) else None,
                         seasons_used=f"{S}:{qinfo[0][2] if qinfo[0][2] is None else round(qinfo[0][2])}|{S-1}:{qinfo[1][2] if qinfo[1][2] is None else round(qinfo[1][2])}",
                         quality=round(Q, 1) if Q is not None else None, max_snap_share=snap,
                         **ct, picks_received=" + ".join(got), picks_sent_with_player=" + ".join(sent),
                         value_received=round(val_in), value_sent=round(val_out), net_value=round(net),
                         source=x.source.iloc[0]))
    df = pd.DataFrame(rows)
    # keep meaningful veteran trades: a real role (>=25% snaps in a reference season) or a real contract (>=2% of cap)
    df["role"] = (df.max_snap_share >= 25) | (df.apy_cap_pct.fillna(0) >= 0.02)
    keep = df[df.role & (df.net_value > 0)].drop(columns=["role"]).sort_values("date")
    print("candidate single-player trades:", len(df), "kept:", len(keep), "skipped:", skipped)
    keep.to_csv(f"{ROOT}/trades/trades.csv", index=False)
    df.drop(columns=["role"]).sort_values("date").to_csv(f"{ROOT}/raw/trades_all_candidates.csv", index=False)

if __name__ == "__main__":
    main()
