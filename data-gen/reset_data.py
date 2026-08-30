"""
Wipe transactional test data (POs, MOs, SOs, their pickings) and zero out
on-hand quantities for the 5 tracked products, without touching master data
(products, BOM, warehouse, locations, suppliers). Use this between test runs
of generate.py so each run starts from a clean slate.

    python reset_data.py
"""
from generate import confirm_wizard_if_returned
from odoo_client import OdooClient


def cancel_and_unlink(client, model, cancel_method="action_cancel"):
    ids = client.execute_kw(model, "search", [[]])
    if not ids:
        return 0
    for rec_id in ids:
        try:
            result = client.call_button(model, cancel_method, [rec_id])
            # Some models (e.g. sale.order) return a confirmation wizard
            # instead of cancelling directly — drive it rather than treating
            # it as done.
            confirm_wizard_if_returned(client, result, confirm_method="action_cancel")
        except Exception as e:
            print(f"  [WARN] could not cancel {model} id={rec_id}: {e}")

    remaining = client.execute_kw(model, "search", [[]])
    deleted = 0
    for rec_id in remaining:
        try:
            client.execute_kw(model, "unlink", [[rec_id]])
            deleted += 1
        except Exception as e:
            print(f"  [WARN] could not delete {model} id={rec_id}: {e}")
    return deleted


def zero_out_quants(client, entities):
    for key, product_id in entities["products"].items():
        for loc_key, location_id in entities["locations"].items():
            qty = client.get_on_hand_qty(product_id, location_id)
            if qty != 0:
                quants = client.search_read(
                    "stock.quant",
                    [["product_id", "=", product_id], ["location_id", "=", location_id]],
                    ["id"],
                )
                for q in quants:
                    client.write("stock.quant", [q["id"]], {"inventory_quantity": 0})
                    client.call_button("stock.quant", "action_apply_inventory", [q["id"]])
                print(f"  Reset {key} at {loc_key}: {qty} -> 0")


def main():
    client = OdooClient()

    from generate import resolve_entities
    entities = resolve_entities(client)

    print("Cancelling and deleting sales orders...")
    cancel_and_unlink(client, "sale.order", "action_cancel")

    print("Cancelling and deleting purchase orders...")
    cancel_and_unlink(client, "purchase.order", "button_cancel")

    print("Cancelling and deleting manufacturing orders...")
    cancel_and_unlink(client, "mrp.production", "action_cancel")

    print("Cancelling and deleting leftover stock pickings...")
    cancel_and_unlink(client, "stock.picking", "action_cancel")

    print("Zeroing out on-hand quantities for tracked products...")
    zero_out_quants(client, entities)

    print("\nDone. Any records that couldn't be deleted (e.g. already 'done') were left in place "
          "and printed above as warnings — those are historical/immutable in Odoo, but on-hand "
          "quantities have been reset to zero so the next generate.py run starts clean.")


if __name__ == "__main__":
    main()
