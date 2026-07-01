# Revisões necessárias

Este pacote usa comandos que ainda estão em branches de trabalho.

## Produtor MPAS

Repositório: `joaogerd/monan-jedi-workflow`

```text
branch: feature/mpas-workflow-foundation
PR:     #42
commit testado pela CI: 8b4a0562cd3d2a7794f36f9825fea8cb57e7a70e
```

A branch deve disponibilizar:

```text
monan-jedi-workflow nmc-campaign-plan
monan-jedi-workflow nmc-campaign-run
monan-jedi-workflow nmc-campaign-status
monan-jedi-workflow nmc-campaign-export-manifest
```

## Consumidor da matriz B

Repositório: `joaogerd/mpas-bmatrix-global`

```text
base:   refactor/bflow-python-pipeline
branch: feature/nmc-campaign-manifest
PR:     #27
```

A branch deve disponibilizar:

```text
mpasnmc validate-manifest
mpasbflow all --manifest ...
```

`./scripts/check_required_branches.sh` apenas informa a situação atual. Ele não
faz checkout automático nem altera seus repositórios.
