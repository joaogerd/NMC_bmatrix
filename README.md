# NMC MPAS B-matrix campaign — 22–25 June 2026

This package produces four daily NMC pairs:

| valid time | f048 init | f024 init |
|---|---:|---:|
| 2026-06-22 00Z | 2026-06-20 00Z | 2026-06-21 00Z |
| 2026-06-23 00Z | 2026-06-21 00Z | 2026-06-22 00Z |
| 2026-06-24 00Z | 2026-06-22 00Z | 2026-06-23 00Z |
| 2026-06-25 00Z | 2026-06-23 00Z | 2026-06-24 00Z |

It uses five atmospheric initialization times, five GFS f000 files, five WPS
runs, five dynamic MPAS-init jobs and eight MPAS forecasts.

## Non-negotiable two-stage initialization contract

The campaign follows the CD-CT/MONAN real-data split:

```text
x1.10242.grid.nc + WPS_GEOG
        │
        └── one static interpolation run ──> static/x1.10242.static.nc
                                                │
GFS f000 ──> WPS FILE:YYYY-MM-DD_HH ───────────┼──> one dynamic init per date
                                                │       mpas_init/YYYYMMDDHH/x1.10242.init.nc
                                                ▼
                                         f024 / f048 forecasts
```

The static run has `config_static_interp = .true.` and no meteorological
interpolation. Every dynamic initialization has `config_static_interp = .false.`,
`config_vertical_grid = .true.`, `config_met_interp = .true.` and
`config_met_prefix = 'FILE'`. The dynamic stream reads the validated
`x1.10242.static.nc`, never the raw mesh grid.

The static stage is derived from the CD-CT `make_static.bash`/`make_initatmos.bash`
contract. It retains the installed MPAS 8.4 namelist fields and overrides only
stage-defining settings, rather than copying an older MONAN namelist wholesale.

## First setup

Do not reuse `config/site.env` from v2.0.x.

```bash
cd /p/projetos/monan_das/$USER/work
unzip -q /caminho/NMC_bmatrix_campaign_v2.1.0.zip
mv NMC_bmatrix_campaign_v2.1.0 NMC_bmatrix
cd NMC_bmatrix
cp config/site.env.example config/site.env
nano config/site.env
```

The key new setting is `WPS_GEOG_ROOT`. `preflight` requires the geographic
tile tree and specifically verifies `topo_gmted2010_30s/index`. The default is
the JACI CD-CT location; correct it only when your site uses a different mount.

## Execution order

```bash
./scripts/run_campaign.sh bootstrap
./scripts/run_campaign.sh preflight

# One time for x1.10242; this does not download GFS or run UNGRIB.
./scripts/run_campaign.sh prepare-static
./scripts/run_campaign.sh submit-static
qstat -u "$USER"
./scripts/run_campaign.sh validate-static

# Only after the static product validates.
./scripts/run_campaign.sh plan
./scripts/run_campaign.sh prepare-init
./scripts/run_campaign.sh submit-init
qstat -u "$USER"

./scripts/run_campaign.sh prepare-forecast
./scripts/run_campaign.sh submit-forecast
qstat -u "$USER"

./scripts/run_campaign.sh finalize
./scripts/run_campaign.sh bflow
```

`prepare-init`, `submit-init`, forecast preparation, forecast submission and
finalization all refuse to proceed when the static product is not validated.

## Safety properties

- `CAMPAIGN_ROOT` is the only mutable runtime root.
- `bootstrap` replaces only generated YAML/templates, never GFS, WPS products,
  static products, init products or forecasts under `CAMPAIGN_ROOT`.
- Static and dynamic MPAS init use separate case directories and separate PBS
  submissions.
- GFS/WPS are not consulted by the static stage.
- The forecast namelist begins with `namelist.atmosphere_240km`; only start
  time, duration, restart flag, partition prefix and `config_dt` are changed.
- `preflight` rejects a configuration that mixes mesh-grid input, static
  interpolation and date-dependent WPS input in the same init stage.
- `prepare-init` stays non-submitting; PBS remains explicit.

## Package commands

```text
bootstrap          generate static + dynamic contracts
preflight          check paths, WPS_GEOG and rendered two-stage contract
prepare-static     render the one static PBS job
submit-static      submit static interpolation
validate-static    validate static/x1.10242.static.nc
plan               write NMC plan
prepare-init       require static; fetch GFS/run WPS/prepare five dynamic inits
submit-init        submit five dynamic inits
prepare-forecast   prepare eight f024/f048 forecasts
submit-forecast    submit eight forecasts
finalize           validate forecasts and export bflow-manifest.tsv
bflow              run BFLOW
status             report campaign products
```
