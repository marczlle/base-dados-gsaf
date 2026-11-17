# Painel diário de 25 km — v006

Fonte `gsaf_eventos_segmentos_v005.csv`.
Intervalo global das datas 1940-01-01 a 2026-05-24.

## Regras

- Usar segmentos fixos de 25 km e vínculos com status `assigned`, incluindo os aproximados aceitos na etapa espacial.
- Gerar uma linha por `segment_id` e `date` entre o primeiro e o último evento de cada segmento, inclusive.
- `attack=1` indica pelo menos um registro no dia. `attack=0` indica ausência de registro na GSAF dentro da janela.
- `attack_count` conta eventos distintos. `reported_attack_count` conta os eventos com data `Reported`.
- `date_status` é `exact`, `reported_date` ou `mixed` se houver ambos no dia, e nulo nos dias com `attack=0`. `date_is_approximate=1` indica pelo menos um evento `Reported` no dia.
- Contagens e flags derivados dos eventos servem à auditoria do alvo. O enriquecimento climático e lunar pertence às etapas seguintes.
- O intervalo primeiro–último é retrospectivo. Um teste prospectivo requer elegibilidade e fim do teste definidos sem usar os ataques futuros.

## Contagens

| Métrica | Total |
| --- | ---: |
| Segmentos no painel | 1.309 |
| Segmentos com janela de um dia | 722 |
| Linhas | 7.432.823 |
| Dias positivos | 4.362 |
| Dias sem registro | 7.428.461 |
| Dias positivos com múltiplos eventos | 111 |
| Dias positivos somente com data exata | 4.198 |
| Dias positivos somente com data Reported | 164 |
| Dias positivos com data exata e Reported | 0 |
| Eventos com data exata | 4.323 |
| Eventos com data Reported | 165 |
| Proporção de dias positivos | 0,05869% |

## Correspondências na fonte

Foram excluídos 476 eventos sem atribuição espacial nessa escala. Os IDs e motivos individuais estão no CSV de origem.

| Status | Eventos |
| --- | ---: |
| `assigned` | 4.488 |
| `country_mismatch` | 63 |
| `country_unverified` | 37 |
| `no_coordinates` | 102 |
| `outside_distance` | 274 |

## Reprodução

```powershell
python -m pip install pyarrow==26.0.1
python Scripts/build_daily_panel.py --source-version v005 --version v006
```

Em `Data/` com esta versão já publicada, use a próxima versão disponível.
Fontes, versão do PyArrow e hashes SHA-256 em `gsaf_painel_diario_25km_manifesto_v006.json`.
