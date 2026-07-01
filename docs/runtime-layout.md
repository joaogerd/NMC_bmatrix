# Runtime layout

All mutable products remain below `CAMPAIGN_ROOT`:

```text
$CAMPAIGN_ROOT/
├── inputs/gfs/                  five GFS f000 files
├── wps/YYYYMMDDHH/              one FILE:* intermediate per init time
├── static/
│   ├── x1.10242.static.nc       validated mesh-level static product
│   └── .monan-jedi-workflow/    static submission and validation records
├── mpas_init/YYYYMMDDHH/
│   └── x1.10242.init.nc         one meteorological initial state per date
├── mpas_runs/YYYYMMDDT000000Z/
│   ├── f24/
│   └── f48/
├── campaign/
│   ├── nmc-campaign-*.json
│   ├── nmc-campaign-execution.json
│   └── bflow-manifest.tsv
└── bflow/
```

The package directory itself contains only versioned source, site-local
configuration and generated YAML/templates. It must never become a second
runtime root.

The static product is intentionally outside `mpas_init/YYYYMMDDHH`: it is not a
cycle product and must not be regenerated once per GFS date.
