from fastapi import FastAPI

app = FastAPI(title="Tesla FDE ERP Reconciliation Agent")


@app.get("/health")
def health():
    return {"status": "ok"}
