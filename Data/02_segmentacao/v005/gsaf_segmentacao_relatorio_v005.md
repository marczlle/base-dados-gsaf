# Segmentação costeira — v005

Data de execução: 05/11/2026.

Fontes: [linhas costeiras e ilhas menores Natural Earth](https://www.naturalearthdata.com/downloads/10m-physical-vectors/) e [unidades cartográficas administrativas](https://www.naturalearthdata.com/downloads/10m-cultural-vectors/10m-admin-0-details/), todas na escala 1:10 milhões. A fonte inclui costa oceânica, não margens interiores de lagos e rios. Fronteiras administrativas atuais de facto são um controle aproximado; não reconstituem territórios históricos.

Foram preservados os 4964 eventos da fonte, dos quais 223 têm data Reported. Cada evento recebe uma linha por escala no CSV de correspondência. Candidatos rejeitados permanecem rastreáveis.

| Resultado | Eventos por escala |
| --- | ---: |
| `assigned` | 4488 |
| `no_coordinates` | 102 |
| `outside_distance` | 274 |
| `country_mismatch` | 63 |
| `country_unverified` | 37 |

| Método de atribuição | Eventos por escala |
| --- | ---: |
| `direct_geocode` | 4434 |
| `reviewed_toponym` | 31 |
| `extended_geocode` | 23 |

Comparação com `gsaf_eventos_segmentos_v004.csv`: 54 recuperados e 0 antes atribuídos agora em revisão.
A trilha por evento está em `gsaf_segmentacao_transicoes_v005.csv`. 
Farallon: a linha costeira contém um trecho insular, mas o mapa administrativo omite as ilhas. Os vínculos do arquipélago usam a geometria disponível como referência; a ilha norte não recebe uma coordenada inventada. O [U.S. Fish & Wildlife Service](https://www.fws.gov/refuge/farallon-islands/about-us) confirma o arquipélago na Califórnia.


| Escala | Segmentos | Com evento atribuído |
| --- | ---: | ---: |
| 10 km | 98003 | 1668 |
| 25 km | 41735 | 1309 |
| 50 km | 23376 | 1062 |

Regiões adaptativas: 903 com pelo menos um evento; 144 atendem ao mínimo de 10 datas positivas distintas, reunindo 2604 eventos. Até 4 segmentos adjacentes de 25 km são unidos na mesma cadeia costeira; não se unem ilhas separadas. Trechos já elegíveis são preservados. As regiões esparsas ficam no atlas, fora do recorte principal pelo critério de frequência.

O ponto mais próximo é calculado sobre a linha, por distância de círculo máximo. O vínculo padrão admite até 25 km. O ponto costeiro precisa estar até 10 km do país/território informado, quando mapeado. Topônimos e territórios revisados têm fonte documentada e critérios locais próprios. O vínculo provisório admite até 75 km quando o topônimo tem indício costeiro específico e o país e o estado cartografado (quando reconhecido) são compatíveis. Nessa extensão, proxies compartilhados por nomes distintos, contextos artificiais/interiores, afastamento explícito acima do limite e nomes de ilha sem correspondência geométrica continuam em revisão. Localidade vazia ainda permite o vínculo padrão. As coordenadas originais não mudam, e a distância mede a separação entre o geocódigo aproximado e o trecho, não entre o incidente real e a costa.

Sensibilidade apenas à distância, antes da validação de país: 4310 eventos até 10 km, 4551 eventos até 25 km, 4673 eventos até 50 km.

Os CSVs e os GeoJSON compactados são produtos da etapa espacial. O painel de treinamento por segmento e dia, com dias negativos e enriquecimento, ainda não é produzido aqui. O atlas é para inspeção e pesquisa, sem estimar risco.
