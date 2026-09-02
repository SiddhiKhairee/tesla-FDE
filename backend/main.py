from fastapi import FastAPI

from odoo_client import OdooClient
from odoo_fetch import (
    fetch_incoming_receipts,
    fetch_manufacturing_orders,
    fetch_outgoing_deliveries,
    fetch_purchase_orders,
    fetch_sales_orders,
    fetch_stock_quants,
)

app = FastAPI(title="Tesla FDE ERP Reconciliation Agent")

odoo = OdooClient()


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/debug/purchase-orders")
def debug_purchase_orders(limit: int = 20):
    return fetch_purchase_orders(odoo, limit=limit)


@app.get("/debug/receipts")
def debug_receipts(limit: int = 20):
    return fetch_incoming_receipts(odoo, limit=limit)


@app.get("/debug/manufacturing-orders")
def debug_manufacturing_orders(limit: int = 20):
    return fetch_manufacturing_orders(odoo, limit=limit)


@app.get("/debug/sales-orders")
def debug_sales_orders(limit: int = 20):
    return fetch_sales_orders(odoo, limit=limit)


@app.get("/debug/deliveries")
def debug_deliveries(limit: int = 20):
    return fetch_outgoing_deliveries(odoo, limit=limit)


@app.get("/debug/quants")
def debug_quants(limit: int = 20):
    return fetch_stock_quants(odoo, limit=limit)
