"""Command-line entry point: `python -m txdot_overlay <command> ...`."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from txdot_overlay.commands import (
    audit_data,
    build_all,
    build_boundaries,
    build_county,
    build_district,
    inspect_sources,
    package_poc,
    validate_output,
)
from txdot_overlay.config import load_config
from txdot_overlay.logging_setup import configure_logging


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="txdot_overlay",
        description=(
            "Download, process, style, and export public TxDOT ArcGIS vector "
            "data as a Google Earth Pro overlay."
        ),
    )
    parser.add_argument(
        "--config", default=None, help="Path to config.yaml (default: config/config.yaml)"
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable debug logging")
    parser.add_argument(
        "--force-refresh",
        action="store_true",
        help="Bypass the disk cache and re-download from ArcGIS",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser(
        "inspect-sources", help="Report live ArcGIS metadata for every configured source"
    )
    subparsers.add_parser(
        "build-boundaries", help="Build master.kml with district boundaries and navigation"
    )

    district_parser = subparsers.add_parser(
        "build-district", help="Build detail KMZs for every county in one district"
    )
    district_parser.add_argument("--district", required=True, help='e.g. "Tyler"')

    county_parser = subparsers.add_parser(
        "build-county", help="Build the detail KMZ for one county"
    )
    county_parser.add_argument("--county", required=True, help='e.g. "Smith"')

    all_parser = subparsers.add_parser(
        "build-all",
        help="Build master.kml plus every county's detail KMZ (optionally scoped)",
    )
    all_parser.add_argument(
        "--district",
        action="append",
        dest="districts",
        help="Limit to this district; repeat to include more than one. Omit for statewide.",
    )
    all_parser.add_argument(
        "--single-file-kmz",
        action="store_true",
        help="Also emit one combined KMZ with everything inlined (no NetworkLinks)",
    )

    subparsers.add_parser("validate-output", help="Sanity-check generated KML/KMZ output")

    audit_parser = subparsers.add_parser(
        "audit-data",
        help="Report source/downloaded/duplicate/geometry/final counts for every source",
    )
    audit_parser.add_argument(
        "--district",
        action="append",
        dest="districts",
        help="Also audit roadway data for every county in this district; repeatable.",
    )
    audit_parser.add_argument(
        "--county",
        action="append",
        dest="counties",
        help="Also audit roadway data for this county; repeatable.",
    )
    audit_parser.add_argument(
        "--audit-output-dir",
        default=None,
        help="Where to write the JSON report (default: ./dist/audits)",
    )

    package_parser = subparsers.add_parser(
        "package-poc",
        help="Assemble a portable directory with master.kml + one district's county KMZs",
    )
    package_parser.add_argument("--district", required=True, help='e.g. "Tyler"')
    package_parser.add_argument(
        "--output-dir",
        default=None,
        help="Where to write the package (default: ./dist/poc_<district>)",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    configure_logging(verbose=args.verbose)
    config = load_config(args.config)

    if args.command == "inspect-sources":
        return inspect_sources.run(config)
    if args.command == "build-boundaries":
        return build_boundaries.run(config, force_refresh=args.force_refresh)
    if args.command == "build-district":
        return build_district.run(args.district, config, force_refresh=args.force_refresh)
    if args.command == "build-county":
        return build_county.run(args.county, config, force_refresh=args.force_refresh)
    if args.command == "build-all":
        return build_all.run(
            config,
            districts_filter=args.districts,
            single_file=args.single_file_kmz,
            force_refresh=args.force_refresh,
        )
    if args.command == "validate-output":
        return validate_output.run(config)
    if args.command == "audit-data":
        audit_output_dir = Path(args.audit_output_dir) if args.audit_output_dir else None
        return audit_data.run(
            config,
            districts_filter=args.districts,
            counties_filter=args.counties,
            audit_output_dir=audit_output_dir,
        )
    if args.command == "package-poc":
        output_dir = Path(args.output_dir) if args.output_dir else None
        return package_poc.run(
            args.district, config, output_dir=output_dir, force_refresh=args.force_refresh
        )

    parser.error(f"Unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
