# Calendário lunar e sazonal — v009

Foram calculadas 31.545 datas distintas de 1940-01-01 a 2026-05-24.
O calendário acompanha `gsaf_painel_diario_25km_v006.parquet` e pode ser associado pelo campo `date`.

## Regras

- Uma linha para cada data presente no painel de origem. A referência comum a todos os trechos é 12:00 UTC.
- A fase é a diferença entre as longitudes eclípticas geocêntricas aparentes da Lua e do Sol, em [0°, 360°). Lua nova corresponde a 0°, quarto crescente a 90°, cheia a 180° e quarto minguante a 270°.
- O rótulo da fase indica o setor de 45° mais próximo. O seno e o cosseno representam o ângulo contínuo.
- A iluminação é a fração do disco lunar iluminada, entre 0 e 1, segundo o PyEphem.
- O dia do ano é codificado em seno e cosseno usando (dia do ano − 1) dividido por 365 ou 366. O ano bruto permite ajustar transformações futuras só com os dados de treino.

## Distribuição dos rótulos

| Fase | Datas |
| --- | ---: |
| `new_moon` | 3862 |
| `waxing_crescent` | 3951 |
| `first_quarter` | 4030 |
| `waxing_gibbous` | 3931 |
| `full_moon` | 3854 |
| `waning_gibbous` | 3951 |
| `last_quarter` | 4016 |
| `waning_crescent` | 3950 |

## Reprodução

```powershell
python -m pip install ephem==4.2.1 pyarrow==26.0.1
python Scripts/build_lunar_calendar.py --panel-version v006 --version v009
```

Se a versão já existir em `Data/`, informe a próxima versão disponível.
