# Execution contract

## Static stage

`prepare-static` and `submit-static` reuse the workflow's generic
`mpas-init-*` commands, but from `case/static/`. That directory is intentionally
separate from the date-dependent `case/mpas_init.yaml` used by the NMC runner.

The static product path is deterministic:

```text
$CAMPAIGN_ROOT/static/x1.10242.static.nc
```

The static configuration receives only:

- `x1.10242.grid.nc`;
- `x1.10242.graph.info` and its selected MPI partition;
- `WPS_GEOG_ROOT` through `config_geog_data_path`;
- `mpas_init_atmosphere`.

It must not contain a `FILE:YYYY-MM-DD_HH` link, GFS data or WPS executables.

## Dynamic init stage

Each cycle-specific directory receives:

- the already validated static NetCDF file;
- the matching `FILE:YYYY-MM-DD_HH` output of WPS/UNGRIB;
- the selected dynamic partition;
- `mpas_init_atmosphere`.

It deliberately does **not** use the raw mesh grid as stream `input`; the
stream input is `x1.10242.static.nc`.

## Rebuild semantics

Changing `WPS_GEOG_ROOT`, mesh, partition count, static namelist values or
streams invalidates the static product. Remove only the static runtime directory
and re-run the static stage:

```bash
rm -rf "$CAMPAIGN_ROOT/static"
./scripts/run_campaign.sh bootstrap
./scripts/run_campaign.sh preflight
./scripts/run_campaign.sh prepare-static
./scripts/run_campaign.sh submit-static
# after PBS finishes
./scripts/run_campaign.sh validate-static
```

This does not remove GFS downloads or WPS intermediates.
