#!/usr/bin/env python3
"""Verify eight f024/f048 namelists against the generated 240-km template."""
from __future__ import annotations
import difflib, json, os, re
from datetime import datetime, timedelta, timezone
from pathlib import Path

PACKAGE=Path(__file__).resolve().parents[1]; ENV=PACKAGE/"config/site.env"; CASE=PACKAGE/"case"
VALIDS=[datetime(2026,6,22,tzinfo=timezone.utc)+timedelta(days=i) for i in range(4)]

def env_values():
    values={}
    for raw in ENV.read_text().splitlines():
        line=raw.strip()
        if not line or line.startswith("#"): continue
        k,v=line.split("=",1); values[k.strip()]=v.strip().strip('"').strip("'")
    for _ in range(16):
        changed=False; scope={**os.environ,**values}
        for k,v in list(values.items()):
            nv=v
            for n,r in scope.items(): nv=nv.replace("${"+n+"}",r).replace("$"+n,r)
            changed |= nv != v; values[k]=nv
        if not changed: break
    return values

def ctx(init, lead):
    valid=init+timedelta(hours=lead)
    return {"cycle_time":init.isoformat(timespec="seconds").replace("+00:00","Z"),"cycle_id":init.strftime("%Y%m%dT%H%M%SZ"),"cycle_yyyymmddhh":init.strftime("%Y%m%d%H"),"cycle_year":init.strftime("%Y"),"cycle_month":init.strftime("%m"),"cycle_day":init.strftime("%d"),"cycle_hour":init.strftime("%H"),"mpas_time":init.strftime("%Y-%m-%d_%H:%M:%S"),"mpas_file_time":init.strftime("%Y-%m-%d_%H.%M.%S"),"valid_time":valid.isoformat(timespec="seconds").replace("+00:00","Z"),"valid_id":valid.strftime("%Y%m%dT%H%M%SZ"),"mpas_valid_time":valid.strftime("%Y-%m-%d_%H:%M:%S"),"mpas_valid_file_time":valid.strftime("%Y-%m-%d_%H.%M.%S"),"mpas_run_duration":f"{lead//24}_{lead%24:02d}:00:00","lead_hours":str(lead)}

def main():
    env=env_values(); root=Path(env["CAMPAIGN_ROOT"]); template=(CASE/"templates/namelist.atmosphere.in").read_text(); streams_template=(CASE/"templates/streams.atmosphere.in").read_text()
    errors=[]; seen=0
    keys={(v-timedelta(hours=48),48) for v in VALIDS}|{(v-timedelta(hours=24),24) for v in VALIDS}
    for init,lead in sorted(keys):
        d=root/"mpas_runs"/init.strftime("%Y%m%dT%H%M%SZ")/f"f{lead}"
        n=d/"namelist.atmosphere"; s=d/"streams.atmosphere"; label=f"{init:%Y-%m-%dT%H:%M:%SZ} f{lead:03d}"
        if not n.exists() or not s.exists():
            errors.append(f"{label}: missing generated files in {d}"); continue
        c=ctx(init,lead); expected=template.format(**c); expected_s=streams_template.format(**c)
        actual=n.read_text(); actual_s=s.read_text()
        if actual!=expected:
            errors.append(f"{label}: namelist differs\n"+''.join(difflib.unified_diff(expected.splitlines(True),actual.splitlines(True),n=2))[:1500])
        if actual_s!=expected_s: errors.append(f"{label}: streams differs")
        for k,v in {"config_start_time":f"'{c['mpas_time']}'","config_run_duration":f"'{c['mpas_run_duration']}'","config_do_restart":".false.","config_block_decomp_file_prefix":f"'{env['MESH']}.graph.info.part.'","config_dt":env["CONFIG_DT"]}.items():
            m=re.search(rf"^\s*{re.escape(k)}\s*=\s*([^,\n]+)",actual,re.M)
            if not m or m.group(1).strip()!=v: errors.append(f"{label}: {k} mismatch")
        if not errors or not any(e.startswith(label) for e in errors): print(f"OK {label}: dt={env['CONFIG_DT']}"); seen+=1
    if errors:
        print("\nNAMELIST CONTRACT FAILED:\n"+"\n".join(errors)); return 1
    print(f"Namelist contract passed for {seen} forecasts."); return 0
if __name__=="__main__": raise SystemExit(main())
