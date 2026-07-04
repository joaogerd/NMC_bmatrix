# MPASWF migration

## Removed dependency

The campaign no longer invokes `monan-jedi-workflow` or its NMC command family.
The old generated `workflow.yaml`, `inputs.yaml`, `wps.yaml`, `mpas_init.yaml`,
and `mpas.yaml` contracts are not used by the new runner.

## New interface

The only MPAS producer interface is:

```bash
mpaswf run --phase prepare  --config case/mpaswf.yaml
mpaswf run --phase init     --config case/mpaswf.yaml [--submit --wait]
mpaswf run --phase forecast --config case/mpaswf.yaml [--submit --wait]
mpaswf run --phase manifest --config case/mpaswf.yaml
```

`bootstrap` renders `case/mpaswf.yaml` plus the small set of CD-CT-derived
namelist and streams templates needed by the fixed x1.10242 campaign.

## Manifest boundary

`mpaswf` is intentionally neutral. It writes an MPAS product manifest with
restart and `da_state` paths. `scripts/export_bflow_manifest.py` validates that
manifest and writes the smaller BFLOW contract consumed by `mpasnmc` and
`mpasbflow`.
