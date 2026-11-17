# Dados do TCC

| Pasta | Conteúdo |
| --- | --- |
| [01_limpeza/v003](01_limpeza/v003/) | Base limpa, eventos elegíveis e auditoria. A entrada da segmentação é `gsaf_eventos_modelagem_v003.csv`. |
| [02_segmentacao/v005](02_segmentacao/v005/) | Eventos por segmento, geometrias de 10, 25 e 50 km, regiões adaptativas e relatório. |
| [03_painel_diario/v006](03_painel_diario/v006/) | [Painel diário de 25 km](03_painel_diario/v006/gsaf_painel_diario_25km_v006.parquet), relatório de qualidade e manifesto. |
| [04_clima/v008](04_clima/v008/) | [Clima diário ERA5](04_clima/v008/gsaf_clima_diario_25km_v008.parquet), células da grade, relatório e manifesto. |
| [05_lua/v009](05_lua/v009/) | [Calendário lunar e sazonal](05_lua/v009/gsaf_calendario_lunar_v009.csv), relatório e manifesto. |
| [atlas/v005](atlas/v005/) | Índice, dados cartográficos, manifesto e pacote da versão publicada do atlas. |
| [atlas/v010](atlas/v010/) | Dados e manifesto da página Clima e Lua, além do pacote atualizado do site. |
| [atlas/v011](atlas/v011/) | Médias comparativas por data e área, manifesto e pacote com a comparação de dias com e sem registro. |
| [fontes](fontes/) | Camadas Natural Earth, revisão de topônimos e cache local do ERA5 em `era5/.cache/`. |
| [historico](historico/) | Segmentação e atlas v004, além do piloto climático v007. |

Os dados originais e as versões v001 e v002 continuam em [Old Data](../Old%20Data/).
Cada execução mantém o mesmo sufixo nos seus produtos. Quando uma versão for
substituída, mova a pasta da versão para `historico/<etapa>/`.

Os manifestos existentes foram preservados. Para referências antigas no formato
`Data/<arquivo>`, procure o mesmo nome nas pastas acima e confira o hash SHA-256.

O Parquet climático é versionado pelo Git LFS. Para baixá-lo em um clone,
execute `git lfs install` e `git lfs pull` na raiz do repositório.
