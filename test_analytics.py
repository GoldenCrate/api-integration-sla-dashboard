"""
test_analytics.py
=================
Unit tests for the framework-free analytics layer. Tests use both a tiny,
hand-built fixture (so the expected numbers are obvious) and the full synthetic
dataset (so we exercise the real shapes and invariants).

Run with:  pytest -q
"""

import numpy as np
import pandas as pd
import pytest

import analytics as an
from data_gen import generate_all, SLA_ATTAINMENT_TARGET


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def synthetic():
    providers, employers, sync_events = generate_all()
    return providers, employers, sync_events


@pytest.fixture
def tiny_events():
    """6 events with known SLA outcomes (budget = 300s).

    success & 100s  -> meets SLA
    success & 250s  -> meets SLA
    success & 500s  -> fails SLA (too slow)
    failure & 100s  -> fails SLA (not success)
    success & 300s  -> meets SLA (boundary, <=)
    failure & 900s  -> fails SLA
    => 3 of 6 meet SLA; success_rate = 4/6
    """
    return pd.DataFrame(
        {
            "employer_id": [f"e{i}" for i in range(6)],
            "provider": ["A", "A", "A", "B", "B", "B"],
            "connection_type": ["API"] * 6,
            "event_ts": pd.to_datetime(
                [
                    "2025-04-01",
                    "2025-04-02",
                    "2025-04-03",
                    "2025-04-04",
                    "2025-04-05",
                    "2025-04-06",
                ]
            ),
            "status": ["success", "success", "success", "failure", "success", "failure"],
            "latency_sec": [100.0, 250.0, 500.0, 100.0, 300.0, 900.0],
            "failure_reason": ["", "", "", "provider_timeout", "", "rate_limited"],
        }
    )


@pytest.fixture
def tiny_employers():
    """10 employers with a known funnel: 10 -> 8 -> 6 -> 5."""
    auth = [True] * 8 + [False] * 2
    first = [True] * 6 + [False] * 4
    ongoing = [True] * 5 + [False] * 5
    return pd.DataFrame(
        {
            "employer_id": [f"e{i}" for i in range(10)],
            "provider": ["A"] * 5 + ["B"] * 5,
            "connection_type": ["API"] * 10,
            "region": ["West"] * 10,
            "size_band": ["1-50"] * 10,
            "connect_ts": pd.to_datetime(["2025-04-01"] * 10),
            "reached_authorize": auth,
            "reached_first_sync": first,
            "reached_ongoing_sync": ongoing,
        }
    )


@pytest.fixture
def tiny_providers():
    return pd.DataFrame(
        {
            "provider": ["A", "B", "C"],
            "category": ["Payroll", "HRIS", "PEO"],
            "base_success": [0.99, 0.95, 0.9],
            "base_latency_sec": [100, 200, 300],
            "connect_weight": [1.0, 1.0, 1.0],
        }
    )


# ---------------------------------------------------------------------------
# meets_sla
# ---------------------------------------------------------------------------
def test_meets_sla_logic(tiny_events):
    res = an.meets_sla(tiny_events, latency_budget_sec=300.0)
    assert res.tolist() == [True, True, False, False, True, False]
    assert res.sum() == 3


def test_meets_sla_boundary_is_inclusive():
    ev = pd.DataFrame({"status": ["success"], "latency_sec": [300.0]})
    assert an.meets_sla(ev, 300.0).iloc[0] == True  # noqa: E712


# ---------------------------------------------------------------------------
# kpi_summary
# ---------------------------------------------------------------------------
def test_kpi_summary_tiny(tiny_employers, tiny_events, tiny_providers):
    kpi = an.kpi_summary(tiny_employers, tiny_events, tiny_providers, latency_budget_sec=300.0)
    assert kpi["connected_employers"] == 5
    assert kpi["total_employers"] == 10
    # Ongoing employers are the first 5 (all provider A) -> 1 of 3 catalog live.
    assert kpi["providers_live"] == 1
    assert kpi["provider_coverage_pct"] == pytest.approx(1 / 3)
    assert kpi["sync_success_rate"] == pytest.approx(4 / 6)
    assert kpi["sla_attainment_pct"] == pytest.approx(3 / 6)
    # Median latency of successful syncs: [100,250,500,300] -> median 275.
    assert kpi["median_latency_sec"] == pytest.approx(275.0)


def test_kpi_summary_empty_events(tiny_employers, tiny_providers):
    empty = pd.DataFrame(
        columns=["status", "latency_sec", "provider", "event_ts"]
    )
    kpi = an.kpi_summary(tiny_employers, empty, tiny_providers)
    assert kpi["total_sync_events"] == 0
    assert np.isnan(kpi["sync_success_rate"])


# ---------------------------------------------------------------------------
# funnel
# ---------------------------------------------------------------------------
def test_funnel_counts(tiny_employers):
    f = an.funnel_counts(tiny_employers)
    assert f["stage"].tolist() == an.FUNNEL_STAGES
    assert f["count"].tolist() == [10, 8, 6, 5]
    assert f["pct_of_top"].tolist() == pytest.approx([1.0, 0.8, 0.6, 0.5])
    # Step conversions: 1.0, 8/10, 6/8, 5/6
    assert f["step_conversion"].tolist() == pytest.approx([1.0, 0.8, 0.75, 5 / 6])


def test_biggest_dropoff(tiny_employers):
    f = an.funnel_counts(tiny_employers)
    drop = an.biggest_funnel_dropoff(f)
    # Steps lose 0%, 20%, 25%, ~16.7% -> biggest is First Sync (25%).
    assert drop["to_stage"] == "First Sync"
    assert drop["from_stage"] == "Authorize"
    assert drop["dropoff"] == pytest.approx(0.25)


# ---------------------------------------------------------------------------
# provider health
# ---------------------------------------------------------------------------
def test_provider_health_tiny(tiny_events):
    h = an.provider_health(tiny_events, latency_budget_sec=300.0, attainment_target=0.98)
    assert set(h["provider"]) == {"A", "B"}
    a = h[h["provider"] == "A"].iloc[0]
    b = h[h["provider"] == "B"].iloc[0]
    # A: 3 success/3 -> success_rate 1.0; SLA meets 2/3 (500s fails).
    assert a["success_rate"] == pytest.approx(1.0)
    assert a["sla_attainment"] == pytest.approx(2 / 3)
    # B: 1 success/3 -> success_rate 1/3; SLA meets 1/3.
    assert b["success_rate"] == pytest.approx(1 / 3)
    assert b["sla_attainment"] == pytest.approx(1 / 3)
    # Both below 0.98 target -> both in breach.
    assert bool(a["is_breach"]) and bool(b["is_breach"])
    # Sorted worst attainment first => B before A.
    assert h.iloc[0]["provider"] == "B"


def test_worst_breachers(tiny_events):
    h = an.provider_health(tiny_events, attainment_target=0.98)
    worst = an.worst_breachers(h, n=1)
    assert len(worst) == 1
    assert worst.iloc[0]["provider"] == "B"


def test_failure_reason_breakdown(tiny_events):
    br = an.failure_reason_breakdown(tiny_events)
    assert set(br["failure_reason"]) == {"provider_timeout", "rate_limited"}
    assert br["count"].sum() == 2
    assert br["pct"].sum() == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# SLA timeseries
# ---------------------------------------------------------------------------
def test_sla_timeseries_daily(tiny_events):
    ts = an.sla_timeseries(tiny_events, latency_budget_sec=300.0, attainment_target=0.98, freq="D")
    assert len(ts) == 6  # 6 distinct days
    assert ts["events"].sum() == 6
    assert (ts["sla_attainment"].between(0, 1)).all()


def test_breach_alert_summary(tiny_events):
    ts = an.sla_timeseries(tiny_events, freq="D")
    summ = an.breach_alert_summary(ts)
    assert summ["n_periods"] == 6
    assert summ["n_breach_periods"] >= 1
    assert 0 <= summ["breach_period_share"] <= 1


# ---------------------------------------------------------------------------
# Invariants on the full synthetic dataset
# ---------------------------------------------------------------------------
def test_synthetic_is_reproducible():
    _, emp1, ev1 = generate_all()
    _, emp2, ev2 = generate_all()
    pd.testing.assert_frame_equal(emp1, emp2)
    pd.testing.assert_frame_equal(ev1, ev2)


def test_synthetic_funnel_monotonic(synthetic):
    _, employers, _ = synthetic
    f = an.funnel_counts(employers)
    counts = f["count"].tolist()
    assert counts == sorted(counts, reverse=True)  # monotonically non-increasing
    assert all(0 <= c <= 1.0 for c in f["step_conversion"])


def test_synthetic_kpis_sane(synthetic):
    providers, employers, sync_events = synthetic
    kpi = an.kpi_summary(employers, sync_events, providers)
    assert kpi["total_employers"] == len(employers)
    assert 0 < kpi["sync_success_rate"] <= 1
    assert 0 < kpi["sla_attainment_pct"] <= 1
    assert kpi["sla_attainment_pct"] <= kpi["sync_success_rate"]  # SLA is stricter
    assert kpi["median_latency_sec"] > 0
    assert 0 < kpi["provider_coverage_pct"] <= 1


def test_synthetic_provider_health_shape(synthetic):
    _, _, sync_events = synthetic
    h = an.provider_health(sync_events)
    assert len(h) >= 1
    assert (h["success_rate"].between(0, 1)).all()
    assert (h["sla_attainment"].between(0, 1)).all()
    # Attainment should be sorted ascending (worst first).
    assert h["sla_attainment"].is_monotonic_increasing


def test_synthetic_has_degraded_breachers(synthetic):
    """The generator injects late-window degradation for TriNet / UKG Pro."""
    _, _, sync_events = synthetic
    h = an.provider_health(sync_events)
    breachers = set(an.worst_breachers(h, n=5)["provider"])
    assert breachers & {"TriNet", "UKG Pro"}
