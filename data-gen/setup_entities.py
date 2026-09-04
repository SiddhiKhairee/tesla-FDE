"""
One-time automated entity setup — the scripted equivalent of the manual
click-through in ODOO_setup.md. Written after a second full Odoo wipe made
it clear redoing that by hand every time a clean database is needed isn't
sustainable. Idempotent: safe to rerun against a database that already has
some of these entities (skips anything that already exists by name/SKU).

    python setup_entities.py
"""
import config
from odoo_client import EntityNotFoundError, OdooClient

RAW_MATERIALS = {
    # key -> (name, sku, supplier_key, unit_cost)
    "cell": ("Li-ion Battery Cell (2170)", "CELL-2170", "cells", 12.50),
    "bms": ("Battery Management System Board", "BMS-100", "bms", 65.00),
    "enclosure": ("Aluminum Enclosure", "ENC-PW3", "enclosures", 95.00),
    "bracket": ("Mounting Bracket Kit", "BRK-PW3", "enclosures", 22.00),
}
FINISHED_GOOD = ("Powerwall Battery Unit", "PW3-ASSY")
FINISHED_GOOD_PRICE = 450.00

BOM_LINES = {
    "cell": 4.0,
    "bms": 1.0,
    "enclosure": 1.0,
    "bracket": 1.0,
}


def install_apps(client: OdooClient):
    """Purchase, Sales, and Manufacturing — the same three apps ODOO_setup.md
    has you install by hand. Inventory (stock) is already installed by
    default in a fresh Odoo database."""
    modules = client.search_read(
        "ir.module.module",
        [["name", "in", ["purchase", "sale_management", "mrp"]], ["state", "!=", "installed"]],
        ["id", "name"],
    )
    if not modules:
        print("Purchase, Sales, and Manufacturing apps already installed.")
        return
    for module in modules:
        client.call_button("ir.module.module", "button_immediate_install", [module["id"]])
        print(f"Installed app: {module['name']}")


def enable_inventory_settings(client: OdooClient):
    """Storage Locations + Multi-Step Routes — same two settings ODOO_setup.md
    has you toggle by hand in Inventory > Configuration > Settings."""
    settings_id = client.create(
        "res.config.settings",
        {"group_stock_multi_locations": True, "group_stock_adv_location": True},
    )
    client.call_button("res.config.settings", "execute", [settings_id])
    print("Enabled Storage Locations + Multi-Step Routes.")


def setup_warehouse(client: OdooClient) -> int:
    """Rename the default warehouse and return its Stock location id (the
    parent the three tracked locations nest under)."""
    warehouses = client.search_read("stock.warehouse", [], ["id", "name", "lot_stock_id"])
    if not warehouses:
        raise EntityNotFoundError("No warehouse found — Inventory app may not be installed.")
    wh = warehouses[0]
    if wh["name"] != config.WAREHOUSE_NAME:
        client.write("stock.warehouse", [wh["id"]], {"name": config.WAREHOUSE_NAME, "code": "BRP"})
        print(f"Renamed warehouse -> {config.WAREHOUSE_NAME} (code BRP).")
    else:
        print(f"Warehouse already named {config.WAREHOUSE_NAME}.")
    return wh["lot_stock_id"][0]


def setup_locations(client: OdooClient, stock_location_id: int) -> dict:
    location_ids = {}
    for key, name in config.LOCATION_NAMES.items():
        existing = client.search_read(
            "stock.location", [["name", "=", name], ["location_id", "=", stock_location_id]], ["id"]
        )
        if existing:
            location_ids[key] = existing[0]["id"]
            print(f"Location already exists: {name}")
        else:
            loc_id = client.create(
                "stock.location", {"name": name, "location_id": stock_location_id, "usage": "internal"}
            )
            location_ids[key] = loc_id
            print(f"Created location: {name}")
    return location_ids


def setup_suppliers(client: OdooClient) -> dict:
    supplier_ids = {}
    for key, name in config.SUPPLIER_NAMES.items():
        existing = client.search_read("res.partner", [["name", "=", name]], ["id"])
        if existing:
            supplier_ids[key] = existing[0]["id"]
            print(f"Supplier already exists: {name}")
        else:
            partner_id = client.create("res.partner", {"name": name, "company_type": "company"})
            supplier_ids[key] = partner_id
            print(f"Created supplier: {name}")
    return supplier_ids


def get_route_id(client: OdooClient, name: str) -> int:
    routes = client.search_read("stock.route", [["name", "=", name]], ["id"])
    if not routes:
        raise EntityNotFoundError(
            f"No route named '{name}' found — is the Purchase/Manufacturing app installed?"
        )
    return routes[0]["id"]


def setup_products(client: OdooClient, supplier_ids: dict) -> dict:
    product_ids = {}
    buy_route_id = get_route_id(client, "Buy")

    for key, (name, sku, supplier_key, unit_cost) in RAW_MATERIALS.items():
        existing = client.search_read("product.template", [["default_code", "=", sku]], ["id"])
        if existing:
            product_ids[key] = existing[0]["id"]
            print(f"Product already exists: {sku}")
            continue
        tmpl_id = client.create(
            "product.template",
            {
                "name": name,
                "default_code": sku,
                "type": "product",
                "purchase_ok": True,
                "sale_ok": False,
                "standard_price": unit_cost,
                "route_ids": [(6, 0, [buy_route_id])],
            },
        )
        client.create(
            "product.supplierinfo",
            {
                "partner_id": supplier_ids[supplier_key],
                "product_tmpl_id": tmpl_id,
                "price": unit_cost,
            },
        )
        product_ids[key] = tmpl_id
        print(f"Created product: {sku} (cost ${unit_cost}, vendor {config.SUPPLIER_NAMES[supplier_key]})")

    fg_name, fg_sku = FINISHED_GOOD
    existing = client.search_read("product.template", [["default_code", "=", fg_sku]], ["id"])
    if existing:
        product_ids["finished_good"] = existing[0]["id"]
        print(f"Product already exists: {fg_sku}")
    else:
        manufacture_route_id = get_route_id(client, "Manufacture")
        tmpl_id = client.create(
            "product.template",
            {
                "name": fg_name,
                "default_code": fg_sku,
                "type": "product",
                "purchase_ok": False,
                "sale_ok": True,
                "list_price": FINISHED_GOOD_PRICE,
                "route_ids": [(6, 0, [manufacture_route_id])],
            },
        )
        product_ids["finished_good"] = tmpl_id
        print(f"Created product: {fg_sku} (price ${FINISHED_GOOD_PRICE})")

    return product_ids


def setup_bom(client: OdooClient, product_ids: dict):
    fg_tmpl_id = product_ids["finished_good"]
    existing = client.search_read("mrp.bom", [["product_tmpl_id", "=", fg_tmpl_id]], ["id"])
    if existing:
        print("BOM already exists for PW3-ASSY.")
        return

    # BOM lines reference product.product (the variant), not product.template.
    variant_ids = {
        key: client.search_read("product.product", [["product_tmpl_id", "=", tmpl_id]], ["id"])[0]["id"]
        for key, tmpl_id in product_ids.items()
        if key in BOM_LINES
    }
    bom_id = client.create(
        "mrp.bom",
        {
            "product_tmpl_id": fg_tmpl_id,
            "type": "normal",
            "bom_line_ids": [
                (0, 0, {"product_id": variant_ids[key], "product_qty": qty})
                for key, qty in BOM_LINES.items()
            ],
        },
    )
    print(f"Created BOM (id={bom_id}) linking PW3-ASSY to its 4 components.")


def main():
    client = OdooClient()
    print(f"Authenticated as uid={client.uid}.\n")

    install_apps(client)
    enable_inventory_settings(client)
    stock_location_id = setup_warehouse(client)
    setup_locations(client, stock_location_id)
    supplier_ids = setup_suppliers(client)
    product_ids = setup_products(client, supplier_ids)
    setup_bom(client, product_ids)

    print("\nDone. Run verify_entities.py to confirm everything resolves.")


if __name__ == "__main__":
    main()
