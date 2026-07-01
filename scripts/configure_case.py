#!/usr/bin/env python3
"""Materialize a coherent x1.10242 NMC campaign from ``config/site.env``.

This program only writes configuration and template files. It does not download
inputs, invoke WPS, run MPAS or submit PBS. The forecast namelist is deliberately
based on the configured 240-km profile and only five runtime fields are changed:
start time, run duration, restart mode, graph partition prefix and config_dt.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

try:
    import yaml
except ImportError as exc:
    raise SystemExit("PyYAML is required. Activate the monan-jedi-workflow environment.") from exc

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = PACKAGE_ROOT / "config" / "site.env"
CASE = PACKAGE_ROOT / "case"
VALID_TIMES = [datetime(2026, 6, 22, tzinfo=timezone.utc) + timedelta(days=index) for index in range(4)]
INIT_TIMES = [datetime(2026, 6, 20, tzinfo=timezone.utc) + timedelta(days=index) for index in range(5)]
RUNTIME_FORECAST_KEYS = (
    "config_start_time",
    "config_run_duration",
    "config_do_restart",
    "config_block_decomp_file_prefix",
    "config_dt",
)


def read_env(path: Path) -> dict[str, str]:
    if not path.is_file():
        raise SystemExit(f"Missing environment file: {path}")
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise SystemExit(f"Invalid line in {path}: {raw!r}")
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            raise SystemExit(f"Invalid environment key: {key!r}")
        values[key] = value
    for _ in range(12):
        changed = False
        merged = {**os.environ, **values}
        for key, value in list(values.items()):
            rendered = os.path.expandvars(value)
            for name, replacement in merged.items():
                rendered = rendered.replace("${" + name + "}", replacement).replace("$" + name, replacement)
            if rendered != value:
                values[key] = rendered
                changed = True
        if not changed:
            break
    return values


def required(env: dict[str, str], name: str) -> str:
    value = env.get(name, "").strip()
    if not value:
        raise SystemExit(f"Missing required setting {name} in {ENV_PATH}")
    return value


def path(env: dict[str, str], name: str) -> Path:
    return Path(required(env, name)).expanduser()


def sha256(path_: Path) -> str:
    digest = hashlib.sha256()
    with path_.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def dump_yaml(path_: Path, value: dict[str, Any]) -> None:
    path_.parent.mkdir(parents=True, exist_ok=True)
    path_.write_text(yaml.safe_dump(value, sort_keys=False, allow_unicode=True, width=120), encoding="utf-8")


def copy_template(source: Path, target: Path) -> None:
    if not source.is_file():
        raise SystemExit(f"Required template source is missing: {source}")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)


def replace_required_assignment(text: str, key: str, value: str) -> str:
    pattern = re.compile(rf"(^\s*{re.escape(key)}\s*=\s*)[^,\n]*(,?.*)$", re.MULTILINE)
    replacement = rf"\g<1>{value}\2"
    updated, count = pattern.subn(replacement, text)
    if count != 1:
        raise SystemExit(
            f"The selected 240-km namelist must define exactly one {key}; found {count}. "
            "Do not use a generic core_atmosphere namelist for this campaign."
        )
    return updated


def patch_forecast_namelist(source: Path, target: Path, mesh: str, dt: int) -> dict[str, str]:
    text = source.read_text(encoding="utf-8")
    replacements = {
        "config_start_time": "'{mpas_time}'",
        "config_run_duration": "'{mpas_run_duration}'",
        "config_do_restart": ".false.",
        "config_block_decomp_file_prefix": f"'{mesh}.graph.info.part.'",
        "config_dt": str(dt),
    }
    for key, value in replacements.items():
        text = replace_required_assignment(text, key, value)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    return replacements


def find_stream(root: ET.Element, name: str) -> ET.Element | None:
    return next((child for child in root if child.get("name") == name), None)


def ensure_stream(root: ET.Element, name: str, tag: str = "stream") -> ET.Element:
    found = find_stream(root, name)
    return found if found is not None else ET.SubElement(root, tag, {"name": name})


def patch_atmosphere_streams(source: Path, target: Path, mesh: str, interval: str) -> None:
    tree = ET.parse(source)
    root = tree.getroot()
    invariant = ensure_stream(root, "invariant", "immutable_stream")
    invariant.attrib.update({"type": "input", "filename_template": f"{mesh}.invariant.nc", "input_interval": "initial_only"})
    input_stream = ensure_stream(root, "input", "immutable_stream")
    input_stream.attrib.update({"type": "input", "filename_template": "init.nc", "input_interval": "initial_only"})
    da = ensure_stream(root, "da_state", "immutable_stream")
    da.attrib.update({
        "type": "output", "precision": da.get("precision", "single"),
        "io_type": da.get("io_type", "pnetcdf,cdf5"),
        "filename_template": "mpasout.$Y-$M-$D_$h.$m.$s.nc", "packages": "jedi_da",
        "output_interval": interval, "filename_interval": "output_interval", "clobber_mode": "overwrite",
    })
    restart = ensure_stream(root, "restart")
    restart.attrib.update({
        "type": "output", "filename_template": "restart.$Y-$M-$D_$h.$m.$s.nc",
        "filename_interval": "output_interval", "output_interval": interval, "clobber_mode": "overwrite",
    })
    for name in ("output", "diagnostics"):
        stream = find_stream(root, name)
        if stream is not None:
            stream.set("type", "none")
            stream.set("output_interval", "none")
    target.parent.mkdir(parents=True, exist_ok=True)
    tree.write(target, encoding="unicode")


def patch_init_streams(source: Path, target: Path) -> None:
    tree = ET.parse(source)
    root = tree.getroot()
    candidates = [child for child in root if child.tag == "immutable_stream"]
    patched = False
    for child in candidates:
        filename = child.get("filename_template", "")
        if child.get("name") == "input" or filename.startswith("FILE"):
            child.set("filename_template", "FILE:{cycle_year}-{cycle_month}-{cycle_day}_{cycle_hour}")
            child.set("input_interval", "initial_only")
            patched = True
    if not patched:
        ET.SubElement(root, "immutable_stream", {
            "name": "input", "type": "input",
            "filename_template": "FILE:{cycle_year}-{cycle_month}-{cycle_day}_{cycle_hour}",
            "input_interval": "initial_only",
        })
    target.parent.mkdir(parents=True, exist_ok=True)
    tree.write(target, encoding="unicode")


def files_in(directory: Path, excluded: set[str]) -> list[Path]:
    if not directory.is_dir():
        raise SystemExit(f"Required directory is missing: {directory}")
    return sorted((item for item in directory.iterdir() if item.is_file() and item.name not in excluded), key=lambda item: item.name)


def as_links(files: list[Path]) -> list[dict[str, str]]:
    return [{"source": str(item), "target": item.name} for item in files]


def write_wrapper(path_: Path, env_script: str, mpiexec: str, mode: str) -> None:
    if mode == "mpi":
        content = f"""#!/usr/bin/env bash
set -euo pipefail
source {env_script!r}
export OMP_NUM_THREADS=1
export FI_CXI_RX_MATCH_MODE=hybrid
export GFORTRAN_CONVERT_UNIT=big_endian:101-200
export F_UFMTENDIAN=big
ulimit -s unlimited || true
exec {mpiexec!r} "$@"
"""
    else:
        content = f"""#!/usr/bin/env bash
set -euo pipefail
source {env_script!r}
export OMP_NUM_THREADS=1
export FI_CXI_RX_MATCH_MODE=hybrid
export GFORTRAN_CONVERT_UNIT=big_endian:101-200
export F_UFMTENDIAN=big
ulimit -s unlimited || true
exec "$@"
"""
    path_.write_text(content, encoding="utf-8")
    path_.chmod(0o755)


def materialize(env: dict[str, str]) -> None:
    mode = required(env, "INPUT_MODE").lower()
    if mode not in {"prebuilt_wps", "raw_grib", "download_gfs"}:
        raise SystemExit("INPUT_MODE must be download_gfs, raw_grib or prebuilt_wps.")
    dt = int(required(env, "CONFIG_DT"))
    if dt not in {1200, 1440}:
        raise SystemExit("CONFIG_DT must be 1200 or 1440 for this x1.10242 package.")
    interval = required(env, "OUTPUT_INTERVAL")
    if interval != "24:00:00":
        raise SystemExit("OUTPUT_INTERVAL must remain 24:00:00 for this daily NMC campaign.")

    install, mesh_root, physics = path(env, "INSTALL_ROOT"), path(env, "MESH_ROOT"), path(env, "TUTORIAL_PHYSICS_DIR")
    mesh, nproc = required(env, "MESH"), int(required(env, "NPROC"))
    invariant, wps_output = path(env, "INVARIANT_FILE"), path(env, "WPS_OUTPUT_ROOT")
    init_root, run_root, campaign_root = path(env, "MPAS_INIT_ROOT"), path(env, "MPAS_RUN_ROOT"), path(env, "CAMPAIGN_ROOT")
    init_share, atmosphere_share = install / "share/MPAS/core_init_atmosphere", install / "share/MPAS/core_atmosphere"
    grid, graph = mesh_root / f"mesh/{mesh}.grid.nc", mesh_root / f"graph/{mesh}.graph.info"
    partition = mesh_root / f"partitions/{mesh}.graph.info.part.{nproc}"

    init_namelist_source = path(env, "INIT_NAMELIST_SOURCE")
    init_streams_source = path(env, "INIT_STREAMS_SOURCE")
    forecast_namelist_source = path(env, "FORECAST_NAMELIST_SOURCE")
    forecast_streams_source = path(env, "FORECAST_STREAMS_SOURCE")
    for label, item in {
        "init namelist": init_namelist_source,
        "init streams": init_streams_source,
        "forecast 240-km namelist": forecast_namelist_source,
        "forecast 240-km streams": forecast_streams_source,
    }.items():
        if not item.is_file():
            raise SystemExit(f"Required {label} source is missing: {item}")
    if forecast_namelist_source.parent != physics:
        raise SystemExit("FORECAST_NAMELIST_SOURCE must belong to TUTORIAL_PHYSICS_DIR so the profile and physics files remain coupled.")

    templates, inventory_dir, bin_dir = CASE / "templates", CASE / "inventory", PACKAGE_ROOT / "bin"
    templates.mkdir(parents=True, exist_ok=True)
    inventory_dir.mkdir(parents=True, exist_ok=True)

    # Init namelist is copied exactly.  Forecast namelist is strict and only
    # runtime geometry is altered; all physics/dynamics choices stay from 240 km.
    copy_template(init_namelist_source, templates / "namelist.init_atmosphere.in")
    patch_init_streams(init_streams_source, templates / "streams.init_atmosphere.in")
    overrides = patch_forecast_namelist(forecast_namelist_source, templates / "namelist.atmosphere.in", mesh, dt)
    patch_atmosphere_streams(forecast_streams_source, templates / "streams.atmosphere.in", mesh, interval)

    contract = {
        "schema_version": 1,
        "profile": "x1.10242_240km",
        "source": str(forecast_namelist_source),
        "source_sha256": sha256(forecast_namelist_source),
        "rendered_template": str(templates / "namelist.atmosphere.in"),
        "rendered_template_sha256": sha256(templates / "namelist.atmosphere.in"),
        "config_dt": dt,
        "output_interval": interval,
        "allowed_runtime_overrides": overrides,
        "preserved_from_profile": "All namelist fields other than allowed_runtime_overrides.",
        "rule": "Do not edit generated namelist.atmosphere files manually; regenerate from site.env and rerun verify-namelist.",
    }
    (inventory_dir / "forecast_namelist_contract.json").write_text(json.dumps(contract, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    write_wrapper(bin_dir / "mpiexec_with_jaci_env.sh", required(env, "JACI_ENV_SCRIPT"), required(env, "MPIEXEC"), "mpi")
    write_wrapper(bin_dir / "run_with_jaci_env.sh", required(env, "JACI_ENV_SCRIPT"), required(env, "MPIEXEC"), "plain")

    init_support = files_in(init_share, {"namelist.init_atmosphere", "streams.init_atmosphere"})
    atmosphere_support = files_in(atmosphere_share, {"namelist.atmosphere", "streams.atmosphere"})
    tutorial_support = files_in(physics, {
        "namelist.atmosphere_240km", "streams.atmosphere_240km", "namelist.atmosphere", "streams.atmosphere",
    })

    if mode in {"raw_grib", "download_gfs"}:
        input_name, use_wps = "gfs_grib2", "auto"
        raw_root = path(env, "RAW_GFS_ROOT")
        input_target = str(raw_root / "gfs.{cycle_yyyymmddhh}.pgrb2.0p25.f000")
        init_wps_file = str(wps_output / "{cycle_yyyymmddhh}/FILE:{cycle_year}-{cycle_month}-{cycle_day}_{cycle_hour}")
        input_spec: dict[str, Any] = {
            "provider": "gfs" if mode == "download_gfs" else "local",
            "target": input_target,
            "format": "grib2",
            "mesh": mesh,
            "min_bytes": int(required(env, "GFS_MIN_BYTES")),
        }
        if mode == "download_gfs":
            input_spec["url"] = required(env, "GFS_URL_TEMPLATE")
    else:
        input_name, use_wps = "prebuilt_wps_file", "never"
        file_root = path(env, "WPS_FILE_ROOT")
        input_target = str(file_root / "FILE:{cycle_year}-{cycle_month}-{cycle_day}_{cycle_hour}")
        init_wps_file = input_target
        input_spec = {"provider": "local", "target": input_target, "format": "wps_intermediate", "mesh": mesh, "min_bytes": 1}

    workflow = {"workflow": {
        "mode": "bmatrix", "mesh": mesh, "input_source": input_name, "use_wps": use_wps,
        "stages": {"mpas_init": True, "forecast": True, "assimilation": False, "bmatrix": True},
        "bmatrix": {"campaign": {
            "start_valid_time": "2026-06-22T00:00:00Z", "end_valid_time": "2026-06-25T00:00:00Z",
            "valid_interval_hours": 24, "minimum_pairs": 4, "output_dir": str(campaign_root),
            "forecasts": {"f024_hours": 24, "f048_hours": 48,
                          "products": {"restart": "restart.{mpas_valid_file_time}.nc", "bflow": "mpasout.{mpas_valid_file_time}.nc"}},
        }},
    }}
    inputs = {"inputs": {"sources": {input_name: input_spec}}}

    wps_root = path(env, "WPS_ROOT")
    wps = {"wps": {
        "variables": {
            "wps_root": str(wps_root), "ungrib": str(wps_root / "ungrib.exe"),
            "link_grib": str(wps_root / "link_grib.csh"), "vtable_gfs": str(wps_root / "ungrib/Variable_Tables/Vtable.GFS"),
            "grib_input": str(path(env, "RAW_GFS_ROOT") / "gfs.{cycle_yyyymmddhh}.pgrb2.0p25.f000"),
            "output_root": str(wps_output), "case_root": str(CASE),
        },
        "work_dir": "{output_root}/{cycle_yyyymmddhh}",
        "clean_patterns": ["GRIBFILE.*", "FILE:*", "PFILE:*", "Vtable", "namelist.wps", "ungrib.exe", "link_grib.csh"],
        "links": [{"source": "{ungrib}", "target": "ungrib.exe"}, {"source": "{link_grib}", "target": "link_grib.csh"}, {"source": "{vtable_gfs}", "target": "Vtable"}],
        "templates": [{"source": str(templates / "namelist.wps.in"), "target": "namelist.wps"}],
        "run": {"link_grib_argv": ["bash", str(bin_dir / "run_with_jaci_env.sh"), "./link_grib.csh", "{grib_input}"],
                "ungrib_argv": ["bash", str(bin_dir / "run_with_jaci_env.sh"), "./ungrib.exe"]},
        "validation": {"log": "logs/ungrib.stdout.log", "required_log_markers": [], "required_outputs": ["{work_dir}/FILE:{wps_time}"]},
    }}

    init_links = [
        {"source": str(install / "bin/mpas_init_atmosphere"), "target": "mpas_init_atmosphere"},
        {"source": str(grid), "target": f"{mesh}.grid.nc"}, {"source": str(graph), "target": f"{mesh}.graph.info"},
        {"source": str(partition), "target": f"{mesh}.graph.info.part.{nproc}"},
        {"source": init_wps_file, "target": "FILE:{cycle_year}-{cycle_month}-{cycle_day}_{cycle_hour}"}, *as_links(init_support),
    ]
    mpas_init = {"mpas_init": {
        "variables": {"install": str(install), "mesh": mesh, "nproc": str(nproc), "mesh_root": str(mesh_root), "wps_file": init_wps_file, "output_root": str(init_root)},
        "run_dir": "{output_root}/{cycle_yyyymmddhh}", "links": init_links,
        "templates": [{"source": str(templates / "namelist.init_atmosphere.in"), "target": "namelist.init_atmosphere"}, {"source": str(templates / "streams.init_atmosphere.in"), "target": "streams.init_atmosphere"}],
        "pbs": {"queue": required(env, "INIT_QUEUE"), "ncpus": nproc, "mpiprocs": nproc, "walltime": required(env, "INIT_WALLTIME"), "launcher": str(bin_dir / "mpiexec_with_jaci_env.sh"), "command": ["./mpas_init_atmosphere"],
                "environment": {"OMP_NUM_THREADS": "1", "FI_CXI_RX_MATCH_MODE": "hybrid", "GFORTRAN_CONVERT_UNIT": "big_endian:101-200", "F_UFMTENDIAN": "big"}},
        "validation": {"log": "log.init_atmosphere.0000.out", "required_log_markers": ["Critical error messages =            0", "Error messages =                     0"], "required_outputs": ["{run_dir}/{mesh}.init.{mpas_file_time}.nc"]},
    }}

    forecast_links = [
        {"source": str(install / "bin/mpas_atmosphere"), "target": "mpas_atmosphere"},
        {"source": str(init_root / "{cycle_yyyymmddhh}" / f"{mesh}.init.{{mpas_file_time}}.nc"), "target": "init.nc"},
        {"source": str(grid), "target": f"{mesh}.grid.nc"}, {"source": str(graph), "target": f"{mesh}.graph.info"},
        {"source": str(partition), "target": f"{mesh}.graph.info.part.{nproc}"}, {"source": str(invariant), "target": f"{mesh}.invariant.nc"},
        *as_links(atmosphere_support), *as_links(tutorial_support),
    ]
    mpas = {"mpas": {
        "lead_hours": 24, "run_dir": str(run_root / "{cycle_id}" / "f{lead_hours}"),
        "clean_patterns": ["mpasout.*.nc", "restart.*.nc", "history.*.nc", "diagnostics.*.nc"],
        "links": forecast_links,
        "templates": [{"source": str(templates / "namelist.atmosphere.in"), "target": "namelist.atmosphere"}, {"source": str(templates / "streams.atmosphere.in"), "target": "streams.atmosphere"}],
        "pbs": {"filename": "run_mpas.pbs", "job_name": "nmc_{cycle_yyyymmddhh}_f{lead_hours}", "queue": required(env, "FORECAST_QUEUE"), "select": 1, "ncpus": nproc, "mpiprocs": nproc, "walltime": required(env, "F048_WALLTIME"), "launcher": str(bin_dir / "mpiexec_with_jaci_env.sh"), "command": ["./mpas_atmosphere"],
                "environment": {"OMP_NUM_THREADS": "1", "FI_CXI_RX_MATCH_MODE": "hybrid", "GFORTRAN_CONVERT_UNIT": "big_endian:101-200", "F_UFMTENDIAN": "big"}},
        "validation": {"log": "log.atmosphere.0000.out", "required_log_markers": ["MPAS Atmosphere Model"], "required_outputs": ["restart.{mpas_valid_file_time}.nc", "mpasout.{mpas_valid_file_time}.nc"]},
    }}

    dump_yaml(CASE / "workflow.yaml", workflow)
    dump_yaml(CASE / "inputs.yaml", inputs)
    dump_yaml(CASE / "wps.yaml", wps)
    dump_yaml(CASE / "mpas_init.yaml", mpas_init)
    dump_yaml(CASE / "mpas.yaml", mpas)
    (templates / "namelist.wps.in").write_text("""&share
  wrf_core = 'ARW',
  max_dom = 1,
  start_date = '{cycle_year}-{cycle_month}-{cycle_day}_{cycle_hour}:00:00',
  end_date = '{cycle_year}-{cycle_month}-{cycle_day}_{cycle_hour}:00:00',
  interval_seconds = 10800,
  io_form_geogrid = 2,
/
&geogrid
/
&ungrib
  out_format = 'WPS',
  prefix = 'FILE',
/
&metgrid
/
""", encoding="utf-8")

    rows = ["kind\tcycle_or_valid\tf048_init\tf024_init\tinput"]
    for valid in VALID_TIMES:
        f048, f024 = valid - timedelta(hours=48), valid - timedelta(hours=24)
        rows.append(f"pair\t{valid:%Y-%m-%dT%H:%M:%SZ}\t{f048:%Y-%m-%dT%H:%M:%SZ}\t{f024:%Y-%m-%dT%H:%M:%SZ}\t")
    rows.append("")
    for init in INIT_TIMES:
        product = (path(env, "RAW_GFS_ROOT") / f"gfs.{init:%Y%m%d%H}.pgrb2.0p25.f000") if mode == "raw_grib" else (path(env, "WPS_FILE_ROOT") / f"FILE:{init:%Y-%m-%d_%H}")
        rows.append(f"input\t{init:%Y-%m-%dT%H:%M:%SZ}\t\t\t{product}")
    (inventory_dir / "campaign_inventory.tsv").write_text("\n".join(rows) + "\n", encoding="utf-8")

    print("Case materialized successfully:")
    print(f"  CASE={CASE}")
    print(f"  mode={mode}")
    print(f"  profile={forecast_namelist_source}")
    print(f"  config_dt={dt}")
    print("  namelist policy=240-km profile preserved; only runtime geometry overridden")
    print("Next: scripts/preflight.py, scripts/run_campaign.sh plan")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env", type=Path, default=ENV_PATH)
    args = parser.parse_args()
    materialize(read_env(args.env.resolve()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
