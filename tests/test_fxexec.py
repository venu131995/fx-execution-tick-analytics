import lzma
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from fxexec import analytics as A  # noqa: E402


def test_bi5_records_decode_to_prices_times_and_sizes():
    rec = np.zeros(2, dtype=A.DT)
    rec["ms"] = [0, 1500]
    rec["ask"], rec["bid"] = [117312, 117315], [117310, 117312]
    rec["askv"], rec["bidv"] = [1.5, 2.25], [0.75, 3.0]
    t0 = pd.Timestamp(2025, 9, 1, 12, tz="UTC")
    d = A.decode(lzma.compress(rec.tobytes(), format=lzma.FORMAT_ALONE), t0, 1e-5)
    assert d.t.iloc[1] == t0 + pd.Timedelta("1500ms")
    assert np.allclose(d.ask, [1.17312, 1.17315]) and np.allclose(d.bidv, [0.75, 3.0])


def synthetic(spread_pips=0.2, drift_pips_per_s=0.0, n=522_000, pip=1e-4):
    """Quotes every 100 ms from 06:00 to 20:30 on a Monday, constant spread, linear mid (the sampled arrivals,
    06:00-20:00, then always have 30 minutes of quotes after them)."""
    t = pd.Timestamp("2025-09-01 06:00", tz="UTC") + pd.to_timedelta(np.arange(n) * 100, unit="ms")
    mid = 1.0 + drift_pips_per_s * pip * np.arange(n) * 0.1
    d = pd.DataFrame(dict(ask=mid + 0.5 * spread_pips * pip, bid=mid - 0.5 * spread_pips * pip,
                          askv=1.0, bidv=1.0), index=t)
    return A.finish(d, pip)


def test_immediate_buy_costs_half_the_spread():
    ex = A.execution(synthetic(spread_pips=0.4), 1e-4, 1e6, horizons_min=(0, 5), n=200)
    assert abs(ex[0]["mean_pips"] - 0.2) < 1e-9 and abs(ex[5]["mean_pips"] - 0.2) < 1e-9


def test_slicing_into_a_rising_market_costs_the_average_drift():
    # mid rises 0.01 pip/s; children every 30 s over 5 min: mean delay 135 s -> 1.35 pip plus half spread
    ex = A.execution(synthetic(spread_pips=0.4, drift_pips_per_s=0.01), 1e-4, 1e6, horizons_min=(5,), n=200)
    assert abs(ex[5]["mean_pips"] - (0.2 + 1.35)) < 1e-6
    assert abs(ex[5]["sell_mean_pips"] - (0.2 - 1.35)) < 1e-6 and abs(ex[5]["both_mean_pips"] - 0.2) < 1e-6


def test_latency_cost_matches_a_known_drift():
    lat = A.latency(synthetic(drift_pips_per_s=0.01), 1e-4, lags_ms=(1000,), n=1000)
    assert abs(lat[1000]["abs_mean"] - 0.01) < 1e-9 and lat[1000]["share_moved"] == 1.0
