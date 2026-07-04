#!/usr/bin/env python3
"""Render a small ``mpaswf`` campaign from CD-CT reference inputs.

This script is intentionally a configuration renderer, not a scientific
workflow. It copies approved CD-CT namelist and streams inputs, applies only the
small substitutions needed by the fixed f024/f048 campaign, and writes the
single YAML file consumed by ``mpaswf``.

The mesh-level static MPAS product is an explicit input in this first version.
It must already exist in ``STATIC_DIR`` before the ``init`` phase is submitted.
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
    """Read a shell-style environment file with ``${NAME}`` expansion.

    Parameters
    ----------
    path : pathlib.Path
        Path to the local, untracked site configuration.

    Returns
    -------
    dict[str, str]
        Fully expanded configuration values.
    """
    if not path.is_file():
        raise SystemExit(f"Missing environment file: {path}")
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise SystemExit(f"Invalid environment line: {raw!r}")
        key, value = line.split("=", 1)
        key = key.strip()
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            raise SystemExit(f"Invalid environment variable name: {key!r}")
        values[key] = value.strip().strip('"').strip("'")

    # Resolve references deterministically without invoking a shell.
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
    raise SystemExit("Could not resolve variables in config/site.env")


def need(values: dict[str, str], key: str) -> str:
    """Return one mandatory environment value or stop with a focused error."""
    value = values.get(key, "").strip()
    if not value:
        raise SystemExit(f"Missing {key} in config/site.env")
    return value


def optional(values: dict[str, str], key: str, default: str) -> str:
    """Return an optional environment value with a stable default."""
    return values.get(key, default).strip() or default


def patch_assignment(text: str, key: str, value: str, *, required: bool = True) -> str:
    """Replace one Fortran namelist assignment while preserving its trailing comma."""
    pattern = re.compile(rf"(^\s*{re.escape(key)}\s*=\s*)[^,\n]*(,?.*)$", re.MULTILINE)
    updated, count = pattern.subn(rf"\g<1>{value}\2", text)
    if required and count != 1:
        raise SystemExit(f"Expected exactly one {key} assignment; found {count}.")
    if not required and count > 1:
        raise SystemExit(f"Expected at most one {key} assignment; found {count}.")
    return updated


def patch_namelist(source: Path, target: Path, overrides: dict[str, str], optional_keys: set[str] | None = None) -> None:
    """Copy a namelist and apply the explicit fixed-campaign overrides."""
    if not source.is_file():
        raise SystemExit(f"Missing template source: {source}")
    text = source.read_text(encoding="utf-8")
    optional_keys = optional_keys or set()
    for key, value in overrides.items():
        text = patch_assignment(text, key, value, required=key not in optional_keys)
    target.write_text(text, encoding="utf-8")


def find_or_create_stream(root: ET.Element, name: str, tag: str = "immutable_stream") -> ET.Element:
    """Return a named stream, creating it when the installed template omits it."""
    for child in root:
        if child.get("name") == name:
            return child
    return ET.SubElement(root, tag, {"name": name})


def write_xml(tree: ET.ElementTree, target: Path) -> None:
    """Write a readable XML streams file."""
    try:
        ET.indent(tree, space="  ")
    except AttributeError:
        pass
    target.write_text(ET.tostring(tree.getroot(), encoding="unicode") + "\n", encoding="utf-8")


def patch_init_streams(source: Path, target: Path, mesh: str) -> None:
    """Render streams for a dynamic init using a prebuilt static MPAS product."""
    tree = ET.parse(source)
    root = tree.getroot()
    input_stream = find_or_create_stream(root, "input")
    input_stream.attrib.update(
        {
            "type": "input",
            "filename_template": f"{mesh}.static.nc",
            "input_interval": "initial_only",
        }
    )
    output_stream = find_or_create_stream(root, "output")
    output_stream.attrib.update(
        {
            "type": "output",
            "filename_template": f"{mesh}.init.$Y-$M-$D_$h.$m.$s.nc",
            "packages": "initial_conds",
            "output_interval": "initial_only",
        }
    )
    write_xml(tree, target)


def patch_forecast_streams(source: Path, target: Path, mesh: str, output_interval: str) -> None:
    """Render streams that emit f024/f048 restart and JEDI ``da_state`` products."""
    tree = ET.parse(source)
    root = tree.getroot()
    invariant = find_or_create_stream(root, "invariant")
    invariant.attrib.update(
        {
            "type": "input",
            "filename_template": f"{mesh}.invariant.nc",
            "input_interval": "initial_only",
        }
    )
    initial = find_or_create_stream(root, "input")
    initial.attrib.update(
        {
            "type": "input",
            "filename_template": f"{mesh}.init.$Y-$M-$D_$h.$m.$s.nc",
            "input_interval": "initial_only",
        }
    )
    da_state = find_or_create_stream(root, "da_state")
    da_state.attrib.update(
        {
            "type": "output",
            "filename_template": "mpasout.$Y-$M-$D_$h.$m.$s.nc",
            "packages": "jedi_da",
            "output_interval": output_interval,
            "filename_interval": "output_interval",
            "clobber_mode": "overwrite",
        }
    )
    restart = find_or_create_stream(root, "restart", tag="stream")
    restart.attrib.update(
        {
            "type": "output",
            "filename_template": "restart.$Y-$M-$D_$h.$m.$s.nc",
            "output_interval": output_interval,
            "filename_interval": "output_interval",
            "clobber_mode": "overwrite",
        }
    )
    for name in ("output", "diagnostics"):
        for child in root:
            if child.get("name") == name:
                child.set("type", "none")
                child.set("output_interval", "none")
    write_xml(tree, target)


def create_templates(values: dict[str, str]) -> None:
    """Create the five templates consumed by the fixed first ``mpaswf`` release."""
    mesh = need(values, "MESH")
    geog_root = need(values, "WPS_GEOG_ROOT")
    config_dt = need(values, "CONFIG_DT")
    output_interval = need(values, "OUTPUT_INTERVAL")
    init_namelist = Path(need(values, "INIT_NAMELIST_SOURCE"))
    init_streams = Path(need(values, "INIT_STREAMS_SOURCE"))
    forecast_namelist = Path(need(values, "FORECAST_NAMELIST_SOURCE"))
    forecast_streams = Path(need(values, "FORECAST_STREAMS_SOURCE"))

    shutil.rmtree(TEMPLATE_DIR, ignore_errors=True)
    TEMPLATE_DIR.mkdir(parents=True, exist_ok=True)

    # One GFS f000 input is sufficient for the fixed single-time WPS contract.
    (TEMPLATE_DIR / "namelist.wps.in").write_text(
        "&share\n"
        " start_date = '{init_date_yyyy_mm_dd_hh}:00:00',\n"
        " end_date   = '{init_date_yyyy_mm_dd_hh}:00:00',\n"
        " interval_seconds = 21600,\n"
        " io_form_geogrid = 2,\n"
        "/\n\n"
        "&ungrib\n"
        " out_format = 'WPS',\n"
        " prefix = 'FILE',\n"
        "/\n",
        encoding="utf-8",
    )

    patch_namelist(
        init_namelist,
        TEMPLATE_DIR / "namelist.init_atmosphere.in",
        {
            "config_init_case": "7",
            "config_start_time": "'{init_date_yyyy_mm_dd_hh}:00:00'",
            "config_stop_time": "'{init_date_yyyy_mm_dd_hh}:00:00'",
            "config_geog_data_path": f"'{geog_root}'",
            "config_met_prefix": "'FILE'",
            "config_fg_interval": "86400",
            "config_static_interp": ".false.",
            "config_vertical_grid": ".true.",
            "config_met_interp": ".true.",
            "config_block_decomp_file_prefix": f"'{mesh}.graph.info.part.'",
        },
        optional_keys={"config_fg_interval"},
    )
    patch_init_streams(init_streams, TEMPLATE_DIR / "streams.init_atmosphere.in", mesh)

    patch_namelist(
        forecast_namelist,
        TEMPLATE_DIR / "namelist.atmosphere.in",
        {
            "config_start_time": "'{init_date_yyyy_mm_dd_hh}:00:00'",
            "config_run_duration": "'{mpas_run_duration}'",
            "config_do_restart": ".false.",
            "config_block_decomp_file_prefix": f"'{mesh}.graph.info.part.'",
            "config_dt": config_dt,
        },
    )
    patch_forecast_streams(forecast_streams, TEMPLATE_DIR / "streams.atmosphere.in", mesh, output_interval)


def make_config(values: dict[str, str]) -> dict[str, Any]:
    """Build the one small YAML configuration consumed by ``mpaswf``."""
    mesh = need(values, "MESH")
    nproc = need(values, "NPROC")
    campaign_root = need(values, "CAMPAIGN_ROOT")
    static_dir = need(values, "STATIC_DIR")
    mesh_root = need(values, "MESH_ROOT")
    wps_root = need(values, "WPS_ROOT")
    gfs_url = optional(values, "GFS_URL_TEMPLATE", "") or None

    return {
        "paths": {
            "work_dir": campaign_root,
            "static_dir": static_dir,
            "gfs_dir": f"{campaign_root}/inputs/gfs",
            "cdct_templates_dir": str(TEMPLATE_DIR),
        },
        "executables": {
            "wps_dir": wps_root,
            "mpas_init": f"{need(values, 'INSTALL_ROOT')}/bin/mpas_init_atmosphere",
            "mpas_atmosphere": f"{need(values, 'INSTALL_ROOT')}/bin/mpas_atmosphere",
        },
        "campaign": {
            "start_valid_time": need(values, "START_VALID_TIME"),
            "end_valid_time": need(values, "END_VALID_TIME"),
            "interval_hours": int(need(values, "VALID_INTERVAL_HOURS")),
            "leads_hours": [24, 48],
        },
        "gfs": {
            "file_template": "gfs.t{init_hour}z.pgrb2.0p25.f000",
            "url_template": gfs_url,
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
            "init_namelist": "namelist.init_atmosphere.in",
            "init_streams": "streams.init_atmosphere.in",
            "forecast_namelist": "namelist.atmosphere.in",
            "forecast_streams": "streams.atmosphere.in",
        },
        "static": {
            "links": [
                {"source": f"{static_dir}/{mesh}.static.nc", "target": f"{mesh}.static.nc"},
                {"source": f"{mesh_root}/{mesh}.grid.nc", "target": f"{mesh}.grid.nc"},
                {"source": f"{mesh_root}/{mesh}.graph.info.part.{nproc}", "target": f"{mesh}.graph.info.part.{nproc}"},
                {"source": need(values, "INVARIANT_FILE"), "target": f"{mesh}.invariant.nc"},
            ]
        },
        "execution": {"backend": "pbs"},
        "pbs": {
            "queue": need(values, "INIT_QUEUE"),
            "select": 1,
            "ncpus": int(nproc),
            "mpiprocs": int(nproc),
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
    """Render templates and the configuration file from ``config/site.env``."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env", type=Path, required=True, help="Path to config/site.env")
    args = parser.parse_args()
    values = read_env(args.env)
    create_templates(values)
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(yaml.safe_dump(make_config(values), sort_keys=False, width=120), encoding="utf-8")
    print(CONFIG_PATH)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
