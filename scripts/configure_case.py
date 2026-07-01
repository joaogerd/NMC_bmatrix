#!/usr/bin/env python3
"""Generate a two-stage MPAS NMC campaign under one runtime root.

The real-data MPAS initial-condition path has two distinct products:

1. a mesh-level ``x1.<mesh>.static.nc`` generated once from ``WPS_GEOG``;
2. one ``x1.<mesh>.init.nc`` generated for every atmospheric initialization
   from that static product and the date-dependent WPS ``FILE:*`` input.

This generator deliberately mirrors that contract.  It never combines static
and meteorological interpolation in the same ``mpas_init_atmosphere`` run.
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
    raise SystemExit("PyYAML is required. Activate the monanwf environment.") from exc

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
CASE = PACKAGE_ROOT / "case"
STATIC_CASE = CASE / "static"
VALID_TIMES = [datetime(2026, 6, 22, tzinfo=timezone.utc) + timedelta(days=i) for i in range(4)]
INIT_TIMES = [datetime(2026, 6, 20, tzinfo=timezone.utc) + timedelta(days=i) for i in range(5)]
GENERATED = ("workflow.yaml", "inputs.yaml", "wps.yaml", "mpas_init.yaml", "mpas.yaml", "templates", "inventory", "static")


def read_env(path: Path) -> dict[str, str]:
    if not path.is_file():
        raise SystemExit(f"Missing {path}. Copy config/site.env.example to config/site.env and edit it.")
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise SystemExit(f"Invalid configuration line: {raw!r}")
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            raise SystemExit(f"Invalid configuration key: {key!r}")
        values[key] = value
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
    raise SystemExit("Could not resolve variables in config/site.env.")


def need(env: dict[str, str], name: str) -> str:
    value = env.get(name, "").strip()
    if not value:
        raise SystemExit(f"Missing {name} in config/site.env")
    return value


def optional(env: dict[str, str], name: str, default: str) -> str:
    return env.get(name, default).strip() or default


def as_path(env: dict[str, str], name: str) -> Path:
    return Path(need(env, name)).expanduser()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def dump_yaml(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=120), encoding="utf-8")


def clean_generated() -> None:
    CASE.mkdir(parents=True, exist_ok=True)
    for name in GENERATED:
        path = CASE / name
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink(missing_ok=True)


def files_in(directory: Path, excluded: set[str]) -> dict[str, Path]:
    if not directory.is_dir():
        raise SystemExit(f"Missing directory: {directory}")
    return {item.name: item for item in directory.iterdir() if item.is_file() and item.name not in excluded}


def links_from(mapping: dict[str, Path]) -> list[dict[str, str]]:
    return [{"source": str(path), "target": name} for name, path in sorted(mapping.items())]


def patch_assignment(text: str, key: str, value: str, *, required: bool = True) -> str:
    pattern = re.compile(rf"(^\s*{re.escape(key)}\s*=\s*)[^,\n]*(,?.*)$", re.MULTILINE)
    updated, count = pattern.subn(rf"\g<1>{value}\2", text)
    if required and count != 1:
        raise SystemExit(f"Expected exactly one {key} in namelist.init_atmosphere; found {count}.")
    if not required and count > 1:
        raise SystemExit(f"Expected at most one {key} in namelist.init_atmosphere; found {count}.")
    return updated


def patch_many(text: str, overrides: dict[str, str], *, optional_keys: set[str] | None = None) -> str:
    optional_keys = optional_keys or set()
    for key, value in overrides.items():
        text = patch_assignment(text, key, value, required=key not in optional_keys)
    return text


def find_stream(root: ET.Element, name: str) -> ET.Element | None:
    return next((child for child in root if child.get("name") == name), None)


def ensure_stream(root: ET.Element, name: str, tag: str = "immutable_stream") -> ET.Element:
    item = find_stream(root, name)
    return item if item is not None else ET.SubElement(root, tag, {"name": name})


def write_xml(tree: ET.ElementTree, target: Path) -> None:
    try:
        ET.indent(tree, space="  ")
    except AttributeError:
        pass
    target.write_text(ET.tostring(tree.getroot(), encoding="unicode") + "\n", encoding="utf-8")


def patch_static_streams(source: Path, target: Path, mesh: str) -> None:
    """Use grid as input and write the one reusable static product."""
    tree = ET.parse(source)
    root = tree.getroot()
    for item in root:
        template = item.get("filename_template")
        if template:
            item.set("filename_template", template.replace("x1.40962", mesh))
    inp = ensure_stream(root, "input")
    inp.attrib.update({"type": "input", "filename_template": f"{mesh}.grid.nc", "input_interval": "initial_only"})
    out = ensure_stream(root, "output")
    out.attrib.update({
        "type": "output",
        "filename_template": f"{mesh}.static.nc",
        "packages": "initial_conds",
        "output_interval": "initial_only",
    })
    write_xml(tree, target)


def patch_dynamic_init_streams(source: Path, target: Path, mesh: str) -> None:
    """Use the static product as input and write one date-local init product."""
    tree = ET.parse(source)
    root = tree.getroot()
    for item in root:
        template = item.get("filename_template")
        if template:
            item.set("filename_template", template.replace("x1.40962", mesh))
    inp = ensure_stream(root, "input")
    inp.attrib.update({"type": "input", "filename_template": f"{mesh}.static.nc", "input_interval": "initial_only"})
    out = ensure_stream(root, "output")
    out.attrib.update({
        "type": "output",
        "filename_template": f"{mesh}.init.nc",
        "packages": "initial_conds",
        "output_interval": "initial_only",
    })
    write_xml(tree, target)


def patch_forecast_streams(source: Path, target: Path, mesh: str, interval: str) -> None:
    tree = ET.parse(source)
    root = tree.getroot()
    invariant = ensure_stream(root, "invariant")
    invariant.attrib.update({"type": "input", "filename_template": f"{mesh}.invariant.nc", "input_interval": "initial_only"})
    inp = ensure_stream(root, "input")
    inp.attrib.update({"type": "input", "filename_template": "init.nc", "input_interval": "initial_only"})
    da = ensure_stream(root, "da_state")
    da.attrib.update({
        "type": "output", "precision": da.get("precision", "single"),
        "io_type": da.get("io_type", "pnetcdf,cdf5"),
        "filename_template": "mpasout.$Y-$M-$D_$h.$m.$s.nc",
        "packages": "jedi_da", "output_interval": interval,
        "filename_interval": "output_interval", "clobber_mode": "overwrite",
    })
    restart = ensure_stream(root, "restart", "stream")
    restart.attrib.update({
        "type": "output", "filename_template": "restart.$Y-$M-$D_$h.$m.$s.nc",
        "output_interval": interval, "filename_interval": "output_interval",
        "clobber_mode": "overwrite",
    })
    for name in ("output", "diagnostics"):
        item = find_stream(root, name)
        if item is not None:
            item.set("type", "none")
            item.set("output_interval", "none")
    write_xml(tree, target)


def patch_forecast_namelist(source: Path, target: Path, mesh: str, dt: int) -> dict[str, str]:
    text = source.read_text(encoding="utf-8")
    overrides = {
        "config_start_time": "'{mpas_time}'",
        "config_run_duration": "'{mpas_run_duration}'",
        "config_do_restart": ".false.",
        "config_block_decomp_file_prefix": f"'{mesh}.graph.info.part.'",
        "config_dt": str(dt),
    }
    target.write_text(patch_many(text, overrides), encoding="utf-8")
    return overrides


def patch_static_namelist(source: Path, target: Path, mesh: str, geog_root: Path, reference_time: str) -> dict[str, str]:
    """Render a CD-CT-equivalent static interpolation stage from the installed defaults."""
    text = source.read_text(encoding="utf-8")
    overrides = {
        "config_init_case": "7",
        "config_start_time": f"'{reference_time}'",
        "config_stop_time": f"'{reference_time}'",
        "config_nvertlevels": "1",
        "config_nsoillevels": "1",
        "config_nfglevels": "1",
        "config_nfgsoillevels": "1",
        "config_geog_data_path": f"'{geog_root}'",
        "config_met_prefix": "'GFS'",
        "config_static_interp": ".true.",
        "config_native_gwd_static": ".true.",
        "config_vertical_grid": ".false.",
        "config_met_interp": ".false.",
        "config_input_sst": ".false.",
        "config_frac_seaice": ".false.",
        "config_block_decomp_file_prefix": f"'{mesh}.graph.info.part.'",
    }
    optional_keys = {"config_native_gwd_static", "config_input_sst", "config_frac_seaice"}
    target.write_text(patch_many(text, overrides, optional_keys=optional_keys), encoding="utf-8")
    return overrides


def patch_dynamic_init_namelist(source: Path, target: Path, mesh: str, geog_root: Path) -> dict[str, str]:
    """Render date-dependent GFS initialization; static interpolation is disabled."""
    text = source.read_text(encoding="utf-8")
    overrides = {
        "config_init_case": "7",
        "config_start_time": "'{mpas_time}'",
        "config_stop_time": "'{mpas_time}'",
        "config_geog_data_path": f"'{geog_root}'",
        "config_met_prefix": "'FILE'",
        "config_fg_interval": "86400",
        "config_static_interp": ".false.",
        "config_native_gwd_static": ".false.",
        "config_native_gwd_gsl_static": ".false.",
        "config_vertical_grid": ".true.",
        "config_met_interp": ".true.",
        "config_input_sst": ".false.",
        "config_frac_seaice": ".true.",
        "config_block_decomp_file_prefix": f"'{mesh}.graph.info.part.'",
    }
    optional_keys = {"config_native_gwd_static", "config_native_gwd_gsl_static", "config_input_sst", "config_frac_seaice"}
    target.write_text(patch_many(text, overrides, optional_keys=optional_keys), encoding="utf-8")
    return overrides


def write_wrapper(path: Path, env_script: Path, mpiexec: str, mpi: bool) -> None:
    command = f"exec {mpiexec!r} \"$@\"" if mpi else 'exec "$@"'
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        "#!/usr/bin/env bash\nset -euo pipefail\n"
        f"source {str(env_script)!r}\n"
        "export OMP_NUM_THREADS=1\n"
        "export FI_CXI_RX_MATCH_MODE=hybrid\n"
        "export GFORTRAN_CONVERT_UNIT=big_endian:101-200\n"
        "export F_UFMTENDIAN=big\n"
        "ulimit -s unlimited || true\n"
        f"{command}\n",
        encoding="utf-8",
    )
    temporary.chmod(0o755)
    temporary.replace(path)


def _under(value: str, root: Path) -> bool:
    return value == str(root) or value.startswith(str(root) + "/")


def root_guard(generated: dict[Path, dict[str, Any]], campaign_root: Path, *, mode: str) -> None:
    """Validate only runtime paths that this package owns."""
    expected = campaign_root.resolve()
    docs = {path.name: data for path, data in generated.items()}
    static_doc = yaml.safe_load((STATIC_CASE / "mpas_init.yaml").read_text(encoding="utf-8"))
    problems: list[str] = []

    static_section = static_doc["mpas_init"]
    dynamic_section = docs["mpas_init.yaml"]["mpas_init"]
    static_vars = static_section.get("variables", {})
    dynamic_vars = dynamic_section.get("variables", {})
    static_run_dir = str(static_section["run_dir"]).format(**static_vars)
    checks = [
        ("workflow campaign output", docs["workflow.yaml"]["workflow"]["bmatrix"]["campaign"]["output_dir"], expected / "campaign"),
        ("WPS output", docs["wps.yaml"]["wps"]["variables"]["output_root"], expected / "wps"),
        ("static run", static_run_dir, expected / "static"),
        ("dynamic init output", dynamic_section["variables"]["output_root"], expected / "mpas_init"),
        ("forecast run", docs["mpas.yaml"]["mpas"]["run_dir"], expected / "mpas_runs"),
    ]
    if mode != "prebuilt_wps":
        source = next(iter(docs["inputs.yaml"]["inputs"]["sources"].values()))
        checks.extend([
            ("GFS input", source["target"], expected / "inputs" / "gfs"),
            ("WPS GRIB", docs["wps.yaml"]["wps"]["variables"]["grib_input"], expected / "inputs" / "gfs"),
        ])
    for label, value, root in checks:
        if not _under(str(value), root):
            problems.append(f"{label}: {value} (expected below {root})")

    dynamic = dynamic_section
    file_sources = [item["source"] for item in dynamic["links"] if item.get("target", "").startswith("FILE:")]
    if mode != "prebuilt_wps" and (len(file_sources) != 1 or not _under(file_sources[0], expected / "wps")):
        problems.append(f"dynamic FILE source: {file_sources}")
    static_sources = [str(item["source"]).format(**dynamic_vars) for item in dynamic["links"] if item.get("target", "").endswith(".static.nc")]
    if len(static_sources) != 1 or not _under(static_sources[0], expected / "static"):
        problems.append(f"dynamic static.nc source: {static_sources}")
    forecast_sources = [item["source"] for item in docs["mpas.yaml"]["mpas"]["links"] if item.get("target") == "init.nc"]
    if len(forecast_sources) != 1 or not _under(forecast_sources[0], expected / "mpas_init"):
        problems.append(f"forecast init.nc source: {forecast_sources}")
    if problems:
        raise SystemExit("Generated YAMLs violate the one-runtime-root contract:\n" + "\n".join(problems))


def materialize(env: dict[str, str]) -> None:
    mode = need(env, "INPUT_MODE").lower()
    if mode not in {"download_gfs", "raw_grib", "prebuilt_wps"}:
        raise SystemExit("INPUT_MODE must be download_gfs, raw_grib or prebuilt_wps.")
    dt = int(need(env, "CONFIG_DT"))
    if dt not in {1200, 1440}:
        raise SystemExit("CONFIG_DT must be 1200 or 1440 for x1.10242.")
    interval = need(env, "OUTPUT_INTERVAL")
    if interval != "24:00:00":
        raise SystemExit("OUTPUT_INTERVAL must be 24:00:00 for this daily NMC campaign.")

    campaign_root = as_path(env, "CAMPAIGN_ROOT").resolve()
    input_root = campaign_root / "inputs" / "gfs"
    wps_root_out = campaign_root / "wps"
    static_root = campaign_root / "static"
    init_root = campaign_root / "mpas_init"
    run_root = campaign_root / "mpas_runs"
    state_root = campaign_root / "campaign"

    install = as_path(env, "INSTALL_ROOT")
    mesh_root = as_path(env, "MESH_ROOT")
    physics = as_path(env, "TUTORIAL_PHYSICS_DIR")
    mesh = need(env, "MESH")
    nproc = int(need(env, "NPROC"))
    static_nproc = int(optional(env, "STATIC_NPROC", str(nproc)))
    invariant = as_path(env, "INVARIANT_FILE")
    env_script = as_path(env, "JACI_ENV_SCRIPT")
    wps_install = as_path(env, "WPS_ROOT")
    wps_geog = as_path(env, "WPS_GEOG_ROOT")
    init_namelist = as_path(env, "INIT_NAMELIST_SOURCE")
    init_streams = as_path(env, "INIT_STREAMS_SOURCE")
    forecast_namelist = as_path(env, "FORECAST_NAMELIST_SOURCE")
    forecast_streams = as_path(env, "FORECAST_STREAMS_SOURCE")
    static_reference_time = optional(env, "STATIC_REFERENCE_TIME", "2010-10-23_00:00:00")

    if forecast_namelist.name != "namelist.atmosphere_240km":
        raise SystemExit("FORECAST_NAMELIST_SOURCE must be namelist.atmosphere_240km.")
    if forecast_namelist.parent != physics:
        raise SystemExit("FORECAST_NAMELIST_SOURCE must live in TUTORIAL_PHYSICS_DIR.")
    required = [
        install / "bin/mpas_init_atmosphere", install / "bin/mpas_atmosphere",
        mesh_root / f"mesh/{mesh}.grid.nc", mesh_root / f"graph/{mesh}.graph.info",
        mesh_root / f"partitions/{mesh}.graph.info.part.{nproc}",
        mesh_root / f"partitions/{mesh}.graph.info.part.{static_nproc}",
        invariant, init_namelist, init_streams, forecast_namelist, forecast_streams,
        wps_geog, wps_geog / "topo_gmted2010_30s" / "index", env_script,
    ]
    if mode != "prebuilt_wps":
        required += [wps_install / "ungrib.exe", wps_install / "link_grib.csh", wps_install / "ungrib/Variable_Tables/Vtable.GFS"]
    missing = [str(item) for item in required if not item.exists()]
    if missing:
        raise SystemExit("Cannot bootstrap; required files missing:\n" + "\n".join(missing))

    clean_generated()
    templates = CASE / "templates"
    inventory = CASE / "inventory"
    templates.mkdir(parents=True)
    inventory.mkdir(parents=True)
    STATIC_CASE.mkdir(parents=True)
    bin_dir = PACKAGE_ROOT / "bin"
    write_wrapper(bin_dir / "run_with_jaci_env.sh", env_script, need(env, "MPIEXEC"), mpi=False)
    write_wrapper(bin_dir / "mpiexec_with_jaci_env.sh", env_script, need(env, "MPIEXEC"), mpi=True)

    static_overrides = patch_static_namelist(init_namelist, templates / "namelist.init_atmosphere.static.in", mesh, wps_geog, static_reference_time)
    dynamic_overrides = patch_dynamic_init_namelist(init_namelist, templates / "namelist.init_atmosphere.dynamic.in", mesh, wps_geog)
    patch_static_streams(init_streams, templates / "streams.init_atmosphere.static.in", mesh)
    patch_dynamic_init_streams(init_streams, templates / "streams.init_atmosphere.dynamic.in", mesh)
    forecast_overrides = patch_forecast_namelist(forecast_namelist, templates / "namelist.atmosphere.in", mesh, dt)
    patch_forecast_streams(forecast_streams, templates / "streams.atmosphere.in", mesh, interval)
    (templates / "namelist.wps.in").write_text(
        "&share\n"
        "  wrf_core = 'ARW',\n"
        "  max_dom = 1,\n"
        "  start_date = '{cycle_year}-{cycle_month}-{cycle_day}_{cycle_hour}:00:00',\n"
        "  end_date = '{cycle_year}-{cycle_month}-{cycle_day}_{cycle_hour}:00:00',\n"
        "  interval_seconds = 10800,\n"
        "  io_form_geogrid = 2,\n"
        "/\n&geogrid\n/\n&ungrib\n  out_format = 'WPS',\n  prefix = 'FILE',\n/\n&metgrid\n/\n",
        encoding="utf-8",
    )

    atm_share = install / "share/MPAS/core_atmosphere"
    support = files_in(atm_share, {"namelist.atmosphere", "streams.atmosphere"})
    support.update(files_in(physics, {
        "namelist.atmosphere_240km", "streams.atmosphere_240km",
        "namelist.atmosphere", "streams.atmosphere", f"{mesh}.invariant.nc",
    }))

    if mode in {"download_gfs", "raw_grib"}:
        input_name = "gfs_grib2"
        input_target = input_root / "gfs.{cycle_yyyymmddhh}.pgrb2.0p25.f000"
        input_spec: dict[str, Any] = {
            "provider": "gfs" if mode == "download_gfs" else "local",
            "target": str(input_target), "format": "grib2", "mesh": mesh,
            "min_bytes": int(need(env, "GFS_MIN_BYTES")),
        }
        if mode == "download_gfs":
            input_spec["url"] = need(env, "GFS_URL_TEMPLATE")
        use_wps = "auto"
        dynamic_wps_file = wps_root_out / "{cycle_yyyymmddhh}/FILE:{cycle_year}-{cycle_month}-{cycle_day}_{cycle_hour}"
    else:
        input_name = "prebuilt_wps_file"
        file_root = as_path(env, "WPS_FILE_ROOT")
        input_target = file_root / "FILE:{cycle_year}-{cycle_month}-{cycle_day}_{cycle_hour}"
        input_spec = {"provider": "local", "target": str(input_target), "format": "wps_intermediate", "mesh": mesh, "min_bytes": 1}
        use_wps = "never"
        dynamic_wps_file = input_target

    workflow = {"workflow": {
        "mode": "bmatrix", "mesh": mesh, "input_source": input_name, "use_wps": use_wps,
        "stages": {"mpas_init": True, "forecast": True, "assimilation": False, "bmatrix": True},
        "bmatrix": {"campaign": {
            "start_valid_time": "2026-06-22T00:00:00Z",
            "end_valid_time": "2026-06-25T00:00:00Z",
            "valid_interval_hours": 24, "minimum_pairs": 4,
            "output_dir": str(state_root),
            "forecasts": {
                "f024_hours": 24, "f048_hours": 48,
                "products": {"restart": "restart.{mpas_valid_file_time}.nc", "bflow": "mpasout.{mpas_valid_file_time}.nc"},
            },
        }},
    }}
    inputs = {"inputs": {"sources": {input_name: input_spec}}}
    wps = {"wps": {
        "variables": {
            "ungrib": str(wps_install / "ungrib.exe"),
            "link_grib": str(wps_install / "link_grib.csh"),
            "vtable_gfs": str(wps_install / "ungrib/Variable_Tables/Vtable.GFS"),
            "grib_input": str(input_root / "gfs.{cycle_yyyymmddhh}.pgrb2.0p25.f000"),
            "output_root": str(wps_root_out),
        },
        "work_dir": "{output_root}/{cycle_yyyymmddhh}",
        "clean_patterns": ["GRIBFILE.*", "FILE:*", "PFILE:*", "Vtable", "namelist.wps", "ungrib.exe", "link_grib.csh"],
        "links": [
            {"source": "{ungrib}", "target": "ungrib.exe"},
            {"source": "{link_grib}", "target": "link_grib.csh"},
            {"source": "{vtable_gfs}", "target": "Vtable"},
        ],
        "templates": [{"source": str(templates / "namelist.wps.in"), "target": "namelist.wps"}],
        "run": {
            "link_grib_argv": ["bash", str(bin_dir / "run_with_jaci_env.sh"), "./link_grib.csh", "{grib_input}"],
            "ungrib_argv": ["bash", str(bin_dir / "run_with_jaci_env.sh"), "./ungrib.exe"],
        },
        "validation": {"log": "logs/ungrib.stdout.log", "required_log_markers": [], "required_outputs": ["{work_dir}/FILE:{wps_time}"]},
    }}

    grid = mesh_root / f"mesh/{mesh}.grid.nc"
    graph = mesh_root / f"graph/{mesh}.graph.info"
    static_partition = mesh_root / f"partitions/{mesh}.graph.info.part.{static_nproc}"
    dynamic_partition = mesh_root / f"partitions/{mesh}.graph.info.part.{nproc}"

    mpas_static = {"mpas_init": {
        "variables": {"mesh": mesh, "nproc": str(static_nproc), "static_root": str(static_root)},
        "run_dir": "{static_root}",
        "clean_patterns": [f"{mesh}.static.nc", f"{mesh}.sfc_update.nc", f"{mesh}.ugwp_oro_data.nc", "log.init_atmosphere.*", "stdout.log", "stderr.log"],
        "links": [
            {"source": str(install / "bin/mpas_init_atmosphere"), "target": "mpas_init_atmosphere"},
            {"source": str(grid), "target": f"{mesh}.grid.nc"},
            {"source": str(graph), "target": f"{mesh}.graph.info"},
            {"source": str(static_partition), "target": f"{mesh}.graph.info.part.{static_nproc}"},
        ],
        "templates": [
            {"source": str(templates / "namelist.init_atmosphere.static.in"), "target": "namelist.init_atmosphere"},
            {"source": str(templates / "streams.init_atmosphere.static.in"), "target": "streams.init_atmosphere"},
        ],
        "pbs": {
            "filename": "run_mpas_static.pbs", "job_name": f"nmc_static_{mesh}",
            "queue": need(env, "STATIC_QUEUE"), "ncpus": static_nproc, "mpiprocs": static_nproc,
            "walltime": need(env, "STATIC_WALLTIME"), "launcher": str(bin_dir / "mpiexec_with_jaci_env.sh"),
            "command": ["./mpas_init_atmosphere"],
            "environment": {"OMP_NUM_THREADS": "1", "FI_CXI_RX_MATCH_MODE": "hybrid"},
        },
        "validation": {
            "log": "log.init_atmosphere.0000.out",
            "required_log_markers": ["Critical error messages =            0", "Error messages =                     0"],
            "required_outputs": ["{run_dir}/{mesh}.static.nc"],
        },
    }}

    dynamic_init = {"mpas_init": {
        "variables": {"mesh": mesh, "nproc": str(nproc), "output_root": str(init_root), "static_root": str(static_root)},
        "run_dir": "{output_root}/{cycle_yyyymmddhh}",
        "links": [
            {"source": str(install / "bin/mpas_init_atmosphere"), "target": "mpas_init_atmosphere"},
            {"source": "{static_root}/{mesh}.static.nc", "target": f"{mesh}.static.nc"},
            {"source": str(dynamic_partition), "target": f"{mesh}.graph.info.part.{nproc}"},
            {"source": str(dynamic_wps_file), "target": "FILE:{cycle_year}-{cycle_month}-{cycle_day}_{cycle_hour}"},
        ],
        "templates": [
            {"source": str(templates / "namelist.init_atmosphere.dynamic.in"), "target": "namelist.init_atmosphere"},
            {"source": str(templates / "streams.init_atmosphere.dynamic.in"), "target": "streams.init_atmosphere"},
        ],
        "pbs": {
            "filename": "run_mpas_init.pbs", "job_name": "nmc_init_{cycle_yyyymmddhh}",
            "queue": need(env, "INIT_QUEUE"), "ncpus": nproc, "mpiprocs": nproc,
            "walltime": need(env, "INIT_WALLTIME"), "launcher": str(bin_dir / "mpiexec_with_jaci_env.sh"),
            "command": ["./mpas_init_atmosphere"],
            "environment": {"OMP_NUM_THREADS": "1", "FI_CXI_RX_MATCH_MODE": "hybrid"},
        },
        "validation": {
            "log": "log.init_atmosphere.0000.out",
            "required_log_markers": ["Critical error messages =            0", "Error messages =                     0"],
            "required_outputs": ["{run_dir}/{mesh}.init.nc"],
        },
    }}

    forecast_links = [
        {"source": str(install / "bin/mpas_atmosphere"), "target": "mpas_atmosphere"},
        {"source": str(init_root / "{cycle_yyyymmddhh}" / f"{mesh}.init.nc"), "target": "init.nc"},
        {"source": str(grid), "target": f"{mesh}.grid.nc"},
        {"source": str(graph), "target": f"{mesh}.graph.info"},
        {"source": str(dynamic_partition), "target": f"{mesh}.graph.info.part.{nproc}"},
        {"source": str(invariant), "target": f"{mesh}.invariant.nc"},
        *links_from(support),
    ]
    mpas = {"mpas": {
        "lead_hours": 24,
        "run_dir": str(run_root / "{cycle_id}" / "f{lead_hours}"),
        "clean_patterns": ["mpasout.*.nc", "restart.*.nc", "history.*.nc", "diagnostics.*.nc"],
        "links": forecast_links,
        "templates": [
            {"source": str(templates / "namelist.atmosphere.in"), "target": "namelist.atmosphere"},
            {"source": str(templates / "streams.atmosphere.in"), "target": "streams.atmosphere"},
        ],
        "pbs": {
            "filename": "run_mpas.pbs", "job_name": "nmc_{cycle_yyyymmddhh}_f{lead_hours}",
            "queue": need(env, "FORECAST_QUEUE"), "select": 1, "ncpus": nproc, "mpiprocs": nproc,
            "walltime": need(env, "FORECAST_WALLTIME"), "launcher": str(bin_dir / "mpiexec_with_jaci_env.sh"),
            "command": ["./mpas_atmosphere"],
            "environment": {"OMP_NUM_THREADS": "1", "FI_CXI_RX_MATCH_MODE": "hybrid"},
        },
        "validation": {
            "log": "log.atmosphere.0000.out", "required_log_markers": ["MPAS Atmosphere Model"],
            "required_outputs": ["restart.{mpas_valid_file_time}.nc", "mpasout.{mpas_valid_file_time}.nc"],
        },
    }}

    outputs: dict[Path, dict[str, Any]] = {
        CASE / "workflow.yaml": workflow,
        CASE / "inputs.yaml": inputs,
        CASE / "wps.yaml": wps,
        CASE / "mpas_init.yaml": dynamic_init,
        CASE / "mpas.yaml": mpas,
    }
    for path, data in outputs.items():
        dump_yaml(path, data)
    dump_yaml(STATIC_CASE / "mpas_init.yaml", mpas_static)

    rows = ["kind\tcycle_or_valid\tf048_init\tf024_init\tinput"]
    for valid in VALID_TIMES:
        rows.append(f"pair\t{valid:%Y-%m-%dT%H:%M:%SZ}\t{valid-timedelta(hours=48):%Y-%m-%dT%H:%M:%SZ}\t{valid-timedelta(hours=24):%Y-%m-%dT%H:%M:%SZ}\t")
    rows += ["", f"static\t{static_reference_time}\t\t\t{static_root / f'{mesh}.static.nc'}"]
    for init in INIT_TIMES:
        product = input_root / f"gfs.{init:%Y%m%d%H}.pgrb2.0p25.f000" if mode != "prebuilt_wps" else as_path(env, "WPS_FILE_ROOT") / f"FILE:{init:%Y-%m-%d_%H}"
        rows.append(f"input\t{init:%Y-%m-%dT%H:%M:%SZ}\t\t\t{product}")
    (inventory / "campaign_inventory.tsv").write_text("\n".join(rows) + "\n", encoding="utf-8")

    contract = {
        "schema_version": 3,
        "profile": "x1.10242_240km",
        "forecast": {
            "source": str(forecast_namelist), "source_sha256": sha256(forecast_namelist),
            "rendered_template": str(templates / "namelist.atmosphere.in"),
            "rendered_template_sha256": sha256(templates / "namelist.atmosphere.in"),
            "config_dt": dt, "output_interval": interval,
            "allowed_runtime_overrides": forecast_overrides,
        },
        "mpas_init": {
            "static_template": str(templates / "namelist.init_atmosphere.static.in"),
            "dynamic_template": str(templates / "namelist.init_atmosphere.dynamic.in"),
            "static_overrides": static_overrides,
            "dynamic_overrides": dynamic_overrides,
            "static_product": str(static_root / f"{mesh}.static.nc"),
            "dynamic_product": f"{mesh}.init.nc",
        },
        "campaign_root": str(campaign_root),
    }
    (inventory / "nmc_runtime_contract.json").write_text(json.dumps(contract, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    root_guard(outputs, campaign_root, mode=mode)
    print("Case generated successfully.")
    print(f"CAMPAIGN_ROOT={campaign_root}")
    print("Generated roots: inputs/gfs, wps, static, mpas_init, mpas_runs, campaign, bflow")
    print(f"CONFIG_DT={dt}; profile={forecast_namelist.name}; static={static_root / f'{mesh}.static.nc'}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env", type=Path, default=PACKAGE_ROOT / "config/site.env")
    args = parser.parse_args()
    materialize(read_env(args.env))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
