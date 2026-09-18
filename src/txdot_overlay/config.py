"""Loads and validates config/config.yaml into typed, attribute-accessible objects."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "config.yaml"


@dataclass(frozen=True)
class SourceConfig:
    key: str
    label: str
    service_url: str
    layer_id: int
    fields: dict[str, str]
    description_fields: list[str]

    @property
    def layer_url(self) -> str:
        return f"{self.service_url.rstrip('/')}/{self.layer_id}"


@dataclass(frozen=True)
class RouteStyleConfig:
    label: str
    line_color: str
    line_width: float
    dashed: bool = False


@dataclass(frozen=True)
class PolygonStyleConfig:
    line_color: str
    line_width: float
    fill: bool
    fill_color: str
    fill_opacity: float


@dataclass(frozen=True)
class Config:
    sources: dict[str, SourceConfig]
    route_classification: dict[str, str]
    district_style: PolygonStyleConfig
    county_style: PolygonStyleConfig
    city_limits_style: PolygonStyleConfig
    route_styles: dict[str, RouteStyleConfig]
    visibility_defaults: dict[str, bool]
    cache_dir: Path
    cache_max_age_hours: float
    output_dir: Path
    master_kml_name: str
    single_file_kmz_name: str
    simplification_enabled: bool
    simplification_tolerance_degrees: float
    county_boundary_tolerance_degrees: float
    district_boundary_tolerance_degrees: float
    city_limits_boundary_tolerance_degrees: float
    network_timeout_seconds: float
    network_max_retries: int
    network_retry_backoff_seconds: float
    network_page_size: int
    raw: dict[str, Any] = field(repr=False)

    def route_category(self, hsys_code: str | None) -> str:
        if not hsys_code:
            return self.route_classification.get("default", "county_local_other")
        return self.route_classification.get(
            hsys_code.strip().upper(),
            self.route_classification.get("default", "county_local_other"),
        )


def _parse_source(key: str, block: dict[str, Any]) -> SourceConfig:
    return SourceConfig(
        key=key,
        label=block["label"],
        service_url=block["service_url"],
        layer_id=int(block["layer_id"]),
        fields=dict(block.get("fields", {})),
        description_fields=list(block.get("description_fields", [])),
    )


def _parse_polygon_style(block: dict[str, Any]) -> PolygonStyleConfig:
    return PolygonStyleConfig(
        line_color=block["line_color"],
        line_width=float(block["line_width"]),
        fill=bool(block.get("fill", False)),
        fill_color=block.get("fill_color", block["line_color"]),
        fill_opacity=float(block.get("fill_opacity", 0.0)),
    )


def load_config(path: Path | str | None = None) -> Config:
    """Load and validate the YAML config. Raises on missing required keys."""
    config_path = Path(path) if path else DEFAULT_CONFIG_PATH
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    with config_path.open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)

    if not raw:
        raise ValueError(f"Config file is empty: {config_path}")

    try:
        sources = {key: _parse_source(key, block) for key, block in raw["sources"].items()}
        styles = raw["styles"]
        route_styles = {
            key: RouteStyleConfig(
                label=block["label"],
                line_color=block["line_color"],
                line_width=float(block["line_width"]),
                dashed=bool(block.get("dashed", False)),
            )
            for key, block in styles["routes"].items()
        }

        base_dir = config_path.parents[1]
        cache_dir = (base_dir / raw["cache"]["directory"]).resolve()
        output_dir = (base_dir / raw["output"]["directory"]).resolve()

        return Config(
            sources=sources,
            route_classification={k: v for k, v in raw["route_classification"].items()},
            district_style=_parse_polygon_style(styles["district_boundary"]),
            county_style=_parse_polygon_style(styles["county_boundary"]),
            city_limits_style=_parse_polygon_style(styles["city_limits_boundary"]),
            route_styles=route_styles,
            visibility_defaults=dict(raw["visibility_defaults"]),
            cache_dir=cache_dir,
            cache_max_age_hours=float(raw["cache"]["max_age_hours"]),
            output_dir=output_dir,
            master_kml_name=raw["output"]["master_kml_name"],
            single_file_kmz_name=raw["output"]["single_file_kmz_name"],
            simplification_enabled=bool(raw["simplification"]["enabled"]),
            simplification_tolerance_degrees=float(raw["simplification"]["tolerance_degrees"]),
            county_boundary_tolerance_degrees=float(
                raw["simplification"]["county_boundary_tolerance_degrees"]
            ),
            district_boundary_tolerance_degrees=float(
                raw["simplification"]["district_boundary_tolerance_degrees"]
            ),
            city_limits_boundary_tolerance_degrees=float(
                raw["simplification"]["city_limits_boundary_tolerance_degrees"]
            ),
            network_timeout_seconds=float(raw["network"]["timeout_seconds"]),
            network_max_retries=int(raw["network"]["max_retries"]),
            network_retry_backoff_seconds=float(raw["network"]["retry_backoff_seconds"]),
            network_page_size=int(raw["network"]["page_size"]),
            raw=raw,
        )
    except KeyError as exc:
        raise ValueError(f"Missing required config key: {exc}") from exc
