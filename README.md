# NMC MPAS B-matrix campaign — MPASWF integration

This repository defines one fixed MPAS forecast campaign for NMC pairs. It is a
thin campaign layer around **mpaswf** and the downstream BFLOW tooling.

```text
GFS f000 files
  -> WPS / ungrib
  -> MPAS static interpolation
  -> MPAS dynamic initialization
  -> MPAS f024 and f048 forecasts
  -> restart + da_state products
  -> MPAS manifest
  -> BFLOW manifest
  -> BFLOW
```

`NMC_bmatrix` does not call `monan-jedi-workflow`, MPAS-JEDI, Obs2IODA, VBAL,
HDIAG, NICAS, DIRAC, or SO. `mpaswf` produces only the MPAS side; BFLOW is the
downstream consumer.

## Fixed first campaign

The current configuration produces four daily NMC pairs:

| Valid time | f048 initialization | f024 initialization |
|---|---:|---:|
| 2026-06-22 00Z | 2026-06-20 00Z | 2026-06-21 00Z |
| 2026-06-23 00Z | 2026-06-21 00Z | 2026-06-22 00Z |
| 2026-06-24 00Z | 2026-06-22 00Z | 2026-06-23 00Z |
| 2026-06-25 00Z | 2026-06-23 00Z | 2026-06-24 00Z |

It requires five GFS f000 files, five WPS products, one static MPAS product,
five dynamic MPAS initial states, and eight forecasts.

## Static interpolation is generated

The static CD-CT product is **not** an input. During the `init` phase, MPASWF
runs `mpas_init_atmosphere` once with:

```text
x1.10242.grid.nc + partition + WPS_GEOG
  -> ${CAMPAIGN_ROOT}/static/x1.10242.static.nc
```

Every date-dependent dynamic initialization then consumes that validated static
product together with its WPS `FILE:YYYY-MM-DD_HH` product:

```text
x1.10242.static.nc + FILE:YYYY-MM-DD_HH
  -> ${CAMPAIGN_ROOT}/init/YYYYMMDDHH/x1.10242.init.YYYY-MM-DD_HH.00.00.nc
```

If the static product already exists and validates, it is reused. It is never
listed as an external `STATIC_DIR` input.

## Installation

Install `mpaswf` 0.2.0 or newer in the same Conda environment used on JACI:

```bash
conda activate bmatrix
cd /path/to/mpaswf
python -m pip install --no-deps -e .

cd /p/projetos/monan_das/$USER/work/NMC_bmatrix
git pull --ff-only origin main
mv config/site.env config/site.env.before-mpaswf 2>/dev/null || true
cp config/site.env.example config/site.env
nano config/site.env
```

## Workflow

```bash
./scripts/run_campaign.sh bootstrap
./scripts/run_campaign.sh preflight

# Reuse/download GFS and generate all WPS FILE:* products.
./scripts/run_campaign.sh prepare

# The first call renders only the static interpolation PBS job.
./scripts/run_campaign.sh init

# Submit static interpolation. After the job completes, call init again.
./scripts/run_campaign.sh init --submit
qstat -u "$USER"
./scripts/run_campaign.sh init

# This now renders five dynamic initialization jobs.
./scripts/run_campaign.sh init --submit
qstat -u "$USER"

# Render and submit the f024/f048 forecast jobs.
./scripts/run_campaign.sh forecast
./scripts/run_campaign.sh forecast --submit
qstat -u "$USER"

# Validate all MPAS products and export both manifests.
./scripts/run_campaign.sh manifest

# Consume the BFLOW manifest.
./scripts/run_campaign.sh bflow
```

For a small smoke case, `init --submit --wait` can submit the static job, wait
for its validation, and then advance to the dynamic layer in the same command.
For the full JACI campaign, separate submissions are easier to inspect.

## Artifacts

`mpaswf` writes the neutral MPAS product manifest:

```text
${CAMPAIGN_ROOT}/products/mpas-forecast-manifest.tsv
```

It contains `valid_time`, f048/f024 `da_state` paths, and their restart paths.
`manifest` then derives the BFLOW-specific hand-off:

```text
${CAMPAIGN_ROOT}/products/bflow-manifest.tsv
```

The BFLOW manifest contains exactly:

```tsv
valid_time	f048	f024
2026-06-22T00:00:00Z	/path/to/f048/mpasout.nc	/path/to/f024/mpasout.nc
```

## Deliberate limitations

- The first YAML remains small: paths, campaign dates, executables, fixed PBS
  resources, and product names only.
- Dynamics, physics, mesh, time step, streams, and namelist details still come
  from CD-CT reference templates rendered during `bootstrap`.
- The static, dynamic-init, and forecast products have separate run directories
  and are reused only after conservative output validation.
