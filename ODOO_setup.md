# Setting Up Odoo Entities — Step by Step

This walks you through creating every base entity for Day 2, in order, with plain-English explanations of why each step exists. Total time: 30-45 minutes of clicking.

## What we're building (and why these choices)

We're modeling a small slice of a battery/energy-storage plant — close enough to Tesla Energy's actual product line (Powerwall) to read as deliberate, without pretending to be exact. A real Powerwall's battery pack contains hundreds of individual cylindrical cells plus a battery management system (BMS), all sealed in an enclosure — modeling that literally would be pointless complexity for a demo. So we're using a **symbolic, simplified BOM**: real component categories, unrealistic (small) quantities. Say this openly if it comes up — "the components are real categories, the quantities are simplified for demo purposes" is honest and sounds like an engineer who understands the real system, not someone who tried to fake it.

**Final entity list:**

| Role | Name | Internal Reference (SKU) |
|---|---|---|
| Raw material | Li-ion Battery Cell (2170) | `CELL-2170` |
| Raw material | Battery Management System Board | `BMS-100` |
| Raw material | Aluminum Enclosure | `ENC-PW3` |
| Raw material | Mounting Bracket Kit | `BRK-PW3` |
| Finished good | Powerwall Battery Unit | `PW3-ASSY` |

Suppliers: **Cell Dynamics Supply Co.** (cells), **Precision Enclosures Inc.** (enclosures/brackets), **CircuitWorks Electronics** (BMS boards).

Warehouse: **Brookshire Energy Plant**, with three locations inside it — Raw Materials, WIP, Finished Goods.

---

## Step 1 — Turn on the settings we need

Odoo hides some features until you enable them, since most small businesses don't need them.

1. Open the **Inventory** app.
2. Go to **Configuration → Settings**.
3. Turn on **Storage Locations** — this lets a single warehouse have multiple named locations inside it (Raw Materials, WIP, Finished Goods), instead of treating the whole warehouse as one blob.
4. Turn on **Multi-Step Routes** if you see it — this is what lets stock move *between* those locations in a trackable way (e.g., raw materials → WIP → finished goods) rather than just appearing and disappearing.
5. Click **Save**.

## Step 2 — Set up your warehouse

1. Still in Inventory, go to **Configuration → Warehouses**.
2. Odoo creates one warehouse by default (often called "My Company" or "WH"). Open it and rename it to **BT Energy Plant**. You can also change its short code (e.g. to `BRP`) — this code prefixes things like order references, so it's a nice authenticity touch.
3. Save.

## Step 3 — Create your three locations

1. Go to **Configuration → Locations**.
2. Click **New**, and create three locations, all nested *under* your Brookshire Energy Plant warehouse's internal stock location (Odoo will show you a parent-location field — pick the warehouse's main stock location as the parent for all three):
   - **Raw Materials**
   - **WIP** (Work in Progress)
   - **Finished Goods**
3. Save each.

This is what lets your later "inventory mismatch" anomalies mean something specific — a mismatch isn't just "wrong number," it's "wrong number *at this specific location*," which is much closer to a real ERP problem.

## Step 4 — Create your suppliers

1. Open the **Contacts** app (or you can do this from Purchase — same underlying records).
2. Click **New** for each supplier:
   - **Cell Dynamics Supply Co.** — Company type, fill in a plausible city/state if you want (doesn't need to be real).
   - **Precision Enclosures Inc.**
   - **CircuitWorks Electronics**
3. Save each. You don't need much detail here — name and company type are enough; this is just so your purchase orders have someone real to be "from."

## Step 5 — Create the raw material / component products

Go to the **Inventory** app → **Products → Products** → **New**, and repeat this for each of the four components:

1. **Product Name**: e.g. "Li-ion Battery Cell (2170)"
2. **Internal Reference**: `CELL-2170` (this is the SKU field, usually near the top)
3. **Product Type**: set to **Storable Product** — this is the critical one. It's what makes Odoo actually track quantity-on-hand for this item, rather than treating it as a service or a one-off item.
4. Go to the **Purchase** tab: add the relevant vendor (e.g. Cell Dynamics Supply Co. for the cell) and a plausible cost.
5. Save.

Repeat for all four: `CELL-2170`, `BMS-100` (vendor: CircuitWorks Electronics), `ENC-PW3` (vendor: Precision Enclosures Inc.), `BRK-PW3` (vendor: Precision Enclosures Inc.).

## Step 6 — Create the finished good product

Same **Products → New** flow, but:

1. **Product Name**: "Powerwall Battery Unit"
2. **Internal Reference**: `PW3-ASSY`
3. **Product Type**: **Storable Product**
4. Go to the **Sales** tab and set a plausible sales price (this product isn't really being "sold" externally in our story, but Odoo wants a price on record regardless).
5. Under general settings for this product, make sure the **Manufacture** route is enabled (you may see route checkboxes like "Buy" / "Manufacture" — check Manufacture, since this item is built, not purchased).
6. Save.

## Step 7 — Create the Bill of Materials (the "recipe")

This is the step that ties everything together — it's what tells Odoo (and later, your agent) what should get consumed when a Powerwall Battery Unit gets built.

1. Open the **Manufacturing** app.
2. Go to **Products → Bills of Materials** → **New**.
3. In **Product**, select "Powerwall Battery Unit" (`PW3-ASSY`).
4. In the **Components** table, add a line for each component with a (simplified, symbolic) quantity, e.g.:
   - `CELL-2170` — qty 4
   - `BMS-100` — qty 1
   - `ENC-PW3` — qty 1
   - `BRK-PW3` — qty 1
5. Save.

## Step 8 — Verify everything's connected

1. Go back to **Inventory → Products**, open "Powerwall Battery Unit," and look for a **Bill of Materials** smart button or a **Structure & Cost** tab — it should show the four components you just linked.
2. Check that all five products show up under **Products** with their internal references intact.
3. Check **Inventory → Configuration → Locations** and confirm your three locations are nested correctly under Brookshire Energy Plant.

Once this is done, you're ready for the parallel data-generation script to start referencing these exact names when it seeds purchase orders, work orders, and stock movements.

---

*Note: Odoo's menu wording can shift slightly between versions (e.g. "Configuration" vs "Settings" placement) — if a menu item isn't exactly where described, look one level up or down in the same app; the underlying concepts (Storage Locations setting, Warehouses, Locations, Products, Bills of Materials) are stable across recent Odoo versions.*