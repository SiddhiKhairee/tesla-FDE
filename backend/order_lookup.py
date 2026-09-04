"""
Builds a lookup from order name (the entity_id detection.py uses for
stuck_order/delayed_delivery/duplicate_entry events — e.g. "P00003",
"S00004") to the record-level detail those events don't carry themselves:
vendor/customer, order value, and the products/quantities on the order.

Kept separate from detection.py because it's not a detection rule — it
exists purely to enrich diagnosis.py's gather_context with facts an
analyst would actually look up before diagnosing a stuck or duplicated
order (who's the vendor, what's on the order, how much is it worth).
"""
from collections import defaultdict


def _m2o_id(value) -> int | None:
    return value[0] if value else None


def _m2o_name(value) -> str | None:
    return value[1] if value else None


def build_order_index(
    purchase_orders: list[dict],
    purchase_order_lines: list[dict],
    sales_orders: list[dict],
    sales_order_lines: list[dict],
    products: list[dict],
) -> dict[str, dict]:
    product_skus = {p["id"]: p["default_code"] for p in products}

    po_lines_by_order = defaultdict(list)
    for line in purchase_order_lines:
        po_lines_by_order[_m2o_id(line["order_id"])].append(line)

    so_lines_by_order = defaultdict(list)
    for line in sales_order_lines:
        so_lines_by_order[_m2o_id(line["order_id"])].append(line)

    def _line_items(order_id: int, lines_by_order: dict, qty_field: str) -> list[dict]:
        return [
            {
                "product": product_skus.get(_m2o_id(line["product_id"])) or str(_m2o_id(line["product_id"])),
                "quantity": line[qty_field],
            }
            for line in lines_by_order.get(order_id, [])
        ]

    index: dict[str, dict] = {}
    for po in purchase_orders:
        index[po["name"]] = {
            "partner": _m2o_name(po.get("partner_id")),
            "order_value": po.get("amount_total"),
            "products": _line_items(po["id"], po_lines_by_order, "product_qty"),
            "reference": po["name"],
        }
    for so in sales_orders:
        index[so["name"]] = {
            "partner": _m2o_name(so.get("partner_id")),
            "order_value": so.get("amount_total"),
            "products": _line_items(so["id"], so_lines_by_order, "product_uom_qty"),
            "reference": so["name"],
        }
    return index
