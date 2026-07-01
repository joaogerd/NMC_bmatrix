# Contrato do namelist 240 km e `config_dt`

## Por que este contrato existe

A malha `x1.10242` é uma configuração de aproximadamente 240 km. Nesta
campanha, o passo de tempo não é tratado como um ajuste isolado: `CONFIG_DT` só
é aceito como `1200` ou `1440` segundos e precisa ser aplicado sobre o perfil
`namelist.atmosphere_240km` coerente com os arquivos de física, invariante e
stream lists selecionados.

## Fonte obrigatória

Em `config/site.env`:

```bash
FORECAST_NAMELIST_SOURCE=${TUTORIAL_PHYSICS_DIR}/namelist.atmosphere_240km
FORECAST_STREAMS_SOURCE=${TUTORIAL_PHYSICS_DIR}/streams.atmosphere_240km
CONFIG_DT=1200
OUTPUT_INTERVAL=24:00:00
```

O bootstrap falha se o namelist 240 km não estiver presente. Não há fallback
para o namelist genérico do core MPAS.

## Campos modificados pelo pacote

Somente estes cinco campos do perfil fonte são modificados:

| Campo | Origem do valor |
|---|---|
| `config_start_time` | ciclo de inicialização |
| `config_run_duration` | `1_00:00:00` para f024; `2_00:00:00` para f048 |
| `config_do_restart` | `.false.` |
| `config_block_decomp_file_prefix` | partição da malha `x1.10242` |
| `config_dt` | 1200 ou 1440 s definido em `site.env` |

O restante permanece exatamente como no perfil de 240 km. O arquivo
`case/inventory/forecast_namelist_contract.json` registra origem, hashes e os
campos autorizados.

## Verificação antes de PBS

Após `prepare-forecast`, execute:

```bash
./scripts/run_campaign.sh verify-namelist
```

A verificação compara os oito namelists e streams renderizados com o contrato.
Qualquer edição manual, uso de template incorreto, duração errada ou ausência
do stream `da_state` bloqueia a submissão de forecast.

## Troca controlada para 1440 s

1. Conclua um f024 com `CONFIG_DT=1200` e valide o log, `restart` e `mpasout`.
2. Edite apenas `CONFIG_DT=1440` em `config/site.env`.
3. Apague ou arquive os diretórios de run da campanha para evitar mistura de
   produtos produzidos com dt diferentes.
4. Rode `bootstrap`, `preflight`, `prepare-init` e `prepare-forecast` de novo.
5. Execute `verify-namelist` antes de `submit-forecast`.

Nunca misture f024 em 1200 s e f048 em 1440 s no mesmo conjunto NMC.
