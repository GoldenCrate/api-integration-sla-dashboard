"""
analytics.py
============
Framework-free analytics for the API Integration SLA & Sync-Health Dashboard.

This module contains ALL of the metric math. It depends only on pandas / numpy
(no Streamlit), so every function here is unit-testable in isolation -- see
test_analytics.py. app.py is a thin presentation layer on top of these
functions.

An individual sync "meets SLA" when it both:
  * succeeded, and
  * finished within the latency budget (default 300s).

SLA attainment for a group of events is the share of events that meet SLA.
A provider / time-window is "in breach" when its attainment falls below the
attainment target (default 0.98).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from data_gen import SLA_ATTAINMENT_TARGET, SLA_LATENCY_BUDGET_SEC

FUNNEL_STAGES = ["Connect", "Authorize", "First Sync", "Ongoing Sync"]


# ---------------------------------------------------------------------------
# Core SLA primitive
# ---------------------------------------------------------------------------
def meets_sla(
    events: pd.DataFrame,
    latency_budget_sec: float = SLA_LATENCY_BUDGET_SEC,
) -> pd.Series:
    """Boolean Series: did each sync event meet SLA (success AND within budget)?"""
    return (events["status"] == "success") & (events["latency_sec"] <= latency_budget_sec)


# ---------------------------------------------------------------------------
# (1) Headline KPIs
# ---------------------------------------------------------------------------
def kpi_summary(
    employers: pd.DataFrame,
    sync_events: pd.DataFrame,
    providers: pd.DataFrame,
    latency_budget_sec: float = SLA_LATENCY_BUDGET_SEC,
) -> dict:
    """Return the headline KPI tile values.

    Keys:
      connected_employers   -- employers at the ongoing-sync stage
      total_employers       -- all employers that started a connection
      provider_coverage_pct -- providers with >=1 connected employer / catalog
      sync_success_rate     -- share of sync events that succeeded
      median_latency_sec    -- median latency of SUCCESSFUL syncs
      sla_attainment_pct    -- share of sync events meeting SLA
    """
    connected = int(employers["reached_ongoing_sync"].sum())
    total = int(len(employers))

    providers_in_catalog = providers["provider"].nunique()
    providers_live = (
        employers.loc[employers["reached_ongoing_sync"], "provider"].nunique()
    )
    coverage = providers_live / providers_in_catalog if providers_in_catalog else 0.0

    n_events = len(sync_events)
    if n_events:
        success_rate = float((sync_events["status"] == "success").mean())
        ok = sync_events["status"] == "success"
        median_latency = (
            float(sync_events.loc[ok, "latency_sec"].median()) if ok.any() else float("nan")
        )
        sla_attainment = float(meets_sla(sync_events, latency_budget_sec).mean())
    else:
        success_rate = float("nan")
        median_latency = float("nan")
        sla_attainment = float("nan")

    return {
        "connected_employers": connected,
        "total_employers": total,
        "provider_coverage_pct": coverage,
        "providers_live": int(providers_live),
        "providers_in_catalog": int(providers_in_catalog),
        "sync_success_rate": success_rate,
        "median_latency_sec": median_latency,
        "sla_attainment_pct": sla_attainment,
        "total_sync_events": n_events,
    }


# ---------------------------------------------------------------------------
# (2) Sync funnel
# ---------------------------------------------------------------------------
def funnel_counts(employers: pd.DataFrame) -> pd.DataFrame:
    """Return the Connect -> Ongoing Sync funnel with step & overall conversion.

    Columns: stage, count, pct_of_top, step_conversion
    """
    connect = len(employers)
    authorize = int(employers["reached_authorize"].sum())
    first = int(employers["reached_first_sync"].sum())
    ongoing = int(employers["reached_ongoing_sync"].sum())

    counts = [connect, authorize, first, ongoing]
    df = pd.DataFrame({"stage": FUNNEL_STAGES, "count": counts})

    top = counts[0] if counts[0] else 1
    df["pct_of_top"] = df["count"] / top

    prev = df["count"].shift(1)
    df["step_conversion"] = np.where(
        prev.isna(), 1.0, df["count"] / prev.replace(0, np.nan)
    )
    df["step_conversion"] = df["step_conversion"].fillna(0.0)
    return df


def biggest_funnel_dropoff(funnel: pd.DataFrame) -> dict:
    """Identify the funnel step with the largest relative drop-off."""
    work = funnel.copy()
    # Drop-off at each stage = 1 - step_conversion; ignore the top stage.
    work = work.iloc[1:]
    work["dropoff"] = 1 - work["step_conversion"]
    idx = work["dropoff"].idxmax()
    row = work.loc[idx]
    prev_stage = funnel.loc[idx - 1, "stage"]
    return {
        "from_stage": prev_stage,
        "to_stage": row["stage"],
        "dropoff": float(row["dropoff"]),
        "step_conversion": float(row["step_conversion"]),
    }


# ---------------------------------------------------------------------------
# (3) Provider / connector health
# ---------------------------------------------------------------------------
def provider_health(
    sync_events: pd.DataFrame,
    latency_budget_sec: float = SLA_LATENCY_BUDGET_SEC,
    attainment_target: float = SLA_ATTAINMENT_TARGET,
) -> pd.DataFrame:
    """Per-provider health table.

    Columns: provider, events, success_rate, median_latency_sec, p95_latency_sec,
             sla_attainment, is_breach
    Sorted worst SLA attainment first.
    """
    if sync_events.empty:
        return pd.DataFrame(
            columns=[
                "provider",
                "events",
                "success_rate",
                "median_latency_sec",
                "p95_latency_sec",
                "sla_attainment",
                "is_breach",
            ]
        )

    ev = sync_events.copy()
    ev["_sla"] = meets_sla(ev, latency_budget_sec)
    ev["_ok"] = ev["status"] == "success"

    def _agg(g: pd.DataFrame) -> pd.Series:
        ok_lat = g.loc[g["_ok"], "latency_sec"]
        return pd.Series(
            {
                "events": len(g),
                "success_rate": g["_ok"].mean(),
                "median_latency_sec": ok_lat.median() if len(ok_lat) else np.nan,
                "p95_latency_sec": (
                    np.percentile(ok_lat, 95) if len(ok_lat) else np.nan
                ),
                "sla_attainment": g["_sla"].mean(),
            }
        )

    out = ev.groupby("provider", group_keys=False).apply(_agg, include_groups=False).reset_index()
    out["is_breach"] = out["sla_attainment"] < attainment_target
    out = out.sort_values("sla_attainment").reset_index(drop=True)
    return out


def worst_breachers(health: pd.DataFrame, n: int = 3) -> pd.DataFrame:
    """Return the n providers in breach with the lowest SLA attainment."""
    breach = health[health["is_breach"]].copy()
    return breach.sort_values("sla_attainment").head(n).reset_index(drop=True)


def failure_reason_breakdown(sync_events: pd.DataFrame) -> pd.DataFrame:
    """Count failures by reason code, descending. Columns: failure_reason, count, pct."""
    fails = sync_events[sync_events["status"] == "failure"]
    if fails.empty:
        return pd.DataFrame(columns=["failure_reason", "count", "pct"])
    counts = (
        fails["failure_reason"].value_counts().rename_axis("failure_reason").reset_index(name="count")
    )
    counts["pct"] = counts["count"] / counts["count"].sum()
    return counts


# ---------------------------------------------------------------------------
# (4) SLA breach drill-down over time
# ---------------------------------------------------------------------------
def sla_timeseries(
    sync_events: pd.DataFrame,
    latency_budget_sec: float = SLA_LATENCY_BUDGET_SEC,
    attainment_target: float = SLA_ATTAINMENT_TARGET,
    freq: str = "W",
) -> pd.DataFrame:
    """SLA attainment over time at the given resampling frequency.

    Columns: period, events, sla_attainment, success_rate, median_latency_sec,
             is_breach
    """
    if sync_events.empty:
        return pd.DataFrame(
            columns=[
                "period",
                "events",
                "sla_attainment",
                "success_rate",
                "median_latency_sec",
                "is_breach",
            ]
        )

    ev = sync_events.copy()
    ev["_sla"] = meets_sla(ev, latency_budget_sec)
    ev["_ok"] = ev["status"] == "success"
    ev = ev.set_index("event_ts")

    grp = ev.resample(freq)
    out = pd.DataFrame(
        {
            "events": grp.size(),
            "sla_attainment": grp["_sla"].mean(),
            "success_rate": grp["_ok"].mean(),
            "median_latency_sec": grp.apply(
                lambda g: g.loc[g["_ok"], "latency_sec"].median()
                if g["_ok"].any()
                else np.nan
            ),
        }
    )
    out = out[out["events"] > 0].reset_index().rename(columns={"event_ts": "period"})
    out["is_breach"] = out["sla_attainment"] < attainment_target
    return out


def provider_sla_timeseries(
    sync_events: pd.DataFrame,
    provider: str,
    latency_budget_sec: float = SLA_LATENCY_BUDGET_SEC,
    attainment_target: float = SLA_ATTAINMENT_TARGET,
    freq: str = "W",
) -> pd.DataFrame:
    """SLA attainment over time for a single provider."""
    subset = sync_events[sync_events["provider"] == provider]
    return sla_timeseries(subset, latency_budget_sec, attainment_target, freq)


def breach_alert_summary(
    timeseries: pd.DataFrame,
    attainment_target: float = SLA_ATTAINMENT_TARGET,
) -> dict:
    """Summarize a breach timeseries into alert-style facts."""
    if timeseries.empty:
        return {
            "n_periods": 0,
            "n_breach_periods": 0,
            "breach_period_share": float("nan"),
            "latest_attainment": float("nan"),
            "latest_in_breach": False,
            "worst_period_attainment": float("nan"),
        }
    n = len(timeseries)
    n_breach = int(timeseries["is_breach"].sum())
    latest = timeseries.iloc[-1]
    return {
        "n_periods": n,
        "n_breach_periods": n_breach,
        "breach_period_share": n_breach / n,
        "latest_attainment": float(latest["sla_attainment"]),
        "latest_in_breach": bool(latest["is_breach"]),
        "worst_period_attainment": float(timeseries["sla_attainment"].min()),
        "attainment_target": attainment_target,
    }
