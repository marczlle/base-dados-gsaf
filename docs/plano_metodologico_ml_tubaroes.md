# Plano metodológico: previsão diária de risco de incidentes com tubarões

## 1. Objetivo do documento

Este documento registra a evolução da proposta de pesquisa e define o plano técnico para construir uma base diária, regionalizada espacialmente, e treinar modelos de machine learning capazes de estimar a probabilidade relativa de ocorrência de pelo menos um incidente com tubarão.

## 1.1 Resumo da ideia central do trabalho

Este trabalho propõe investigar se variáveis climáticas, sazonais e lunares podem contribuir para estimar o risco diário de ocorrência de incidentes com tubarões em diferentes regiões costeiras.

A pesquisa utilizará uma base previamente limpa da Global Shark Attack File, contendo registros históricos de incidentes, datas e localidades. Como as coordenadas disponíveis são estimativas obtidas a partir de informações textuais, os ataques não serão tratados como pontos exatos. Em vez disso, a costa será dividida automaticamente em segmentos geográficos, reduzindo o impacto da imprecisão espacial.

Pernambuco será utilizado como estudo de caso. O modelo global será avaliado separadamente na região, verificando se padrões aprendidos em outras áreas costeiras conseguem generalizar para um contexto local com características ambientais próprias. Essa etapa permitirá discutir as limitações da transferência de modelos entre regiões.

O trabalho não pretende desenvolver um sistema oficial de alerta nem calcular a probabilidade individual de uma pessoa ser atacada. A proposta é avaliar a capacidade preditiva de dados históricos e ambientais em escala regional. Os resultados também deverão considerar limitações como a ausência de dados sobre quantidade de pessoas na água, a possível subnotificação dos incidentes e a incerteza das coordenadas geográficas.

## 2. Estado atual dos dados e dos scripts

A base utilizada atualmente é `GSAF_clima_lua.csv`, localizada na raiz do projeto. A auditoria preliminar identificou:

- 5.253 registros;
- 21 colunas;
- registros entre 1940 e 2026;
- dados de ataque, localização, data, clima e lua;
- 5.125 registros com coordenadas e variáveis climáticas preenchidas aproximadamente;
- muitos campos categóricos com o valor `unknown`;
- cerca de 4.232 dias distintos com data exata de ataque após a normalização preliminar;
- 117 registros para o Brasil e aproximadamente 80 para Pernambuco.

O script `enrich_data.py` geocodifica localidades e consulta a API histórica da Open-Meteo para obter:

- `temperature_2m_mean`;
- `precipitation_sum`;
- `wind_speed_10m_max`;
- `wind_direction_10m_dominant`.

Atualmente, o script realiza uma consulta por registro, usando a mesma data em `start_date` e `end_date`. Para a base expandida, esse processo precisará ser substituído por consultas em intervalos maiores, agrupadas por ponto geográfico e protegidas por cache.

O script `moon.py` utiliza `ephem` para calcular `moon_illumination` e `moon_phase`. Como esses valores dependem essencialmente da data, o cálculo poderá ser feito uma única vez para cada dia do calendário e depois associado a todos os segmentos costeiros.

Há um problema importante nas datas incompletas: `enrich_data.py` usa o dia 1 para consultar a Open-Meteo quando o dia original é desconhecido, enquanto `moon.py` usa o dia 15 para calcular a lua. Essa imputação não será utilizada na variável-alvo diária. Registros sem dia conhecido serão excluídos do treinamento diário ou analisados separadamente em uma versão mensal. Por decisão do pesquisador em 23/10/2026, datas de registro/notícia (`Reported`) são elegíveis como aproximação do dia do ataque, com identificação explícita dessa condição.

## 3. Evolução da ideia

### 3.1 Ideia inicial: classificar ataque ou não ataque

A proposta inicial era treinar um modelo para prever se haveria ataque ou não. Como a base contém apenas registros positivos, a primeira hipótese foi considerar todo dia ausente como dia sem ataque.

Essa hipótese é razoável como aproximação porque a fonte é uma base global consolidada de incidentes. Entretanto, ficou claro que a unidade de análise precisava ser definida corretamente: um ataque é registrado em uma localização específica, enquanto um dia sem ataque não possui naturalmente uma localização equivalente.

### 3.2 Remoção de colunas incompletas ou indisponíveis antecipadamente

Foram consideradas inadequadas para previsão:

- `Species`;
- `Shark_Size_Meters`;
- `Activity`;
- `Time`;
- `Hour`.

Essas variáveis têm muitos valores desconhecidos, são preenchidas de forma inconsistente ou podem ser conhecidas apenas depois do incidente. Utilizá-las poderia gerar vazamento de informação ou criar uma diferença artificial entre dias com e sem ataque.

As variáveis climáticas, lunares, temporais e geográficas foram mantidas como candidatas porque podem estar disponíveis antes ou no início do dia previsto.

### 3.3 Seleção de dias negativos próximos aos ataques

Foi considerada a criação de dias sem ataque próximos às datas positivas, por exemplo, no mesmo local, mês ou janela de alguns dias. O objetivo seria controlar sazonalidade e condições ambientais.

Essa abordagem foi descartada como estratégia principal porque:

- altera artificialmente a prevalência real do fenômeno;
- pode eliminar padrões sazonais que o modelo deveria aprender;
- pode gerar controles excessivamente semelhantes aos ataques;
- faz a probabilidade prevista depender da regra de amostragem;
- não preserva necessariamente a distribuição real de dias positivos e negativos.

Dias próximos poderão ser usados futuramente como análise de sensibilidade, mas não como o painel principal.

### 3.4 Modelo global com uma linha por dia

Também foi considerada uma base com uma linha por dia no mundo inteiro:

```text
data | houve_ataque_global
```

Essa estrutura é simples e pode ser usada como baseline. Porém, ela não combina naturalmente com variáveis climáticas obtidas em coordenadas específicas. Um dia com ataque no Brasil e um dia sem ataque na Austrália não possuem uma única representação climática global sem uma agregação adicional complexa.

Essa opção será mantida apenas como modelo de referência, não como estrutura principal.

### 3.5 Agregação por país ou estado

Foi considerada a criação de linhas como:

```text
Brasil + data
Pernambuco + data
```

Essa alternativa resolve parte do problema espacial, mas pode diluir o sinal ambiental. Países e estados podem conter diferentes litorais, habitats, espécies, níveis de exposição humana e condições climáticas.

O estudo de Midway, Wagner e Burgess mostrou que o país é útil para tendências amplas, mas pode esconder padrões locais. Os autores usaram regiões ecologicamente mais coerentes em uma análise complementar e destacaram que o risco local é melhor interpretado em escalas menores. [Midway et al. (2019)](https://doi.org/10.1371/journal.pone.0211049)

### 3.6 Modelo por localidade exata

Foi considerada a criação de todas as combinações:

```text
Location + todos os dias do período
```

Essa abordagem seria espacialmente detalhada, mas foi descartada como estrutura principal porque:

- existem milhares de localidades;
- muitas aparecem poucas vezes;
- não é possível afirmar que uma localidade foi observada todos os dias;
- o número de linhas poderia crescer para dezenas ou centenas de milhões;
- seria necessário consultar a Open-Meteo para muitos pontos e datas;
- nomes textuais de localidades são inconsistentes.

### 3.7 Modelo exclusivo para Pernambuco

Pernambuco possui grande relevância científica e social, especialmente na região metropolitana do Recife. Entretanto, a auditoria atual encontrou aproximadamente 80 registros para Pernambuco e cerca de 79 dias distintos com data exata.

Esse volume é pequeno para sustentar sozinho um modelo complexo de machine learning. A criação de dias negativos aumentaria o número de linhas, mas não aumentaria a quantidade de exemplos positivos nem a diversidade de condições associadas a ataques.

Por isso, Pernambuco será tratado como estudo de caso e avaliação de generalização, não como único conjunto de treinamento.

### 3.8 Contribuição do CEMIT

A página oficial do CEMIT apresenta uma abordagem operacional baseada em trecho costeiro. O comitê considera um trecho de aproximadamente 33 km entre a Praia do Paiva e a Praia do Farol, em Olinda, como área de atenção, além de uma área legalmente proibida de 2,2 km em Piedade. [CEMIT/SEMAS-PE](https://semas.pe.gov.br/cemit/)

Essa estrutura mostrou que a unidade mais adequada não precisa ser um país, estado ou praia individual. Ela pode ser um segmento costeiro com características ambientais e de risco relativamente semelhantes.

O CEMIT não será copiado literalmente para outros países, porque suas áreas são específicas de Pernambuco e também incorporam decisões legais e operacionais locais. Sua contribuição para o projeto será conceitual: utilizar trechos costeiros como unidades de análise.

### 3.9 Abordagem final escolhida

A unidade principal será:

```text
segmento costeiro + data
```

A costa mundial será dividida automaticamente em segmentos geográficos, sem desenhar regiões manualmente apenas a partir do mapa de calor.

A estratégia espacial será multiescalar:

- segmentação-base por trechos costeiros de aproximadamente 25 km;
- análises de sensibilidade com 10 km e 50 km;
- união automática de segmentos vizinhos com poucos dias positivos, quando necessário;
- nenhuma região será escolhida manualmente apenas por observação visual dos ataques.

Cada segmento receberá dados climáticos agregados de pontos fixos da costa e dados lunares calculados pela data.

A janela temporal será independente para cada segmento. Se um segmento possuir ataques entre 1995 e 2015, serão geradas as datas desse intervalo para esse segmento. Não serão geradas linhas para esse segmento antes da primeira ocorrência válida ou depois da última, porque não há garantia de cobertura equivalente nesses períodos.

As datas não serão compartilhadas entre regiões como se um único dia negativo global pudesse ser reutilizado. Em um painel regional, a unidade é `segmento + data`. Portanto, a mesma data poderá aparecer uma vez para cada segmento ativo, com clima, localização e rótulo próprios. Isso não é duplicação indevida: são observações diferentes para regiões diferentes. O que não pode ocorrer é haver mais de uma linha para o mesmo par `segmento + data`.

## 4. Fundamentação científica considerada

### Ryan et al. (2019)

Ryan et al. desenvolveram modelos ambientais de risco de ataques em águas australianas usando localização, temperatura da água, chuva e distância até a foz de rios. O estudo utilizou modelos aditivos generalizados e dados de pseudo-ausência.

É o trabalho metodologicamente mais próximo da ideia de relacionar ataques com condições ambientais e construir observações sem ataque. [Environmental predictive models for shark attacks in Australian waters](https://doi.org/10.3354/meps13138)

### French et al. (2021)

French et al. analisaram quase 50 anos de ataques globais e investigaram a relação com iluminação lunar. O trabalho destaca que bases de ataques normalmente não possuem registros de dias sem ataque suficientes para formar um desenho probabilístico convencional.

O estudo usou análises de frequência e qui-quadrado, não machine learning, mas fundamenta a inclusão de variáveis lunares e a discussão sobre ausência de registros. [Shark Side of the Moon](https://doi.org/10.3389/fmars.2021.745221)

### Afonso, Niella e Hazin (2017)

Afonso, Niella e Hazin estudaram a região metropolitana do Recife, relacionando a frequência de ataques à sazonalidade e à abundância de tubarões potencialmente perigosos. O estudo utilizou modelos aditivos generalizados e representa um antecedente regional relevante para Pernambuco.

[Inferring trends and linkages between shark abundance and shark bites](https://doi.org/10.1071/MF16274)

### Midway, Wagner e Burgess (2019)

Midway et al. modelaram tendências globais por país e por regiões. Usaram um modelo Bayesiano hierárquico com distribuição Poisson inflacionada de zeros e analisaram a quantidade de ataques por localidade e ano.

O estudo é relevante porque mostra que países podem ser unidades muito amplas e que regiões ecologicamente coerentes são mais informativas. Também mostra que modelar tendências anuais não é o mesmo que prever ataques diariamente.

[Trends in global shark attacks](https://doi.org/10.1371/journal.pone.0211049)

### Meyer (2025)

Meyer utilizou um modelo em duas etapas no Havaí: primeiro estimou a probabilidade de ocorrer pelo menos um ataque em um mês; depois modelou a quantidade de ataques quando um incidente ocorria.

Essa separação é relevante para o projeto porque reforça a diferença entre ocorrência de um evento e quantidade de eventos. A primeira versão do TCC tratará apenas da ocorrência diária, mantendo a quantidade de ataques como variável secundária.

[Sharktober: tiger shark parturition drives seasonality in shark bite incidents](https://doi.org/10.3389/fmars.2025.1587902)

### Revisão sistemática de 2025

Uma revisão sistemática recente reuniu os principais fatores estudados em ataques de tubarão e mostrou que os resultados sobre temperatura, chuva e fase lunar ainda são inconsistentes entre regiões e estudos.

Isso reforça que o TCC deve tratar o modelo como uma avaliação empírica de generalização, e não como confirmação de que uma variável ambiental causa ataques.

[Global systematic review of the factors influencing shark bites](https://doi.org/10.1016/j.gecco.2025.e03684)

### Contribuição pretendida

A contribuição do TCC não será afirmar que ninguém estudou clima e ataques de tubarão. A contribuição será integrar:

- painel diário global;
- segmentos costeiros replicáveis;
- clima da Open-Meteo;
- variáveis lunares calculadas;
- classificação de risco relativo;
- avaliação de generalização para Pernambuco.

## 5. Plano técnico de implementação

### Etapa 1 — Auditoria e padronização da base

Usar `GSAF_clima_lua.csv` como base inicial.

Procedimentos:

- normalizar nomes de países, estados e localidades;
- corrigir variações de mês;
- transformar ano, mês e dia em datas;
- separar datas exatas de registros com dia desconhecido;
- normalizar latitude e longitude;
- identificar ataques duplicados ou múltiplos no mesmo dia;
- utilizar dias positivos com data exata ou data `Reported` aceita como aproximação no modelo diário;
- produzir um relatório de qualidade com linhas removidas e motivos.

Registros com dia desconhecido não receberão artificialmente o dia 1 ou 15 na variável-alvo.
Datas `Reported` são aceitas sob a hipótese de que o intervalo entre ataque e notícia
seja pequeno. Esse intervalo não foi medido. A flag de aproximação será preservada
para permitir comparação posterior com um recorte restrito às datas exatas.

#### Execução da etapa 1 — versão v001 (23/10/2026)

A implementação reproduzível está em `scripts/clean_data.py`. A fonte inicial foi
preservada. Os resultados estão em `Data/`, sempre com sufixo de versão sequencial
compartilhado por execução. Novas execuções escolhem a próxima versão livre e não
sobrescrevem resultados anteriores.

- `gsaf_limpa_v001.csv`: 5.250 registros, após remover 3 duplicações comprovadas.
- `gsaf_eventos_data_exata_v001.csv`: 4.741 registros com data exata confirmada.
- `gsaf_datas_nao_exatas_v001.csv`: 509 registros retidos sem data exata confirmada.
- `gsaf_dias_positivos_local_v001.csv`: 4.438 pares positivos de localidade e data,
  reunindo 4.549 registros com data exata, localidade, país e coordenadas numéricas.
- `gsaf_qualidade_v001.md`, `gsaf_auditoria_v001.csv` e arquivos de evidências,
  normalizações e manifesto: regras, exclusões, contagens e rastreabilidade.

A conferência do arquivo anterior em `Old Data/Md` permitiu distinguir vítimas
diferentes de duplicações reais e separar datas de notícia (`Reported`), datas
numéricas ambíguas e conflitos de ano. A ausência de dia não é a única razão para
uma data ficar fora do modelo diário. Os campos brutos foram preservados, e o
enriquecimento climático/lunar foi esvaziado nos registros sem data exata.

O resumo por localidade é provisório: a unidade principal permanece **segmento
costeiro + data**. Coordenadas numericamente válidas ainda precisam de validação
espacial, e a seleção de tipos de incidente deve ser definida antes do treinamento.
O clima e a lua antigos não substituem o enriquecimento padronizado das etapas 4 e 5.

#### Atualização da etapa 1 — versão v002 (23/10/2026)

A política atual inclui os 223 registros com `date_status=reported_date` e data
completa válida no recorte diário. A hipótese é tratar o dia de registro como
aproximação do dia do ataque, sem afirmar que o intervalo foi observado ou medido.
Esses registros mantêm `date_is_approximate=1`. Datas exatas mantêm a flag igual a 0.
A fonte inicial foi arquivada em `Old Data/GSAF_clima_lua.csv`; esse é o caminho
padrão atualizado do script, com o mesmo conteúdo usado na v001.

O arquivo elegível passa a se chamar `gsaf_eventos_diarios_v002.csv`, pois inclui
datas exatas e aproximadas. Os registros ainda inelegíveis ficam em
`gsaf_datas_inelegiveis_v002.csv`. O resumo por localidade e dia inclui as contagens
`exact_attack_count` e `reported_attack_count`, além da flag `has_reported_date`.
Os produtos v001 são preservados como histórico da política anterior.

A v002 contém 4.964 registros elegíveis pela data (4.741 exatos e 223 Reported),
286 registros com data ainda inelegível e 4.611 pares positivos de localidade/data,
que agregam 4.723 registros com os requisitos geográficos preenchidos. A base
completa retida continua com 5.250 registros.

Dia desconhecido, formatos numéricos ambíguos, intervalos explícitos e conflitos de
ano continuam excluídos. O enriquecimento antigo dos registros Reported elegíveis
é preservado para o dia adotado como aproximação. As mesmas exigências geográficas
continuam valendo para o agrupamento por localidade. As flags e contagens do próprio
dia servem à auditoria e não serão usadas como preditores.

#### Entrada enxuta da modelagem — versão v003 (23/10/2026)

O arquivo de partida da etapa espacial é `Data/01_limpeza/v003/gsaf_eventos_modelagem_v003.csv`.
O script agora localiza a única fonte `GSAF_clima_lua.csv` no projeto, atualmente
em `Old Data/Md`, acompanhando sua reorganização sem alterar seu conteúdo.
Ele preserva os 4.964 eventos com data elegível, com data, país, estado, localidade,
latitude, longitude, identificador e flags de precisão temporal e qualidade espacial.
Não contém hora, espécie, tamanho do tubarão, atividade nem cópias dos valores brutos.
São 4.862 registros com coordenadas numericamente válidas e 102 sem par válido,
sinalizados para recuperar coordenadas. Os 139 registros sem nome de localidade
mas com coordenadas válidas são mantidos para a atribuição aos segmentos.

O resumo provisório por localidade exige país e localidade preenchidos e coordenadas
válidas. Entre os 4.964 eventos com data elegível, 241 não entram nesse resumo:
237 sem localidade, 102 sem coordenadas e 9 sem país, com sobreposição entre motivos.
Os 4.723 eventos representados no resumo se agregam em 4.611 pares localidade/data.
A diferença de 112 linhas é agregação de múltiplos registros, preservados em
`attack_count`. Essas exigências textuais do resumo não filtram a entrada enxuta.

A tabela de eventos ainda não é a base final de treinamento. Ela alimentará a
atribuição aos segmentos e a criação de uma linha por `segment_id + date`, com
alvo `attack` igual a 0 ou 1, coordenadas do segmento, clima regional, lua e
sazonalidade. O enriquecimento antigo por ponto de ataque permanece na base completa
para rastreabilidade, sem substituir o processamento uniforme das etapas 4 e 5.
IDs, nomes, flags de qualidade e contagens do próprio dia não são automaticamente
preditores. A versão v003 não muda as regras temporais nem remove novos eventos.

### Etapa 2 — Construção dos segmentos costeiros

Usar uma base global de linha costeira e criar segmentos seguindo a distância ao longo da costa, em vez de uma grade retangular de latitude e longitude.

Procedimento principal:

1. dividir a costa em segmentos de aproximadamente 25 km;
2. preservar segmentos independentes para ilhas;
3. atribuir cada ataque ao segmento costeiro mais próximo;
4. usar uma distância máxima para evitar atribuição incorreta de ataques mal geocodificados;
5. armazenar a geometria e o identificador de cada segmento;
6. gerar versões alternativas com 10 km e 50 km;
7. manter uma tabela de correspondência entre ataque, segmento e distância até a costa.

A segmentação-base deverá ser geométrica e independente dos ataques. O mapa de calor será usado para inspeção e validação visual, não para desenhar regiões manualmente.

A união adaptativa será usada somente quando um segmento tiver poucos dias positivos. A regra inicial será unir segmentos costeiros vizinhos até obter pelo menos 10 dias positivos distintos, sem ultrapassar quatro segmentos-base. Regiões que continuarem com poucos dados serão mantidas no mapa, mas excluídas do modelo principal.

#### Atlas da etapa 2 — versão v004 (05/11/2026)

O **Atlas Costeiro** é a interface de inspeção dos resultados desta etapa. O mapa
permite comparar os recortes de 10, 25 e 50 km, buscar segmentos e eventos e
inspecionar a distância e a decisão de atribuição. A animação percorre os anos
dos registros; ela não estima risco nem representa observação contínua da costa.
A [versão publicada do atlas](https://atlas-costeiro-gsaf.mysticcake16.chatgpt.site)
é privada e requer login com a conta proprietária.

A geometria de análise usa a linha costeira e as ilhas menores do
[Natural Earth 1:10 milhões](https://www.naturalearthdata.com/downloads/10m-physical-vectors/).
O [mapa-base 1:110 milhões](https://www.naturalearthdata.com/downloads/110m-physical-vectors/)
é apenas visual. Os comprimentos de segmento (10/25/50 km) e o limite operacional
de atribuição (25 km) têm funções diferentes: um controla como a linha é
dividida; o outro controla quão distante dela um registro pode estar. O limite
não é uma medida de precisão da geocodificação e deve ser reavaliado na análise
de sensibilidade. A compatibilidade geográfica também é verificada para não
aceitar automaticamente um ponto próximo à costa de outro país.

O inventário mantém os 4.964 eventos elegíveis pela data, inclusive os 102 sem
coordenadas e os 223 com data `Reported`. A falta de topônimo não impede uma
atribuição quando as demais verificações permitem usar o ponto. Registros sem
atribuição permanecem na correspondência com sua situação, para revisão. O
resultado desta etapa contém registros positivos e segmentos; os dias sem
registro, o clima regional e as variáveis lunares do painel vêm nas etapas seguintes.

O recorte de 25 km tem 41.735 segmentos; os recortes de 10 e 50 km têm 98.003 e
23.376. Foram atribuídos 4.434 eventos. Entre os 530 sem atribuição, 102 estão
sem coordenadas, 311 estão além do limite, 86 têm incompatibilidade de país e
31 precisam de revisão do país ou território. Das 884 regiões adaptativas com
eventos, 142 atendem ao mínimo de dez datas distintas; elas contêm 2.580 registros.

O relatório `Data/historico/02_segmentacao/v004/gsaf_segmentacao_relatorio_v004.md` documenta as fontes,
os controles de distância e os resultados. A correspondência por evento e
escala está em `Data/historico/02_segmentacao/v004/gsaf_eventos_segmentos_v004.csv`.
As regiões adaptativas e as geometrias `gsaf_segmentos_{10,25,50}km_v004.geojson.gz`
estão na mesma pasta.

#### Revisão da atribuição costeira — v005 (05/11/2026)

O geocodificador original consultava combinações de localidade, estado e país
e podia recorrer apenas a estado e país. A coordenada resultante representa
uma referência geográfica aproximada. A distância calculada até a costa é
a distância a partir dessa referência, e não a distância medida do ataque.

O caso Farallon revelou uma limitação da regra anterior: a linha costeira
representa o arquipélago, mas o polígono administrativo usado para conferir o
país não inclui essas ilhas. A associação é recuperada pelo topônimo e pela
confirmação do [U.S. Fish & Wildlife Service](https://www.fws.gov/refuge/farallon-islands/about-us).
Para registros que citam o arquipélago ou uma ilha que a geometria não distingue,
o trecho disponível é uma aproximação. As coordenadas originais não são alteradas.

O recorte revisado mantém o critério de 25 km para vínculos padrão e permite
vínculos provisórios até 75 km quando há contexto costeiro específico e
compatibilidade geográfica. Exceções e territórios são verificados dentro do
contexto informado. Uma distância maior, por si só, não confirma nem invalida
um registro. O método fica identificado para comparação futura entre o recorte
estrito e o recorte que inclui as aproximações recuperadas.

Foram recuperadas 54 associações sem remover vínculos da v004: 31 por revisão
de topônimo ou território (incluindo os oito registros de Farallon) e 23 pela
distância ampliada. A v005 tem 4.488 registros associados e 476 pendentes.
As escalas permanecem 10, 25 e 50 km; as regiões adaptativas passam a 903,
das quais 144 alcançam o mínimo de dez datas positivas distintas. Os arquivos
`Data/02_segmentacao/v005/gsaf_segmentacao_relatorio_v005.md` e `Data/02_segmentacao/v005/gsaf_segmentacao_transicoes_v005.csv`
registram as regras e as decisões por evento.

Para abrir uma cópia local da versão atual do atlas, execute na raiz do projeto:

```powershell
python Scripts/preparar_atlas.py --version v005 --serve
```

O servidor imprime `http://127.0.0.1:8765/`. A interface recebe apenas as projeções
cartográficas versionadas e não requer acesso ao CSV bruto no navegador.

Para reproduzir a segmentação, instale as dependências fixadas em
`Scripts/requirements-segmentacao.txt` e execute `Scripts/segment_coast.py` com
`--as-of` (data ISO), `--source-version v004` e uma nova `--version`. As versões
anteriores permanecem preservadas. Os manifestos em `Data/` registram os hashes das
fontes, dos resultados e dos arquivos usados pela página.

### Etapa 3 — Construção do painel diário

O painel de 25 km v006 e seu relatório estão em [Data/03_painel_diario/v006](../Data/03_painel_diario/v006/).

Usar uma janela ativa individual para cada segmento:

```text
primeira data válida de ataque do segmento
até
última data válida de ataque do segmento
```

Para cada segmento elegível, gerar todos os dias desse intervalo. Um segmento com ataques entre 1995 e 2015 terá os dias positivos e negativos desse período. Outro segmento costeiro poderá ter uma janela diferente.

Os dias negativos são criados por segmento, e não globalmente. Por exemplo:

```text
segmento_A + 2000-01-01 + clima_A + ataque=0
segmento_B + 2000-01-01 + clima_B + ataque=0
```

As duas linhas representam unidades distintas, mesmo tendo a mesma data. A data não precisa ser gerada duas vezes dentro do mesmo segmento, mas precisa existir para cada segmento que esteja sendo modelado naquele dia.

Agrupar os ataques por:

```text
segment_id + date
```

Criar:

```text
attack = 1 se houver pelo menos um ataque
attack = 0 caso contrário
attack_count = quantidade de ataques no dia
```

A variável `attack_count` será preservada para análises complementares, mas não será usada como entrada do classificador.

O painel final será uma tabela de dados em painel, com exatamente uma linha por par `segmento + data`. A ausência de ataque será interpretada como ausência de registro na base dentro da janela ativa daquele segmento e da hipótese metodológica adotada.

Não serão criados dias negativos para segmentos sem nenhum ataque registrado, porque não há uma janela observacional mínima que permita distinguir ausência de ataque de ausência de cobertura. Esses segmentos poderão aparecer em mapas ou análises descritivas, mas ficarão fora do painel principal de treinamento.

### Etapa 4 — Clima regional

A base expandida usa o ERA5 horário original do Copernicus, em um snapshot público
do espelho Icechunk da Earthmover. `Scripts/build_climate_panel.py` extrai as células
dos trechos do painel v006 e gera um Parquet em `Data/04_clima/`, acompanhado de mapa
das células, relatório e manifesto. A [v008](../Data/04_clima/v008/) cobre o painel
v006. O [piloto v007](../Data/historico/04_clima/v007/) avaliou Recife, Califórnia
e a costa oeste da Austrália.

O processo usa:

- selecionar três pontos fixos por segmento, aproximadamente nos extremos e no centro;
- consultar os blocos horários que intersectam os intervalos do painel, com margem para chuva antecedente;
- usar cache;
- baixar uma vez cada bloco da grade e agrupar os três pontos pela célula selecionada;
- evitar uma requisição por linha do painel;
- registrar falhas, lacunas e pontos sem retorno.

Para cada segmento e data, calcular:

- temperatura média;
- precipitação média;
- velocidade média do vento;
- velocidade máxima do vento;
- direção do vento convertida em componentes seno/cosseno;
- chuva acumulada nos 3 e 7 dias anteriores.

A regra de agregação será igual para dias positivos e negativos. O clima não será consultado no ponto exato do ataque para os positivos e em um ponto arbitrário para os negativos.

O agrupamento diário usa o fuso local do trecho. A chuva horária corresponde à
hora que termina no horário fornecido pelo ERA5. A temperatura representa a
estimativa da reanálise para o ar a 2 m da superfície.

### Etapa 5 — Variáveis lunares e sazonais

O [calendário lunar v009](../Data/05_lua/v009/gsaf_calendario_lunar_v009.csv)
cobre as 31.545 datas distintas do painel v006. `Scripts/build_lunar_calendar.py`
usa o PyEphem para calcular as variáveis da Lua uma vez por data, às 12h UTC.

- `moon_illumination` guarda a fração iluminada.
- `moon_phase_deg` guarda o ângulo da fase, com seno e cosseno para o modelo.
- `moon_phase` rotula o setor de 45° mais próximo para inspeção.
- `year` guarda o ano bruto. `day_of_year`, `day_of_year_sin` e
  `day_of_year_cos` representam a posição no calendário com ajuste de ano bissexto.

A chave `date` vincula o calendário aos trechos. Latitude, longitude e eventual
classificação de hemisfério ou bacia vêm da geometria dos segmentos na montagem
da base de treino.

### Etapa 6 — Variáveis excluídas

Não utilizar como preditores principais:

- espécie;
- tamanho do tubarão;
- atividade;
- horário;
- hora;
- número de ataques do próprio dia.

Essas variáveis são incompletas, posteriores ao evento ou indisponíveis para os dias sem ataque.

### Etapa 7 — Modelos

Treinar inicialmente:

1. baseline climatológico por região e época do ano;
2. regressão logística regularizada;
3. modelo de árvores, como Random Forest ou HistGradientBoosting.

Não utilizar redes neurais na primeira versão.

O desbalanceamento natural será preservado na validação e no teste. No treinamento, poderão ser usados pesos de classe. Se houver redução do número de negativos no treinamento, a validação deverá manter uma distribuição representativa e as probabilidades deverão ser recalibradas.

As probabilidades serão calibradas posteriormente. As categorias baixa, média e alta serão apenas uma camada de apresentação e não as classes originais do treinamento.

### Etapa 8 — Avaliação global

Usar divisão temporal, sem embaralhamento aleatório:

- treinamento: período inicial;
- validação: período intermediário;
- teste: período final.

Avaliar:

- PR-AUC;
- ROC-AUC como métrica secundária;
- Brier Score;
- Log Loss;
- calibração;
- recall entre os dias classificados como de maior risco;
- comparação com os baselines.

Acurácia não será usada como métrica principal, porque um classificador que prevê quase todos os dias como negativos pode apresentar acurácia alta e utilidade baixa.

### Etapa 9 — Avaliação em Pernambuco

Pernambuco será utilizado como avaliação de generalização espacial.

Procedimento principal:

- retirar os segmentos costeiros de Pernambuco do treinamento;
- treinar o modelo com as demais regiões;
- aplicar o modelo aos segmentos pernambucanos;
- comparar o desempenho com o baseline local;
- reportar intervalos de incerteza, pois o número de dias positivos é pequeno.

Uma análise temporal interna em Pernambuco poderá ser adicionada se houver quantidade suficiente de eventos posteriores para formar um teste confiável.

O resultado deverá ser descrito como estudo de caso e avaliação de transferência geográfica, não como validação definitiva de um sistema de alerta.

## 6. Arquivos e produtos esperados

A implementação deverá produzir:

- `regions.geojson`: segmentos costeiros e geometrias;
- `region_day_panel.parquet` ou `.csv`: painel diário final;
- tabela de clima por segmento e data;
- tabela de lua por data;
- modelos treinados;
- métricas globais;
- métricas de Pernambuco;
- mapas de segmentos e distribuição de ataques;
- gráficos de calibração e risco;
- documentação metodológica em Markdown.

Os arquivos intermediários grandes deverão ser preferencialmente salvos em formato Parquet para reduzir espaço e acelerar leituras. O CSV poderá ser exportado para inspeção e apresentação.

## 7. Testes e critérios de aceitação

Antes do treinamento final, verificar:

- nenhuma data positiva duplicada indevidamente;
- ataques no mesmo segmento e dia agregados corretamente;
- nenhuma variável pós-ataque usada como entrada;
- todos os dias do painel possuem rótulo;
- clima positivo e negativo calculado pela mesma regra;
- fase lunar consistente para a mesma data;
- ataques sem coordenadas identificados em relatório;
- segmentos de 10, 25 e 50 km comparáveis;
- divisão temporal sem vazamento;
- Pernambuco realmente ausente do treinamento na avaliação espacial;
- resultados comparados com baselines;
- probabilidades calibradas antes da criação das categorias de risco.

Também deverá ser feita uma verificação de sensibilidade para confirmar se os resultados mudam radicalmente quando:

- o tamanho do segmento muda;
- segmentos esparsos são unidos;
- a fase lunar é removida;
- as variáveis climáticas são substituídas apenas por sazonalidade;
- o modelo usa ou não coordenadas geográficas.

## 8. Limitações que deverão aparecer na conclusão

O trabalho deverá declarar que:

- ausência na GSAF significa ausência de registro, não necessariamente ausência absoluta de incidente;
- a base não possui denominador de exposição, como número de banhistas ou horas na água;
- o clima da Open-Meteo representa condições ambientais agregadas e não necessariamente condições oceânicas locais;
- o modelo histórico não equivale a uma previsão meteorológica operacional;
- a qualidade dos registros varia por país, período e região;
- Pernambuco possui poucos exemplos positivos para conclusões locais fortes;
- baixa performance também será um resultado válido;
- o sistema não deverá ser apresentado como ferramenta oficial de segurança ou alerta à população;
- os resultados representam associação e capacidade preditiva, não causalidade ambiental.

## 9. Assumptions and defaults

- Formato da documentação: Markdown.
- Unidade principal: segmento costeiro por dia.
- Janela temporal principal: primeira à última data válida de cada segmento.
- Segmentação-base: trechos costeiros de 25 km ao longo da linha costeira.
- Sensibilidade espacial: 10 km e 50 km.
- União adaptativa: segmentos vizinhos com menos de 10 dias positivos, limitada a quatro segmentos-base.
- Ataque positivo: pelo menos um registro no segmento e na data.
- Dias com dia desconhecido: excluídos do alvo diário.
- Datas Reported: elegíveis como aproximação do dia do ataque, com flag preservada.
- Lua: calculada localmente, sem API.
- Clima: ERA5 horário via espelho Earthmover, extraído em blocos e com cache.
- Pernambuco: avaliação externa de generalização, não conjunto principal de treinamento.
- Modelo inicial: regressão logística regularizada e modelo de árvores.
- Categorias baixa/média/alta: derivadas somente após calibração.
- Uso do mapa de calor: exploração e validação visual, não definição manual das regiões.
