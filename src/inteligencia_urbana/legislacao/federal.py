"""Regras federais aplicáveis ao parcelamento, incorporação e regularização.

Fontes principais:
- Lei 6.766/1979 (parcelamento do solo urbano)
- Lei 12.651/2012 (Código Florestal) — APPs; Lei 14.285/2021 (APP em área urbana consolidada)
- Lei 13.465/2017 (REURB)
- Lei 4.591/1964 (incorporação) e Lei 10.931/2004 (patrimônio de afetação / RET)

A legislação municipal pode ser mais restritiva e prevalece no que for de sua competência.
"""

from __future__ import annotations

from dataclasses import dataclass

# Lei 6.766/1979, art. 4º, II
LOTE_MINIMO_FEDERAL_M2 = 125.0
TESTADA_MINIMA_FEDERAL_M = 5.0
# Lei 6.766/1979, art. 4º, III (faixa não edificável ao longo de rodovias e ferrovias)
FAIXA_NAO_EDIFICAVEL_RODOVIA_M = 15.0
# Lei 6.766/1979, art. 3º, parágrafo único, III
DECLIVIDADE_MAXIMA_SEM_EXIGENCIAS_PCT = 30.0


def app_curso_dagua(largura_leito_m: float) -> float:
    """Largura mínima da APP (cada margem) — Código Florestal, art. 4º, I.

    Em área urbana consolidada, lei municipal pode fixar outras faixas
    (Lei 14.285/2021, que alterou o art. 4º, §10 do Código Florestal).
    """
    if largura_leito_m < 10:
        return 30.0
    if largura_leito_m < 50:
        return 50.0
    if largura_leito_m < 200:
        return 100.0
    if largura_leito_m < 600:
        return 200.0
    return 500.0


APP_NASCENTE_RAIO_M = 50.0  # art. 4º, IV
APP_LAGO_NATURAL_URBANO_M = 30.0  # art. 4º, II, b


@dataclass
class VerificacaoLote:
    conforme: bool
    pendencias: list[str]


def verificar_lote_federal(area_m2: float, testada_m: float, interesse_social: bool = False) -> VerificacaoLote:
    pend = []
    if not interesse_social:
        if area_m2 < LOTE_MINIMO_FEDERAL_M2:
            pend.append(f"Área {area_m2:.2f} m² < mínimo federal de {LOTE_MINIMO_FEDERAL_M2:.0f} m² (Lei 6.766/79, art. 4º, II).")
        if testada_m < TESTADA_MINIMA_FEDERAL_M:
            pend.append(f"Testada {testada_m:.2f} m < mínimo federal de {TESTADA_MINIMA_FEDERAL_M:.0f} m (Lei 6.766/79, art. 4º, II).")
    return VerificacaoLote(not pend, pend)


CHECKLIST_LOTEAMENTO = [
    "Certidão de inteiro teor da matrícula atualizada (≤ 30 dias) e certidão vintenária/filiação (art. 18, II e III)",
    "Certidões negativas de tributos e de ações reais/pessoais/penais dos proprietários (art. 18, III e IV)",
    "Consulta prévia / diretrizes do município (IPPUL em Londrina) — art. 6º e 7º",
    "Levantamento planialtimétrico cadastral georreferenciado e laudo de declividade",
    "Laudo de caracterização ambiental / delimitação de APP, nascentes e vegetação",
    "Licenciamento ambiental no IAT (Licença Prévia, de Instalação e de Operação, conforme porte)",
    "Projeto urbanístico (quadras, lotes, sistema viário, áreas públicas) e memoriais descritivos",
    "Projetos complementares: água/esgoto (Sanepar), energia/iluminação (Copel), drenagem, pavimentação, terraplenagem",
    "Cronograma físico-financeiro de obras e garantia de execução (caução/hipoteca de lotes) — art. 18, V",
    "Aprovação municipal e, quando aplicável, anuência metropolitana/estadual (art. 13)",
    "Registro no Cartório de Registro de Imóveis em até 180 dias da aprovação (art. 18)",
    "Contrato-padrão de compromisso de compra e venda depositado no registro (art. 18, VI)",
]

CHECKLIST_INCORPORACAO = [
    "Memorial de incorporação (art. 32 da Lei 4.591/1964) — título, certidões, projeto aprovado, NBR 12.721",
    "Quadros de áreas e custos da NBR 12.721 (CUB) e cálculo da área equivalente",
    "Alvará de construção / projeto arquitetônico aprovado",
    "Patrimônio de afetação (Lei 10.931/2004) — habilita o RET (4% sobre receita; 1% em HIS/MCMV elegível)",
    "Convenção de condomínio (minuta) e instituição de condomínio após habite-se",
    "Prazo de carência (até 180 dias) se previsto, e quadro-resumo nos contratos (Lei 13.786/2018 — distrato)",
]


@dataclass
class ClassificacaoReurb:
    modalidade: str
    fundamentos: list[str]
    instrumentos: list[str]
    documentos: list[str]
    alertas: list[str]


def classificar_reurb(
    baixa_renda_predominante: bool,
    nucleo_consolidado_ate_2016: bool,
    area_publica: bool = False,
    em_app: bool = False,
    em_area_de_risco: bool = False,
) -> ClassificacaoReurb:
    """Classificação preliminar de núcleo urbano informal pela Lei 13.465/2017."""
    fund = ["Lei 13.465/2017, art. 13 (modalidades)", "Decreto 9.310/2018"]
    alertas = []
    if baixa_renda_predominante:
        modalidade = "Reurb-S (interesse social)"
        fund.append("Art. 13, I — núcleo ocupado predominantemente por população de baixa renda")
    else:
        modalidade = "Reurb-E (interesse específico)"
        fund.append("Art. 13, II — demais casos; custos da infraestrutura podem ser atribuídos aos beneficiários")

    instrumentos = []
    if nucleo_consolidado_ate_2016:
        instrumentos.append("Legitimação fundiária (art. 23) — núcleos existentes até 22/12/2016")
    instrumentos.append("Legitimação de posse (art. 25) — conversível em propriedade após 5 anos (art. 26)")
    if area_publica:
        instrumentos.append("Concessão de direito real de uso / doação / alienação de bem público (art. 15 e 71)")
    instrumentos += ["Usucapião (art. 15, II)", "Desapropriação por interesse social (art. 15, VI e VII)"]

    docs = [
        "Levantamento planialtimétrico cadastral georreferenciado (art. 35, I)",
        "Planta do perímetro com matrículas/transcrições atingidas (art. 35, II)",
        "Estudo preliminar das desconformidades e situação jurídica, urbanística e ambiental (art. 35, III)",
        "Projeto urbanístico (art. 36)",
        "Memoriais descritivos (art. 35, V)",
        "Cronograma físico de obras e termo de compromisso (art. 35, IX e X)",
        "Certidão de Regularização Fundiária — CRF (art. 41)",
    ]
    if em_app:
        docs.append("Estudo técnico ambiental (art. 11, §2º; Código Florestal, arts. 64 e 65)")
        alertas.append("Ocupação em APP: regularização condicionada a estudo técnico que demonstre melhoria ambiental.")
    if em_area_de_risco:
        docs.append("Estudo técnico de risco e obras de mitigação (art. 39)")
        alertas.append("Área de risco: unidades não mitigáveis exigem realocação (art. 39, §2º).")
    return ClassificacaoReurb(modalidade, fund, instrumentos, docs, alertas)
