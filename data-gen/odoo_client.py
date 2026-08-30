"""
Thin XML-RPC wrapper around Odoo, plus name/SKU-based entity resolution.

Resolution is intentionally name/SKU-based rather than hardcoded ID-based,
since the base entities are created by hand in the Odoo UI (see
ODOO_setup.md) and their record IDs aren't known ahead of time.
"""
import xmlrpc.client

import config


class EntityNotFoundError(Exception):
    """Raised when a configured entity name/SKU doesn't resolve in Odoo."""


class OdooClient:
    def __init__(self):
        self.url = config.ODOO_URL
        self.db = config.ODOO_DB
        self.username = config.ODOO_USERNAME
        self.api_key = config.ODOO_API_KEY

        common = xmlrpc.client.ServerProxy(f"{self.url}/xmlrpc/2/common")
        self.uid = common.authenticate(self.db, self.username, self.api_key, {})
        if not self.uid:
            raise EntityNotFoundError(
                "Odoo authentication failed — check ODOO_DB/ODOO_USERNAME/ODOO_API_KEY in .env"
            )

        self.models = xmlrpc.client.ServerProxy(f"{self.url}/xmlrpc/2/object")

    def execute_kw(self, model, method, args, kwargs=None):
        try:
            return self.models.execute_kw(
                self.db, self.uid, self.api_key, model, method, args, kwargs or {}
            )
        except xmlrpc.client.Fault as e:
            # Some Odoo button methods (e.g. mrp.production.button_mark_done
            # or stock.quant.action_apply_inventory) return Python None on
            # success, which Odoo's own XML-RPC layer can't marshal back over
            # the wire. The action has already applied server-side by the
            # time this fails — safe to treat as success rather than an error.
            if "cannot marshal None" in str(e):
                return None
            raise

    def search_read(self, model, domain, fields, limit=None):
        kwargs = {"fields": fields}
        if limit:
            kwargs["limit"] = limit
        return self.execute_kw(model, "search_read", [domain], kwargs)

    def create(self, model, vals):
        return self.execute_kw(model, "create", [vals])

    def write(self, model, ids, vals):
        return self.execute_kw(model, "write", [ids, vals])

    def call_button(self, model, method, ids, **kwargs):
        return self.execute_kw(model, method, [ids], kwargs)

    # --- Entity resolution ---

    def get_product_id(self, sku: str) -> int:
        """Look up a product by its Internal Reference (default_code), not display name."""
        results = self.search_read(
            "product.product", [["default_code", "=", sku]], ["id", "name"], limit=1
        )
        if not results:
            raise EntityNotFoundError(
                f"No product found with Internal Reference '{sku}'. "
                f"Check the SKU in Odoo (Inventory > Products) matches config.py exactly."
            )
        return results[0]["id"]

    def get_warehouse_id(self, name: str) -> int:
        results = self.search_read("stock.warehouse", [["name", "=", name]], ["id"], limit=1)
        if not results:
            raise EntityNotFoundError(
                f"No warehouse found named '{name}'. Check config.WAREHOUSE_NAME."
            )
        return results[0]["id"]

    def get_location_id(self, name: str, warehouse_id: int) -> int:
        """Look up a stock location by name, scoped to descendants of the given warehouse."""
        warehouse = self.search_read(
            "stock.warehouse", [["id", "=", warehouse_id]], ["view_location_id"]
        )[0]
        parent_id = warehouse["view_location_id"][0]
        results = self.search_read(
            "stock.location",
            [["name", "=", name], ["id", "child_of", parent_id]],
            ["id"],
            limit=1,
        )
        if not results:
            raise EntityNotFoundError(
                f"No location named '{name}' found under warehouse id {warehouse_id}. "
                f"Check config.LOCATION_NAMES and that it's nested under the warehouse."
            )
        return results[0]["id"]

    def get_partner_id(self, name: str) -> int:
        results = self.search_read("res.partner", [["name", "=", name]], ["id"], limit=1)
        if not results:
            raise EntityNotFoundError(
                f"No contact found named '{name}'. Check config.SUPPLIER_NAMES."
            )
        return results[0]["id"]

    def get_or_create_customer_id(self, name: str) -> int:
        """Customers aren't part of the manual Day-2 entity list — create on first use."""
        results = self.search_read("res.partner", [["name", "=", name]], ["id"], limit=1)
        if results:
            return results[0]["id"]
        return self.create("res.partner", {"name": name, "company_type": "company"})

    def get_on_hand_qty(self, product_id: int, location_id: int) -> float:
        """Sum stock.quant quantity for a product at one exact location."""
        quants = self.search_read(
            "stock.quant",
            [["product_id", "=", product_id], ["location_id", "=", location_id]],
            ["quantity"],
        )
        return sum(q["quantity"] for q in quants)

    def get_bom_id(self, product_id: int) -> int:
        results = self.search_read(
            "mrp.bom", [["product_tmpl_id.product_variant_ids", "in", [product_id]]], ["id"], limit=1
        )
        if not results:
            raise EntityNotFoundError(
                f"No Bill of Materials found for product id {product_id}. "
                f"Check that the BOM was created in Odoo's Manufacturing app."
            )
        return results[0]["id"]
