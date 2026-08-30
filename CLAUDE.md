# Tesla FDE Portfolio Project — ERP Reconciliation & Failure-Reporting Agent

## Context (why this project exists)

This is a portfolio project built to support a referral pitch for a **Forward Deployed Engineer (FDE)** role on Tesla Energy's team at the Brookshire, TX plant (Megafactories / cell production / Powerwall sites). The JD lists 5+ years of experience, which the candidate (Sid) does not have. The strategy: a friend at Tesla (Astin, industrial engineer, ~8 days in) is willing to pitch Sid directly to the technical head — but wants a concrete, relevant project in hand first, ideally validated informally with Astin's coworker Ashwin (~2 months in, closer to the software/floor side) before that pitch happens.

**Do not treat this as a generic AI/ERP demo.** Every design choice below exists to map as directly as possible onto the actual FDE job description, and to be honest about what's simulated vs. real — that honesty is itself part of the pitch.

## The role this project is built to mirror

Tesla Energy FDE JD, key points:
- Owns the path from a live production issue to shipped software: diagnose → code → integrate with factory systems → make it stick.
- Stack: Python backend, TypeScript/React frontend, REST APIs, SQL, Git, Docker, CI/CD, plus Kubernetes/Terraform/a major cloud, and hands-on production LLM/agent systems (auth, latency, evals, uptime).
- Time split between "the line" (floor) and "the desk" (build/productize).
- Turns a working solution into a reusable playbook.
- Requires: full-stack fluency, a portfolio of deployed work, comfort going from an unclear production problem to working software.

Tesla's internal ERP is called **WARP** — a heavily customized system in the SAP/Oracle category, covering supply chain, CRM, and order management. No external access to WARP exists, so this project stands in an open-source equivalent.

## What we're building

**Core deliverable — ERP Reconciliation Agent.** An agent that monitors an ERP for operational discrepancies (stuck orders, inventory count drift, duplicate records) that currently require a human to manually notice and investigate, diagnoses the likely cause, and either resolves or flags them for human review.

**Sub-problem — shared diagnose-and-ticket engine, two input paths.** Astin confirmed Tesla currently has **no sensors** on plant equipment — all failure detection today is done by a human physically noticing a problem, then manually messaging the team on Slack/Teams. So:
- **Version B (primary, "works today"):** a human reports a failure through a simple intake form → the same diagnosis engine checks it against historical incidents → generates a structured report/ticket → auto-notifies the team via a Slack/Teams webhook. This directly replaces the manual "someone has to type it into Slack" step, which is the real, confirmed pain point.
- **Version A (bonus/roadmap, explicitly framed as forward-looking):** the identical engine, fed by sensor data instead of a human report, using a public dataset (AI4I 2020 Predictive Maintenance, or similar) as a stand-in. Pitch this as "ready to retrain on real sensor parameters the moment Tesla adds sensors" — not as solving a problem that exists today.

Both the core and the sub-problem share one internal event schema: `{source, entity_id, field, expected_value, actual_value, timestamp}`. Each data source (ERP, human report form, simulated sensors) is a thin **adapter** that translates its native format into this shared shape — diagnosis, ticketing, and notification logic is written once against that shape, not once per source. This reusable-engine framing is a deliberate architectural choice, not incidental — it's the strongest "systems thinking" signal in the whole project.

## Key technical decisions (already made — do not re-litigate without reason)

- **ERP: Odoo Community Edition, self-hosted via Docker** (not ERPNext, not Odoo Online). Community edition is genuinely free (LGPL v3) when self-hosted, includes everything needed (Inventory, Purchase, Manufacturing, Sales modules), and Astin noted its interface resembles WARP's. Odoo's Enterprise-only features (bank sync, its own automated reconciliation, barcode scanning) are irrelevant — we're not using Odoo's built-in reconciliation, we're building our own agent against its API.
- **Backend:** Python, FastAPI.
- **Diagnosis/agent logic:** LangGraph (reuse existing experience with multi-agent orchestration / RAG-style reasoning).
- **Frontend:** React — a dashboard showing detected issues/tickets, status, and the agent's reasoning, plus the failure-report intake form.
- **Containerization:** Docker for all services; a top-level `docker-compose.yml` tying together Odoo + Postgres + backend + frontend.
- **CI/CD:** GitHub Actions (lint, test, build on push).
- **Auth/logging:** basic API key or JWT auth on backend endpoints; structured logging per pipeline run.
- **Notifications:** Slack or Teams webhook integration for Version B.

## Synthetic data approach

No real Tesla data exists or is accessible, so data must be simulated — and this should be stated openly in the README/pitch, not implied to be real.

- **Entities to model** (the standard backbone of any manufacturing ERP — this is what WARP/Odoo/SAP all track): Products/SKUs (raw materials + finished goods, named plausibly — e.g. battery cells, Powerwall components), a simple Bill of Materials (BOM) for at least one finished product, a few Suppliers/Vendors, Warehouses/Locations (raw materials, WIP, finished goods), Purchase Orders, Sales Orders, Manufacturing/Work Orders, and Stock/Inventory levels per product per location.
- **Generation method:** a Python script (Faker for realistic IDs/names/dates, numpy/pandas for realistic volume patterns) generates a believable "normal" baseline of orders and stock movement over a simulated multi-month period, pushed into Odoo via its API (not just a static CSV — the integration itself needs to be real).
- **Anomaly injection:** deliberately and separately inject a known set of anomalies (stuck orders, quantity mismatches, duplicate entries, delayed deliveries) at a controlled rate, logging ground truth separately. This ground truth is what makes the eval (precision/recall) possible — a real, defensible number for the pitch, not just "it seems to work."
- **Sensor data (Version A only):** AI4I 2020 Predictive Maintenance Dataset preferred over NASA CMAPSS — it reads as general industrial machine sensors (torque, rotational speed, tool wear, temperature) rather than jet engines, which fits a car/battery plant pitch much better. Detection approach: rolling baseline (mean/std) with threshold flagging, validated against the dataset's labeled failures for precision/recall.

## Build plan

A day-by-day (6-day) build plan with checkboxes, priorities, and parallelizable tasks was built and published as an artifact: https://claude.ai/code/artifact/b825c2ec-e6d3-4646-ab58-7421f7d06a4d

High-level shape:
1. **Day 1 — Foundations & environment.** Docker/Odoo running (self-hosted, WSL2 backend on Windows — avoid running across the Windows/Linux filesystem boundary, it's slow), backend/frontend scaffolded in parallel, Odoo API access proven. This is the highest-risk single step of the week.
2. **Day 2 — Entities & synthetic data.** Base entities created in Odoo, data generator built, anomalies injected with ground truth logged.
3. **Day 3 — Core diagnosis engine.** Odoo fetch layer, rule-based detection, shared event schema, LangGraph diagnosis agent, eval script (precision/recall).
4. **Day 4 — Failure-report path (Version B) + notifications.** Intake endpoint, historical-incident matching, Slack/Teams webhook, wired into the shared engine. Version A adapter only if ahead of schedule.
5. **Day 5 — Dashboard & containerization.** React dashboard + report form, Dockerfiles, docker-compose, full local integration run-through.
6. **Day 6 — Testing, CI/CD, polish, pitch prep.** Final eval numbers, CI/CD pipeline, README (architecture, what's simulated vs. real, Version-A roadmap), demo recording, one-page pitch summary for Ashwin/the technical head.

## Working conventions for this project

- Prioritize the ERP core (Version B path included) being fully solid and demoable over the sensor/Version-A stretch being built at all. A complete, working core beats a half-built extra feature.
- Keep the "what's simulated vs. real" distinction explicit everywhere — code comments, README, and any pitch material. Overstating this project as using real Tesla data would undermine credibility if it came up in conversation.
- Favor interview-defensibility over inflated claims — every number cited (eval accuracy, etc.) must come from something actually run, not estimated.