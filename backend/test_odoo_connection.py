import os
import xmlrpc.client

from dotenv import load_dotenv

load_dotenv()

url = os.environ["ODOO_URL"]
db = os.environ["ODOO_DB"]
username = os.environ["ODOO_USERNAME"]
api_key = os.environ["ODOO_API_KEY"]

common = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/common")
uid = common.authenticate(db, username, api_key, {})

if not uid:
    raise SystemExit("Authentication failed — check ODOO_DB/ODOO_USERNAME/ODOO_API_KEY")

print(f"Authenticated as uid={uid}")

models = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/object")
products = models.execute_kw(
    db, uid, api_key,
    "product.product", "search_read",
    [[]],
    {"fields": ["id", "name"], "limit": 5},
)

print(f"Read {len(products)} product(s):")
for p in products:
    print(f"  [{p['id']}] {p['name']}")
