# Geometria NMC da campanha

A campanha usa pares NMC `f048 - f024` no mesmo tempo válido.

```text
valid=2026-06-22T00Z: f048 init=2026-06-20T00Z, f024 init=2026-06-21T00Z
valid=2026-06-23T00Z: f048 init=2026-06-21T00Z, f024 init=2026-06-22T00Z
valid=2026-06-24T00Z: f048 init=2026-06-22T00Z, f024 init=2026-06-23T00Z
valid=2026-06-25T00Z: f048 init=2026-06-23T00Z, f024 init=2026-06-24T00Z
```

Em `prebuilt_wps`, a campanha espera os cinco arquivos:

```text
FILE:2026-06-20_00
FILE:2026-06-21_00
FILE:2026-06-22_00
FILE:2026-06-23_00
FILE:2026-06-24_00
```

Em `raw_grib`, ela espera cinco GFS f000:

```text
gfs.2026062000.pgrb2.0p25.f000
gfs.2026062100.pgrb2.0p25.f000
gfs.2026062200.pgrb2.0p25.f000
gfs.2026062300.pgrb2.0p25.f000
gfs.2026062400.pgrb2.0p25.f000
```

Os oito diretórios de forecast são separados por ciclo e lead:

```text
.../mpas_runs/20260620T000000Z/f48
.../mpas_runs/20260621T000000Z/f24
.../mpas_runs/20260621T000000Z/f48
.../mpas_runs/20260622T000000Z/f24
.../mpas_runs/20260622T000000Z/f48
.../mpas_runs/20260623T000000Z/f24
.../mpas_runs/20260623T000000Z/f48
.../mpas_runs/20260624T000000Z/f24
```

O nono diretório aparente não existe: 2026-06-20 tem apenas f48 e
2026-06-24 apenas f24.


## Coerência temporal

Todos os oito forecasts usam o mesmo `CONFIG_DT`: 1200 s por padrão ou 1440 s após validação. Com `OUTPUT_INTERVAL=24:00:00`, ambos dividem exatamente o intervalo diário de saída.
