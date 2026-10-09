"""
data_gen.py
===========
Generates SYNTHETIC data for the "API Integration SLA & Sync-Health Dashboard".

ALL DATA PRODUCED HERE IS FAKE. It is created with a fixed random seed so the
dashboard is fully reproducible. No real employer, employee, provider account,
or payroll record is represented. Provider names refer to well-known HR/payroll
systems only to make the demo feel realistic -- the connections, employers, and
sync events attached to them are entirely invented.

Domain model (loosely modeled on a Finch-style unified employment API):

  providers   -- the HR / payroll systems we integrate with (the "connectors")
  employers   -- customer accounts that connect ONE provider through the funnel
                 Connect -> Authorize -> First Sync -> Ongoing Sync
  sync_events -- individual data-sync jobs run against connected employers,
                 each with a status (success/failure), a latency, and (on
                 failure) a reason code.

The three builder functions each accept an optional seed so tests are
deterministic. `generate_all()` wires them together into a consistent set.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

SEED = 42

# Date window for the synthetic history.
START_DATE = pd.Timestamp("2025-04-01")
END_DATE = pd.Timestamp("2025-09-30")

# --- SLA targets used across the app -------------------------------------
# An individual sync "meets SLA" if it succeeded AND finished within the
# latency budget. A provider / time-window is "in breach" if its SLA
# attainment falls below the target below.
SLA_LATENCY_BUDGET_SEC = 300.0   # a sync should finish within 5 minutes
SLA_ATTAINMENT_TARGET = 0.98     # 98% of syncs should meet SLA

# Provider catalog. Each row carries "base" characteristics that drive the
# synthetic sync behavior so that some connectors are healthier than others.
#   base_success     -> underlying probability a sync succeeds
#   base_latency_sec -> typical (median-ish) latency for a successful sync
#   auth_latency     -> relative richness, used to vary funnel drop-off
_PROVIDER_CATALOG = [
    # provider,            category,     base_success, base_latency_sec, connect_weight
    ("Gusto",              "Payroll",    0.991, 95,  1.6),
    ("ADP Workforce Now",  "HRIS",       0.965, 240, 1.4),
    ("Workday",            "HRIS",       0.958, 310, 1.1),
    ("BambooHR",           "HRIS",       0.987, 120, 1.3),
    ("Rippling",           "HRIS",       0.990, 85,  1.5),
    ("Paychex Flex",       "Payroll",    0.972, 205, 1.0),
    ("QuickBooks Payroll", "Payroll",    0.983, 140, 1.2),
    ("Justworks",          "PEO",        0.985, 150, 0.9),
    ("TriNet",             "PEO",        0.948, 360, 0.7),
    ("Zenefits",           "HRIS",       0.969, 230, 0.6),
    ("Namely",             "HRIS",       0.955, 290, 0.5),
    ("UKG Pro",            "HRIS",       0.946, 400, 0.6),
    ("Paylocity",          "Payroll",    0.977, 180, 0.8),
    ("Insperity",          "PEO",        0.961, 265, 0.4),
]

_CONNECTION_TYPES = ["API", "Assisted"]
_REGIONS = ["West", "Midwest", "Northeast", "South"]
_SIZE_BANDS = ["1-50", "51-200", "201-1000", "1000+"]
_FAILURE_REASONS = [
    "credential_expired",
    "provider_timeout",
    "rate_limited",
    "schema_mismatch",
    "mfa_required",
    "permission_revoked",
]


def generate_providers() -> pd.DataFrame:
    """Return the static provider / connector catalog as a DataFrame."""
    df = pd.DataFrame(
        _PROVIDER_CATALOG,
        columns=[
            "provider",
            "category",
            "base_success",
            "base_latency_sec",
            "connect_weight",
        ],
    )
    return df


def generate_employers(providers: pd.DataFrame, n: int = 900, seed: int = SEED) -> pd.DataFrame:
    """Generate synthetic connected-employer accounts and their funnel path.

    Each employer attempts to connect exactly one provider and then walks the
    funnel Connect -> Authorize -> First Sync -> Ongoing Sync. Drop-off is
    monotonic: an employer cannot reach a later stage without the earlier one.
    """
    rng = np.random.default_rng(seed)

    weights = providers["connect_weight"].to_numpy()
    probs = weights / weights.sum()
    provider_choice = rng.choice(providers["provider"].to_numpy(), size=n, p=probs)

    conn_type = rng.choice(_CONNECTION_TYPES, size=n, p=[0.78, 0.22])
    region = rng.choice(_REGIONS, size=n, p=[0.34, 0.2, 0.26, 0.2])
    size_band = rng.choice(_SIZE_BANDS, size=n, p=[0.46, 0.3, 0.17, 0.07])

    connect_offsets = rng.integers(0, (END_DATE - START_DATE).days - 20, size=n)
    connect_ts = START_DATE + pd.to_timedelta(connect_offsets, unit="D")

    # Funnel conversion. API connections authorize more reliably than assisted.
    p_authorize = np.where(conn_type == "API", 0.90, 0.78)
    reached_authorize = rng.random(n) < p_authorize

    # Given authorize, probability of a successful first sync.
    p_first = np.where(conn_type == "API", 0.93, 0.86)
    reached_first = reached_authorize & (rng.random(n) < p_first)

    # Given first sync, probability of becoming an ongoing (recurring) sync.
    p_ongoing = 0.94
    reached_ongoing = reached_first & (rng.random(n) < p_ongoing)

    df = pd.DataFrame(
        {
            "employer_id": [f"emp_{i:05d}" for i in range(n)],
            "provider": provider_choice,
            "connection_type": conn_type,
            "region": region,
            "size_band": size_band,
            "connect_ts": connect_ts,
            "reached_authorize": reached_authorize,
            "reached_first_sync": reached_first,
            "reached_ongoing_sync": reached_ongoing,
        }
    )
    return df


def generate_sync_events(
    employers: pd.DataFrame,
    providers: pd.DataFrame,
    seed: int = SEED,
) -> pd.DataFrame:
    """Generate synthetic recurring sync-job events for ongoing-sync employers.

    Only employers that reached the ongoing-sync stage emit recurring events.
    Each event has a timestamp, a success/failure status, a latency in seconds,
    and (on failure) a reason code. Provider base characteristics drive the
    behavior, and a gentle degradation is injected for a couple of connectors in
    the final weeks so the SLA drill-down has a story to tell.
    """
    rng = np.random.default_rng(seed + 1)

    prov_lookup = providers.set_index("provider")[["base_success", "base_latency_sec"]]
    ongoing = employers[employers["reached_ongoing_sync"]].copy()

    rows = []
    total_span_days = (END_DATE - START_DATE).days

    for row in ongoing.itertuples(index=False):
        base_success = prov_lookup.loc[row.provider, "base_success"]
        base_latency = prov_lookup.loc[row.provider, "base_latency_sec"]

        # Syncs run roughly daily from first sync until end of window.
        first_day = max((row.connect_ts - START_DATE).days + 2, 0)
        n_events = max(total_span_days - first_day, 5)
        # Sample a subset of days (not every employer syncs every single day).
        n_events = int(n_events * rng.uniform(0.55, 0.9))
        if n_events <= 0:
            continue
        day_offsets = np.sort(
            rng.choice(np.arange(first_day, total_span_days), size=n_events, replace=True)
        )
        event_ts = START_DATE + pd.to_timedelta(day_offsets, unit="D")

        for ts in event_ts:
            # Late-window degradation for two historically weaker connectors.
            degrade = 0.0
            days_from_end = (END_DATE - ts).days
            if row.provider in ("TriNet", "UKG Pro") and days_from_end <= 35:
                degrade = 0.09 * (1 - days_from_end / 35.0)

            success_prob = max(base_success - degrade, 0.5)
            is_success = rng.random() < success_prob

            # Latency: log-normal around provider base, inflated on failures and
            # during degradation.
            latency = float(
                rng.lognormal(mean=np.log(base_latency), sigma=0.45)
            )
            if not is_success:
                latency *= rng.uniform(1.3, 2.6)
            if degrade > 0:
                latency *= 1 + degrade * 2.5

            reason = "" if is_success else rng.choice(_FAILURE_REASONS)

            rows.append(
                (
                    row.employer_id,
                    row.provider,
                    row.connection_type,
                    ts,
                    "success" if is_success else "failure",
                    round(latency, 1),
                    reason,
                )
            )

    df = pd.DataFrame(
        rows,
        columns=[
            "employer_id",
            "provider",
            "connection_type",
            "event_ts",
            "status",
            "latency_sec",
            "failure_reason",
        ],
    )
    df["event_date"] = df["event_ts"].dt.normalize()
    df = df.sort_values("event_ts").reset_index(drop=True)
    df["event_id"] = [f"evt_{i:07d}" for i in range(len(df))]
    return df


def generate_all(seed: int = SEED):
    """Build a consistent (providers, employers, sync_events) triple."""
    providers = generate_providers()
    employers = generate_employers(providers, seed=seed)
    sync_events = generate_sync_events(employers, providers, seed=seed)
    return providers, employers, sync_events


def main():
    parser = argparse.ArgumentParser(description="Generate synthetic sync-health data.")
    parser.add_argument(
        "--out",
        default=str(Path(__file__).parent / "data"),
        help="Output directory for CSV files.",
    )
    args = parser.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    providers, employers, sync_events = generate_all()

    providers.to_csv(out_dir / "providers.csv", index=False)
    employers.to_csv(out_dir / "employers.csv", index=False)
    sync_events.to_csv(out_dir / "sync_events.csv", index=False)

    print(f"[synthetic] wrote {len(providers)} providers -> {out_dir/'providers.csv'}")
    print(f"[synthetic] wrote {len(employers)} employers -> {out_dir/'employers.csv'}")
    print(f"[synthetic] wrote {len(sync_events)} sync events -> {out_dir/'sync_events.csv'}")
    print("[synthetic] NOTE: all rows are fake, generated with a fixed seed.")


if __name__ == "__main__":
    main()
