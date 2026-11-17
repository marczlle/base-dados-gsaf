# Convenções do projeto

- Preserve os arquivos de origem e as alterações existentes do usuário.
- Salve novos conjuntos de dados e relatórios em `Data/<etapa>/<versão>/`. Use
  `Data/fontes/` para entradas auxiliares, `Data/atlas/` para a publicação do
  mapa e `Data/historico/<etapa>/<versão>/` para versões substituídas.
- Use nomes descritivos com uma versão sequencial: `<produto>_v001.csv`,
  `<produto>_v002.csv`, etc. Não use sufixos como `final`, `novo` ou `final_final`.
- Uma execução deve compartilhar a mesma versão entre todos os seus produtos.
  Não sobrescreva versões existentes. Registre fontes, regras, contagens e hashes.
- Scripts e arquivos convencionais de configuração/instruções mantêm nomes estáveis.
- Nunca invente um dia para registros de data incompleta. Preserve a rastreabilidade
  de exclusões e diferencie múltiplos incidentes/vítimas de duplicações comprovadas.
- Por decisão do pesquisador, datas `Reported` são elegíveis como aproximação do
  dia do ataque. Preserve `date_status=reported_date` e `date_is_approximate=1`.
  Dia desconhecido, intervalos explícitos, ambiguidades e conflitos permanecem inelegíveis.
- A entrada enxuta da modelagem preserva todos os eventos com data elegível, inclusive
  os que não têm nome de localidade. Na etapa de segmentos, use coordenadas e valide
  sua posição; não descarte pontos apenas porque um topônimo está desconhecido.
- Diferencie tabelas de eventos positivos da matriz final de treinamento, cuja unidade
  é segmento + dia e que precisa incluir dias negativos e enriquecimento regional.
