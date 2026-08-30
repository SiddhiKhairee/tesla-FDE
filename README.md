# Tesla FDE Portfolio Project — ERP Reconciliation & Failure-Reporting Agent

An agent that monitors an ERP (Odoo Community, standing in for Tesla's internal WARP system) for
operational discrepancies — stuck orders, inventory drift, duplicate records — diagnoses the
likely cause, and either resolves or flags them for human review. A shared diagnose-and-ticket
engine also powers a human failure-report intake path: a floor worker reports an issue, the agent
checks it against historical incidents, drafts a structured ticket, and notifies the team via
Slack/Teams — replacing the current manual "type it into Slack" step.

**Status:** early build — see `PLAN.md` for the day-by-day build plan and progress.

All ERP data is synthetic (Faker/numpy-generated), pushed into a self-hosted Odoo instance via its
API. No real Tesla data is used anywhere in this project.

## Stack

- **ERP:** Odoo Community Edition, self-hosted via Docker (Postgres-backed)
- **Backend:** Python, FastAPI
- **Diagnosis/agent logic:** LangGraph
- **Frontend:** React (Vite)
- **Containerization:** Docker / docker-compose
- **CI/CD:** GitHub Actions

## Repo layout

- `odoo/` — docker-compose for Odoo + Postgres
- `backend/` — FastAPI service (diagnosis engine, API endpoints)
- `frontend/` — React dashboard + failure-report intake form
- `data-gen/` — synthetic data generator and anomaly injection scripts

## Local setup (in progress)

1. `cd odoo && docker compose up -d` — starts Odoo + Postgres, UI at http://localhost:8069
2. `cd backend && python3 -m venv venv && ./venv/bin/pip install -r requirements.txt`
3. `cd frontend && npm install && npm run dev`

Full setup docs and architecture notes will be filled in as the build progresses.
