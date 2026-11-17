# Segmentação costeira — v004

Data de execução: 05/11/2026.

Fontes: [linhas costeiras e ilhas menores Natural Earth](https://www.naturalearthdata.com/downloads/10m-physical-vectors/) e [unidades cartográficas administrativas](https://www.naturalearthdata.com/downloads/10m-cultural-vectors/10m-admin-0-details/), todas na escala 1:10 milhões. A fonte inclui costa oceânica, não margens interiores de lagos e rios. Fronteiras administrativas atuais de facto são um controle aproximado; não reconstituem territórios históricos.

Foram preservados os 4964 eventos da fonte, dos quais 223 têm data Reported. Cada evento recebe uma linha por escala no CSV de correspondência. Candidatos rejeitados permanecem rastreáveis.

| Resultado | Eventos por escala |
| --- | ---: |
| `assigned` | 4434 |
| `no_coordinates` | 102 |
| `outside_distance` | 311 |
| `country_mismatch` | 86 |
| `country_unverified` | 31 |

| Escala | Segmentos | Com evento atribuído |
| --- | ---: | ---: |
| 10 km | 98003 | 1637 |
| 25 km | 41735 | 1281 |
| 50 km | 23376 | 1038 |

Regiões adaptativas: 884 com pelo menos um evento; 142 atendem ao mínimo de 10 datas positivas distintas, reunindo 2580 eventos. Até 4 segmentos adjacentes de 25 km são unidos na mesma cadeia costeira; não se unem ilhas separadas. Trechos já elegíveis são preservados. As regiões esparsas ficam no atlas, fora do recorte principal pelo critério de frequência.

O ponto mais próximo é calculado sobre a linha, por distância de círculo máximo. Adota-se limite de 25 km. O ponto costeiro precisa estar até 10 km do país/território informado, quando mapeado. País marítimo, histórico ou sem correspondência fica em revisão. Nome de localidade vazio não impede a atribuição. A checagem não comprova a localidade exata: um ponto mal geocodificado dentro do país ainda pode passar. Coordenadas originais não são corrigidas; o CSV preserva tanto o ponto original como o candidato mais próximo.

Sensibilidade apenas à distância, antes da validação de país: 4310 eventos até 10 km, 4551 eventos até 25 km, 4673 eventos até 50 km.

Os CSVs e os GeoJSON compactados são produtos da etapa espacial. O painel de treinamento por segmento e dia, com dias negativos e enriquecimento, ainda não é produzido aqui. O atlas é para inspeção e pesquisa, sem estimar risco.
