#!/usr/bin/env python3
"""Validate static files and templates required by the MPASWF campaign."""
from __future__ import annotations

import argparse
import shutil
from pathlib import Path
from typing import Any

import yaml


def require_file(path: Path, label: str) -> None:
    """Stop when one required file is absent."""
    if not path.is_file():
        raise SystemExit(f"Missing {label}: {path}")


def require_directory(path: Path, label: str) -> None:
    """Stop when one required directory is absent."""
    if not path.is_dir():
        raise SystemExit(f"Missing {label}: {path}")


def main() -> int:
    """Validate all local prerequisites declared in ``mpaswf.yaml``."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--mpaswf", required=True)
    args = parser.parse_args()

    if not args.config.is_file():
        raise SystemExit(f"Missing mpaswf configuration: {args.config}")
    if "/" in args.mpaswf:
        require_file(Path(args.mpaswf), "mpaswf executable")
    elif shutil.which(args.mpaswf) is None:
        raise SystemExit(f"mpaswf command is not available in PATH: {args.mpaswf}")

    payload: dict[str, Any] = yaml.safe_load(args.config.read_text(encoding="utf-8"))
    templates_dir = Path(payload["paths"]["cdct_templates_dir"])
    require_directory(templates_dir, "CD-CT template directory")
    for name in (
        "namelist.wps.in",
        "namelist.init_atmosphere.in",
        "streams.init_atmosphere.in",
        "namelist.atmosphere.in",
        "streams.atmosphere.in",
    ):
        require_file(templates_dir / name, f"CD-CT template {name}")
    require_directory(Path(payload["executables"]["wps_dir"]), "WPS directory")
    require_file(Path(payload["executables"]["mpas_init"]), "mpas_init_atmosphere executable")
    require_file(Path(payload["executables"]["mpas_atmosphere"]), "mpas_atmosphere executable")
    for entry in payload.get("static", {}).get("links", []):
        require_file(Path(entry["source"]), f"static input {entry['target']}")

    print("[OK] mpaswf preflight completed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
