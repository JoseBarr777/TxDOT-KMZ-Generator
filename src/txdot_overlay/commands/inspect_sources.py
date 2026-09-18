"""`inspect-sources`: report live ArcGIS metadata for every configured source."""

from __future__ import annotations

from txdot_overlay.acquisition.inspect import format_inspection_report, inspect_source
from txdot_overlay.config import Config
from txdot_overlay.logging_setup import get_logger

logger = get_logger(__name__)


def run(config: Config) -> int:
    exit_code = 0
    for source in config.sources.values():
        try:
            inspection = inspect_source(
                source,
                timeout_seconds=config.network_timeout_seconds,
                max_retries=config.network_max_retries,
                retry_backoff_seconds=config.network_retry_backoff_seconds,
            )
        except Exception as exc:  # noqa: BLE001 - report and continue to other sources
            logger.error("Failed to inspect %s: %s", source.label, exc)
            exit_code = 1
            continue

        print(format_inspection_report(inspection))
        print()
        if inspection.missing_configured_fields:
            exit_code = 1
    return exit_code
