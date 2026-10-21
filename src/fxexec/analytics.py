"""Top-of-book tick analytics: Dukascopy bi5 decoding, liquidity by hour, event windows, latency cost and
implementation shortfall of immediate vs sliced orders."""
import lzma

import numpy as np
import pandas as pd

SYMS = {"EURUSD": (1e-5, 1e-4), "USDCHF": (1e-5, 1e-4), "XAUUSD": (1e-3, 0.1)}   # price scale, pip size
DT = np.dtype([("ms", ">u4"), ("ask", ">u4"), ("bid", ">u4"), ("askv", ">f4"), ("bidv", ">f4")])
EVENTS = {"US payrolls": "2025-09-05 12:30", "US CPI": "2025-09-11 12:30", "FOMC": "2025-09-17 18:00",
          "SNB": "2025-09-25 07:30"}


def decode(raw, t0, scale):
    """One hour of Dukascopy ticks: LZMA-compressed big-endian records (ms after the hour, ask, bid, ask and bid
    volume in millions)."""
    a = np.frombuffer(lzma.decompress(raw), dtype=DT)
    return pd.DataFrame(dict(t=t0 + pd.to_timedelta(a["ms"].astype(np.int64), unit="ms"),
                             ask=a["ask"] * scale, bid=a["bid"] * scale, askv=a["askv"], bidv=a["bidv"]))


def load(data, sym):
    scale, pip = SYMS[sym]
    parts = []
    for f in sorted((data / sym).glob("*/*.bi5")):
        if f.stat().st_size == 0:
            continue
        day, hour = int(f.parent.name), int(f.stem)
        parts.append(decode(f.read_bytes(), pd.Timestamp(2025, 9, day, hour, tz="UTC"), scale))
    return finish(pd.concat(parts).set_index("t").sort_index(), pip)


def finish(d, pip):
    d["mid"] = 0.5 * (d.ask + d.bid)
    d["spread_pips"] = (d.ask - d.bid) / pip
    return d


def hourly(d, pip):
    m1 = d.mid.resample("1min").last().dropna()
    r = np.log(m1).diff().dropna()
    g = d.groupby(d.index.hour)
    return pd.DataFrame(dict(spread_med=g.spread_pips.median(), spread_p90=g.spread_pips.quantile(0.9),
                             top_size_med=g.askv.median(), ticks_per_min=g.size() / (d.index.normalize().nunique() * 60),
                             vol_1min_bp=r.groupby(r.index.hour).std() * 1e4))


def events(d, pip):
    out = {}
    for name, ts in EVENTS.items():
        t = pd.Timestamp(ts, tz="UTC")
        win = d[(d.index >= t - pd.Timedelta("10min")) & (d.index < t + pd.Timedelta("10min"))]
        if len(win) == 0:
            continue
        before = win[win.index < t]
        after = win[(win.index >= t) & (win.index < t + pd.Timedelta("2min"))]
        base = d[(d.index.weekday == t.weekday()) & (d.index.hour == t.hour) & (d.index.normalize() != t.normalize())]
        m = d.mid
        move = abs(m.asof(t + pd.Timedelta("5min")) - m.asof(t - pd.Timedelta("1s"))) / pip
        base_moves = []
        for day in sorted(set(base.index.normalize())):
            t1 = day + pd.Timedelta(hours=t.hour, minutes=t.minute)
            a, b = m.asof(t1 - pd.Timedelta("1s")), m.asof(t1 + pd.Timedelta("5min"))
            if np.isfinite(a) and np.isfinite(b):
                base_moves.append(abs(b - a) / pip)
        out[name] = dict(spread_before_med=float(before.spread_pips.median()) if len(before) else None,
                         spread_first2min_max=float(after.spread_pips.max()) if len(after) else None,
                         spread_baseline_med=float(base.spread_pips.median()) if len(base) else None,
                         move_5min_pips=float(move), baseline_move_5min_pips_med=float(np.median(base_moves)) if base_moves else None)
    return out


def latency(d, pip, lags_ms=(50, 100, 250, 500, 1000), n=20000, seed=0):
    rng = np.random.default_rng(seed)
    t = d.index.values.astype("datetime64[ns]").astype(np.int64)
    mid = d.mid.values
    idx = rng.choice(len(d) - 1, size=min(n, len(d) - 1), replace=False)
    res = {}
    for lag in lags_ms:
        j = np.searchsorted(t, t[idx] + lag * 1_000_000, side="right") - 1      # last quote before t + lag
        mv = (mid[j] - mid[idx]) / pip
        res[lag] = dict(abs_mean=float(np.mean(np.abs(mv))), p95=float(np.percentile(np.abs(mv), 95)),
                        share_moved=float(np.mean(mv != 0)))
    return res


def execution(d, pip, size, horizons_min=(0, 5, 15, 30), n=2000, seed=0, max_stale_s=60):
    """Buy (and, separately, sell) at random arrival times, uniform in clock time on weekdays 06:00-20:00 UTC. Immediate: lift the ask once.
    Sliced: equal child orders every 30 s over the horizon, each lifting the ask. The same arrivals are used for every
    horizon; an arrival is kept only if every child order finds a quote at most `max_stale_s` old (no data gaps).
    Sizes are assumed to fit within the displayed top of book (median sizes are reported per hour), so no impact or
    depth beyond the top is modelled; `size` only documents the clip that the top-of-book statistics refer to."""
    rng = np.random.default_rng(seed)
    t = d.index.values.astype("datetime64[ns]").astype(np.int64)
    ask, bid, mid = d.ask.values, d.bid.values, d.mid.values
    days = pd.DatetimeIndex(sorted({x for x in d.index.normalize() if x.weekday() < 5}))
    H_max = max(horizons_min)
    children = {H: (np.arange(0, H * 60, 30) if H else np.zeros(1)) * 1e9 for H in horizons_min}
    starts = []
    while len(starts) < n:
        day = days[rng.integers(len(days))]
        s = (day + pd.Timedelta(hours=6) + pd.Timedelta(seconds=rng.uniform(0, 14 * 3600))).value
        probe = s + children[H_max].astype(np.int64) if H_max else np.array([s])
        j = np.searchsorted(t, probe, side="right") - 1
        if j[0] >= 0 and np.all(probe - t[j] <= max_stale_s * 1e9):
            starts.append(s)
    starts = np.array(starts, dtype=np.int64)
    arr = mid[np.searchsorted(t, starts, side="right") - 1]
    out = {}
    for H in horizons_min:
        x = starts[:, None] + children[H][None, :].astype(np.int64)
        j = np.searchsorted(t, x, side="right") - 1
        sf = (ask[j].mean(1) - arr) / pip                    # buy: pay the ask
        ss = (arr - bid[j].mean(1)) / pip                    # sell: hit the bid
        both = np.concatenate([sf, ss])                      # buys and sells together: the month's drift cancels
        out[H] = dict(mean_pips=float(sf.mean()), std_pips=float(sf.std()), p95_pips=float(np.percentile(sf, 95)),
                      p05_pips=float(np.percentile(sf, 5)), sell_mean_pips=float(ss.mean()),
                      both_mean_pips=float(both.mean()), both_std_pips=float(both.std()),
                      both_p95_pips=float(np.percentile(both, 95)), n=int(len(sf)))
    return out
