# NMC MPAS B-matrix campaign — MPASWF integration

This repository defines one fixed MPAS forecast campaign for NMC pairs. It is a
thin campaign layer around **mpaswf** and the downstream BFLOW tooling.

```text
GFS f000 files
  -> WPS / ungrib
  -> MPAS dynamic initialization
  -> MPAS f024 and f048 forecasts
  -> restart + da_state products
  -> MPAS manifest
  -> BFLOW manifest
  -> BFLOW
```

`NMC_bmatrix` does not call `monan-jedi-workflow`, MPAS-JEDI, Obs2IODA, VBAL,
HDIAG, NICAS, DIRAC, or SO. The first four stages are produced only by
`mpaswf`; BFLOW is the downstream consumer.

## Fixed first campaign

The current configuration produces four daily NMC pairs:

| Valid time | f048 initialization | f024 initialization |
|---|---:|---:|
| 2026-06-22 00Z | 2026-06-20 00Z | 2026-06-21 00Z |
| 2026-06-23 00Z | 2026-06-21 00Z | 2026-06-22 00Z |
| 2026-06-24 00Z | 2026-06-22 00Z | 2026-06-23 00Z |
| 2026-06-25 00Z | 2026-06-23 00Z | 2026-06-24 00Z |

It therefore requires five GFS f000 files, five WPS products, five MPAS
initial states, and eight forecasts.

## Static-input prerequisite

The mesh-level CD-CT static product is a fixed external input in this first
version. `STATIC_DIR` must contain `x1.10242.static.nc`; `MESH_ROOT` must
provide the grid and 128-rank partition; `INVARIANT_FILE` must exist.

The package deliberately does not create the static product yet. This keeps the
first MPASWF integration restricted to the dynamic chain that must be proven:
GFS, WPS, MPAS initialization, and f024/f048 forecasts.

## Installation

Install `mpaswf` in the same Conda environment used on JACI. Version 0.1.1 or
newer is required because the forecast templates use the `mpas_run_duration`
placeholder.

```bash
conda activate mpaswf
cd /path/to/mpaswf
python -m pip install --no-deps -e .

cd /p/projetos/monan_das/$USER/work/NMC_bmatrix
cp config/site.env.example config/site.env
nano config/site.env
```

## Workflow

```bash
./scripts/run_campaign.sh bootstrap
./scripts/run_campaign.sh preflight

# Reuse valid GFS products or download absent products, then run WPS.
./scripts/run_campaign.sh prepare

# First render PBS scripts. Review them under CAMPAIGN_ROOT/init/.
./scripts/run_campaign.sh init

# Submit and wait only after review.
./scripts/run_campaign.sh init --submit --wait

# Render, then submit f024/f048 jobs.
./scripts/run_campaign.sh forecast
./scripts/run_campaign.sh forecast --submit --wait

# Validate MPAS products and write both manifests.
./scripts/run_campaign.sh manifest

# Consume the BFLOW manifest.
./scripts/run_campaign.sh bflow
```

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

- The first YAML remains small: paths, campaign dates, executables, fixed
  resource settings, and product names only.
- Dynamics, physics, mesh, time step, streams, and namelist details still come
  from the CD-CT reference templates rendered during `bootstrap`.
- The static interpolation stage will be added only after the dynamic campaign
  is validated end to end.
