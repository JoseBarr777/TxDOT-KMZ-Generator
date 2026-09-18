"""`validate-output`: sanity-check generated KML/KMZ files."""

from __future__ import annotations

from txdot_overlay.config import Config
from txdot_overlay.export.validate import validate_output
from txdot_overlay.logging_setup import get_logger

logger = get_logger(__name__)


def run(config: Config) -> int:
    report = validate_output(config)

    print(f"Errors:   {len(report.errors)}")
    print(f"Warnings: {len(report.warnings)}")
    for message in report.errors:
        print(f"  ERROR:   {message}")
    for message in report.warnings:
        print(f"  WARNING: {message}")

    return 0 if report.ok else 1
