# Analisador Inteligente de Matrículas — arquitetura e plano

Princípio central: transformar a matrícula em uma história cronológica, visual e **rastreável**, sem inventar
nada. Toda informação exibida aponta para página, ato e trecho original; o que não está no documento aparece
como **"Não identificado no documento analisado."**

## Arquitetura (modular, compatível com o projeto atual)

O projeto já usa FastAPI (Python) + interface web com mapa, publicado na Vercel. O Analisador segue esse padrão
e acrescenta módulos próprios, separados por responsabilidade:

| Camada | Onde | Responsabilidade |
|---|---|---|
| Interface | `web/index.html` (menu "Analisador de Matrícula") | Upload, progresso, painel, linha do tempo, ônus, riscos, visão lado a lado documento × análise |
| Processamento de arquivos | navegador (`pdf.js`) | PDF com texto → texto por página; PDF escaneado/JPG/PNG → imagem por página |
| OCR | navegador (`Tesseract.js`, português) | Texto e **confiança** por página; nenhum arquivo sai do navegador nesta fase |
| Extração estruturada | `analisador/extracao.py` | Identificação, separação R-/AV-, datas, páginas, sequência e lacunas |
| Motor de regras | `analisador/regras.py` (Fases 4–7) | Cadeia dominial, ônus × cancelamentos, área/perímetro, atualidade, riscos |
| Interpretação por IA | `analisador/ia.py` (Fase 8) | Explicações em linguagem simples **a partir dos fatos extraídos**; chave só no servidor |
| Relatórios | `analisador/relatorio.py` (Fase 10) | PDF técnico com referências a página e ato |
| Banco de dados | Supabase/PostgreSQL (fase de persistência) | Usuários, documentos, atos, ônus, alertas, correções — com isolamento por usuário (RLS) |

Regras de confiabilidade (valem para todas as fases):

1. Cada dado extraído carrega `fonte = {pagina, ato, trecho, metodo (texto|ocr), confianca}`.
2. Ônus só é **BAIXADO/CANCELADO** quando há ato registral expresso que o cancela; quitação financeira ≠ cancelamento.
3. Sem evidência, o campo fica `null` e a interface mostra "Não identificado no documento analisado.".
4. A IA não cria fatos: recebe os atos já extraídos e só redige explicações, marcadas como **interpretação**.
5. Correções manuais guardam o texto original e o histórico de alterações.

## Fases

| Fase | Conteúdo | Situação |
|---|---|---|
| 1 | Estrutura, menu, upload de PDF/JPG/PNG com várias páginas, progresso | ✅ concluída |
| 2 | Leitura integral por página (texto ou OCR com confiança), visualização do texto original | ✅ concluída |
| 3 | Identificação e classificação de registros e averbações (páginas, datas, sequência, lacunas) | ✅ base concluída |
| 4 | Cadeia dominial e sucessões (linha do tempo de proprietários) | pendente |
| 5 | Ônus, garantias e baixas (constituição ↔ cancelamento) | pendente |
| 6 | Localização e caracterização (reaproveita o leitor de perímetro e o mapa) | pendente |
| 7 | Motor de riscos e inconsistências | pendente |
| 8 | Tradutor jurídico (versão técnica × simplificada) | pendente |
| 9 | Dashboard completo e linha do tempo | parcial (indicadores da Fase 3) |
| 10 | Relatório técnico em PDF | pendente |
| 11 | Testes de precisão com o conjunto de casos | contínuo |
| — | Persistência (Supabase), login, isolamento e registro de atividades | depende de decisão (ver abaixo) |

## Decisões pendentes

- **Persistência e login:** Supabase (PostgreSQL + Storage + Auth com RLS). Até lá, as análises ficam salvas só no
  navegador de quem analisou (IndexedDB).
- **IA:** chave da API do modelo de linguagem configurada apenas no servidor (variável de ambiente na Vercel).
- **Repositório público:** para tratar documentos de clientes, tornar o repositório privado. Nenhum documento real
  é versionado; os testes usam matrículas fictícias.

## Identidade visual

Paleta oficial: primária `#142D3A` (menu lateral), secundária `#315568`, fundo `#F4F5F2`, superfície `#FFFFFF`,
destaque `#C6A66B` (uso pontual: item ativo, marca, realce de trecho), sucesso `#27866A`, alerta `#D49A3A`,
perigo `#C65353`. Tipografia Inter, ícones Lucide (versão fixada), cantos de 8–12 px, sombras suaves e tabelas com
cabeçalho discreto e linhas espaçadas. Cores cartográficas (vias do IPPUL, hidrografia, masterplan) seguem as
convenções de mapa e não a paleta da interface.
