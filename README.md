# Inteligência Urbana

Ferramenta de apoio à **incorporação e ao desenvolvimento urbano**: lê a matrícula do imóvel, interpreta as
diretrizes de parcelamento (IPPUL/Londrina), cruza com o zoneamento municipal, sugere a vocação da área, gera
um **masterplan preliminar** e calcula a **viabilidade** (VGV, CUB, ROI, TIR, VPL, exposição de caixa). Exporta
perímetros, confrontações e masterplan para o **Google Earth** (KML/KMZ).

Municípios iniciais: **Londrina, Cambé, Rolândia e Ibiporã** (PR). Outros entram com um arquivo YAML.

![Masterplan](docs/img/2_masterplan.png)

## Módulos

| Módulo | O que faz |
|---|---|
| `documentos/matricula.py` | Nº da matrícula, cartório, lote/quadra, CCIR/CAR e área declarada (m², ha, alqueire paulista). Lê os atos **R/AV**, classifica 30 tipos e marca ônus como *ativo* ou *possivelmente cancelado*. Também lê o memorial descritivo (vértices em UTM ou lat/long, azimutes/rumos, distâncias, confrontantes), confere área declarada × calculada e o fechamento da poligonal |
| `documentos/consulta_ippul.py` | Diretrizes de parcelamento: zonas, macrozona, lote mínimo, testada, % de áreas públicas, caixas de via, faixas de fundo de vale, trechos por tema (viário, ambiental, infraestrutura, licenciamento) |
| `geo/` | SIRGAS 2000 / UTM 22S (EPSG:31982), SAD-69 e lat/long; DMS; rumo → azimute; área, perímetro e fechamento; KML/KMZ com vértices e confrontações |
| `legislacao/federal.py` | Lei 6.766/79 (lote 125 m², testada 5 m, faixa de 15 m, declividade de 30%), APP do Código Florestal, checklists de loteamento/incorporação e classificação de **REURB** (Lei 13.465/17) |
| `legislacao/zoneamento.py` + `dados/zoneamento/*.yaml` | Parâmetros por zona (CA, TO, permeabilidade, gabarito, lote mínimo, recuos) e análise de **vocação** (loteamento, condomínio de lotes, vertical, misto, logístico, ZEIS) |
| `viabilidade/loteamento.py` | Quadro de áreas, nº de lotes, permuta, VGV, infraestrutura, comissão, impostos e fluxo mensal com vendas parceladas |
| `viabilidade/incorporacao.py` | Área computável/construída/privativa a partir do CA, custo pelo **CUB** × fator, RET (4%), permuta, fluxo com repasse nas chaves |
| `masterplan/gerador.py` | Traçado ortogonal com vias, quadras e lotes, desconto de APP de córregos, alocação de verde e institucional, render **SVG** e GeoJSON/KML |
| `api/main.py` + `web/index.html` | API FastAPI (`/docs`) e interface web com mapa satélite |

## Como rodar

```bash
pip install -e ".[dev]"
```

```bash
uvicorn inteligencia_urbana.api.main:app --reload
```

Abra http://localhost:8000. A documentação da API fica em http://localhost:8000/docs.

```bash
pytest
```

## Avisos importantes

- **Zoneamento:** os YAML de cada cidade trazem a estrutura completa, mas os **índices são ilustrativos**
  (`validado: false`). Antes de usar o estudo para decidir, substitua-os pelos da lei vigente e do mapa oficial.
- **CUB:** não é fixado no código. Informe o valor do mês (Sinduscon-PR, padrão do projeto).
- **Leitura de documentos:** é heurística e funciona em PDF com texto. Matrícula escaneada exige OCR (ver roadmap).
  O resultado apoia a due diligence e **não substitui** a leitura da certidão por profissional habilitado.
- **Masterplan:** é um estudo de massa. Não considera topografia nem drenagem.

Veja o [roadmap](docs/ROADMAP.md).
