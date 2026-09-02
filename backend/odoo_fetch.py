"""
One fetch function per ERP record type the diagnosis engine cares about.
Each returns a plain list of dicts (search_read already decodes XML-RPC
into native Python types — no further wrapping needed).
"""
from odoo_client import OdooClient


def fetch_purchase_orders(client: OdooClient, limit: int | None = None) -> list[dict]:
    return client.search_read(
        "purchase.order",
        [],
        ["name", "state", "date_order", "date_planned", "amount_total"],
        limit=limit,
    )


def fetch_incoming_receipts(client: OdooClient, limit: int | None = None) -> list[dict]:
    return client.search_read(
        "stock.picking",
        [["picking_type_id.code", "=", "incoming"]],
        ["name", "state", "scheduled_date", "date_done", "origin"],
        limit=limit,
    )


def fetch_manufacturing_orders(client: OdooClient, limit: int | None = None) -> list[dict]:
    return client.search_read(
        "mrp.production",
        [],
        ["name", "state", "date_finished", "product_qty", "qty_produced"],
        limit=limit,
    )


def fetch_sales_orders(client: OdooClient, limit: int | None = None) -> list[dict]:
    return client.search_read(
        "sale.order",
        [],
        ["name", "state", "date_order", "amount_total"],
        limit=limit,
    )


def fetch_outgoing_deliveries(client: OdooClient, limit: int | None = None) -> list[dict]:
    return client.search_read(
        "stock.picking",
        [["picking_type_id.code", "=", "outgoing"]],
        ["name", "state", "scheduled_date", "date_done", "origin"],
        limit=limit,
    )


def fetch_stock_quants(client: OdooClient, limit: int | None = None) -> list[dict]:
    return client.search_read(
        "stock.quant",
        [],
        ["product_id", "location_id", "quantity"],
        limit=limit,
    )
