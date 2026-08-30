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
SIMULATION_MONTHS = 3  # how far back the generated history stretches, ending "today"

# --- Anomaly injection ---
ANOMALY_RATE = 0.08  # fraction of generated orders that get an anomaly injected
RANDOM_SEED = 42  # fixed seed so a run is reproducible; change for a fresh dataset

# --- Output paths ---
GROUND_TRUTH_PATH = "output/ground_truth.json"
