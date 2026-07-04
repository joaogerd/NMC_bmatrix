#!/usr/bin/env python3
"""Add CD-CT support-file links to the small MPASWF configuration.

The first renderer keeps the YAML schema small. This helper preserves the
important CD-CT detail that MPAS run directories also need support files from
``share/MPAS/core_atmosphere`` and the selected physics profile.
"""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import yaml

from configure_mpaswf import need, read_env


def regular_files(directory: Path, excluded: set[str]) -> dict[str, Path]:
    """Return regular files in one directory, excluding named template files."""
    if not directory.is_dir():
        raise SystemExit(f"Missing support directory: {directory}")
    return {
        item.name: item
        for item in directory.iterdir()
        if item.is_file() and item.name not in excluded
    }


def main() -> int:
    """Rewrite ``static.links`` with all fixed CD-CT assets for MPAS runs."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    args = parser.parse_args()

    values = read_env(args.env)
    if not args.config.is_file():
        raise SystemExit(f"Missing generated MPASWF configuration: {args.config}")

    mesh = need(values, "MESH")
    nproc = need(values, "NPROC")
    static_dir = Path(need(values, "STATIC_DIR"))
    mesh_root = Path(need(values, "MESH_ROOT"))
    install_root = Path(need(values, "INSTALL_ROOT"))
    physics_dir = Path(need(values, "TUTORIAL_PHYSICS_DIR"))
    invariant = Path(need(values, "INVARIANT_FILE"))

    # Physics-profile files intentionally override same-name generic MPAS files.
    support = regular_files(install_root / "share/MPAS/core_atmosphere", {"namelist.atmosphere", "streams.atmosphere"})
    support.update(
        regular_files(
            physics_dir,
            {
                "namelist.atmosphere_240km",
                "streams.atmosphere_240km",
                "namelist.atmosphere",
                "streams.atmosphere",
                invariant.name,
            },
        )
    )

    fixed: dict[str, Path] = {
        f"{mesh}.static.nc": static_dir / f"{mesh}.static.nc",
        f"{mesh}.grid.nc": mesh_root / "mesh" / f"{mesh}.grid.nc",
        f"{mesh}.graph.info": mesh_root / "graph" / f"{mesh}.graph.info",
        f"{mesh}.graph.info.part.{nproc}": mesh_root / "partitions" / f"{mesh}.graph.info.part.{nproc}",
        f"{mesh}.invariant.nc": invariant,
    }
    fixed.update(support)
    missing = [str(path) for path in fixed.values() if not path.is_file()]
    if missing:
        raise SystemExit("Missing CD-CT static/support inputs:\n" + "\n".join(sorted(missing)))

    payload: dict[str, Any] = yaml.safe_load(args.config.read_text(encoding="utf-8"))
    payload["static"] = {
        "links": [
            {"source": str(source), "target": target}
            for target, source in sorted(fixed.items())
        ]
    }
    args.config.write_text(yaml.safe_dump(payload, sort_keys=False, width=120), encoding="utf-8")
    print(args.config)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
