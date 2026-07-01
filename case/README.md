Este diretório é gerado por `../scripts/configure_case.py`.

Não edite os YAMLs gerados diretamente para alterar caminhos globais. Edite
`../config/site.env` e execute novamente:

```bash
../scripts/run_campaign.sh bootstrap
```

Os templates materializados são derivados do build MPAS e do diretório de
física do tutorial configurados em `site.env`. Isso evita congelar no ZIP uma
cópia potencialmente incompatível de namelist, streams ou tabelas físicas.


A fonte do namelist de forecast deve ser explicitamente `namelist.atmosphere_240km`. O bootstrap só altera os cinco campos de geometria de execução descritos em `../docs/04_namelist_dt_contract.md`.
