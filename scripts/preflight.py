#!/usr/bin/env python3
"""Check the concrete dependencies of the 22--25 June 2026 NMC campaign."""
from __future__ import annotations

import os
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[1]
ENV = PACKAGE / "config/site.env"
CASE = PACKAGE / "case"
DATES = [datetime(2026, 6, 20) + timedelta(days=index) for index in range(5)]

def env_values() -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in ENV.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        key, val = line.split("=", 1)
        values[key.strip()] = val.strip().strip('"').strip("'")
    for _ in range(5):
        merged = {**os.environ, **values}
        for key, val in list(values.items()):
            for name, repl in merged.items():
                val = val.replace("${" + name + "}", repl).replace("$" + name, repl)
            values[key] = val
    return values

def main() -> int:
    if not ENV.is_file():
        print(f"MISSING {ENV}")
        return 2
    e = env_values()
    mode = e.get("INPUT_MODE", "").lower()
    checks: list[tuple[str, Path, bool]] = []

    def add(label: str, value: str, directory: bool = False) -> None:
        p = Path(value)
        checks.append((label, p, p.is_dir() if directory else p.is_file()))

    install = e.get("INSTALL_ROOT", "")
    mesh_root = e.get("MESH_ROOT", "")
    mesh = e.get("MESH", "x1.10242")
    nproc = e.get("NPROC", "128")
    add("JACI environment script", e.get("JACI_ENV_SCRIPT", ""))
    add("mpas_init_atmosphere", f"{install}/bin/mpas_init_atmosphere")
    add("mpas_atmosphere", f"{install}/bin/mpas_atmosphere")
    add("core_init_atmosphere", f"{install}/share/MPAS/core_init_atmosphere", directory=True)
    add("core_atmosphere", f"{install}/share/MPAS/core_atmosphere", directory=True)
    add("mesh grid", f"{mesh_root}/mesh/{mesh}.grid.nc")
    add("mesh graph", f"{mesh_root}/graph/{mesh}.graph.info")
    add("mesh partition", f"{mesh_root}/partitions/{mesh}.graph.info.part.{nproc}")
    add("invariant", e.get("INVARIANT_FILE", ""))
    add("tutorial physics directory", e.get("TUTORIAL_PHYSICS_DIR", ""), directory=True)
    add("forecast 240-km namelist", e.get("FORECAST_NAMELIST_SOURCE", ""))
    add("forecast 240-km streams", e.get("FORECAST_STREAMS_SOURCE", ""))
    add("init namelist", e.get("INIT_NAMELIST_SOURCE", ""))
    add("init streams", e.get("INIT_STREAMS_SOURCE", ""))

    if mode in {"raw_grib", "download_gfs"}:
        wps = e.get("WPS_ROOT", "")
        add("WPS root", wps, directory=True)
        add("ungrib.exe", f"{wps}/ungrib.exe")
        add("link_grib.csh", f"{wps}/link_grib.csh")
        add("Vtable.GFS", f"{wps}/ungrib/Variable_Tables/Vtable.GFS")
        raw_root = Path(e.get("RAW_GFS_ROOT", ""))
        if mode == "raw_grib":
            for day in DATES:
                add(f"GFS f000 {day:%Y%m%d%H}", str(raw_root / f"gfs.{day:%Y%m%d%H}.pgrb2.0p25.f000"))
        else:
            url = e.get("GFS_URL_TEMPLATE", "")
            min_bytes = int(e.get("GFS_MIN_BYTES", "0") or 0)
            if not url.startswith("https://") or "{cycle_year}" not in url or "{cycle_hour}" not in url:
                print("ERROR  GFS_URL_TEMPLATE must be an HTTPS URL using cycle placeholders.")
                return 2
            if min_bytes < 1:
                print("ERROR  GFS_MIN_BYTES must be positive.")
                return 2
            print("PENDING remote GFS input: files will be acquired by prepare-init --fetch-inputs")
            print(f"        target directory: {raw_root}")
            print(f"        URL template: {url}")
    elif mode == "prebuilt_wps":
        file_root = Path(e.get("WPS_FILE_ROOT", ""))
        for day in DATES:
            add(f"WPS FILE {day:%Y-%m-%d_%H}", str(file_root / f"FILE:{day:%Y-%m-%d_%H}"))
    else:
        print("ERROR INPUT_MODE must be download_gfs, raw_grib or prebuilt_wps")
        return 2

    missing = 0
    for label, value, ok in checks:
        print(f"{'OK     ' if ok else 'MISSING'} {label}: {value}")
        if not ok:
            missing += 1

    generated = ["workflow.yaml", "inputs.yaml", "wps.yaml", "mpas_init.yaml", "mpas.yaml"]
    for name in generated:
        p = CASE / name
        print(f"{'OK     ' if p.is_file() else 'MISSING'} generated config: {p}")
        if not p.is_file():
            missing += 1
    mpas_yaml = CASE / "mpas.yaml"
    if mpas_yaml.is_file():
        text = mpas_yaml.read_text(encoding="utf-8")
        if "f{lead_hours}" not in text:
            print("MISSING lead-specific forecast directory in mpas.yaml")
            missing += 1

    dt = int(e.get("CONFIG_DT", "0") or 0)
    if dt not in {1200, 1440}:
        print(f"ERROR  CONFIG_DT={dt}: this package permits only 1200 or 1440 s for x1.10242.")
        missing += 1
    else:
        print(f"OK     CONFIG_DT={dt}: x1.10242 240-km campaign setting.")
    if e.get("OUTPUT_INTERVAL", "") != "24:00:00":
        print("ERROR  OUTPUT_INTERVAL must be 24:00:00 for daily f024/f048 NMC products.")
        missing += 1
    profile = e.get("FORECAST_NAMELIST_SOURCE", "")
    if not profile.endswith("namelist.atmosphere_240km"):
        print("ERROR  FORECAST_NAMELIST_SOURCE must be the explicit namelist.atmosphere_240km profile.")
        missing += 1

    if missing:
        print(f"\nPreflight failed: {missing} item(s) missing.")
        return 1
    print("\nPreflight passed. Safe next command: ./scripts/run_campaign.sh plan")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
