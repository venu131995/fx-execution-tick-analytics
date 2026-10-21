"""Execution analytics on one month of top-of-book ticks (Dukascopy, September 2025) for EUR/USD, USD/CHF and XAU/USD.

1. Liquidity by hour (UTC): quoted spread, displayed top-of-book size, tick rate, 1-minute realised volatility.
2. Event windows: US payrolls (5 Sep, 12:30 UTC), US CPI (11 Sep, 12:30), FOMC (17 Sep, 18:00), SNB (25 Sep, 07:30):
   spread and absolute mid move in the minutes around each release against the same weekday-time baseline.
3. Latency cost: the adverse mid move within 50 ms - 1 s after a quote, i.e. what a slow fill or a last-look window
   costs on average and in the tail.
4. Immediate vs sliced execution of a client order: implementation shortfall against the arrival mid, from the real
   quotes at random arrival times, crossing the spread at each child order (no market impact assumed).
Writes results/summary.json and figures/.
"""
import json
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from fxexec.analytics import SYMS, events, execution, hourly, latency, load  # noqa: E402

DATA = ROOT / "data"


def main():
    (ROOT / "results").mkdir(exist_ok=True)
    (ROOT / "figures").mkdir(exist_ok=True)
    res = {}
    hours = {}
    for sym, (scale, pip) in SYMS.items():
        d = load(DATA, sym)
        h = hourly(d, pip)
        hours[sym] = h
        size = 1e6 if sym != "XAUUSD" else 1000.0
        res[sym] = dict(ticks=int(len(d)), days=int(d.index.normalize().nunique()),
                        spread_median_pips=float(d.spread_pips.median()),
                        hourly=h.round(4).to_dict(orient="index"), events=events(d, pip), latency=latency(d, pip),
                        execution=execution(d, pip, size))
        print(sym, json.dumps({k: v for k, v in res[sym].items() if k != "hourly"}, default=float)[:1500], flush=True)
    (ROOT / "results" / "summary.json").write_text(json.dumps(res, indent=1, default=float))
    fig, ax = plt.subplots(1, 2, figsize=(10, 3.6))
    for sym, h in hours.items():
        ax[0].plot(h.index, h.spread_med / h.spread_med.min(), marker="o", ms=3, label=sym)
        ax[1].plot(h.index, h.vol_1min_bp, marker="o", ms=3, label=sym)
    ax[0].set_xlabel("hour (UTC)"); ax[0].set_ylabel("median spread / best hour"); ax[0].legend(frameon=True, fontsize=8)
    ax[1].set_xlabel("hour (UTC)"); ax[1].set_ylabel("1-minute volatility (bp)")
    fig.tight_layout(); fig.savefig(ROOT / "figures" / "liquidity_by_hour.png", dpi=150); plt.close(fig)


if __name__ == "__main__":
    main()
