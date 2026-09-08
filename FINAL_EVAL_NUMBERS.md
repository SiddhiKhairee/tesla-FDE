# Final Eval Numbers — Day 6, Task 1

Consolidated, traceable precision/recall/accuracy numbers for the pitch. Every number below
is read directly from a committed eval-output file (not recomputed, rounded, or estimated
for this document) and cross-checked against the code that produced it. No re-run was
needed — see staleness check below for why.

---

## Staleness check (does the Groq-primary switch affect any of these?)

Commit `7a9d960` ("Switch ERP diagnosis path to Groq-primary...") changed exactly one thing:
`get_diagnosis_llm()` / `GroqGeminiStubFallbackLLM` in `backend/llm_client.py`, used only by
`diagnose_event`/`diagnose_all` in `backend/diagnosis.py` — the ERP (`/pipeline/run`) and
Version B (human report) ticket-diagnosis path. Checked each eval against that scope:

| Eval | Calls the changed code path? | Verdict |
|---|---|---|
| ERP detection eval (`backend/eval_results.json`) | No — `eval.py` calls `_detect_all_events()` (`backend/main.py:91`), which is purely `detect_stuck_orders`/`detect_delayed_deliveries`/`detect_duplicate_orders`/`detect_quantity_mismatches`. Zero LLM calls, confirmed by reading `main.py`. | **Unaffected**, current as-is. |
| Sensor detection eval (`before_derived_features`/`after_derived_features`/`v2_ml_classifier` in `sensor_detection_eval.json`) | No — pure statistical/ML comparison against labels, zero API calls, per the file's own scope (Version A spec Section 4). | **Unaffected**, current as-is. |
| Sensor diagnosis-agent eval (`v_diagnosis_agent_eval` in the same file) | No — it uses its own independent provider probe, `probe_and_select_llm()` in `backend/eval_diagnosis_sensor.py`, never touched by commit `7a9d960` (diff only lists `diagnosis.py`, `llm_client.py`, and two test files). This probe already treated *any* exception as fallback-worthy before the switch existed — same philosophy, separate code. | **Unaffected**, current as-is. |

Also verified `backend/detection.py` (ERP rule-based detection) has had **zero commits since**
`3de9555` (the ground-truth-gap fix that `eval_results.json` was generated against), so that
eval reflects the exact code and ground truth currently in the repo — not just "not stale
re: Groq" but not stale at all.

**Conclusion: nothing needed to be re-run.** All three eval outputs below are already current.

---

## 1. ERP-path anomaly detection (rule-based, Version B / core reconciliation)

**Source:** [`backend/eval_results.json`](backend/eval_results.json), produced by
[`backend/eval.py`](backend/eval.py) against ground truth in
[`data-gen/output/ground_truth.json`](data-gen/output/ground_truth.json)
(`generated_through` / reference date: `2026-09-07`). Deterministic, no seed needed — this
is exact rule matching against a fixed ground-truth set, reproducible by rerunning
`python eval.py` any time without Odoo state drifting the answer (reference date is passed
in, not wall-clock).

| Anomaly type | TP | FP | FN | Precision | Recall |
|---|---|---|---|---|---|
| stuck_order | 28 | 0 | 0 | 100.0% | 100.0% |
| delayed_delivery | 13 | 0 | 0 | 100.0% | 100.0% |
| duplicate_entry | 10 | 1 | 0 | 90.9% | 100.0% |
| quantity_mismatch | 5 | 0 | 0 | 100.0% | 100.0% |
| **Overall** | **56** | **1** | **0** | **98.2%** | **100.0%** |

The single false positive is a real, inspectable case (`P00272`, flagged as a duplicate of
`P00046`) — logged in full in `eval_results.json`'s `false_positives` array, not hidden.

---

## 2. Sensor-path anomaly detection (Version A, AI4I dataset)

**Source:** [`data-gen/sensor/sensor_detection_eval.json`](data-gen/sensor/sensor_detection_eval.json),
evaluated over the full 10,000-row AI4I dataset
([`data-gen/sensor/data_summary.json`](data-gen/sensor/data_summary.json): 339 real failures,
9,661 normal rows — a ~3.4% positive rate).

Three versions exist in the file; **v2 (ML classifier) is the one to cite** — it's the only
one that cleared the project's own trust condition (`meets_trust_condition: true` in the
file: a genuine improvement in *both* precision and recall over v1.5, not a trade-off of
one for the other). v1 and v1.5 are kept below for the honest before/after story, not as
competing "final" numbers.

| Version | Precision | Recall | Accuracy | Scope | Notes |
|---|---|---|---|---|---|
| v1 (5 raw columns, per-column z-score) | 66.7% | 19.5% | 96.9% | Full dataset (10,000 rows) | Cold-start baseline |
| v1.5 (+ 3 derived features: temp_differential/mechanical_power/strain_proxy) | 75.0% | 29.2% | 97.3% | Full dataset (10,000 rows) | Structurally can't catch combination-driven failures (independent per-column thresholds) |
| **v2 (Random Forest, `class_weight='balanced'`, tuned threshold=0.6)** | **79.2%** | **83.8%** | **98.7%** | **Held-out test split only** (68 positives / 1932 negatives, stratified 3.4% rate) | **Cite this one** — random_state=42, threshold chosen on validation split only (precision ≥ 75.0% benchmark, then max recall) |

v2's per-failure-type recall on the test split (**do not average these away** — this is the
real trade-off the project made): TWF 14.3% (1/7), **HDF 100% (26/26)**, PWF 86.7% (13/15),
OSF 90% (18/20), RNF 0% (0/5). HDF and RNF sit at opposite extremes by design/dataset
limitation, not by an error — see `sensor_detection_version_a.md` Sections 1.4 and the RNF
caveat for why.

Note the scope difference: v1/v1.5 numbers are full-dataset; v2's are held-out-test-only (the
methodologically correct way to report an ML classifier, and the only portion never touched
during threshold tuning) — don't present them side-by-side as if measured on the same rows.

---

## 3. Diagnosis-agent accuracy (Version A, sampled)

**Source:** `v_diagnosis_agent_eval` block in
[`data-gen/sensor/sensor_detection_eval.json`](data-gen/sensor/sensor_detection_eval.json),
produced by [`backend/eval_diagnosis_sensor.py`](backend/eval_diagnosis_sensor.py).

- **True positive pool:** 57 rows (v2 ML classifier's flags on the held-out test split that
  are real failures — matches v2's test-set TP count in Section 2 above, confirmed by reading
  `build_true_positive_set()` in `eval_diagnosis_sensor.py`, which draws from `df_test`).
- **Sample:** fixed-seed random sample of 50 of those 57 (`seed = 42`).
- **Result: 25 of 50 correct — 50.0% accuracy.** Provider: `groq` (Gemini probed first and
  returned a 503, logged in `provider_probe_log`). 0 errored, 0 fell back to the stub — the
  50% figure is not diluted or inflated by fallback noise.

**Per-failure-type breakdown — report this alongside the aggregate, never the bare 50% alone:**

| Failure type | In sample | Correct | Accuracy |
|---|---|---|---|
| HDF | 25 | 3 | 12% |
| PWF | 11 | 11 | 100% |
| OSF | 13 | 10 | 76.9% |
| TWF | 1 | 1 | — (n=1, not meaningful) |
| RNF | 0 | 0 | — (n=0, not meaningful) |

HDF makes up half the sample precisely *because* v2 now catches ~100% of real HDF cases
(Section 2) — the aggregate 50% is a direct, mechanical consequence of the detector's win on
HDF, not an unrelated coincidence. PWF and OSF are strong because `mechanical_power` /
`strain_proxy` were purpose-built for them. This is the documented, parked "HDF Diagnosis
Accuracy" limitation (`sensor_detection_version_a.md` Section 5.5) — the honest headline
here is **"strong detection, weak HDF diagnosis explanation"**, not "50% accuracy."

---

## Things worth double-checking yourself before this goes in the README

1. **Scope mismatch between v1/v1.5 (full 10,000-row dataset) and v2 (2,000-row held-out
   test split only)** — both are legitimate and correctly labeled in the source file, but if
   these get pulled into a single slide/table without the scope column, a reader could wrongly
   compare them as apples-to-apples. Worth a footnote wherever they appear together.
2. **`FINAL_SPOT_CHECK.md` line 38** flags "no `duplicate_entry` in ground_truth.json" as an
   open item (marked `[~]`) — I re-opened `data-gen/output/ground_truth.json` directly (not
   just `eval_results.json`) and it currently has **10 `duplicate_entry` events**, matching
   the 10 true positives in the eval. The 1 `duplicate_entry` false positive (`P00272`) is a
   detector over-flag with *no* ground-truth counterpart at all — it doesn't add to that count.
   So the file as it stands today does not reproduce the gap your spot-check note describes.
   This is presumably already resolved by the Day-2 fix commit (`3de9555`, same commit
   `eval_results.json` was generated from) — but since your note was written from directly
   looking at the file yourself, worth a 30-second re-open to confirm you're now seeing 10, not
   0, before treating that spot-check line as still open.
3. **No wall-clock timestamp field exists in `sensor_detection_eval.json` itself** — I
   established currency via `git log` (last touched by commit `a2071af`, 2026-09-06, and the
   code path it exercises is untouched since) rather than an in-file timestamp. If you want a
   belt-and-suspenders check, `git log -1 --format=%cd data-gen/sensor/sensor_detection_eval.json`
   gives the same date.
