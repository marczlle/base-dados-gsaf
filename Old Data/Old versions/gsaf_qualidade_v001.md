# Qualidade e limpeza GSAF — v001

Data de referência: 2026-10-23. Regras: 1.0.0.

## Resultado

| Medida | Quantidade |
| --- | ---: |
| Registros de entrada | 5253 |
| Duplicações comprovadas removidas da base limpa | 3 |
| Registros preservados na base limpa | 5250 |
| Registros preservados com data exata | 4741 |
| Registros sem data exata, separados | 509 |
| Datas exatas distintas no mundo | 4061 |
| Registros aptos ao agrupamento por localidade e dia | 4549 |
| Pares localidade + data positivos | 4438 |
| Pares com mais de um registro | 98 |
| Pares com coordenadas divergentes | 0 |

A unidade principal do plano continua sendo **segmento costeiro + data**. Nesta etapa, o agrupamento por localidade textual é provisório. Não representa a atribuição a segmentos da etapa 2 nem o painel final de treinamento. Nenhum dia negativo foi criado.

## Fontes e rastreabilidade

- `GSAF_clima_lua.csv`: 5253 registros. SHA-256 `ee2adcba9803fc3e2f7277ac49abdf0a059db097136d6d9fe1fce93ccc612b75`.
- `Old Data/Md/GSAF5_ml_ready_final.csv`: 7097 registros. SHA-256 `5ddabae8839cf7ef1537a301b9c10f2249d0b900cc6a744f85df9deb222c5a1c`.

A base da raiz é a fonte dos valores. O arquivo anterior em Old Data é usado somente para conferir a precisão das datas e provar duplicações. Não foram acrescentados ataques antigos. A associação usa ano, país, estado, localidade, horário e atividade, com confirmação da data quando há várias candidatas. Horários numéricos com zeros à esquerda são equivalentes apenas nessa associação. Listas de candidatas não são uma atribuição individual de identidade. Nenhum nome de vítima foi atribuído à base limpa.

`source_csv_record` e `legacy_csv_records` contam registros CSV com cabeçalho = 1. Não são linhas físicas quando um campo contém quebras de linha. `record_id` identifica o registro da fonte atual e deve ser interpretado junto ao hash dessa fonte.

## Regras aplicadas

- País, estado e localidade: Unicode NFKC, espaços e pontuação equivalentes, maiúsculas com acentos preservados, ausentes em branco. Aliases explícitos e contextualizados por país corrigem, por exemplo, COLUMBIA, NSW, Westerm Australia, Guerro e Inhambe Province. As variantes MEXICO, Mexico e MeXICO passam a MEXICO. Não houve agrupamento por semelhança aproximada nem tradução geral dos topônimos.
- Meses: nomes completos, abreviações e números tornam-se inteiros de 1 a 12. Ano e dia também são inteiros; ausentes permanecem vazios.
- `date`: ISO 8601 (AAAA-MM-DD), preenchida somente quando os componentes são válidos e a fonte confirma uma data exata. `extracted_date` guarda a reconstrução da base atual, mesmo quando reprovada. `year_month` é apenas o mês extraído e pode precisar de revisão quando a fonte é conflitante. Não é uma data mensal validada.
- Datas numéricas ambíguas, Reported, intervalos e conflitos ficam separados. Não se corrigiu dia/mês por ordenação das linhas, nem se substituiu ano errado por suposição.
- Latitude e longitude: decimal com ponto, sinal preservado, zeros válidos, ausência diferenciada de zero, checagem de finitude e limites ±90/±180. Valores brutos preservados.
- Clima e lua dos registros sem data exata ficam vazios na base limpa. Os valores anteriores continuam nas colunas `_raw`, pois os scripts antigos consultavam clima no dia 1 e lua no dia 15 quando o dia era desconhecido. Não houve recálculo nem consulta a APIs.
- Apenas duplicações comprovadas por registros completos repetidos na fonte anterior são removidas. Mesmo Case Number ou mesmos atributos ambientais não bastam. Vítimas e registros distintos no mesmo dia são preservados.
- Os dias positivos usam somente registros retidos com `date_status=exact`, país e localidade preenchidos e par de coordenadas numericamente válido. Estado pode faltar. Cada par localidade normalizada + data aparece uma vez, com `attack=1` e `attack_count`. Contagens representam registros/vítimas na fonte, não encontros independentes comprovados. `attack_count` e demais informações posteriores ao incidente não são preditores.
- Se o mesmo local/dia tiver coordenadas distintas, elas não são promediadas nem escolhidas arbitrariamente: ficam vazias no resumo, com `coordinate_conflict=1`. As coordenadas individuais continuam no arquivo de eventos.

## Distribuição e mudanças

Países/rótulos: 193 valores brutos distintos, 141 valores preenchidos normalizados. Meses: 35 representações brutas para 12 meses.

| Campo | Registros com valor alterado |
| --- | ---: |
| Country | 187 |
| State | 5247 |
| Location | 5252 |
| Month | 5182 |

## Precisão das datas na base retida

| Situação | Registros |
| --- | ---: |
| ambiguous_numeric | 31 |
| day_unknown | 232 |
| exact | 4741 |
| range_or_approximate | 4 |
| reported_date | 223 |
| year_conflict | 19 |

## Exclusões do recorte de eventos diários

Todos os registros de entrada aparecem no arquivo de auditoria. Uma linha pode ter mais de um motivo; as contagens por motivo não devem ser somadas como linhas distintas.

| Motivo | Registros de entrada | Explicação |
| --- | ---: | --- |
| ambiguous_numeric | 31 | Data com barras admite DD/MM e MM/DD diferentes. Não foi escolhido um formato. |
| confirmed_duplicate | 3 | Duplicação comprovada por repetição completa no arquivo anterior. |
| day_unknown | 234 | Dia desconhecido. Nenhum dia foi imputado. |
| range_or_approximate | 4 | Fonte registra intervalo ou data aproximada. |
| reported_date | 223 | Data de notícia/registro (Reported), sem comprovação do dia do incidente. |
| year_conflict | 19 | Ano explícito da data original diverge da coluna Year. |

Motivos adicionais para não entrar no resumo por localidade:

| Motivo | Registros de entrada |
| --- | ---: |
| coordinates_missing_or_invalid | 128 |
| country_missing | 16 |
| location_missing | 292 |

## Repetições e múltiplos no mesmo dia

Foram encontrados 45 grupos de atributos completos repetidos após normalização, dos quais 3 possuem duplicação comprovada. O arquivo de duplicidades registra as linhas candidatas, os casos e os nomes originais que justificam preservar ou remover cada repetição.

Registros removidos da base limpa (numeração da fonte atual, cabeçalho = 1): 5248, 5250, 5254. Todos continuam integralmente na auditoria, com `duplicate_removed=1` e `daily_exclusion_reasons` contendo `confirmed_duplicate`.

## Limitações mantidas para as próximas etapas

- Validade numérica não comprova geocodificação correta. Todas as linhas têm `coordinates_spatially_verified=0`. Há indícios de geocodificação incorreta: registros originalmente NEW BRITAIN aparecem com latitude positiva e longitude do Reino Unido/EUA. Não foram inventadas novas coordenadas. A etapa 2 deve verificar país, distância à costa e atribuição ao segmento antes de liberar esses pontos para treinamento.
- A coluna Country ainda contém oceanos, regiões históricas, fronteiras e rótulos incertos. A normalização não os transforma artificialmente em países. State também contém ilhas, cidades e áreas marítimas: não é um cadastro administrativo validado.
- O recorte de tipos segue a definição do plano: presença de registro na base. Não foi aplicada uma nova seleção por Type. `legacy_types` permite identificar Invalid, Questionable, Watercraft etc. A decisão sobre a população de incidentes deve ser explícita antes do treinamento; `attack=1` aqui indica registro, não validação factual do incidente.
- Dados climáticos/lunares retidos para datas exatas continuam sendo o enriquecimento antigo por ponto de ataque. Não devem entrar diretamente no painel regional final: as etapas 4 e 5 preveem clima padronizado por segmento e lua única por data. Colunas `_raw`, identificadores, `legacy_types`, atividade, espécie, horário e contagens do próprio dia são de rastreabilidade e não definem a lista de preditores.

## Arquivos da execução

| Produto | Uso |
| --- | --- |
| gsaf_limpa_v001.csv | Base completa retida; preserva os campos brutos e as flags. |
| gsaf_eventos_data_exata_v001.csv | Eventos com data exata para a etapa de segmentos; pode haver coordenadas ausentes. |
| gsaf_datas_nao_exatas_v001.csv | Registros retidos sem data exata, separados para revisão/análise mensal. |
| gsaf_dias_positivos_local_v001.csv | Uma linha por localidade e data exata; agrupamento provisório. |
| gsaf_auditoria_v001.csv | Uma linha para cada entrada, incluindo removidas, destinos e motivos. |
| gsaf_duplicidades_v001.csv | Evidências de repetições e múltiplos registros. |
| gsaf_normalizacoes_v001.csv | Correspondência de cada valor original para o normalizado e frequência. |
| gsaf_qualidade_v001.md | Este relatório. |
| gsaf_manifesto_v001.json | Fontes, versão, parâmetros, contagens e hashes de todos os produtos. |

## Reexecução e verificações

```powershell
python scripts/clean_data.py --as-of 2026-10-23
python -m unittest discover -s tests -v
```

A próxima execução escolhe automaticamente a próxima versão livre em Data. Uma versão solicitada explicitamente só pode ser usada se não existir. CSV: UTF-8 com BOM, delimitador vírgula, decimal com ponto, ausentes vazios. Os artefatos incluem conferência de contagens, chaves, datas e preservação dos brutos. Não houve mudança nos arquivos de origem.
