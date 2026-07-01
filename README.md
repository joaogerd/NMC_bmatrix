# Campanha NMC MPAS — 22 a 25 de junho de 2026

Este pacote prepara a campanha diária NMC que substitui o comando antigo
`mpascycle nmc-range`. Ele cria quatro pares NMC: f048–f024 válidos às 00Z de
22, 23, 24 e 25 de junho de 2026.

## Para o seu caso: nenhum `FILE:*` e nenhum GRIB local

Use o padrão já configurado:

```bash
INPUT_MODE=download_gfs
```

Você **não precisa preencher** `WPS_FILE_ROOT` nem criar previamente
`RAW_GFS_ROOT`. Durante `prepare-init`, o `monan-jedi-workflow` baixa os cinco
GFS `f000` necessários, grava-os em `RAW_GFS_ROOT`, executa UNGRIB e prepara os
cinco trabalhos `mpas_init_atmosphere`.

Os ciclos de entrada são:

```text
2026-06-20 00Z
2026-06-21 00Z
2026-06-22 00Z
2026-06-23 00Z
2026-06-24 00Z
```

O pacote declara a fonte remota em `GFS_URL_TEMPLATE` no `config/site.env`.
Como estas datas são históricas, teste primeiro a aquisição; a disponibilidade
do objeto remoto depende da retenção do provedor. Caso algum objeto não esteja
mais acessível, o comando falhará **antes** do WPS/MPAS e indicará o ciclo e a
URL envolvidos. Nesse caso, baixe os cinco arquivos por uma fonte de arquivo
aprovada e mude somente para `INPUT_MODE=raw_grib`.

## Política de `config_dt` e namelist

Para `x1.10242` (~240 km), o pacote usa `CONFIG_DT=1200`. A alternativa `1440`
é permitida somente após validar um f024 com o mesmo perfil físico, partição,
streams e ambiente MPI. O pacote exige `namelist.atmosphere_240km` e preserva
todo o seu conteúdo, alterando exclusivamente:

```text
config_start_time
config_run_duration
config_do_restart
config_block_decomp_file_prefix
config_dt
```

Antes de submeter forecast, ele compara os oito namelists/streams renderizados
com esse contrato.

## Preparação

Edite apenas os caminhos institucionais já conhecidos em `config/site.env`:
`WORKFLOW_REPO`, `BMATRIX_REPO`, `JACI_ENV_SCRIPT`, `INSTALL_ROOT`, `MESH_ROOT`,
`TUTORIAL_PHYSICS_DIR` e `INVARIANT_FILE`. Mantenha `INPUT_MODE=download_gfs`.

Garanta as branches requeridas:

```bash
git -C "$WORKFLOW_REPO" fetch origin feature/mpas-workflow-foundation
git -C "$WORKFLOW_REPO" switch feature/mpas-workflow-foundation

git -C "$BMATRIX_REPO" fetch origin feature/nmc-campaign-manifest
git -C "$BMATRIX_REPO" switch feature/nmc-campaign-manifest
```

Depois:

```bash
./scripts/run_campaign.sh bootstrap
./scripts/run_campaign.sh preflight
./scripts/run_campaign.sh plan
```

`preflight` não exige que os GFS já existam quando o modo é `download_gfs`.

## Execução por fronteiras

```bash
# Baixa GFS, roda UNGRIB e prepara os cinco jobs de init. Não submete PBS.
./scripts/run_campaign.sh prepare-init

# Submete os cinco mpas_init_atmosphere.
./scripts/run_campaign.sh submit-init

# Quando os inits terminarem: prepara oito forecasts f024/f048 e valida
# o contrato completo de namelist/streams.
./scripts/run_campaign.sh prepare-forecast
./scripts/run_campaign.sh verify-namelist

# Submete os oito forecasts.
./scripts/run_campaign.sh submit-forecast

# Depois de todos completarem: valida e produz bflow-manifest.tsv.
./scripts/run_campaign.sh finalize

# Consome o manifesto no mpas-bmatrix-global.
./scripts/run_campaign.sh bflow
```

Não use `run-all-wait` na primeira execução: ele mantém a sessão bloqueada e é
pior para diagnóstico de uma campanha de oito forecasts. Acompanhe PBS com
`qstat` e avance manualmente pelas fronteiras.

## Produtos

Os GRIBs ficam em `${RAW_GFS_ROOT}`. UNGRIB produz um `FILE:*` isolado por
ciclo em `${WPS_OUTPUT_ROOT}`. Cada forecast recebe diretório próprio com
`f24` ou `f48`, e a campanha só escreve `${CAMPAIGN_ROOT}/bflow-manifest.tsv`
quando os quatro pares têm `restart` e `mpasout` válidos.

O ZIP não contém GFS, WPS, MPAS, malha, física ou matriz B.
