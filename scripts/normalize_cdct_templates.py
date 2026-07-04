#!/usr/bin/env python3
"""Normalize CD-CT partition prefixes after template rendering.

MPAS expects ``config_block_decomp_file_prefix`` to end at ``.part.`` and
appends the MPI rank count itself. The linked partition file retains the full
``.part.<N>`` filename.
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path


PATTERN = re.compile(
    r"(?m)^(\s*config_block_decomp_file_prefix\s*=\s*)'([^']+\.graph\.info\.part\.)\d+'"
)


def normalize(path: Path) -> None:
    """Replace a rank-specific decomposition prefix with the MPAS prefix form."""
    text = path.read_text(encoding="utf-8")
    updated, count = PATTERN.subn(r"\1'\2'", text)
    if count != 1:
        raise SystemExit(f"Expected one config_block_decomp_file_prefix in {path}; found {count}.")
    path.write_text(updated, encoding="utf-8")


def main() -> int:
    """Normalize static, dynamic-init, and forecast namelist templates."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--templates", type=Path, required=True)
    args = parser.parse_args()
    for name in (
        "namelist.init_atmosphere.static.in",
        "namelist.init_atmosphere.in",
        "namelist.atmosphere.in",
    ):
        normalize(args.templates / name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
