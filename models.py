"""Pydantic request models for the sandbox logistics API.

The Problem Statement names four action types (reroute, purchase, allocate,
transfer); each gets its own typed request model plus a demand signal model
used by the detection layer.
"""
from datetime import datetime

from pydantic import BaseModel


class TransferRequest(BaseModel):
    source_facility_id: str
    dest_facility_id: str
    quantity_kg: float
    transport_mode: str
    requested_by: str


class PurchaseRequest(BaseModel):
    vendor_id: str
    dest_facility_id: str
    quantity_kg: float
    unit_cost_inr: float
    transport_mode: str
    requested_by: str


class RerouteRequest(BaseModel):
    shipment_id: str
    new_destination: str
    new_eta: datetime
    reason: str


class AllocationRequest(BaseModel):
    facility_id: str
    sku_id: str
    quantity_kg: float
    reserved_for: str   # e.g. order/customer id


class DemandSignal(BaseModel):
    facility_id: str
    sku_id: str
    observed_daily_burn_kg: float
    forecast_daily_burn_kg: float
    surge_ratio: float   # observed / baseline
