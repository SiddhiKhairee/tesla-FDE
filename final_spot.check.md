# Final Spot Check — Everything, Before Calling This Portfolio-Ready

This is the "look at it with your own eyes, one last time, across the whole project"
pass — not a re-do of everything Claude Code already tested, but the specific things that
have so far only been verified by *reading a report*, not by you personally looking at the
real thing. Budget genuine time for this — an hour or more, not 10 minutes. Go in order;
each section says exactly what to do, not just what to check.

Check off each box as you go. If anything looks wrong at any point, stop and write down
exactly what you saw (which record/screen/message, what you expected, what you actually
got) — same reporting style that's caught every real bug in this project so far. Don't
explain it away, don't skip ahead.

---

## 1. Odoo entities & seeded data (previously spot-checked — quick re-confirm only)

You already did a thorough pass on this per `SPOT_CHECK_GUIDE.md` back in Day 2. This is
just a fast sanity re-check, not a full redo, since containers have been rebuilt and
volumes moved around several times since then.

- [x] Log into Odoo (`localhost:8069`) and confirm all 5 products still show up under
      Inventory → Products, with correct Internal References (`CELL-2170`, `BMS-100`,
      `ENC-PW3`, `BRK-PW3`, `PW3-ASSY`).
- [x] Confirm the BOM for `PW3-ASSY` still lists all 4 components with the right
      quantities (Manufacturing → Bills of Materials).
- [x] Confirm the three locations (Raw Materials, WIP, Finished Goods) are still nested
      under BT Energy Plant (Inventory → Configuration → Locations).
- [x] Spot-check on-hand quantity for one raw material (e.g. `CELL-2170`) — should be a
      plausible non-negative number, not zero (unless nothing's been generated/consumed) and
      not something absurd.

## 2. Day 2 synthetic data + anomalies (previously spot-checked — quick re-confirm only)

- [~] Open `ground_truth.json` (or wherever Day 2's anomaly log lives) and confirm it still
      has all 4 types logged (stuck_order, quantity_mismatch, duplicate_entry,
      delayed_delivery) — a non-zero count for each. 
    _________________X No duplicate_entry in ground truth.json X_________________________
- [x] Pick one anomaly from the log and verify it in Odoo directly (same process as your
      original Day 2 spot check) — confirm it's still there and still looks like a genuine
      anomaly, not something that got overwritten by a later container rebuild.

## 3. Day 3 — core ERP diagnosis engine (you likely haven't looked at this directly yet)

- [x] Find the eval script's output/log file for the ERP path (precision/recall numbers).
      Open it and read the actual numbers — do they match what's been quoted to you in any
      summary you've seen? If you've never actually opened this file yourself, do it now.
- [x] Trigger `/pipeline/run` for real (via the dashboard, or directly against the API) and
      read one full diagnosis end to end — likely_cause, reasoning, recommended_action.
      Does it read as genuinely reasoned from the data, or generic/templated? This is the
      same "read it, don't just check it returned 200" instinct as everywhere else.
- [x] Confirm: does this call currently work, or does it hit the known Gemini 503 gap
      (no fallback for that specific error)? If it fails, that's expected and already
      tracked — just confirm it fails the way you expect, not some new, different error.

## 4. Day 4 — Version B (human failure-report path)

- [x] Submit one real failure report through the actual form UI (not curl, not a script —
      the real form, in a real browser) with a machine name and issue description you make
      up yourself right now.
- [x] Read the returned diagnosis in full — likely_cause, reasoning (does it reference
      historical incident matches with plausible similarity scores?), recommended_action,
      confidence.
- [x] Check your actual Slack channel and confirm the notification for this exact report
      landed, reads correctly, and isn't missing any of the expected fields.
- [x] Reload the dashboard and confirm this new ticket appears at the top of the list.

## 5. Version A — sensor pipeline (ML detector + diagnosis + demo)

Most of this has been reviewed with you already, but do these specific checks yourself,
directly, rather than trusting summaries:

- [x] Open `data-gen/sensor/sensor_detection_eval.json` yourself and read through it top to
      bottom — confirm the v1/v1.5/v2 (ML) numbers and the diagnosis-agent eval numbers are
      actually in there, actually match what's been reported to you, and the file isn't
      missing any of the sections it should have.
- [x] Pick 2 rows from that file's per-failure-type breakdown and manually cross-check the
      math (does TP/(TP+FN) actually equal the reported recall for that type?).
- [x] Re-read `sensor_detection_version_a.md` end to end, once, start to finish — confirm
      it accurately reflects the current state (v1 → v1.5 → v2 ML → diagnosis eval → demo),
      including the "Known Limitation — HDF Diagnosis Accuracy" section you asked to be
      added. Does anything in it feel out of date given what's been built since?
- [x] Confirm `model_v2.pkl` and `model_v2_meta.json` are actually present in the repo
      (`backend/sensor/` or wherever they landed) and are tracked by git — not accidentally
      gitignored alongside the runtime-state files.
- [x] Check your Slack channel for the 3 real messages from the earlier diagnosis-agent
      review and the 3 from the live demo dry-run — confirm they're actually there and
      readable, not just reported as sent.

## 6. Day 5 — React dashboard (frontend)

- [x] Open the dashboard in a real browser (not headless, not a screenshot someone else
      took) and look at the ticket list yourself. Does it look right — readable, not
      overlapping, source badges (ERP/Human report/Sensor) showing correctly for a few
      different tickets?
- [x] Click into 2-3 different tickets (ideally one from each source if you have them) and
      read the expanded reasoning. Confirm nothing looks broken, truncated, or like raw
      unformatted JSON leaking through.
- [x] Manually trigger the empty state (temporarily point at a fresh/empty ticket store, or
      just confirm you remember what it looked like from earlier testing) and the error
      state (stop the backend, reload) — confirm both still look intentional, not like a
      crashed page.

## 7. Failure-report form UI

- [x] Submit a deliberately invalid report (missing required field) and confirm the
      client-side validation actually stops you, rather than sending a bad request to the
      backend.
- [x] Confirm the loading state ("Submitting…") is visible during a real submission — not
      instant, not stuck forever.

## 8. Docker / docker-compose (full stack)

This overlaps with what Claude Code is running for you as its own final run-through — this
is your independent check on top of that, not a repeat of the same steps.

- [x] After Claude Code's run-through finishes, bring the stack up yourself
      (`docker compose up`) and open every URL yourself: Odoo (`8069`), the frontend
      (whatever port it's published on), and hit `/health` on the backend directly.
- [x] Confirm `odoo/docker-compose.yml` is actually gone from the repo (not just deleted
      locally — check it's gone in `git log`/on GitHub if pushed).
- [x] Run `docker compose down` yourself and confirm it exits cleanly, no hung containers,
      no errors.

## 9. Repo hygiene

- [x] `git log --oneline` — read through the commit history once. Does it read coherently
      as a story of how this was built? Any commit message that's confusing out of context?
- [x] Confirm nothing sensitive is committed: no `.env` file, no real API keys anywhere in
      tracked files (`git grep` for anything that looks like a key pattern if you want to be
      thorough), no Slack webhook URL hardcoded anywhere.
- [x] Confirm `.gitignore` actually covers everything it should: `tickets.json`, `.env`,
      `node_modules`, `venv`, `__pycache__`, the AI4I CSV if it was never meant to be
      committed, etc. — open `.gitignore` and read it, don't just assume it's complete.
- [x] Confirm no leftover debug/scratch files made it into the repo (a stray
      `dry_run_pipeline.py` output dump, a `test.py` someone forgot, etc.) — a quick
      `git ls-files` skim catches this.

## 10. The honest-limitations list (for your own memory, not a file check)

Before moving to Day 6, make sure you personally can state, out loud, without looking
anything up: why TWF and RNF are weak detection-wise, why HDF is weak diagnosis-wise, and
why Gemini 503s aren't currently handled. If you can't explain any of these fluently
yourself right now, re-read the relevant section of `sensor_detection_version_a.md` before
moving on — these are exactly the questions most likely to come up if Ashwin or the
technical head looks closely.