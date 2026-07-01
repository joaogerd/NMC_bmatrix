# Diagnóstico e retomada

## A campanha não passa no preflight

Leia o primeiro caminho marcado como `MISSING` ou `ERROR`. Os casos mais comuns
são:

1. `WPS_FILE_ROOT` não contém os cinco `FILE:YYYY-MM-DD_HH`;
2. não existe a partição 128 da malha;
3. `FORECAST_NAMELIST_SOURCE` não aponta para `namelist.atmosphere_240km`;
4. o diretório de física não corresponde ao invariante/stream lists escolhidos;
5. a branch do workflow não contém `nmc-campaign-run`.

## `CONFIG_DT=1200` ou `1440` e o MPAS falha

Não reduza o passo automaticamente. Primeiro confirme que o forecast realmente
recebeu o perfil 240 km e não um namelist genérico:

```bash
./scripts/run_campaign.sh verify-namelist
```

O comando compara, para os oito forecasts, o `namelist.atmosphere` e
`streams.atmosphere` do diretório de execução contra o contrato renderizado no
bootstrap. Ele verifica `config_dt`, `config_start_time`,
`config_run_duration`, `config_do_restart` e a partição, além de impedir
alterações silenciosas nos demais campos do perfil.

Inspecione um f024 antes de submetê-lo:

```bash
grep -nE 'config_start_time|config_run_duration|config_dt|config_do_restart|config_block_decomp_file_prefix' \
  "$MPAS_RUN_ROOT/20260622T000000Z/f24/namelist.atmosphere"

grep -nE 'da_state|restart|mpasout|output_interval' \
  "$MPAS_RUN_ROOT/20260622T000000Z/f24/streams.atmosphere"
```

Para o primeiro par, os valores esperados são:

```text
f024: start = 2026-06-21_00:00:00; duration = 1_00:00:00
f048: start = 2026-06-20_00:00:00; duration = 2_00:00:00
config_dt = 1200  (ou 1440, sempre igual em toda a campanha)
```

Se o contrato passar e o modelo ainda falhar, então o problema é científico ou
de ambiente — não uma renderização incompleta. Preserve o diretório do run e
compare `log.atmosphere.0000.out`, `stderr.log`, a física do perfil e as
variáveis do `init.nc` antes de alterar dt.

## O WPS falha

Use apenas em `INPUT_MODE=raw_grib`.

```bash
./scripts/run_campaign.sh prepare-init
find "$WPS_OUTPUT_ROOT" -maxdepth 3 -type f | sort
```

Cada ciclo deve produzir `FILE:YYYY-MM-DD_00`; os logs ficam no diretório
`logs/` de cada trabalho WPS.

## Retomar

Os comandos são idempotentes. Depois de corrigir a causa, repita a fronteira:

```bash
./scripts/run_campaign.sh prepare-init
./scripts/run_campaign.sh submit-init
./scripts/run_campaign.sh prepare-forecast
./scripts/run_campaign.sh submit-forecast
./scripts/run_campaign.sh finalize
```

Use `--resubmit` somente quando quiser substituir deliberadamente uma submissão
PBS registrada no manifesto daquele run.
