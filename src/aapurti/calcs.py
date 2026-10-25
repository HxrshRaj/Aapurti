"""Approved business calculations (pure Python). The Spark gold layer must match these."""
from __future__ import annotations

import math

from .config import SERVICE_Z


def days_of_cover(on_hand: float, avg_daily_demand: float) -> float | None:
    if avg_daily_demand is None or avg_daily_demand <= 0:
        return None
    return on_hand / avg_daily_demand


def safety_stock(sigma_daily: float, lead_time_days: float, z: float = SERVICE_Z) -> float:
    """z * sigma_d * sqrt(L), sigma_d = population std-dev of trailing daily demand."""
    return z * sigma_daily * math.sqrt(lead_time_days)


def reorder_point(avg_daily_demand: float, lead_time_days: float, ss: float) -> float:
    return avg_daily_demand * lead_time_days + ss


def utilization(run_hours: float, available_hours: float) -> float | None:
    if available_hours <= 0:
        return None
    return run_hours / available_hours


def stockout_risk(on_hand: float, avg_daily_demand: float, lead_time_days: float, rop: float) -> str:
    """HIGH: cover shorter than lead time. MEDIUM: below reorder point. Else LOW."""
    doc = days_of_cover(on_hand, avg_daily_demand)
    if doc is None:
        return "LOW"
    if doc < lead_time_days:
        return "HIGH"
    if on_hand < rop:
        return "MEDIUM"
    return "LOW"
