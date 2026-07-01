#!/usr/bin/env python3
"""Preflight the two-stage MPAS NMC campaign without submitting PBS."""
from __future__ import annotations

import os
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError as exc:
    raise SystemExit("PyYAML is required. Activate the monanwf environment.") from exc

PACKAGE = Path(__file__).resolve().parents[1]
ENV = PACKAGE / "config/site.env"
CASE = PACKAGE / "case"
STATIC_CASE = CASE / "static"
DATES = [datetime(2026, 6, 20) + timedelta(days=i) for i in range(5)]
GENERATED = ("workflow.yaml", "inputs.yaml", "wps.yaml", "mpas_init.yaml", "mpas.yaml")


def parse_env(path: Path) -> dict[str, str]:
    if not path.is_file():
        raise SystemExit(f"Missing {path}.")
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise SystemExit(f"Invalid env line: {raw!r}")
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    for _ in range(16):
        changed = False
        scope = {**os.environ, **values}
        for key, value in list(values.items()):
            rendered = value
            for name, replacement in scope.items():
                rendered = rendered.replace("${" + name + "}", replacement).replace("$" + name, replacement)
            changed |= rendered != value
            values[key] = rendered
        if not changed:
            return values
    raise SystemExit("Could not resolve config/site.env variables.")


def under(value: object, expected: Path) -> bool:
    rendered = str(value)
    root = str(expected)
    return rendered == root or rendered.startswith(root + "/")


def assignment(text: str, key: str) -> str | None:
    match = re.search(rf"(?m)^\s*{re.escape(key)}\s*=\s*([^,\n]+)", text)
    return match.group(1).strip() if match else None


def require_assignment(errors: list[str], text: str, key: str, expected: str, label: str) -> None:
    found = assignment(text, key)
    if found != expected:
        errors.append(f"{label}: {key}={found!r}; expected {expected!r}")


def main() -> int:
    env = parse_env(ENV)
    root = Path(env.get("CAMPAIGN_ROOT", "")).expanduser().resolve()
    if not str(root) or str(root) == ".":
        raise SystemExit("CAMPAIGN_ROOT is missing or invalid.")
    mesh = env.get("MESH", "")
    nproc = env.get("NPROC", "")
    static_nproc = env.get("STATIC_NPROC", nproc)
    checks: list[tuple[str, Path, bool]] = []

    def add(label: str, path: str | Path, directory: bool = False) -> None:
        item = Path(path)
        checks.append((label, item, item.is_dir() if directory else item.is_file()))

    install = env.get("INSTALL_ROOT", "")
    mesh_root = env.get("MESH_ROOT", "")
    geog = Path(env.get("WPS_GEOG_ROOT", ""))
    add("JACI environment", env.get("JACI_ENV_SCRIPT", ""))
    add("mpas_init", f"{install}/bin/mpas_init_atmosphere")
    add("mpas_atmosphere", f"{install}/bin/mpas_atmosphere")
    add("240km namelist", env.get("FORECAST_NAMELIST_SOURCE", ""))
    add("240km streams", env.get("FORECAST_STREAMS_SOURCE", ""))
    add("init namelist", env.get("INIT_NAMELIST_SOURCE", ""))
    add("init streams", env.get("INIT_STREAMS_SOURCE", ""))
    add("invariant", env.get("INVARIANT_FILE", ""))
    add("mesh grid", f"{mesh_root}/mesh/{mesh}.grid.nc")
    add("mesh graph", f"{mesh_root}/graph/{mesh}.graph.info")
    add("dynamic mesh partition", f"{mesh_root}/partitions/{mesh}.graph.info.part.{nproc}")
    add("static mesh partition", f"{mesh_root}/partitions/{mesh}.graph.info.part.{static_nproc}")
    add("WPS_GEOG root", geog, True)
    add("GMTED2010 geotile index", geog / "topo_gmted2010_30s" / "index")

    mode = env.get("INPUT_MODE", "").lower()
    if mode in {"download_gfs", "raw_grib"}:
        wps = env.get("WPS_ROOT", "")
        add("WPS root", wps, True)
        add("ungrib", f"{wps}/ungrib.exe")
        add("link_grib", f"{wps}/link_grib.csh")
        add("Vtable.GFS", f"{wps}/ungrib/Variable_Tables/Vtable.GFS")
        if mode == "raw_grib":
            for date in DATES:
                add(f"GFS {date:%Y%m%d%H}", root / "inputs/gfs" / f"gfs.{date:%Y%m%d%H}.pgrb2.0p25.f000")
        else:
            print(f"PENDING remote GFS: prepare-init downloads to {root / 'inputs/gfs'}")
    elif mode == "prebuilt_wps":
        folder = Path(env.get("WPS_FILE_ROOT", ""))
        for date in DATES:
            add(f"WPS FILE {date:%Y-%m-%d_%H}", folder / f"FILE:{date:%Y-%m-%d_%H}")
    else:
        print(f"ERROR invalid INPUT_MODE={mode!r}")
        return 2

    errors: list[str] = []
    for label, path, ok in checks:
        print(("OK     " if ok else "MISSING") + f" {label}: {path}")
        if not ok:
            errors.append(f"missing {label}: {path}")

    generated_paths = [CASE / name for name in GENERATED] + [STATIC_CASE / "mpas_init.yaml"]
    for item in generated_paths:
        ok = item.is_file()
        print(("OK     " if ok else "MISSING") + f" generated: {item}")
        if not ok:
            errors.append(f"missing generated file: {item}")

    template_dir = CASE / "templates"
    template_names = (
        "namelist.init_atmosphere.static.in",
        "streams.init_atmosphere.static.in",
        "namelist.init_atmosphere.dynamic.in",
        "streams.init_atmosphere.dynamic.in",
        "namelist.atmosphere.in",
        "streams.atmosphere.in",
        "namelist.wps.in",
    )
    for name in template_names:
        path = template_dir / name
        ok = path.is_file()
        print(("OK     " if ok else "MISSING") + f" template: {path}")
        if not ok:
            errors.append(f"missing template: {path}")

    if not errors:
        docs: dict[str, Any] = {
            "workflow": yaml.safe_load((CASE / "workflow.yaml").read_text(encoding="utf-8")),
            "inputs": yaml.safe_load((CASE / "inputs.yaml").read_text(encoding="utf-8")),
            "wps": yaml.safe_load((CASE / "wps.yaml").read_text(encoding="utf-8")),
            "dynamic_init": yaml.safe_load((CASE / "mpas_init.yaml").read_text(encoding="utf-8")),
            "mpas": yaml.safe_load((CASE / "mpas.yaml").read_text(encoding="utf-8")),
            "static_init": yaml.safe_load((STATIC_CASE / "mpas_init.yaml").read_text(encoding="utf-8")),
        }
        workflow = docs["workflow"]["workflow"]
        dynamic = docs["dynamic_init"]["mpas_init"]
        static_doc = docs["static_init"]["mpas_init"]
        wps_doc = docs["wps"]["wps"]
        mpas_doc = docs["mpas"]["mpas"]
        sources = docs["inputs"]["inputs"]["sources"]
        source = next(iter(sources.values()))

        static_vars = static_doc.get("variables", {})
        dynamic_vars = dynamic.get("variables", {})
        static_run_dir = str(static_doc["run_dir"]).format(**static_vars)
        runtime_checks = [
            ("workflow output_dir", workflow["bmatrix"]["campaign"]["output_dir"], root / "campaign"),
            ("WPS output_root", wps_doc["variables"]["output_root"], root / "wps"),
            ("static run_dir", static_run_dir, root / "static"),
            ("dynamic init output_root", dynamic["variables"]["output_root"], root / "mpas_init"),
            ("forecast run_dir", mpas_doc["run_dir"], root / "mpas_runs"),
        ]
        if mode != "prebuilt_wps":
            runtime_checks += [
                ("input target", source["target"], root / "inputs/gfs"),
                ("WPS GRIB source", wps_doc["variables"]["grib_input"], root / "inputs/gfs"),
            ]
        for label, value, expected in runtime_checks:
            if not under(value, expected):
                errors.append(f"one-root violation {label}: {value} (expected below {expected})")

        dynamic_file_sources = [entry["source"] for entry in dynamic["links"] if entry.get("target", "").startswith("FILE:")]
        dynamic_static_sources = [str(entry["source"]).format(**dynamic_vars) for entry in dynamic["links"] if entry.get("target", "").endswith(".static.nc")]
        forecast_init_sources = [entry["source"] for entry in mpas_doc["links"] if entry.get("target") == "init.nc"]
        if mode != "prebuilt_wps" and (len(dynamic_file_sources) != 1 or not under(dynamic_file_sources[0], root / "wps")):
            errors.append(f"dynamic FILE source is not exactly one product below WPS root: {dynamic_file_sources}")
        if len(dynamic_static_sources) != 1 or not under(dynamic_static_sources[0], root / "static"):
            errors.append(f"dynamic static source is not exactly one product below static root: {dynamic_static_sources}")
        if len(forecast_init_sources) != 1 or not under(forecast_init_sources[0], root / "mpas_init"):
            errors.append(f"forecast init source is not exactly one product below init root: {forecast_init_sources}")
        if "f{lead_hours}" not in str(mpas_doc["run_dir"]):
            errors.append("mpas.run_dir lacks f{lead_hours}; f024/f048 would collide")
        if any(entry.get("target", "").startswith("FILE:") for entry in static_doc.get("links", [])):
            errors.append("static stage must not link a date-dependent WPS FILE product")

        static_nml = (template_dir / "namelist.init_atmosphere.static.in").read_text(encoding="utf-8")
        dynamic_nml = (template_dir / "namelist.init_atmosphere.dynamic.in").read_text(encoding="utf-8")
        static_streams = (template_dir / "streams.init_atmosphere.static.in").read_text(encoding="utf-8")
        dynamic_streams = (template_dir / "streams.init_atmosphere.dynamic.in").read_text(encoding="utf-8")
        require_assignment(errors, static_nml, "config_static_interp", ".true.", "static namelist")
        require_assignment(errors, static_nml, "config_vertical_grid", ".false.", "static namelist")
        require_assignment(errors, static_nml, "config_met_interp", ".false.", "static namelist")
        require_assignment(errors, static_nml, "config_block_decomp_file_prefix", f"'{mesh}.graph.info.part.'", "static namelist")
        require_assignment(errors, dynamic_nml, "config_static_interp", ".false.", "dynamic init namelist")
        require_assignment(errors, dynamic_nml, "config_vertical_grid", ".true.", "dynamic init namelist")
        require_assignment(errors, dynamic_nml, "config_met_interp", ".true.", "dynamic init namelist")
        require_assignment(errors, dynamic_nml, "config_met_prefix", "'FILE'", "dynamic init namelist")
        require_assignment(errors, dynamic_nml, "config_block_decomp_file_prefix", f"'{mesh}.graph.info.part.'", "dynamic init namelist")
        if f'filename_template="{mesh}.grid.nc"' not in static_streams:
            errors.append("static streams input must be the mesh grid")
        if f'filename_template="{mesh}.static.nc"' not in static_streams:
            errors.append("static streams output must be x1.<mesh>.static.nc")
        if f'filename_template="{mesh}.static.nc"' not in dynamic_streams:
            errors.append("dynamic init streams input must be x1.<mesh>.static.nc")
        if f'filename_template="{mesh}.init.nc"' not in dynamic_streams:
            errors.append("dynamic init streams output must be x1.<mesh>.init.nc")

    dt = int(env.get("CONFIG_DT", "0") or 0)
    if dt not in {1200, 1440}:
        errors.append(f"CONFIG_DT must be 1200 or 1440, found {dt}")
    if env.get("OUTPUT_INTERVAL") != "24:00:00":
        errors.append("OUTPUT_INTERVAL must be 24:00:00")
    if not env.get("FORECAST_NAMELIST_SOURCE", "").endswith("namelist.atmosphere_240km"):
        errors.append("FORECAST_NAMELIST_SOURCE must be namelist.atmosphere_240km")

    if errors:
        print("\nPreflight failed:")
        for error in errors:
            print(f"  - {error}")
        return 1
    print(f"\nPreflight passed. Runtime is rooted at: {root}")
    print(f"Static product required before NMC init: {root / 'static' / f'{mesh}.static.nc'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
