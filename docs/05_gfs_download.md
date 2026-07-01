# Aquisição automática de GFS

`INPUT_MODE=download_gfs` configura `inputs.yaml` com `provider: gfs`,
`format: grib2` e uma URL por ciclo. `prepare-init` chama
`nmc-campaign-run --execute --fetch-inputs`; o workflow recupera somente
os produtos declarados que estejam ausentes, valida tamanho mínimo e então
prossegue a WPS/MPAS-init sem submissão PBS.

Se uma aquisição histórica falhar, não altere datas nem fabrique `FILE:*`.
Registre a falha, obtenha os mesmos GFS f000 de uma fonte de arquivo aprovada,
coloque-os em `RAW_GFS_ROOT` com os nomes esperados e mude para `INPUT_MODE=raw_grib`.
