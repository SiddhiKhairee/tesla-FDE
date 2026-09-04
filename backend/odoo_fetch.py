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
        ["name", "state", "date_order", "date_planned", "amount_total", "partner_id"],
        limit=limit,
    )


def fetch_purchase_order_lines(client: OdooClient, limit: int | None = None) -> list[dict]:
    return client.search_read(
        "purchase.order.line",
        [],
        ["order_id", "product_id", "product_qty"],
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
        ["name", "state", "date_order", "amount_total", "partner_id"],
        limit=limit,
    )


def fetch_sales_order_lines(client: OdooClient, limit: int | None = None) -> list[dict]:
    return client.search_read(
        "sale.order.line",
        [],
        ["order_id", "product_id", "product_uom_qty"],
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


def fetch_stock_moves(client: OdooClient, limit: int | None = None) -> list[dict]:
    """Completed, real stock movements only — excludes the "Product Quantity
    Updated" moves Odoo auto-creates for manual inventory adjustments (e.g.
    the ones the Day 2 anomaly injector uses to corrupt a quant), since those
    would just re-launder the corrupted value back into the ledger.
    """
    return client.search_read(
        "stock.move",
        [["state", "=", "done"], ["reference", "!=", "Product Quantity Updated"]],
        ["product_id", "location_id", "location_dest_id", "quantity", "reference"],
        limit=limit,
    )


def fetch_internal_locations(client: OdooClient, limit: int | None = None) -> list[dict]:
    """Real physical stock locations only (Raw Materials, WIP, Finished Goods)
    — excludes virtual accounting locations (Partners/Vendors, Partners/
    Customers, Virtual Locations/Production, Inventory adjustment) that
    legitimately carry large positive/negative quantities as double-entry
    bookkeeping counterparts, not physical drift.
    """
    return client.search_read(
        "stock.location",
        [["usage", "=", "internal"]],
        ["name"],
        limit=limit,
    )


def fetch_products(client: OdooClient, limit: int | None = None) -> list[dict]:
    return client.search_read(
        "product.product",
        [],
        ["default_code"],
        limit=limit,
    )
