"""
Read-only check: confirm every name/SKU in config.py resolves to a real
record in Odoo. Run this after finishing the manual Odoo setup, before
running generate.py for the first time.

    python verify_entities.py
"""
import config
from odoo_client import EntityNotFoundError, OdooClient


def check(label, fn):
    try:
        result = fn()
        print(f"  [OK] {label} -> id={result}")
        return True
    except EntityNotFoundError as e:
        print(f"  [FAIL] {label} -> {e}")
        return False


def main():
    print("Connecting to Odoo...")
    client = OdooClient()
    print(f"  [OK] Authenticated as uid={client.uid}\n")

    ok = True

    print("Warehouse:")
    ok &= check(config.WAREHOUSE_NAME, lambda: client.get_warehouse_id(config.WAREHOUSE_NAME))
    warehouse_id = None
    try:
        warehouse_id = client.get_warehouse_id(config.WAREHOUSE_NAME)
    except EntityNotFoundError:
        pass

    print("\nLocations:")
    if warehouse_id:
        for key, name in config.LOCATION_NAMES.items():
            ok &= check(f"{key} ({name})", lambda n=name: client.get_location_id(n, warehouse_id))
    else:
        print("  [SKIP] warehouse not found, can't check locations under it")
        ok = False

    print("\nSuppliers:")
    for key, name in config.SUPPLIER_NAMES.items():
        ok &= check(f"{key} ({name})", lambda n=name: client.get_partner_id(n))

    print("\nProducts (by SKU):")
    product_ids = {}
    for key, sku in config.PRODUCT_SKUS.items():
        try:
            product_ids[key] = client.get_product_id(sku)
            print(f"  [OK] {key} ({sku}) -> id={product_ids[key]}")
        except EntityNotFoundError as e:
            print(f"  [FAIL] {key} ({sku}) -> {e}")
            ok = False

    print("\nBill of Materials:")
    if "finished_good" in product_ids:
        ok &= check(
            config.PRODUCT_SKUS["finished_good"],
            lambda: client.get_bom_id(product_ids["finished_good"]),
        )
    else:
        print("  [SKIP] finished good product not found, can't check its BOM")
        ok = False

    print("\n" + ("All entities resolved — safe to run generate.py." if ok else
                  "Some entities did NOT resolve — fix config.py or the Odoo records above before running generate.py."))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
