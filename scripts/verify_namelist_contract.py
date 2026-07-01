#!/usr/bin/env python3
"""Verify that all prepared f024/f048 namelists exactly match the 240-km contract."""
from __future__ import annotations

import argparse
import difflib
import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[1]
ENV = PACKAGE / "config" / "site.env"
CASE = PACKAGE / "case"
VALID_TIMES = [datetime(2026, 6, 22, tzinfo=timezone.utc) + timedelta(days=index) for index in range(4)]


def env_values() -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in ENV.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    for _ in range(12):
        merged = {**os.environ, **values}
        changed = False
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


def context(init: datetime, lead: int) -> dict[str, str]:
    valid = init + timedelta(hours=lead)
    return {
        "cycle_time": init.isoformat(timespec="seconds").replace("+00:00", "Z"),
        "cycle_id": init.strftime("%Y%m%dT%H%M%SZ"),
        "cycle_yyyymmddhh": init.strftime("%Y%m%d%H"),
        "cycle_year": init.strftime("%Y"), "cycle_month": init.strftime("%m"), "cycle_day": init.strftime("%d"), "cycle_hour": init.strftime("%H"),
        "mpas_time": init.strftime("%Y-%m-%d_%H:%M:%S"), "mpas_file_time": init.strftime("%Y-%m-%d_%H.%M.%S"),
        "valid_time": valid.isoformat(timespec="seconds").replace("+00:00", "Z"),
        "valid_id": valid.strftime("%Y%m%dT%H%M%SZ"),
        "mpas_valid_time": valid.strftime("%Y-%m-%d_%H:%M:%S"), "mpas_valid_file_time": valid.strftime("%Y-%m-%d_%H.%M.%S"),
        "mpas_run_duration": f"{lead // 24}_{lead % 24:02d}:00:00", "lead_hours": str(lead),
    }


def check_assignment(text: str, key: str, expected: str) -> str | None:
    match = re.search(rf"^\s*{re.escape(key)}\s*=\s*([^,\n]+)", text, re.MULTILINE)
    if match is None:
        return f"missing {key}"
    actual = match.group(1).strip()
    return None if actual == expected else f"{key}={actual!r}, expected {expected!r}"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--allow-missing", action="store_true", help="report, but do not fail, run directories that have not been prepared yet")
    args = parser.parse_args()
    if not ENV.is_file():
        raise SystemExit(f"Missing {ENV}")
    env = env_values()
    template = CASE / "templates" / "namelist.atmosphere.in"
    streams_template = CASE / "templates" / "streams.atmosphere.in"
    contract_path = CASE / "inventory" / "forecast_namelist_contract.json"
    if not all(item.is_file() for item in (template, streams_template, contract_path)):
        raise SystemExit("Run ./scripts/run_campaign.sh bootstrap first.")
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    dt = int(env["CONFIG_DT"])
    if dt != int(contract["config_dt"]):
        raise SystemExit("site.env CONFIG_DT changed after bootstrap. Run bootstrap again before preparing forecasts.")
    run_root = Path(env["MPAS_RUN_ROOT"])
    template_text = template.read_text(encoding="utf-8")
    streams_text = streams_template.read_text(encoding="utf-8")
    failures: list[str] = []
    checked = 0
    keys = {(valid - timedelta(hours=48), 48) for valid in VALID_TIMES}
    keys.update((valid - timedelta(hours=24), 24) for valid in VALID_TIMES)
    for init, lead in sorted(keys):
        run_dir = run_root / init.strftime("%Y%m%dT%H%M%SZ") / f"f{lead}"
        namelist = run_dir / "namelist.atmosphere"
        streams = run_dir / "streams.atmosphere"
        label = f"{init:%Y-%m-%dT%H:%M:%SZ} f{lead:03d}"
        if not namelist.is_file() or not streams.is_file():
            message = f"{label}: missing prepared namelist/streams in {run_dir}"
            if args.allow_missing:
                print(f"PENDING {message}")
                continue
            failures.append(message)
            continue
        ctx = context(init, lead)
        expected_namelist = template_text.format(**ctx)
        expected_streams = streams_text.format(**ctx)
        actual_namelist = namelist.read_text(encoding="utf-8")
        actual_streams = streams.read_text(encoding="utf-8")
        expected_pairs = {
            "config_start_time": f"'{ctx['mpas_time']}'",
            "config_run_duration": f"'{ctx['mpas_run_duration']}'",
            "config_do_restart": ".false.",
            "config_block_decomp_file_prefix": f"'{env['MESH']}.graph.info.part.'",
            "config_dt": str(dt),
        }
        assignment_errors = [error for key, value in expected_pairs.items() if (error := check_assignment(actual_namelist, key, value))]
        if actual_namelist != expected_namelist:
            diff = "".join(difflib.unified_diff(expected_namelist.splitlines(True), actual_namelist.splitlines(True), fromfile="expected", tofile=str(namelist), n=2))
            failures.append(f"{label}: namelist differs from rendered 240-km contract\n{diff[:3000]}")
        if actual_streams != expected_streams:
            failures.append(f"{label}: streams.atmosphere differs from generated da_state/restart contract")
        if assignment_errors:
            failures.append(f"{label}: " + "; ".join(assignment_errors))
        if not assignment_errors and actual_namelist == expected_namelist and actual_streams == expected_streams:
            print(f"OK      {label}: dt={dt}, duration={ctx['mpas_run_duration']}, 240-km contract")
        checked += 1
    if failures:
        print("\nNAMELIST CONTRACT FAILED:")
        print("\n".join(failures))
        return 1
    print(f"\nNamelist contract passed for {checked} prepared forecast(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
