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

Bootstrap renders the MPASWF YAML plus CD-CT-derived namelist and streams
templates for the fixed x1.10242 campaign.

The init phase owns two MPAS-init layers:

```text
mesh + partition + WPS geographic data -> x1.10242.static.nc
FILE:* + x1.10242.static.nc -> one dynamic init state per date
```

The static product is generated below the campaign runtime directory, not
provided as a prebuilt input, and reused only after validation.

## Manifest boundary

MPASWF writes an MPAS product manifest with restart and da_state paths.
The export script validates that manifest and writes the smaller BFLOW contract
consumed by `mpasnmc` and `mpasbflow`.
