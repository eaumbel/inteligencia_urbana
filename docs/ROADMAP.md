# Roadmap

## Fase 1 — MVP (feito)
- [x] Leitura de matrícula: atos, ônus, memorial georreferenciado, confrontações e conferência de área
- [x] Leitura heurística de diretrizes de parcelamento
- [x] Conversões SIRGAS 2000/SAD-69/lat-long e exportação KML/KMZ para o Google Earth
- [x] Base de zoneamento em YAML (Londrina, Cambé, Rolândia, Ibiporã) e análise de vocação
- [x] Viabilidade de loteamento e de incorporação (VGV, CUB, ROI, TIR, VPL, payback, exposição)
- [x] Masterplan preliminar (SVG + KML) com APP de córregos e áreas públicas
- [x] Classificação preliminar de REURB
- [x] API + interface web com mapa
- [x] Camadas oficiais (IBGE: hidrografia, municípios; CAR via proxy), Street View, camadas do usuário (KML/GeoJSON/WMS)
- [x] Córregos do IBGE → APP automática no masterplan
- [x] OCR no navegador (Tesseract.js, português) para certidões escaneadas; leitor calibrado com certidão real do 3º RI de Londrina
- [x] CAR: camada, consulta por clique e sobreposição com a matrícula (proxy com TLS legado só para o SICAR)

## Fase 2 — Dados oficiais (depende de material do usuário)
- [ ] Preencher e validar os parâmetros de zoneamento de cada cidade a partir das leis vigentes
- [ ] Importar os mapas de zoneamento (shapefile/KML do SIGLON e das prefeituras) para descobrir a zona pelo perímetro
- [ ] Calibrar o leitor de diretrizes com consultas prévias reais do IPPUL
- [ ] Calibrar o leitor de matrícula com certidões reais dos Registros de Imóveis da região
- [ ] Tabela histórica do CUB-PR (atualização mensal)

- [ ] INCRA SIGEF/SNCI (parcelas certificadas): o servidor não respondeu a partir do ambiente de desenvolvimento;
      testar a partir de uma rede brasileira ou importar o shapefile por município
- [ ] Geoportal de Londrina (SIGLON): verificar se publica lotes/zoneamento em WMS/WFS

## Fase 3 — Produto
- [ ] Persistência de projetos e estudos (Supabase/Postgres + PostGIS) e login
- [ ] Relatório de viabilidade em PDF/DOCX com mapa, masterplan e quadros
- [ ] Topografia: importar curvas de nível/MDE, mapa de declividade (bloqueio de ≥ 30%) e hidrografia
- [ ] Masterplan com diretrizes viárias obrigatórias e quadras não ortogonais
- [ ] Cenários e sensibilidade (preço, velocidade de vendas, custo, juros) e correção das parcelas (IPCA/INCC)
- [ ] Importar KML/KMZ/DXF de levantamento topográfico
