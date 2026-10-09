# API Integration SLA & Sync-Health Dashboard

An operational analytics dashboard — styled after a **Sigma** operational
report — for a **unified employment / HR / payroll API** (think
[Finch](https://www.tryfinch.com/)-style connectivity to systems like Gusto,
ADP, Workday, Rippling, and others).

It answers the question an integrations/ops team actually lives with:

> *Are our provider connectors keeping up with their sync SLAs — and if not,
> where exactly is the problem, and what should we do about it?*

> ⚠️ **All data in this project is SYNTHETIC.** It is generated locally with a
> fixed random seed (`data_gen.py`). No real employer, employee, provider
> account, or payroll record is represented. Provider names refer to real HR /
> payroll systems only to make the demo realistic; everything attached to them
> is invented.

---

## What it shows

The app is a multi-view Streamlit dashboard. Every view leads with a
**takeaway title**, uses a restrained palette (gray baseline, one accent,
red reserved for SLA breaches), labels values directly, and closes with a
**"So what / recommendation"** — following Cole Nussbaumer Knaflic's
*Storytelling with Data* approach.

**SLA definition used throughout:** a single sync *meets SLA* if it both
**succeeds** and **finishes within the latency budget (300s / 5 min)**. A
connector or week is *in breach* when its SLA attainment falls below the
**98%** target.

1. **Overview — headline KPI tiles**
   Connected employers, provider coverage %, sync success rate, median sync
   latency, and SLA attainment %. The lead insight: syncs succeed ~97% of the
   time, yet SLA attainment is far lower — the gap is **latency, not failures**.

2. **Sync Funnel** — `Connect → Authorize → First Sync → Ongoing Sync`
   Stage counts, overall and step-by-step conversion, and an automatic callout
   of the biggest drop-off step.

3. **Connector Health**
   SLA attainment and latency **by provider**, a latency-vs-success scatter that
   explains *why* slow connectors breach even when they rarely fail, and the
   **worst breachers** flagged for prioritization — plus a full data table.

4. **SLA Breach Drill-down**
   Weekly SLA attainment vs. the target line, with breach weeks flagged and an
   alert-style summary. Drill into any single connector, and see the
   failure-reason mix for context.

A sidebar provider-category filter (`Payroll / HRIS / PEO`) applies across all
views.

---

## Project structure

| File | Role |
|------|------|
| `app.py` | Streamlit presentation layer (multi-view dashboard). |
| `analytics.py` | **Framework-free** metric math (pandas/numpy only) — all KPIs, funnel, provider health, SLA timeseries. Unit-testable. |
| `data_gen.py` | Generates the synthetic providers / employers / sync-events data with a fixed seed. |
| `test_analytics.py` | `pytest` unit tests for `analytics.py` (tiny hand-checked fixtures + full-dataset invariants). |
| `requirements.txt` | Dependencies. |

The split is intentional: `analytics.py` has **no Streamlit import**, so the
analytics can be tested in CI and reused outside the UI.

---

## Run it locally

```bash
# 1. (optional) create a virtual environment
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

# 2. install dependencies
pip install -r requirements.txt

# 3. (optional) regenerate the synthetic CSVs
python data_gen.py               # writes to ./data/

# 4. run the tests
pytest -q

# 5. launch the dashboard
streamlit run app.py
```

The app generates its data in-memory on startup, so step 3 is optional — it is
only there if you want the CSVs on disk to inspect.

---

## Design notes (Storytelling with Data)

- **Titles are the takeaway**, not the chart type ("The gap is speed, not
  reliability", not "Bar chart of metrics").
- **Color is restrained**: a single accent blue for the main series, gray for
  secondary/context, red used *only* to signal an SLA breach, green used
  sparingly for "healthy".
- **Direct labeling** over legends where it keeps the eye on the data.
- **Decluttered**: muted gridlines, no chartjunk, thresholds drawn as reference
  lines so "good vs. breach" is readable at a glance.

---

## Author

**Leo Chan** — [github.com/GoldenCrate](https://github.com/GoldenCrate)

Portfolio demonstration project. Synthetic data only.
