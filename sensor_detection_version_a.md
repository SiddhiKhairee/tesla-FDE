# Version A — Sensor-Based Detection Pipeline (Spec for Claude Code)

Forward-looking stretch feature (Day 4, P2). This reuses the exact same shared engine as
Version B (ERP reconciliation + human failure-report path) — same event schema, same
diagnosis agent — with a new adapter that feeds it sensor data instead of ERP/human input.
Nothing here should require changes to the diagnosis agent's core reasoning logic, only a
new adapter and a new context source.

**Framing for the pitch (keep this explicit in code comments and the README):** Tesla has
no sensors on plant equipment today — this is the honest, stated "ready to retrain the
moment sensors exist" stretch piece, not a claim that this solves a problem Tesla has right
now. The AI4I 2020 Predictive Maintenance Dataset stands in for real sensor telemetry.

---

## 0. Dataset procurement

- Source: [AI4I 2020 Predictive Maintenance Dataset](https://archive.ics.uci.edu/dataset/601/ai4i+2020+predictive+maintenance+dataset), UCI ML Repository.
- Download the CSV, store it under `data-gen/sensor/ai4i2020.csv` (or equivalent — match
  existing repo structure), not committed if it's large; document the download step in
  README instead.
- **First step, before writing any adapter or detection code:** load the CSV and print a
  real breakdown — total row count, count of `Machine failure == 1`, and count per failure
  type (`TWF`, `HDF`, `PWF`, `OSF`, `RNF`). Do not trust prior conversation estimates as
  ground truth for code — those were sourced from the UCI page description, not the actual
  file, and are only reliable to roughly the right order of magnitude. Log this breakdown
  somewhere durable (a comment, a `data_summary.json`, or console output captured in the
  PR) since your threshold and sampling choices downstream are justified by these real
  numbers.
- Expected columns: `UDI`, `Product ID`, `Type`, `Air temperature [K]`, `Process
  temperature [K]`, `Rotational speed [rpm]`, `Torque [Nm]`, `Tool wear [min]`, `Machine
  failure`, `TWF`, `HDF`, `PWF`, `OSF`, `RNF`.
- There is no real "machine identity" in this dataset the way there's a real SKU/location
  in the Odoo side — use `Product ID` (or `UDI` if `Product ID` isn't unique enough) as the
  stand-in `entity_id` for the shared event schema, and say so explicitly in a code comment
  — this is a known simplification, same spirit as the BOM quantity simplification in the
  Odoo setup.

---

## 1. Sensor adapter (`sensor_adapter.py`) — v1, cold-start baseline

**v1 — cold-start baseline, no training data required.** This is the detector that exists
today (implemented, evaluated, logged in `data-gen/sensor/sensor_detection_eval.json`):
five raw sensor columns plus three derived composite features
(`temp_differential`/`mechanical_power`/`strain_proxy`, added after the initial v1 numbers
showed the raw-column-only detector was structurally blind to combination-driven failure
modes — see the per-failure-type breakdown in that eval file), each thresholded
independently by a per-column z-score against a `k` swept and validated per Section 4. It
needs zero labeled history to run and is the shipped default. Current numbers (5 raw + 3
derived columns): **75.0% precision / 29.2% recall / 97.3% accuracy.** See Section 1.5
below for why recall is still considered too low and what's planned next.

**Job:** read AI4I rows, decide per row whether it counts as "off," and translate a
flagged row into the shared event schema:

```
{source: "sensor", entity_id, field, expected_value, actual_value, timestamp}
```

Since a single flagged row can deviate on more than one sensor column at once, the adapter
should emit one event per deviating column (or a single event carrying all deviating
columns as a list — pick whichever shape is easier for `gather_context` and the diagnosis
agent to consume downstream, but be consistent with how the ERP/human-report adapters
already shape multi-field events).

**Threshold logic — statistical, per-column, validated, not guessed:**

1. Compute baseline mean and standard deviation for each sensor column (`Air temperature`,
   `Process temperature`, `Rotational speed`, `Torque`, `Tool wear`) — independently per
   column, not one global threshold. Use only rows where `Machine failure == 0` to compute
   the baseline, so failures don't pollute what "normal" means.
2. Flag a row as anomalous if any sensor column falls more than `k` standard deviations
   from that column's baseline mean. Start with `k = 3` per column.
3. Validate `k` against real labels (see Section 4 — detection eval) rather than assuming
   `k = 3` is right. If detection precision/recall is bad, adjust `k` per column
   independently — tool wear likely tolerates more natural variance than air temperature,
   so don't assume one `k` fits all five columns equally.
4. Known, stated limitation — put this in the README, not just here: this detector flags
   *individual* sensor columns crossing a threshold. AI4I's own failure modes are partly
   defined by *combinations* of sensors (e.g. HDF ties temperature differential to
   rotational speed together). A single-sensor threshold detector may structurally miss
   some combination-driven failures no matter how `k` is tuned. Say this openly rather than
   let the eval numbers surface it unexplained.

**Output of the adapter, per row:** the shared event(s) if flagged, plus (for downstream
use by `gather_context` and the diagnosis agent) the deviation itself — which column(s),
by how much, and in which direction relative to baseline. Don't discard that on the way to
the event schema; the diagnosis agent needs it to reason about *which* failure type is
plausible.

---

## 1.5 / v2 — ML classifier, once labeled history exists

**Status: planned, not yet implemented — spec only, pending review before any code is
written.**

Recall is still too low for a genuinely imbalanced dataset like this (v1.5's 29.2%
recall on a ~3% positive-rate dataset means the detector misses roughly 7 of every 10
real failures). v1's per-column/per-derived-feature z-score thresholds are independent —
each column casts an up-or-down vote on its own — so they can't learn joint, nonlinear
interactions across all eight signals the way a classifier trained on labeled examples
can. That's the motivation for escalating to v2, on top of v1 rather than replacing it
outright until v2 earns its place (see the trust condition in point 5).

Baseline v2 has to beat (v1.5, Sections 1 + 4, logged in
`data-gen/sensor/sensor_detection_eval.json`): **75.0% precision / 29.2% recall / 97.3%
accuracy.**

### 1. Model

Random Forest classifier, to start — matches prior sklearn experience (the WolfJobs
project), so it's a defensible, explainable starting choice rather than an unfamiliar
one reached for because it sounds more sophisticated. Do not reach for Gradient
Boosting, XGBoost, or anything fancier unless Random Forest is proven insufficient
first — same "simplest thing that could work" discipline that started v1 at a uniform
`k = 3` before any per-column tuning.

### 2. Class imbalance handling — mandatory from the first run, not an afterthought

- Use `class_weight='balanced'` (or equivalent resampling) in the classifier from the
  very first run.
- Evaluate and optimize on precision/recall/F1 — **never accuracy alone.** A model that
  predicts "never fails" on this ~3% positive-rate data would still show ~97% accuracy
  and be useless — the same trap v1's uniform `k = 3` threshold fell into (18.3% recall)
  before per-column tuning exposed it.
- Tune the classification threshold on `predict_proba` output (not the default 0.5)
  toward whichever cutoff maximizes recall without collapsing precision. This is a lever
  the v1 z-score approach never had — each column only had its own `k`, not one shared,
  continuously tunable decision boundary over a learned probability.

### 3. Train/val/test methodology

- Stratified split preserving the real ~3% failure rate in every split (train/val/test)
  — don't let any split's class balance drift from the true distribution.
- Fit nothing (scaling, imputation, the model itself) on test data. The held-out test set
  is touched exactly once, at the very end, for the final reported numbers — never used
  to pick hyperparameters or the classification threshold.
- Use a validation split (or stratified k-fold CV on the training portion only) for all
  hyperparameter/threshold tuning, so the final test-set numbers are genuinely unseen
  data, not numbers already iterated against directly.

### 4. Explanation split — this changes how detection and notification connect

- The ML model's job is **only** to decide anomalous vs. not — it replaces the z-score
  threshold's gating role from v1.
- The existing z-score/deviation computations (all five raw columns plus the three
  derived features) keep running on every row regardless of which detector does the
  gating, purely to produce the descriptive "which sensors were off, by how much" text
  that feeds `gather_context_sensor.py` and the Slack message. v2 doesn't remove or
  replace this — it only changes what decides whether that description gets surfaced at
  all.
- Do not build SHAP or per-instance feature attribution for this. Only reconsider that
  if the plain z-score description reads badly in practice once real ML-flagged rows are
  looked at.
- Global `feature_importances_` from the Random Forest is a nice-to-have for the README
  (e.g. "the model leaned most heavily on X, Y, Z") — not required per-message.

### 5. Trust condition — "we built an ML model" is not automatically "done"

Only lock in and commit the ML detector if it shows a genuine, real improvement in
**both** precision and recall over the current v1.5 numbers (75.0% precision / 29.2%
recall) on the held-out test set — not just accuracy, and not an improvement in one
metric traded off against a collapse in the other (the same standard already applied to
`temp_differential`'s k choice in Section 1 — see that section's rejected k=2.0/k=1.5
alternatives for what a metric trade-off that doesn't clear the bar looks like).

If Random Forest with `class_weight='balanced'` doesn't clear that bar on the first
attempt, don't ship it as-is. Iterate in this order, logging each attempt's numbers
honestly — same discipline as the `k`-sweep and the derived-features before/after
already logged in `sensor_detection_eval.json`:

1. Threshold tuning on `predict_proba` first (cheapest lever, no retraining needed).
2. Resampling techniques (e.g. SMOTE) next.
3. A different model only as a last resort, after 1 and 2 are exhausted.

If none of the above clears the bar, explicitly decide to stop and keep v1.5 (threshold
+ derived features) as the shipped detector. That is an acceptable, honest outcome to
land on — not a failure to hide or a reason to keep iterating indefinitely.

---

## 2. `gather_context` — sensor failure taxonomy (extend existing `gather_context` file/module)

Add a sensor-specific context block, structured similarly to however the ERP/report paths
already supply context to the diagnosis agent. Contents:

- The five failure categories as a closed taxonomy the diagnosis agent classifies into:
  `Tool Wear Failure`, `Heat Dissipation Failure`, `Power Failure`, `Overstrain Failure`,
  `Random Failure`, plus an `Unclear` fallback for readings that don't cleanly fit any of
  the five.
- A **generic, real-world-plausible description** of each category — written from general
  predictive-maintenance domain knowledge (what each failure type typically looks like:
  which sensors tend to be involved, roughly which direction), **not** AI4I's exact
  numeric trigger thresholds. Do not encode "HDF triggers when temp differential < 8.6K
  and rpm < 1380" verbatim — that's the dataset's literal label-generation formula, and
  handing it to the agent turns diagnosis into a lookup table instead of reasoning. Keep
  descriptions at the level a real reliability engineer would write them, not at the level
  of the dataset's internal answer key.
- This taxonomy is domain knowledge given up front — same pattern as the ERP path already
  predefining `stuck_order` / `quantity_mismatch` / `duplicate_entry` / `delayed_delivery`
  as known categories rather than having the agent invent categories per event.

---

## 3. Diagnosis agent — sensor path output schema

Reuses the existing LangGraph diagnosis agent from Day 3. For the sensor path, its
structured output needs these fields (extend whatever output schema already exists for the
ERP/report paths, don't fork a separate schema if avoidable):

```
{
  predicted_failure_type: one of [TWF, HDF, PWF, OSF, RNF, Unclear],
  explanation: free text — why the agent thinks this,
  suggested_solution: free text,
  confidence: agent's own self-reported certainty (pick one: categorical
              "high"/"medium"/"low", or a 0–1 / 0–100 self-assessed number —
              decide based on which reads as more honest vs. more rigorous
              for the pitch; document which was chosen and why)
}
```

**Important — keep two concepts named separately and don't conflate them anywhere in code,
eval output, or the Slack message:**

- **Diagnosis accuracy** — an aggregate, offline, ground-truth-validated number computed
  once by the eval script (Section 5). Never shown per-message.
- **Confidence** — a per-instance, live, self-reported hedge from the agent itself, with no
  ground truth backing it at generation time. Shown in every notification.

The agent should receive: the flagged row's deviation data from the sensor adapter (which
column(s), by how much, which direction) and the `gather_context` taxonomy block. It should
**never** receive AI4I's `Machine failure` / `TWF`/`HDF`/`PWF`/`OSF`/`RNF` ground-truth
columns for the row it's diagnosing — that would leak the answer.

---

## 4. Evaluation, part 1 — sensor adapter detection quality

Runs over the **full AI4I dataset** (all rows, real class balance from Section 0). Zero API
calls — this is pure statistical comparison, same spirit as the existing `eval.py` for the
ERP path.

- For each row, compare the adapter's flag (anomalous / not) against the real label
  (`Machine failure` == 1 / 0).
- Compute TP / FP / TN / FN, then precision, recall, and accuracy from those.
- This is the number that validates (or invalidates) the choice of `k` from Section 1 —
  iterate on `k` per column using this script's output, don't finalize `k` before running
  it at least once.
- Log the confusion matrix somewhere durable (console output captured in the PR, or a
  `sensor_detection_eval.json`) — this is a real, sourced number for the pitch, not an
  estimate.

---

## 5. Evaluation, part 2 — diagnosis agent accuracy

**Scope carefully — this is the one place API cost matters, and it's easy to accidentally
build this as "run diagnosis on everything the adapter flagged," which would mean hundreds
of LLM calls for a metric that doesn't need them.**

1. From Section 4's results, take the **true positive set only** — rows the adapter flagged
   *and* that are real failures (`Machine failure == 1`). False positives have no real
   failure type to score against and don't belong in this sample.
2. From that TP set, take a **fixed-seed random sample of 50 rows** (or the full TP set if
   it's small enough to be cheap — check the real TP count from Section 0 first; if it's
   well under 50, just use all of them and say so).
3. Run each of those 50 through the diagnosis agent (Section 3), with the row's real
   `Machine failure` label withheld from the prompt as always.
4. Compare `predicted_failure_type` to the real triggered failure type(s) for that row
   (exact match). Compute an accuracy percentage across the 50.
5. Report this explicitly as a **sampled** metric — "diagnosis agent correctly identified
   the failure type in N of 50 sampled true positives (fixed seed = X)" — never phrase it
   as if it covers the whole dataset.
6. `confidence` is not scored against anything here — it's not part of this accuracy
   number. If useful later, a stretch addition is checking whether self-reported confidence
   *correlates* with correctness (a calibration check) — optional, not required for a
   working demo.

This and Section 4 are two independent scripts/functions (or two independent modes of one
`eval.py`) — neither should trigger Slack.

---

## 6. Live demo — Slack notification path

Separate from both eval scripts above. Purpose: show the pipeline actually notifying,
without spamming a channel with hundreds of messages from the full dataset.

1. Build a **fixed-seed, stratified sample of 20 rows**: 40% (8 rows) actually
   malfunctioning (`Machine failure == 1`, spanning whichever real failure types are
   available — include all types you have room for, RNF included if you want it, knowing
   it's the one type least likely to be caught by a threshold detector and having a
   sentence ready to explain that if it happens live), 60% (12 rows) genuinely normal
   (`Machine failure == 0`) — including a couple of "close to the edge but still normal"
   rows on purpose, so the demo also shows the detector *not* crying wolf on borderline
   data, not just detecting the obvious cases.
2. Hardcode or fix the seed for this sample so the same 20 rows are used every demo run —
   don't re-randomize per run.
3. **Run this sample through the pipeline once, ahead of time, before presenting it live.**
   Know in advance exactly which of the 8 real failures the sensor adapter actually catches
   (it may not be all 8 — that's fine and realistic, but you want to know going in, not
   discover it live) and whether it ever flags one of the 12 normal rows (also fine and
   worth a sentence, not a surprise).
4. Each of the 20 rows goes through: sensor adapter (flag or not) → for flagged rows only,
   `gather_context` + diagnosis agent → for flagged rows only, a Slack notification.
   Normal (unflagged) rows produce no message — that's the intended behavior, not a gap.
5. **Stub the diagnosis agent for demo rehearsal, not for the actual recorded run** — use a
   stub/mock in place of real LLM calls while you're iterating on the Slack message
   formatting and rehearsing timing, so you're not burning API calls on every take. Switch
   to real calls for the take you actually keep.

**Slack message template** (per flagged row, using the agent's own output only — never the
dataset's ground-truth answer):

```
:warning: Machine [Product ID] — anomaly detected

Sensor readings deviating from normal baseline:
  [sensor name]: [actual value] (normal range: ~[baseline mean] ± [baseline std])
  [repeat for each deviating sensor]

Likely failure type: [predicted_failure_type]
Diagnosis: [explanation]
Suggested action: [suggested_solution]
Confidence: [confidence]
```

This mirrors the same shared event schema and notification pattern already built for the
Version B human-report path — reuse that webhook integration code rather than building a
second one.

---

## 7. Suggested file layout

```
data-gen/sensor/
  ai4i2020.csv              # downloaded dataset (document download step if not committed)
  data_summary.json         # real row/failure-type counts from Section 0

backend/sensor/
  sensor_adapter.py         # Section 1
  gather_context_sensor.py  # Section 2 (or extend existing gather_context module)
  eval_detection.py         # Section 4 — full-dataset, no API calls
  eval_diagnosis.py         # Section 5 — 50-sample TP subset, real API calls, fixed seed
  demo_live_sim.py          # Section 6 — 20-row stratified sample, fixed seed, Slack
```

Diagnosis agent itself stays the shared module from Day 3 — no fork, just a new adapter and
context source feeding it.

---

## 8. Open decisions to lock in before/while building

- [ ] Confidence field format: categorical (high/medium/low) or numeric (0–1 / 0–100)?
- [ ] Final `k` per sensor column, after running Section 4 at least once against real data.
- [ ] Diagnosis eval sample size: 50, or the full TP set if the real TP count turns out
      small enough to be cheap (check Section 0's real numbers first).
- [ ] Exact wording of the RNF caveat for the README ("this failure type is
      near-unpredictable by design and our single-sensor threshold detector isn't expected
      to reliably catch it").