"""Illustrative supply-chain carbon accounting over the synthetic demand data.

The emission factors below are ILLUSTRATIVE PLACEHOLDERS (kg CO2e per unit produced and per unit-km shipped),
not audited or sourced values. The point of this module is the calculation and the API shape, not the numbers.
"""
from __future__ import annotations

import pandas as pd

DEFAULT_PRODUCTION_FACTOR = 2.0   # kg CO2e per unit, used when a category has no entry
DEFAULT_TRANSPORT_KM = 400.0      # assumed average distance to customer
TRANSPORT_FACTOR_PER_UNIT_KM = 0.0005   # kg CO2e per unit-km (road freight, illustrative)

PRODUCTION_FACTORS = {   # kg CO2e per unit, illustrative
    "Bearings": 3.2, "Valves": 5.8, "Pumps": 14.0, "Motors": 21.0, "Gaskets": 0.9, "Filters": 1.6,
}


def production_factor(category: str) -> float:
    return PRODUCTION_FACTORS.get(category, DEFAULT_PRODUCTION_FACTOR)


def estimate(units_by_category: pd.DataFrame, transport_km: float = DEFAULT_TRANSPORT_KM) -> pd.DataFrame:
    """units_by_category: columns category, units. Returns per-category kg CO2e split into production and transport."""
    if transport_km < 0:
        raise ValueError("transport_km must be >= 0")
    df = units_by_category.copy()
    df["production_kg"] = df["units"] * df["category"].map(production_factor)
    df["transport_kg"] = df["units"] * transport_km * TRANSPORT_FACTOR_PER_UNIT_KM
    df["total_kg"] = df["production_kg"] + df["transport_kg"]
    df["kg_per_unit"] = (df["total_kg"] / df["units"]).where(df["units"] > 0)
    return df.sort_values("total_kg", ascending=False).reset_index(drop=True)
