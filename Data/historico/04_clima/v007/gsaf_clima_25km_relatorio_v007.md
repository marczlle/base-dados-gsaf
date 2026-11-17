# Clima ERA5 de 25 km — v007

Trechos processados: 3. Linhas: 42.
Arquivo horário replicado pela Earthmover. Snapshot Icechunk `VKGPX45BPEQJMVZZXZEG`. Blocos: 3.

## Regras

- Células ERA5 de 0,25° mais próximas do início, centro geodésico e fim de cada trecho. Cada célula distinta tem o mesmo peso.
- Fuso IANA encontrado no centro, com busca de terra próxima quando o centro está no mar; último recurso é o fuso náutico.
- Temperatura em °C, chuva total em mm e vento em km/h. Calcular médias horárias espaciais antes dos resumos diários.
- Velocidade vem de √(u² + v²) em cada célula. Direção meteorológica vem do vetor médio diário, com seno e cosseno derivados.
- A chuva etiquetada em t abrange a hora anterior. Atribuí-la pelo ponto médio do intervalo, inclusive em fusos fracionários.
- Calcular chuva antecedente usando apenas os 3 ou 7 dias anteriores, com janela completa.
- Campos ficam nulos quando faltam horas para a agregação. Horas nunca são preenchidas artificialmente.

## Valores ausentes

| Campo | Linhas sem valor |
| --- | ---: |
| `temperature_2m_mean` | 0 |
| `precipitation_sum` | 0 |
| `wind_speed_10m_mean` | 0 |
| `wind_speed_10m_max` | 0 |
| `wind_direction_10m_dominant` | 0 |
| `wind_direction_sin` | 0 |
| `wind_direction_cos` | 0 |
| `precipitation_previous_3d` | 0 |
| `precipitation_previous_7d` | 0 |
