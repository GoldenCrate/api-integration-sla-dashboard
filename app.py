"""
app.py
======
API Integration SLA & Sync-Health Dashboard -- a Streamlit demo styled after a
Sigma operational dashboard, built for a Finch-style unified employment API.

ALL DATA IS SYNTHETIC (see data_gen.py). This is a portfolio piece, not a view
of any real system. The compute lives in analytics.py; this file is the
presentation layer only.

Author: Leo Chan -- github.com/GoldenCrate
"""

from __future__ import annotations

import altair as alt
import pandas as pd
import streamlit as st

import analytics as an
from data_gen import (
    SLA_ATTAINMENT_TARGET,
    SLA_LATENCY_BUDGET_SEC,
    generate_all,
)

# ---------------------------------------------------------------------------
# Storytelling-with-Data palette: mostly gray, one accent, red only for alarm.
# ---------------------------------------------------------------------------
INK = "#1F2A37"          # near-black text
GRAY = "#9AA4B2"         # muted baseline / secondary
GRAY_LIGHT = "#E5E8EC"   # gridlines / tracks
ACCENT = "#2457D6"       # single highlight blue
GOOD = "#1F9D6B"         # healthy (used sparingly)
BREACH = "#D64545"       # SLA breach / alarm
GOLD = "#C68A12"         # watch / near-threshold

alt.data_transformers.disable_max_rows()

st.set_page_config(
    page_title="Sync-Health & SLA Dashboard",
    page_icon="🔌",
    layout="wide",
)


# ---------------------------------------------------------------------------
# Data loading (cached)
# ---------------------------------------------------------------------------
@st.cache_data(show_spinner=False)
def load_data():
    providers, employers, sync_events = generate_all()
    return providers, employers, sync_events


providers, employers, sync_events = load_data()


# ---------------------------------------------------------------------------
# Small presentation helpers
# ---------------------------------------------------------------------------
def pct(x: float, digits: int = 1) -> str:
    if x is None or pd.isna(x):
        return "--"
    return f"{x * 100:.{digits}f}%"


def kpi_tile(col, label: str, value: str, sub: str = "", tone: str = "neutral"):
    bar = {"neutral": ACCENT, "good": GOOD, "breach": BREACH, "watch": GOLD}[tone]
    col.markdown(
        f"""
        <div style="border:1px solid {GRAY_LIGHT};border-left:5px solid {bar};
             border-radius:8px;padding:14px 16px;background:#FFFFFF;">
          <div style="font-size:0.72rem;letter-spacing:.04em;text-transform:uppercase;
               color:{GRAY};font-weight:600;">{label}</div>
          <div style="font-size:1.85rem;font-weight:700;color:{INK};line-height:1.15;
               margin-top:2px;">{value}</div>
          <div style="font-size:0.78rem;color:{GRAY};margin-top:2px;">{sub}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def so_what(title: str, body: str):
    st.markdown(
        f"""
        <div style="border:1px solid {GRAY_LIGHT};border-radius:8px;
             background:#F7F9FC;padding:14px 18px;margin-top:8px;">
          <div style="font-size:0.78rem;letter-spacing:.05em;text-transform:uppercase;
               color:{ACCENT};font-weight:700;">So what → {title}</div>
          <div style="font-size:0.95rem;color:{INK};margin-top:6px;line-height:1.5;">{body}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def takeaway_title(text: str):
    st.markdown(
        f"<div style='font-size:1.15rem;font-weight:700;color:{INK};"
        f"margin:4px 0 2px;'>{text}</div>",
        unsafe_allow_html=True,
    )


# ---------------------------------------------------------------------------
# Sidebar: navigation + global filters
# ---------------------------------------------------------------------------
st.sidebar.markdown("### 🔌 Sync-Health & SLA")
st.sidebar.caption("Operational dashboard · synthetic demo data")

view = st.sidebar.radio(
    "View",
    ["Overview", "Sync Funnel", "Connector Health", "SLA Breach Drill-down"],
)

st.sidebar.divider()
st.sidebar.markdown("**SLA definition**")
st.sidebar.caption(
    f"A sync *meets SLA* if it succeeds **and** finishes within "
    f"**{int(SLA_LATENCY_BUDGET_SEC)}s**. A connector is *in breach* below "
    f"**{pct(SLA_ATTAINMENT_TARGET, 0)}** attainment."
)

cat_options = ["All"] + sorted(providers["category"].unique().tolist())
sel_cat = st.sidebar.selectbox("Provider category", cat_options)

if sel_cat != "All":
    keep = providers.loc[providers["category"] == sel_cat, "provider"]
    f_sync = sync_events[sync_events["provider"].isin(keep)]
    f_emp = employers[employers["provider"].isin(keep)]
else:
    f_sync, f_emp = sync_events, employers

st.sidebar.divider()
st.sidebar.warning("All figures are SYNTHETIC (fixed-seed). Not real data.", icon="⚠️")
st.sidebar.caption("Leo Chan · github.com/GoldenCrate")


# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------
st.markdown(
    f"<h1 style='margin-bottom:0;color:{INK};'>API Integration Sync-Health & SLA</h1>",
    unsafe_allow_html=True,
)
st.caption(
    "Unified-employment-API operations view · "
    f"window {sync_events['event_ts'].min():%b %d} – {sync_events['event_ts'].max():%b %d, %Y} · "
    "synthetic data"
)


# ===========================================================================
# VIEW 1 — OVERVIEW / KPI TILES
# ===========================================================================
if view == "Overview":
    kpi = an.kpi_summary(f_emp, f_sync, providers)

    takeaway_title(
        "Volumes are healthy, but latency — not failures — is dragging SLA attainment to "
        f"{pct(kpi['sla_attainment_pct'], 0)}."
    )

    c1, c2, c3, c4, c5 = st.columns(5)
    kpi_tile(
        c1, "Connected employers",
        f"{kpi['connected_employers']:,}",
        f"of {kpi['total_employers']:,} started",
        tone="neutral",
    )
    kpi_tile(
        c2, "Provider coverage",
        pct(kpi["provider_coverage_pct"], 0),
        f"{kpi['providers_live']}/{kpi['providers_in_catalog']} connectors live",
        tone="good" if kpi["provider_coverage_pct"] >= 0.9 else "watch",
    )
    kpi_tile(
        c3, "Sync success rate",
        pct(kpi["sync_success_rate"], 1),
        f"{kpi['total_sync_events']:,} syncs",
        tone="good" if kpi["sync_success_rate"] >= 0.97 else "watch",
    )
    kpi_tile(
        c4, "Median sync latency",
        f"{kpi['median_latency_sec']:.0f}s",
        f"budget {int(SLA_LATENCY_BUDGET_SEC)}s",
        tone="good" if kpi["median_latency_sec"] <= SLA_LATENCY_BUDGET_SEC else "watch",
    )
    sla_tone = "good" if kpi["sla_attainment_pct"] >= SLA_ATTAINMENT_TARGET else "breach"
    kpi_tile(
        c5, "SLA attainment",
        pct(kpi["sla_attainment_pct"], 0),
        f"target {pct(SLA_ATTAINMENT_TARGET, 0)}",
        tone=sla_tone,
    )

    st.write("")
    left, right = st.columns([3, 2])

    # SLA attainment trend (weekly) with threshold.
    ts = an.sla_timeseries(f_sync)
    base = alt.Chart(ts).encode(
        x=alt.X("period:T", title=None, axis=alt.Axis(format="%b %d", grid=False))
    )
    line = base.mark_line(color=ACCENT, strokeWidth=2.5).encode(
        y=alt.Y(
            "sla_attainment:Q",
            title="SLA attainment",
            scale=alt.Scale(domain=[0, 1]),
            axis=alt.Axis(format="%", grid=True, gridColor=GRAY_LIGHT),
        ),
        tooltip=[
            alt.Tooltip("period:T", title="Week of", format="%b %d"),
            alt.Tooltip("sla_attainment:Q", title="SLA", format=".1%"),
            alt.Tooltip("events:Q", title="Syncs", format=","),
        ],
    )
    rule = (
        alt.Chart(pd.DataFrame({"y": [SLA_ATTAINMENT_TARGET]}))
        .mark_rule(color=BREACH, strokeDash=[5, 4])
        .encode(y="y:Q")
    )
    with left:
        takeaway_title("SLA attainment sits well below the 98% target every week")
        st.altair_chart((line + rule).properties(height=260), use_container_width=True)

    # Success vs SLA gap framing.
    with right:
        takeaway_title("The gap is speed, not reliability")
        gap_df = pd.DataFrame(
            {
                "metric": ["Sync success rate", "SLA attainment"],
                "value": [kpi["sync_success_rate"], kpi["sla_attainment_pct"]],
                "tone": [GOOD, BREACH],
            }
        )
        bars = (
            alt.Chart(gap_df)
            .mark_bar(size=46)
            .encode(
                y=alt.Y("metric:N", title=None, sort=None, axis=alt.Axis(labelLimit=200)),
                x=alt.X(
                    "value:Q",
                    title=None,
                    scale=alt.Scale(domain=[0, 1]),
                    axis=alt.Axis(format="%", grid=False),
                ),
                color=alt.Color("tone:N", scale=None, legend=None),
            )
        )
        labels = bars.mark_text(align="left", dx=5, color=INK, fontWeight="bold").encode(
            text=alt.Text("value:Q", format=".0%")
        )
        st.altair_chart((bars + labels).properties(height=160), use_container_width=True)

    so_what(
        "Attack latency on the slow connectors",
        "Syncs succeed 97% of the time, yet only ~78% land inside the 5-minute SLA — the "
        "shortfall is almost entirely latency on a handful of slow HRIS/PEO connectors, not "
        "outright failures. Prioritizing latency work (pagination, incremental pulls, caching) "
        "on the worst connectors would lift SLA attainment far more than chasing the last "
        "point of success rate. See the Connector Health view for the specific targets.",
    )


# ===========================================================================
# VIEW 2 — SYNC FUNNEL
# ===========================================================================
elif view == "Sync Funnel":
    funnel = an.funnel_counts(f_emp)
    drop = an.biggest_funnel_dropoff(funnel)

    takeaway_title(
        f"{pct(funnel.iloc[-1]['pct_of_top'], 0)} of employers that start a connection reach "
        "steady-state ongoing sync"
    )

    funnel = funnel.copy()
    funnel["label"] = funnel.apply(
        lambda r: f"{int(r['count']):,}  ({pct(r['pct_of_top'],0)})", axis=1
    )
    funnel["is_worst"] = funnel["stage"] == drop["to_stage"]

    bars = (
        alt.Chart(funnel)
        .mark_bar(size=40)
        .encode(
            y=alt.Y("stage:N", sort=an.FUNNEL_STAGES, title=None,
                    axis=alt.Axis(labelFontWeight="bold")),
            x=alt.X("count:Q", title="Employers", axis=alt.Axis(grid=False, format=",")),
            color=alt.condition(
                alt.datum.is_worst, alt.value(BREACH), alt.value(ACCENT)
            ),
        )
    )
    labels = bars.mark_text(align="left", dx=6, color=INK, fontWeight="bold").encode(
        text="label:N"
    )
    st.altair_chart((bars + labels).properties(height=280), use_container_width=True)

    # Step-conversion strip.
    takeaway_title("Step-by-step conversion")
    cols = st.columns(len(an.FUNNEL_STAGES) - 1)
    for i, col in enumerate(cols, start=1):
        row = funnel.iloc[i]
        tone = "breach" if row["stage"] == drop["to_stage"] else "neutral"
        kpi_tile(
            col,
            f"{funnel.iloc[i-1]['stage']} → {row['stage']}",
            pct(row["step_conversion"], 1),
            f"{int(funnel.iloc[i-1]['count']):,} → {int(row['count']):,}",
            tone=tone,
        )

    so_what(
        f"Biggest leak: {drop['from_stage']} → {drop['to_stage']}",
        f"The largest single drop-off is {drop['from_stage']} → {drop['to_stage']} "
        f"(losing {pct(drop['dropoff'],0)} of employers at that step). Because assisted "
        "connections authorize less reliably than direct API connections in this data, the "
        "highest-leverage fixes are at authorization: clearer credential/permission prompts and "
        "proactive handling of MFA. Recovering even half of that step would add hundreds of "
        "steady-state connected employers without any new provider work.",
    )


# ===========================================================================
# VIEW 3 — CONNECTOR / PROVIDER HEALTH
# ===========================================================================
elif view == "Connector Health":
    health = an.provider_health(f_sync)
    worst = an.worst_breachers(health, n=3)

    takeaway_title(
        f"{int(health['is_breach'].sum())} of {len(health)} connectors are below the "
        f"{pct(SLA_ATTAINMENT_TARGET,0)} SLA target — latency is the common thread"
    )

    h = health.copy()
    h["is_worst"] = h["provider"].isin(worst["provider"])

    left, right = st.columns(2)

    # SLA attainment by provider.
    with left:
        takeaway_title("SLA attainment by connector")
        bars = (
            alt.Chart(h)
            .mark_bar()
            .encode(
                y=alt.Y("provider:N", sort="-x", title=None),
                x=alt.X("sla_attainment:Q", title="SLA attainment",
                        scale=alt.Scale(domain=[0, 1]),
                        axis=alt.Axis(format="%", grid=False)),
                color=alt.condition(
                    alt.datum.sla_attainment < SLA_ATTAINMENT_TARGET,
                    alt.value(BREACH), alt.value(GOOD)
                ),
                tooltip=[
                    alt.Tooltip("provider:N"),
                    alt.Tooltip("sla_attainment:Q", title="SLA", format=".1%"),
                    alt.Tooltip("success_rate:Q", title="Success", format=".1%"),
                    alt.Tooltip("median_latency_sec:Q", title="Median latency (s)", format=".0f"),
                    alt.Tooltip("events:Q", title="Syncs", format=","),
                ],
            )
        )
        target = (
            alt.Chart(pd.DataFrame({"x": [SLA_ATTAINMENT_TARGET]}))
            .mark_rule(color=INK, strokeDash=[4, 4])
            .encode(x="x:Q")
        )
        st.altair_chart((bars + target).properties(height=360), use_container_width=True)

    # Latency vs success scatter.
    with right:
        takeaway_title("Why: slow connectors breach even when syncs succeed")
        budget_rule = (
            alt.Chart(pd.DataFrame({"x": [SLA_LATENCY_BUDGET_SEC]}))
            .mark_rule(color=BREACH, strokeDash=[5, 4])
            .encode(x="x:Q")
        )
        pts = (
            alt.Chart(h)
            .mark_circle(size=140, opacity=0.85)
            .encode(
                x=alt.X("median_latency_sec:Q", title="Median sync latency (s)",
                        axis=alt.Axis(grid=False)),
                y=alt.Y("success_rate:Q", title="Sync success rate",
                        scale=alt.Scale(domain=[0.9, 1.0]),
                        axis=alt.Axis(format="%", grid=True, gridColor=GRAY_LIGHT)),
                color=alt.condition(alt.datum.is_breach, alt.value(BREACH), alt.value(GOOD)),
                tooltip=[
                    alt.Tooltip("provider:N"),
                    alt.Tooltip("median_latency_sec:Q", title="Median latency (s)", format=".0f"),
                    alt.Tooltip("success_rate:Q", title="Success", format=".1%"),
                    alt.Tooltip("sla_attainment:Q", title="SLA", format=".1%"),
                ],
            )
        )
        text = (
            alt.Chart(h[h["is_worst"]])
            .mark_text(align="left", dx=8, dy=-4, color=INK, fontWeight="bold", fontSize=11)
            .encode(x="median_latency_sec:Q", y="success_rate:Q", text="provider:N")
        )
        st.altair_chart(
            (pts + budget_rule + text).properties(height=360), use_container_width=True
        )

    takeaway_title("Worst breachers to prioritize")
    wcols = st.columns(len(worst) if len(worst) else 1)
    for col, (_, row) in zip(wcols, worst.iterrows()):
        kpi_tile(
            col,
            row["provider"],
            pct(row["sla_attainment"], 0),
            f"median {row['median_latency_sec']:.0f}s · p95 {row['p95_latency_sec']:.0f}s",
            tone="breach",
        )

    with st.expander("Full connector health table"):
        show = health.copy()
        for c in ["success_rate", "sla_attainment"]:
            show[c] = (show[c] * 100).round(1)
        show[["median_latency_sec", "p95_latency_sec"]] = show[
            ["median_latency_sec", "p95_latency_sec"]
        ].round(0)
        show = show.rename(
            columns={
                "events": "Syncs",
                "success_rate": "Success %",
                "median_latency_sec": "Median lat (s)",
                "p95_latency_sec": "p95 lat (s)",
                "sla_attainment": "SLA %",
                "is_breach": "In breach",
            }
        )
        st.dataframe(show, use_container_width=True, hide_index=True)

    worst_names = ", ".join(worst["provider"].tolist()) if len(worst) else "—"
    so_what(
        "Concentrate latency engineering on a short list",
        f"The worst breachers ({worst_names}) succeed almost as often as healthy connectors but "
        "routinely exceed the 5-minute budget, so they fail SLA on speed alone. These are "
        "typically the largest enterprise HRIS/PEO systems with heavier payloads — the fix is "
        "latency engineering (incremental/delta syncs, pagination tuning, off-peak scheduling), "
        "not reliability work. A focused push on this short list is the fastest route back to "
        "the SLA target.",
    )


# ===========================================================================
# VIEW 4 — SLA BREACH DRILL-DOWN
# ===========================================================================
elif view == "SLA Breach Drill-down":
    prov_list = ["All connectors"] + (
        an.provider_health(f_sync)["provider"].tolist()
    )
    sel_prov = st.selectbox("Drill into a connector", prov_list)

    if sel_prov == "All connectors":
        ts = an.sla_timeseries(f_sync)
        scope_label = "All connectors"
    else:
        ts = an.provider_sla_timeseries(f_sync, sel_prov)
        scope_label = sel_prov

    summ = an.breach_alert_summary(ts)

    status_tone = "breach" if summ["latest_in_breach"] else "good"
    takeaway_title(
        f"{scope_label}: breached the SLA target in "
        f"{summ['n_breach_periods']} of {summ['n_periods']} weeks"
    )

    c1, c2, c3 = st.columns(3)
    kpi_tile(
        c1, "Latest week SLA", pct(summ["latest_attainment"], 1),
        "in breach" if summ["latest_in_breach"] else "meeting SLA", tone=status_tone,
    )
    kpi_tile(
        c2, "Weeks in breach",
        f"{summ['n_breach_periods']}/{summ['n_periods']}",
        pct(summ["breach_period_share"], 0) + " of weeks", tone="watch",
    )
    kpi_tile(
        c3, "Worst week SLA", pct(summ["worst_period_attainment"], 1),
        f"target {pct(SLA_ATTAINMENT_TARGET, 0)}", tone="breach",
    )

    st.write("")
    takeaway_title("Weekly SLA attainment vs. target — breach weeks flagged in red")

    ts_plot = ts.copy()
    base = alt.Chart(ts_plot).encode(
        x=alt.X("period:T", title=None, axis=alt.Axis(format="%b %d", grid=False))
    )
    area = base.mark_area(opacity=0.08, color=ACCENT).encode(
        y=alt.Y("sla_attainment:Q", title="SLA attainment",
                scale=alt.Scale(domain=[0, 1]),
                axis=alt.Axis(format="%", grid=True, gridColor=GRAY_LIGHT))
    )
    line = base.mark_line(color=ACCENT, strokeWidth=2.5).encode(y="sla_attainment:Q")
    points = base.mark_point(size=70, filled=True).encode(
        y="sla_attainment:Q",
        color=alt.condition(
            alt.datum.sla_attainment < SLA_ATTAINMENT_TARGET,
            alt.value(BREACH), alt.value(GOOD)
        ),
        tooltip=[
            alt.Tooltip("period:T", title="Week of", format="%b %d"),
            alt.Tooltip("sla_attainment:Q", title="SLA", format=".1%"),
            alt.Tooltip("median_latency_sec:Q", title="Median latency (s)", format=".0f"),
            alt.Tooltip("events:Q", title="Syncs", format=","),
        ],
    )
    target = (
        alt.Chart(pd.DataFrame({"y": [SLA_ATTAINMENT_TARGET]}))
        .mark_rule(color=BREACH, strokeDash=[5, 4])
        .encode(y="y:Q")
    )
    target_txt = (
        alt.Chart(pd.DataFrame({"y": [SLA_ATTAINMENT_TARGET], "t": [f"Target {pct(SLA_ATTAINMENT_TARGET,0)}"]}))
        .mark_text(align="left", dx=4, dy=-6, color=BREACH, fontSize=11)
        .encode(y="y:Q", x=alt.value(5), text="t:N")
    )
    st.altair_chart(
        (area + line + points + target + target_txt).properties(height=320),
        use_container_width=True,
    )

    # Failure-reason context.
    if sel_prov == "All connectors":
        reasons = an.failure_reason_breakdown(f_sync)
    else:
        reasons = an.failure_reason_breakdown(f_sync[f_sync["provider"] == sel_prov])

    if not reasons.empty:
        takeaway_title("When syncs do fail, no single cause dominates")
        rbar = (
            alt.Chart(reasons)
            .mark_bar(color=GRAY)
            .encode(
                y=alt.Y("failure_reason:N", sort="-x", title=None),
                x=alt.X("count:Q", title="Failed syncs", axis=alt.Axis(grid=False)),
                tooltip=[
                    alt.Tooltip("failure_reason:N", title="Reason"),
                    alt.Tooltip("count:Q", title="Count", format=","),
                    alt.Tooltip("pct:Q", title="Share", format=".1%"),
                ],
            )
        )
        st.altair_chart(rbar.properties(height=220), use_container_width=True)

    scope_note = (
        "Across all connectors"
        if sel_prov == "All connectors"
        else f"For {sel_prov}"
    )
    so_what(
        "Treat SLA breaches as a latency alert, routed by connector",
        f"{scope_note}, SLA attainment stays under the {pct(SLA_ATTAINMENT_TARGET,0)} target in "
        f"{summ['n_breach_periods']} of {summ['n_periods']} weeks, and the dips track latency "
        "rather than a spike in any one failure reason. An operational alert that fires when a "
        "connector's weekly attainment crosses the threshold — and routes to the owning "
        "integration team with its latency profile attached — would turn this from a lagging "
        "report into a same-week response.",
    )

# Footer disclaimer (always on).
st.divider()
st.caption(
    "⚠️ Synthetic demo data generated with a fixed seed (data_gen.py). "
    "No real employers, employees, providers, or payroll records are represented. "
    "Built by Leo Chan — github.com/GoldenCrate."
)
