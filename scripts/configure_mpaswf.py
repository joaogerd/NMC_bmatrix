#!/usr/bin/env python3
"""Render the fixed NMC MPASWF campaign from CD-CT reference files.

The generated ``case/mpaswf.yaml`` remains intentionally small. This renderer
owns the CD-CT-specific template transformation for one mesh, one physics
profile, one static interpolation product, and f024/f048 forecasts.
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

import yaml

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
CASE_DIR = PACKAGE_ROOT / "case"
TEMPLATE_DIR = CASE_DIR / "templates"
CONFIG_PATH = CASE_DIR / "mpaswf.yaml"


def read_env(path: Path) -> dict[str, str]:
    """Read a shell-style site file with deterministic variable expansion."""
    if not path.is_file():
        raise SystemExit(f"Missing environment file: {path}")
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise SystemExit(f"Invalid configuration line: {raw!r}")
        key, value = line.split("=", 1)
        key = key.strip()
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            raise SystemExit(f"Invalid variable name: {key!r}")
        values[key] = value.strip().strip('"').strip("'")
    for _ in range(16):
        changed = False
        scope = {**os.environ, **values}
        for key, value in list(values.items()):
            rendered = value
            for name, replacement in scope.items():
                rendered = rendered.replace("${" + name + "}", replacement).replace("$" + name, replacement)
            if rendered != value:
                values[key] = rendered
                changed = True
        if not changed:
            return values
    raise SystemExit("Could not resolve config/site.env variables")


def need(values: dict[str, str], key: str) -> str:
    """Return one mandatory site value."""
    item = values.get(key, "").strip()
    if not item:
        raise SystemExit(f"Missing {key} in config/site.env")
    return item


def optional(values: dict[str, str], key: str, default: str) -> str:
    """Return one optional site value with a default."""
    return values.get(key, default).strip() or default


def patch_assignment(text: str, key: str, replacement: str, *, required: bool = True) -> str:
    """Replace one Fortran namelist assignment without reformatting the file."""
    pattern = re.compile(rf"(^\s*{re.escape(key)}\s*=\s*)[^,\n]*(,?.*)$", re.MULTILINE)
    updated, count = pattern.subn(rf"\g<1>{replacement}\2", text)
    if required and count != 1:
        raise SystemExit(f"Expected exactly one {key} assignment; found {count}.")
    if not required and count > 1:
        raise SystemExit(f"Expected at most one {key} assignment; found {count}.")
    return updated


def patch_namelist(source: Path, target: Path, overrides: dict[str, str], optional_keys: set[str] | None = None) -> None:
    """Copy a CD-CT namelist and apply explicit stage-defining overrides."""
    if not source.is_file():
        raise SystemExit(f"Missing namelist source: {source}")
    text = source.read_text(encoding="utf-8")
    for key, replacement in overrides.items():
        text = patch_assignment(text, key, replacement, required=key not in (optional_keys or set()))
    target.write_text(text, encoding="utf-8")


def stream(root: ET.Element, name: str, tag: str = "immutable_stream") -> ET.Element:
    """Return one named stream, adding it when absent from the source XML."""
    for child in root:
        if child.get("name") == name:
            return child
    return ET.SubElement(root, tag, {"name": name})


def write_streams(tree: ET.ElementTree, target: Path) -> None:
    """Write a readable streams XML document."""
    try:
        ET.indent(tree, space="  ")
    except AttributeError:
        pass
    target.write_text(ET.tostring(tree.getroot(), encoding="unicode") + "\n", encoding="utf-8")


def patch_static_streams(source: Path, target: Path, mesh: str) -> None:
    """Render streams for one grid-to-static interpolation stage."""
    tree = ET.parse(source)
    root = tree.getroot()
    inp = stream(root, "input")
    inp.attrib.update({"type": "input", "filename_template": f"{mesh}.grid.nc", "input_interval": "initial_only"})
    out = stream(root, "output")
    out.attrib.update(
        {
            "type": "output",
            "filename_template": f"{mesh}.static.nc",
            "packages": "initial_conds",
            "output_interval": "initial_only",
        }
    )
    write_streams(tree, target)


def patch_dynamic_init_streams(source: Path, target: Path, mesh: str) -> None:
    """Render streams for one WPS-driven dynamic MPAS initialization."""
    tree = ET.parse(source)
    root = tree.getroot()
    inp = stream(root, "input")
    inp.attrib.update({"type": "input", "filename_template": f"{mesh}.static.nc", "input_interval": "initial_only"})
    out = stream(root, "output")
    out.attrib.update(
        {
            "type": "output",
            "filename_template": f"{mesh}.init.$Y-$M-$D_$h.$m.$s.nc",
            "packages": "initial_conds",
            "output_interval": "initial_only",
        }
    )
    write_streams(tree, target)


def patch_forecast_streams(source: Path, target: Path, mesh: str, interval: str) -> None:
    """Render streams that emit the restart and ``da_state`` NMC products."""
    tree = ET.parse(source)
    root = tree.getroot()
    invariant = stream(root, "invariant")
    invariant.attrib.update({"type": "input", "filename_template": f"{mesh}.invariant.nc", "input_interval": "initial_only"})
    initial = stream(root, "input")
    initial.attrib.update({"type": "input", "filename_template": f"{mesh}.init.$Y-$M-$D_$h.$m.$s.nc", "input_interval": "initial_only"})
    da_state = stream(root, "da_state")
    da_state.attrib.update(
        {
            "type": "output",
            "filename_template": "mpasout.$Y-$M-$D_$h.$m.$s.nc",
            "packages": "jedi_da",
            "output_interval": interval,
            "filename_interval": "output_interval",
            "clobber_mode": "overwrite",
        }
    )
    restart = stream(root, "restart", tag="stream")
    restart.attrib.update(
        {
            "type": "output",
            "filename_template": "restart.$Y-$M-$D_$h.$m.$s.nc",
            "output_interval": interval,
            "filename_interval": "output_interval",
            "clobber_mode": "overwrite",
        }
    )
    for name in ("output", "diagnostics"):
        for child in root:
            if child.get("name") == name:
                child.set("type", "none")
                child.set("output_interval", "none")
    write_streams(tree, target)


def files_in(directory: Path, excluded: set[str]) -> dict[str, Path]:
    """Collect regular support files from one CD-CT source directory."""
    if not directory.is_dir():
        raise SystemExit(f"Missing support directory: {directory}")
    return {item.name: item for item in directory.iterdir() if item.is_file() and item.name not in excluded}


def static_time(values: dict[str, str]) -> str:
    """Return the static reference time as a timezone-aware ISO timestamp."""
    raw = optional(values, "STATIC_REFERENCE_TIME", "2010-10-23_00:00:00").replace("_", "T")
    return raw if raw.endswith("Z") or "+" in raw[10:] else raw + "Z"


def create_templates(values: dict[str, str]) -> None:
    """Create all fixed CD-CT-derived templates used by MPASWF."""
    mesh = need(values, "MESH")
    geog = need(values, "WPS_GEOG_ROOT")
    nproc = need(values, "NPROC")
    dt = need(values, "CONFIG_DT")
    interval = need(values, "OUTPUT_INTERVAL")
    init_namelist = Path(need(values, "INIT_NAMELIST_SOURCE"))
    init_streams = Path(need(values, "INIT_STREAMS_SOURCE"))
    forecast_namelist = Path(need(values, "FORECAST_NAMELIST_SOURCE"))
    forecast_streams = Path(need(values, "FORECAST_STREAMS_SOURCE"))

    shutil.rmtree(TEMPLATE_DIR, ignore_errors=True)
    TEMPLATE_DIR.mkdir(parents=True, exist_ok=True)
    (TEMPLATE_DIR / "namelist.wps.in").write_text(
        "&share\n"
        "  wrf_core = 'ARW',\n"
        "  max_dom = 1,\n"
        "  start_date = '{init_date_yyyy_mm_dd_hh}:00:00',\n"
        "  end_date = '{init_date_yyyy_mm_dd_hh}:00:00',\n"
        "  interval_seconds = 10800,\n"
        "  io_form_geogrid = 2,\n"
        "/\n&geogrid\n/\n&ungrib\n  out_format = 'WPS',\n  prefix = 'FILE',\n/\n&metgrid\n/\n",
        encoding="utf-8",
    )

    patch_namelist(
        init_namelist,
        TEMPLATE_DIR / "namelist.init_atmosphere.static.in",
        {
            "config_init_case": "7",
            "config_start_time": "'{init_date_yyyy_mm_dd_hh}:00:00'",
            "config_stop_time": "'{init_date_yyyy_mm_dd_hh}:00:00'",
            "config_nvertlevels": "1",
            "config_nsoillevels": "1",
            "config_nfglevels": "1",
            "config_nfgsoillevels": "1",
            "config_geog_data_path": f"'{geog}'",
            "config_met_prefix": "'GFS'",
            "config_static_interp": ".true.",
            "config_native_gwd_static": ".true.",
            "config_vertical_grid": ".false.",
            "config_met_interp": ".false.",
            "config_input_sst": ".false.",
            "config_frac_seaice": ".false.",
            "config_block_decomp_file_prefix": f"'{mesh}.graph.info.part.{nproc}'",
        },
        optional_keys={"config_native_gwd_static", "config_input_sst", "config_frac_seaice"},
    )
    patch_static_streams(init_streams, TEMPLATE_DIR / "streams.init_atmosphere.static.in", mesh)

    patch_namelist(
        init_namelist,
        TEMPLATE_DIR / "namelist.init_atmosphere.in",
        {
            "config_init_case": "7",
            "config_start_time": "'{init_date_yyyy_mm_dd_hh}:00:00'",
            "config_stop_time": "'{init_date_yyyy_mm_dd_hh}:00:00'",
            "config_geog_data_path": f"'{geog}'",
            "config_met_prefix": "'FILE'",
            "config_fg_interval": "86400",
            "config_static_interp": ".false.",
            "config_vertical_grid": ".true.",
            "config_met_interp": ".true.",
            "config_block_decomp_file_prefix": f"'{mesh}.graph.info.part.{nproc}'",
        },
        optional_keys={"config_fg_interval"},
    )
    patch_dynamic_init_streams(init_streams, TEMPLATE_DIR / "streams.init_atmosphere.in", mesh)

    patch_namelist(
        forecast_namelist,
        TEMPLATE_DIR / "namelist.atmosphere.in",
        {
            "config_start_time": "'{init_date_yyyy_mm_dd_hh}:00:00'",
            "config_run_duration": "'{mpas_run_duration}'",
            "config_do_restart": ".false.",
            "config_block_decomp_file_prefix": f"'{mesh}.graph.info.part.{nproc}'",
            "config_dt": dt,
        },
    )
    patch_forecast_streams(forecast_streams, TEMPLATE_DIR / "streams.atmosphere.in", mesh, interval)


def make_config(values: dict[str, str]) -> dict[str, Any]:
    """Build the single YAML document consumed by MPASWF."""
    mesh = need(values, "MESH")
    nproc = need(values, "NPROC")
    root = need(values, "CAMPAIGN_ROOT")
    mesh_root = Path(need(values, "MESH_ROOT"))
    install = Path(need(values, "INSTALL_ROOT"))
    physics = Path(need(values, "TUTORIAL_PHYSICS_DIR"))
    invariant = Path(need(values, "INVARIANT_FILE"))

    support = files_in(install / "share/MPAS/core_atmosphere", {"namelist.atmosphere", "streams.atmosphere"})
    support.update(
        files_in(
            physics,
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
        f"{mesh}.grid.nc": mesh_root / "mesh" / f"{mesh}.grid.nc",
        f"{mesh}.graph.info": mesh_root / "graph" / f"{mesh}.graph.info",
        f"{mesh}.graph.info.part.{nproc}": mesh_root / "partitions" / f"{mesh}.graph.info.part.{nproc}",
        f"{mesh}.invariant.nc": invariant,
    }
    fixed.update(support)
    missing = [str(path) for path in fixed.values() if not path.is_file()]
    if missing:
        raise SystemExit("Missing fixed CD-CT assets:\n" + "\n".join(sorted(missing)))

    queue = optional(values, "QUEUE", optional(values, "INIT_QUEUE", "pesqmini"))
    static_queue = optional(values, "STATIC_QUEUE", queue)
    init_queue = optional(values, "INIT_QUEUE", queue)
    forecast_queue = optional(values, "FORECAST_QUEUE", queue)
    return {
        "paths": {
            "work_dir": root,
            "static_dir": f"{root}/static",
            "gfs_dir": f"{root}/inputs/gfs",
            "cdct_templates_dir": str(TEMPLATE_DIR),
        },
        "executables": {
            "wps_dir": need(values, "WPS_ROOT"),
            "mpas_init": str(install / "bin/mpas_init_atmosphere"),
            "mpas_atmosphere": str(install / "bin/mpas_atmosphere"),
        },
        "campaign": {
            "start_valid_time": need(values, "START_VALID_TIME"),
            "end_valid_time": need(values, "END_VALID_TIME"),
            "interval_hours": int(need(values, "VALID_INTERVAL_HOURS")),
            "leads_hours": [24, 48],
        },
        "gfs": {
            "file_template": "gfs.t{init_hour}z.pgrb2.0p25.f000",
            "url_template": optional(values, "GFS_URL_TEMPLATE", "") or None,
            "minimum_size_bytes": int(need(values, "GFS_MIN_BYTES")),
        },
        "wps": {
            "output_template": "FILE:{init_date_yyyy_mm_dd_hh}",
            "vtable": "{wps_dir}/ungrib/Variable_Tables/Vtable.GFS",
            "namelist_target": "namelist.wps",
            "link_grib_command": ["./link_grib.csh", "{gfs_file}"],
            "ungrib_command": ["./ungrib.exe"],
        },
        "products": {
            "init_state_template": f"{mesh}.init.{{init_date_yyyy_mm_dd_hh_mm_ss}}.nc",
            "restart_template": "restart.{valid_date_yyyy_mm_dd_hh_mm_ss}.nc",
            "da_state_template": "mpasout.{valid_date_yyyy_mm_dd_hh_mm_ss}.nc",
        },
        "templates": {
            "wps": "namelist.wps.in",
            "static_namelist": "namelist.init_atmosphere.static.in",
            "static_streams": "streams.init_atmosphere.static.in",
            "init_namelist": "namelist.init_atmosphere.in",
            "init_streams": "streams.init_atmosphere.in",
            "forecast_namelist": "namelist.atmosphere.in",
            "forecast_streams": "streams.atmosphere.in",
        },
        "static": {
            "reference_time": static_time(values),
            "product_template": f"{mesh}.static.nc",
            "links": [{"source": str(source), "target": target} for target, source in sorted(fixed.items())],
        },
        "execution": {"backend": "pbs"},
        "pbs": {
            "queue": queue,
            "queue_static": static_queue,
            "queue_init": init_queue,
            "queue_forecast": forecast_queue,
            "select": 1,
            "ncpus": int(nproc),
            "mpiprocs": int(nproc),
            "walltime_static": need(values, "STATIC_WALLTIME"),
            "walltime_init": need(values, "INIT_WALLTIME"),
            "walltime_forecast": need(values, "FORECAST_WALLTIME"),
            "launcher": [need(values, "MPIEXEC"), "-n", "{mpi_ranks}"],
            "qsub_command": ["qsub"],
            "qstat_command": ["qstat", "-f"],
            "poll_seconds": 30,
            "modules": [f"source {need(values, 'JACI_ENV_SCRIPT')}"],
            "environment": {
                "OMP_NUM_THREADS": "1",
                "FI_CXI_RX_MATCH_MODE": "hybrid",
                "GFORTRAN_CONVERT_UNIT": "big_endian:101-200",
                "F_UFMTENDIAN": "big",
            },
        },
        "validation": {"require_netcdf": False, "minimum_size_bytes": 1024},
    }


def main() -> int:
    """Render templates and ``case/mpaswf.yaml`` from ``config/site.env``."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env", type=Path, required=True)
    args = parser.parse_args()
    values = read_env(args.env)
    create_templates(values)
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(yaml.safe_dump(make_config(values), sort_keys=False, width=120), encoding="utf-8")
    print(CONFIG_PATH)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
