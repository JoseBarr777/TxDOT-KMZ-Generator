"""Inspects ArcGIS service/layer metadata so field names are never assumed."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import requests

from txdot_overlay.acquisition.arcgis_client import ArcGISLayerClient, LayerMetadata
from txdot_overlay.config import SourceConfig


@dataclass
class ServiceLayerSummary:
    """One layer/table advertised by a FeatureServer's service root."""

    layer_id: int
    name: str
    layer_type: str


@dataclass
class SourceInspection:
    source_key: str
    label: str
    service_url: str
    configured_layer_id: int
    available_layers: list[ServiceLayerSummary]
    metadata: LayerMetadata
    record_count: int
    configured_fields_present: dict[str, bool]

    @property
    def missing_configured_fields(self) -> list[str]:
        return [
            field_key
            for field_key, present in self.configured_fields_present.items()
            if not present
        ]


def list_service_layers(
    service_url: str, *, timeout_seconds: float = 30.0
) -> list[ServiceLayerSummary]:
    """Query the FeatureServer/MapServer root to list every layer and table it exposes."""
    response = requests.get(service_url, params={"f": "json"}, timeout=timeout_seconds)
    response.raise_for_status()
    payload = response.json()
    summaries: list[ServiceLayerSummary] = []
    for layer in payload.get("layers", []):
        summaries.append(
            ServiceLayerSummary(
                layer_id=layer["id"], name=layer.get("name", ""), layer_type="layer"
            )
        )
    for table in payload.get("tables", []):
        summaries.append(
            ServiceLayerSummary(
                layer_id=table["id"], name=table.get("name", ""), layer_type="table"
            )
        )
    return summaries


def inspect_source(
    source: SourceConfig,
    *,
    timeout_seconds: float = 30.0,
    max_retries: int = 3,
    retry_backoff_seconds: float = 2.0,
) -> SourceInspection:
    """Fetch live metadata for a configured source and check its configured fields exist."""
    client = ArcGISLayerClient(
        source.layer_url,
        timeout_seconds=timeout_seconds,
        max_retries=max_retries,
        retry_backoff_seconds=retry_backoff_seconds,
    )
    available_layers = list_service_layers(
        source.service_url, timeout_seconds=timeout_seconds
    )
    metadata = client.get_metadata()
    record_count = client.count()

    field_names = set(metadata.field_names)
    configured_fields_present = {
        field_key: (field_name in field_names)
        for field_key, field_name in source.fields.items()
    }

    return SourceInspection(
        source_key=source.key,
        label=source.label,
        service_url=source.service_url,
        configured_layer_id=source.layer_id,
        available_layers=available_layers,
        metadata=metadata,
        record_count=record_count,
        configured_fields_present=configured_fields_present,
    )


def format_inspection_report(inspection: SourceInspection) -> str:
    lines: list[str] = []
    lines.append(f"=== {inspection.label} ({inspection.source_key}) ===")
    lines.append(f"Service URL:        {inspection.service_url}")
    lines.append(f"Configured layer:   {inspection.configured_layer_id}")
    lines.append("Available layers/tables:")
    for layer in inspection.available_layers:
        marker = "*" if layer.layer_id == inspection.configured_layer_id else " "
        lines.append(f"  [{marker}] {layer.layer_id}: {layer.name} ({layer.layer_type})")
    lines.append(f"Layer name:         {inspection.metadata.name}")
    lines.append(f"Geometry type:      {inspection.metadata.geometry_type}")
    lines.append(f"Spatial reference:  EPSG:{inspection.metadata.spatial_reference_wkid}")
    lines.append(f"Max record count:   {inspection.metadata.max_record_count}")
    lines.append(
        f"Query formats:      {', '.join(inspection.metadata.supported_query_formats)}"
    )
    lines.append(f"Record count:       {inspection.record_count}")
    lines.append(f"Total fields:       {len(inspection.metadata.fields)}")
    lines.append("Configured fields:")
    for field_key, present in inspection.configured_fields_present.items():
        status = "OK" if present else "MISSING"
        lines.append(f"  {status:7s} {field_key}")
    if inspection.missing_configured_fields:
        lines.append(
            "WARNING: configured fields not found on live service: "
            + ", ".join(inspection.missing_configured_fields)
        )
    return "\n".join(lines)
