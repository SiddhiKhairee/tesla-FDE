# ERP Reconciliation & Failure-Reporting Agent — 6-Day Build Plan

Build plan for the Tesla FDE portfolio project — an agent that watches an Odoo-based ERP for order/inventory discrepancies, diagnoses the cause, and a shared engine that turns human-reported equipment failures into structured, notified tickets.

**Stack:** Odoo Community (self-hosted) · FastAPI + LangGraph · React · Docker + GitHub Actions · Windows / WSL2

> **Windows note** — Docker Desktop needs the WSL2 backend enabled (Settings → General → "Use the WSL 2 based engine"). Clone the repo and run everything *inside* the WSL2 filesystem (e.g. `~/tesla/tesla-FDE`), not on the Windows `C:\` mount — file-watching and volume performance are meaningfully worse across the Windows/Linux boundary, and Odoo + Postgres + your services running together will feel it. Use VS Code's "Remote — WSL" mode to edit those files directly.

Priority key: **P0** = must-do · **P1** = important · **P2** = stretch, only if ahead of schedule.

---

## Day 1 — Foundations & Environment

**Goal:** Docker/Odoo running, both service skeletons scaffolded, API access to Odoo proven.

**Sequential — do first**
- [x] Install Docker Desktop (WSL2 backend) and confirm `docker run hello-world` works — **P0**
- [x] Create repo structure: `/backend`, `/frontend`, `/data-gen`, `/odoo`, `README.md` — **P0**
- [x] Stand up Odoo Community via docker-compose (odoo + postgres) — **P0**
  - Use the official Odoo docker-compose reference — don't hand-roll the Postgres wiring.
- [x] Log into Odoo, enable Inventory, Purchase, Manufacturing, Sales apps — **P0**

**Parallel — while Odoo is standing up**
- [x] Scaffold FastAPI backend (venv, requirements.txt, health-check endpoint) — **P1**
- [x] Scaffold React frontend (Vite), confirm it builds and runs — **P1**

**Sequential — after Odoo is up**
- [x] Enable Odoo's external API (XML-RPC or REST) and make one successful authenticated read call from Python — **P0**
  - This is the riskiest single step in the whole week — don't leave it for later.
- [x] Push initial commit, write a one-paragraph README stub — **P1**
- [ ] Add an empty GitHub Actions workflow file (lint job only, for now) — **P2**

**Depends on:** Nothing — this is day zero. Everything else in the week depends on the Odoo API connection working, so don't leave this day partial.

---

## Day 2 — Entities & Synthetic Data

**Goal:** Core entities defined in Odoo; a generator script produces realistic order/inventory history with labeled anomalies.

**Parallel — independent tracks**
- [ ] Manually create the base entity set in Odoo UI: 4–6 products (raw + finished), 2 warehouses, 2–3 suppliers, one simple BOM — **P0**
- [ ] Build the Python data-generator (Faker + numpy): purchase orders, work orders, sales orders, stock moves over a simulated 2–3 month window — **P0**

**Sequential — needs both tracks above**
- [ ] Design the anomaly-injection logic (stuck orders, quantity mismatches, duplicate entries) and a ground-truth log of what was injected — **P0**
- [ ] Push generated records into Odoo through the API proven on Day 1 — **P0**
- [ ] Spot-check in the Odoo UI that orders/stock look right — **P0**
- [ ] Run the anomaly injection pass, confirm the ground-truth file matches what landed in Odoo — **P0**

**Depends on:** the Odoo API connection from Day 1. If that's shaky, fix it before writing the generator.

---

## Day 3 — Core Diagnosis Engine

**Goal:** A backend service that pulls Odoo data, detects discrepancies, and reasons about likely cause.

**Parallel — independent tracks**
- [ ] Build the Odoo data-fetch layer in FastAPI (orders, stock levels, work orders) — **P0**
- [ ] Define the shared event schema — `{source, entity_id, field, expected, actual, timestamp}` — used by both the ERP and failure-report paths — **P0**

**Sequential**
- [ ] Build rule-based detection logic on top of the fetch layer (mismatch checks, stuck-order checks, quantity drift) — **P0**
- [ ] Build the LangGraph diagnosis agent: takes a raised event, reasons about likely cause, drafts a structured report — **P0**
- [ ] Wire detection → event schema → agent, end to end — **P0**
- [ ] Write the eval script: compare detected anomalies against Day 2's ground truth, compute precision/recall — **P0**
  - This number is your strongest defensible claim in the pitch — don't skip it.

**Parallel — polish, lower priority**
- [ ] Add basic auth (API key or JWT) on the endpoints — **P1**
- [ ] Add structured logging for each pipeline run — **P1**

**Depends on:** seeded, anomaly-tagged data from Day 2.

---

## Day 4 — Failure-Report Path & Notifications

**Goal:** The human-reported path (Version B) works end to end and fires real notifications.

**Parallel — independent tracks**
- [ ] Build the failure-report intake endpoint (machine, issue, timestamp, notes) — **P0**
- [ ] Build a small historical-incident store + similarity/pattern-match logic — **P0**

**Sequential**
- [ ] Wire the intake endpoint into the same diagnosis engine from Day 3, using the shared event schema — **P0**
- [ ] Build the Slack or Teams webhook integration for auto-notification — **P0**
- [ ] Connect report/ticket generation → notification trigger — **P0**
- [ ] Write a handful of tests covering both pipelines (ERP path + report path) — **P1**

**Stretch — only if ahead of schedule**
- [ ] Stub the Version-A adapter: feed the AI4I sensor dataset into the same engine as a forward-looking demo — **P2**

**Depends on:** the shared event schema and diagnosis agent from Day 3.

---

## Day 5 — Dashboard & Containerization

**Goal:** A working UI for both flows, and the whole system runs from one `docker-compose up`.

**Parallel — independent tracks**
- [ ] Build the React dashboard: list of detected issues/tickets, status, the agent's reasoning — **P0**
- [ ] Write Dockerfiles for the backend and frontend — **P0**

**Parallel — independent tracks**
- [ ] Build the failure-report form UI (Version B intake) — **P0**
- [ ] Write the top-level `docker-compose.yml` tying Odoo + Postgres + backend + frontend together — **P0**

**Sequential — integration**
- [ ] Connect the frontend to the backend API — **P0**
- [ ] Full local run-through: `docker-compose up`, confirm every service talks to the others — **P0**
- [ ] Fix whatever breaks — budget real time for this, it always takes longer than expected — **P0**

**Depends on:** a working backend (Day 3–4). This is the day most likely to run long — protect it.

---

## Day 6 — Testing, CI/CD, Polish & Pitch Prep

**Goal:** Demo-ready, documented, and the pitch material Astin can actually use.

**Parallel — independent tracks**
- [ ] Run the full eval, record final precision/recall numbers — **P0**
- [ ] Finish the GitHub Actions pipeline: lint + test + build on push — **P1**

**Parallel — independent tracks**
- [ ] Write the README: architecture diagram, setup steps, what's simulated vs. real, the Version-A roadmap — **P0**
- [ ] Record a short demo video or GIF of the working system — **P1**

**Sequential — final push**
- [ ] End-to-end demo run-through; fix any last bugs — **P0**
- [ ] Write the one-page summary for Ashwin / the technical head — **P0**
- [ ] Push final code, tag a release — **P1**
- [ ] Stretch: deploy to a free cloud tier (Render/Railway/Azure free tier) for a live demo link — **P2**

**Depends on:** everything above being integrated by end of Day 5.

---

*Interactive, checkbox-tracked version of this plan: https://claude.ai/code/artifact/b825c2ec-e6d3-4646-ab58-7421f7d06a4d*