# fifa_player_database_v4.sqlite — notas de qualidade

Consolidado em 12/07/2026. 13 tabelas, 100 partidas (grupos + R32 + R16 + Quartas completas).

## Cobertura por tabela
| Tabela | Partidas | Observação |
|---|---|---|
| matches | 100 | inclui M99 (NOR-ENG) e M100 (ARG-SUI), adicionadas nesta atualização |
| player_match_minutes_all | 98 | **M99/M100 não têm escalação de linha completa em nenhuma fonte fornecida** — só goleiros |
| player_stats_long_all / wide_all | 98 | mesma limitação acima; dedupe de M01/M02/M07/M47 já aplicado |
| goalkeeper_player_match_stats_mapped / team_stats | 100 | goleiros cobrem as 100 partidas |
| player_rankings_by_position, team_summary, match_team_summary, player_percentiles, player_style_profiles, goalkeeper_advanced_rankings | 100 | base "clean" — sem gols/chutes/xG/desarmes individuais (ver abaixo) |

## Limitações conhecidas (não são bugs, são lacunas de dados-fonte)
- **Nenhuma tabela tem gols, chutes, assistências, xG ou desarmes/interceptações individuais.** Essas métricas foram removidas na extração "clean" por terem mapeamento de coluna quebrado na base anterior (ex.: um volante aparecia com 78 gols). Ficou só: passe (volume/precisão), oferta/recepção de bola, físico (distância/sprints/velocidade) e uma métrica composta de "ações defensivas" (proxy, não é contagem de desarme).
- `minutes_total`, `line_breaks_pdf`, `shots_pdf`, `xg_pdf`: 100% nulos em `player_percentiles` / `player_rankings_by_position` para todos os 1.252 jogadores.
- `player_style_profiles`: as colunas `ataque_proxy_index` e `progressao_passe_index` foram **removidas** desta versão — vinham 100% vazias pra todo mundo (dependiam dos campos nulos acima). `style_profile_dictionary` também já não lista essas duas.
- Corrigido nesta atualização: duplicata "Marcos SENESI" (Argentina) em `player_percentiles` e `player_style_profiles` — mantida a linha com dados, removida a vazia.
