"""
Central config for the Day 2 synthetic data generator.

Everything under "Entity references" below must match, exactly, what was
manually created in Odoo per ODOO_setup.md — lookups are done by name (for
warehouse/locations/suppliers) or by internal reference/SKU (for products),
not by Odoo record ID, since IDs aren't known until after manual entry.

Run `python verify_entities.py` after finishing the Odoo UI setup to confirm
every name/SKU below actually resolves before running the full generator.
"""
import os

from dotenv import load_dotenv

load_dotenv()

# --- Odoo connection (same variable names as backend/.env) ---
ODOO_URL = os.getenv("ODOO_URL", "http://localhost:8069")
ODOO_DB = os.getenv("ODOO_DB", "tesla_fde")
ODOO_USERNAME = os.getenv("ODOO_USERNAME")
ODOO_API_KEY = os.getenv("ODOO_API_KEY")

# --- Entity references — PLACEHOLDER values, confirm against the live Odoo instance ---

# Warehouse display name, as set in Inventory > Configuration > Warehouses.
# Confirmed against the live Odoo instance.
WAREHOUSE_NAME = "BT Energy Plant"

# Storage location display names, as set in Inventory > Configuration > Locations,
# nested under the warehouse's internal stock location.
# Confirmed against the live Odoo instance.
LOCATION_NAMES = {
    "raw_materials": "Raw Materials",
    "wip": "WIP",
    "finished_goods": "Finished Goods",
}

# Supplier (vendor) display names, as created in Contacts.
# Confirmed against the live Odoo instance.
SUPPLIER_NAMES = {
    "cells": "Cell Dynamics Supply Co.",
    "bms": "CircuitWorks Electronics",
    "enclosures": "Precision Enclosures Inc.",
}

# Product internal references (SKUs) — the reliable lookup key, since display
# names are more likely to drift than a typed-once SKU field.
# Confirmed against the live Odoo instance.
PRODUCT_SKUS = {
    "cell": "CELL-2170",
    "bms": "BMS-100",
    "enclosure": "ENC-PW3",
    "bracket": "BRK-PW3",
    "finished_good": "PW3-ASSY",
}

# Which raw material SKU is bought from which supplier key — must agree with
# the vendor assigned on each product's Purchase tab in Odoo.
PRODUCT_SUPPLIER = {
    "cell": "cells",
    "bms": "bms",
    "enclosure": "enclosures",
    "bracket": "enclosures",
}

# --- Simulation window ---
# Bumped from 3 -> 8 months (post-Day-2 fix): a full Odoo wipe-and-reseed
# after the original Day 2 spot-check produced a much smaller run (only ~13
# total anomalies, 0 of them duplicate_entry) than what was originally
# approved, purely from random luck on a small sample — see
# data-gen/GROUND_TRUTH_NOTES.md. 3 months' worth of orders at the old
# ANOMALY_RATE gave too few draws for every type to reliably clear even one
# example, let alone enough for a meaningful eval. 8 months + the ANOMALY_RATE
# bump below is sized (see that file) to comfortably clear ~10+ expected
# stuck_order/delayed_delivery examples even after typical live-Odoo skip/
# failure attrition.
SIMULATION_MONTHS = 8  # how far back the generated history stretches, ending "today"

# --- Anomaly injection ---
ANOMALY_RATE = 0.12  # fraction of generated orders that get an anomaly injected — bumped from 0.08, see above
RANDOM_SEED = 42  # fixed seed so a run is reproducible; change for a fresh dataset

# quantity_mismatch anomalies are injected as a separate pass at the very end
# of the simulated window (see generate.py's inject_quantity_mismatches), one
# per distinct product/location so they don't collide on the same quant.
# Capped at 5 — the number of distinct product/location combos available
# under the current entity model (4 raw materials + 1 finished good, each at
# a single natural location). This is a real ceiling, not a target we chose:
# getting quantity_mismatch above 5 would require adding more product/
# location combos to the Odoo entity set itself, out of scope for this fix.
QUANTITY_MISMATCH_COUNT = 5

# duplicate_entry anomalies are now a dedicated guaranteed-count pass (see
# generate.py's inject_duplicate_entries), exactly like quantity_mismatch
# above, instead of being one arm of a per-order random.choice — the random
# 3-way split was the root cause of the Day 2 gap (0 duplicate_entry
# examples from only 3 independent 1-in-3 draws). Capped at however many
# real, non-anomalous purchase orders the run actually produced.
DUPLICATE_ENTRY_COUNT = 10

# --- Output paths ---
GROUND_TRUTH_PATH = "output/ground_truth.json"
