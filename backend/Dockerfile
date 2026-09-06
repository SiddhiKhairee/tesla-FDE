# Matches the Python version this project has actually been developed and
# tested against (backend/venv is 3.12.3) — see requirements.txt for pinned
# dependency versions.
FROM python:3.12-slim

WORKDIR /app

# Copy requirements first so dependency installs are cached separately from
# application code changes.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Everything else, including the checked-in sensor ML artifacts
# (model_v2.pkl, model_v2_meta.json) and backend/data/historical_incidents.json
# — all committed source/data the backend loads at runtime. .dockerignore
# excludes venv/, tests, caches, .env, and the gitignored runtime ticket
# store (backend/data/tickets.json), which is meant to be mounted as a
# volume in docker-compose, not baked into the image.
COPY . .

ENV PYTHONUNBUFFERED=1

# Matches the port this project has been run on locally (uvicorn main:app
# --port 8000) and what frontend/vite.config.js's dev proxy targets.
EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
