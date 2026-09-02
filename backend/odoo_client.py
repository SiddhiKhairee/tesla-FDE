"""
Reusable XML-RPC client for the Odoo instance — reuses the same credentials
and connection approach proven working in test_odoo_connection.py on Day 1.
"""
import os
import xmlrpc.client

from dotenv import load_dotenv

load_dotenv()


class OdooClient:
    def __init__(self):
        self.url = os.environ["ODOO_URL"]
        self.db = os.environ["ODOO_DB"]
        self.username = os.environ["ODOO_USERNAME"]
        self.api_key = os.environ["ODOO_API_KEY"]

        common = xmlrpc.client.ServerProxy(f"{self.url}/xmlrpc/2/common")
        self.uid = common.authenticate(self.db, self.username, self.api_key, {})
        if not self.uid:
            raise RuntimeError(
                "Odoo authentication failed — check ODOO_DB/ODOO_USERNAME/ODOO_API_KEY in .env"
            )

        self.models = xmlrpc.client.ServerProxy(f"{self.url}/xmlrpc/2/object")

    def search_read(self, model: str, domain: list, fields: list[str], limit: int | None = None) -> list[dict]:
        kwargs = {"fields": fields}
        if limit:
            kwargs["limit"] = limit
        return self.models.execute_kw(
            self.db, self.uid, self.api_key, model, "search_read", [domain], kwargs
        )
