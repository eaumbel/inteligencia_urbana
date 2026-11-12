"""Leitura de Consulta Prévia / Diretrizes de Parcelamento do Solo (IPPUL — Londrina).

O IPPUL (Instituto de Pesquisa e Planejamento Urbano de Londrina) emite as diretrizes
para parcelamento: zoneamento incidente, sistema viário a respeitar, percentuais de
áreas públicas, faixas de fundo de vale/APP, exigências de infraestrutura etc.

Este extrator é heurístico e foi escrito sem um modelo oficial do documento: ele
deve ser calibrado com exemplos reais (ver docs/ROADMAP.md).
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field

from ..geo.coordenadas import parse_numero_br

NUM = r"\d[\d.]*(?:,\d+)?"

ZONA_RE = re.compile(r"\b(?!ZONA\b)(Z[A-Z]{1,4}[\s\-]?\d{1,2}[A-Z]?|ZEIS[\s\-]?\d?|ZEPP?|ZUE|ZEU|MZ[A-Z]{1,3})\b")

TEMAS = {
    "sistema_viario": r"via\s+(?:arterial|coletora|local|estrutural|marginal)|diretriz(?:es)?\s+vi[áa]ri|caixa\s+de\s+via|prolongamento",
    "ambiental": r"fundo\s+de\s+vale|\bAPP\b|preserva[çc][ãa]o\s+permanente|nascente|c[óo]rrego|ribeir[ãa]o|mata\s+ciliar|faixa\s+sanit[áa]ria|drenagem",
    "areas_publicas": r"[áa]rea\s+(?:institucional|verde|p[úu]blica|de\s+lazer)|equipamentos?\s+(?:urbanos|comunit[áa]rios)|espa[çc]os?\s+livres",
    "infraestrutura": r"sanepar|copel|rede\s+de\s+(?:[áa]gua|esgoto|energia|drenagem)|pavimenta[çc][ãa]o|ilumina[çc][ãa]o|galerias?\s+pluviais|meio[-\s]fio",
    "lote_minimo": r"lote\s+m[íi]nimo|testada\s+m[íi]nima|frente\s+m[íi]nima",
    "restricoes": r"faixa\s+(?:non\s+aedificandi|n[ãa]o\s+edific[áa]vel)|linha\s+de\s+transmiss|rodovia|ferrovia|gasoduto|aeroporto|cone\s+de\s+aproxima",
    "licenciamento": r"\bIAT\b|licen[çc]a\s+(?:pr[ée]via|ambiental|de\s+instala)|EIV|estudo\s+de\s+impacto|RIMA|\bEIA\b|outorga",
}


@dataclass
class DiretrizesParcelamento:
    numero_consulta: str | None = None
    processo_sei: str | None = None
    caracterizacao: dict = field(default_factory=dict)  # lote, gleba, área total, modalidade, finalidade...
    vias: list[dict] = field(default_factory=list)  # tabela de vias com hierarquia e larguras
    parametros: dict = field(default_factory=dict)  # faixa de transição, quadra máxima, áreas públicas...
    legislacao: list[str] = field(default_factory=list)
    orgaos_consultar: list[str] = field(default_factory=list)
    croqui: dict | None = None
    zonas: list[str] = field(default_factory=list)
    macrozona: str | None = None
    lote_minimo_m2: float | None = None
    testada_minima_m: float | None = None
    percentuais_areas: dict[str, float] = field(default_factory=dict)
    larguras_vias_m: list[float] = field(default_factory=list)
    faixas_m: list[dict] = field(default_factory=list)
    trechos_por_tema: dict[str, list[str]] = field(default_factory=dict)
    alertas: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def _frases(texto: str) -> list[str]:
    partes = re.split(r"(?<=[.;])\s+|\n{1,}", texto)
    return [re.sub(r"\s+", " ", p).strip() for p in partes if len(p.strip()) > 15]


def _caracterizacao(texto: str) -> dict:
    """Quadro "CARACTERIZAÇÃO DO OBJETO DA CONSULTA" (lote, gleba, área total...)."""
    def campo(rotulo, fim=r"(?=\s+[A-ZÀ-Úa-zà-ú][\wÀ-ú. ]{2,40}:|\n|$)"):
        m = re.search(rotulo + r"\s*:\s*(.+?)" + fim, texto, re.I)
        return m.group(1).strip(" .-") if m else None

    area = re.search(rf"[ÁA]rea\s+total\s*:\s*({NUM})\s*(?:m²|m2)", texto, re.I)
    c = {
        "lote": campo(r"\bLote(?!\s+de\s+origem)"),
        "gleba": campo(r"\bGleba"),
        "quadra": campo(r"\bQuadra"),
        "loteamento": campo(r"\bLoteamento(?!\s+Aberto)"),
        "area_total_m2": parse_numero_br(area.group(1)) if area else None,
        "lote_origem": campo(r"Lote\s+de\s+origem"),
        "matricula": campo(r"Matr[íi]cula(?:\s+n[º°o.]*)?"),
        "inscricao_imobiliaria": campo(r"Inscri[çc][ãa]o(?:\s+imobili[áa]ria)?"),
        "modalidade": campo(r"Modalidade", r"(?=\s+Finalidade\s*:|\n\S+:|$)"),
        "finalidade": campo(r"Finalidade"),
        "n_lotes_estimado": campo(r"N[º°o.]*\s+estimado\s+de\s+lotes"),
        "mapa_vinculado": campo(r"Mapa\s+vinculado"),
    }
    if c["modalidade"]:  # "Loteamento Aberto, Condomínio\nUrbanístico"
        m = re.search(r"Modalidade\s*:\s*(.+?)(?:\s+Finalidade\s*:.*?)?\n(\w+)\s*\n", texto)
        if m and m.group(2) in ("Urbanístico", "Urbanistico", "Fechado", "Horizontal", "Industrial"):
            c["modalidade"] = (m.group(1).strip() + " " + m.group(2)).strip()
    if c["n_lotes_estimado"] and re.search(r"N[º°o.]*\s+estimado", c["n_lotes_estimado"]):
        c["n_lotes_estimado"] = None
    return {k: v for k, v in c.items() if v not in (None, "", "-")}


def _vias(texto: str) -> list[dict]:
    """Tabela "LARGURA DAS VIAS DE CIRCULAÇÃO" (VIA 01 Coletora 20,00m ...)."""
    out = []
    for m in re.finditer(rf"\bVIA\s+(\d{{1,2}})\s+(Arterial|Coletora|Local|Estrutural|Expressa|Marginal|Ciclovia)\s+({NUM})\s*m\b((?:\s+{NUM}\s*m)*)",
                         texto, re.I):
        partes = [parse_numero_br(x) for x in re.findall(rf"({NUM})\s*m", m.group(4))]
        via = {"via": f"VIA {int(m.group(1)):02d}", "hierarquia": m.group(2).capitalize(), "largura_total_m": parse_numero_br(m.group(3))}
        if len(partes) >= 2:
            via["calcada_m"], via["pista_m"] = partes[0], partes[1]
        if any(v["via"] == via["via"] for v in out):
            continue
        out.append(via)
    return out


def _parametros(texto: str) -> dict:
    t = re.sub(r"\s+", " ", texto)
    def num(padrao):
        m = re.search(padrao, t, re.I)
        return parse_numero_br(m.group(1)) if m else None
    p = {
        "faixa_transicao_m": num(rf"faixa\s+de\s+transi[çc][ãa]o\s+de,?\s*(?:no\s+m[íi]nimo,?\s*)?({NUM})\s*m"),
        "quadra_max_m": num(rf"maior\s+dimens[ãa]o\s+das\s+quadras\s+n[ãa]o\s+poder[áa]\s+ser\s+superior\s+a\s+({NUM})\s*m"),
        "distancia_coletoras_max_m": num(rf"vias\s+coletoras\s+devem\s+apresentar\s+entre\s+si\s+uma\s+dist[âa]ncia\s+nunca\s+superior\s+a\s+({NUM})\s*m"),
        "areas_publicas_min_pct": num(rf"no\s+m[íi]nimo,?\s*({NUM})\s*%\s*(?:\([^)]*\))?\s*da\s+[áa]rea\s+comput[áa]vel"),
        "declividade_max_pct": num(rf"declividade\s+igual\s+ou\s+superior\s+a\s+({NUM})\s*%"),
        "circulo_minimo_area_publica_m": num(rf"inscrito\s+um\s+c[íi]rculo\s+de\s+({NUM})\s*m"),
        "validade_dias": num(r"validade\s+de\s+(\d+)\s+dias"),
    }
    return {k: v for k, v in p.items() if v is not None}


def analisar_consulta_parcelamento(texto: str) -> DiretrizesParcelamento:
    d = DiretrizesParcelamento()
    m = re.search(r"\bCPS\s*N[º°o.]*\s*([\d/]+)", texto) or re.search(
        r"(?:consulta|diretriz(?:es)?|protocolo)\s*(?:pr[ée]via\s*)?(?:de\s+parcelamento\s+do\s+solo\s*)?(?:n[º°o.]*\s*)?[:\-]?\s*(\d[\d./\-]{3,})", texto, re.I)
    d.numero_consulta = m.group(1).strip(".-/") if m else None
    m = re.search(r"PROCESSO\s+SEI\s*N[º°o.]*\s*([\d./\-]+)", texto, re.I)
    d.processo_sei = m.group(1).strip(".-") if m else None
    d.caracterizacao = _caracterizacao(texto)
    d.vias = _vias(texto)
    d.parametros = _parametros(texto)
    leis = sorted(set(re.sub(r"\s+", " ", x) for x in re.findall(
        r"(?:Lei(?:\s+(?:Municipal|Estadual|Federal|Complementar))?|Decreto(?:\s+Municipal)?)\s+n[º°o.]*\s*\d[\d.]*/\d{4}", texto)))
    num = lambda x: x.split()[-1]
    d.legislacao = [l for l in leis if not any(o != l and num(o) == num(l) and len(o) > len(l) for o in leis)]
    m = re.search(r"OUTROS\s+[ÓO]RG[ÃA]OS\s+P[ÚU]BLICOS.{0,400}", texto, re.I | re.S)
    if m:
        d.orgaos_consultar = list(dict.fromkeys(re.findall(r"(Secretaria\s+Municipal\s+d[eoa]s?\s+[A-ZÀ-Úa-zà-ú ]+?\s*-\s*[A-Z]{2,6}|[ÓO]rg[ãa]o\s+respons[áa]vel\s+pela\s+\w+\s*\([^)]*\))", m.group(0))))

    zonas = []
    for z in ZONA_RE.findall(texto):
        z = re.sub(r"\s", "", z)
        if z not in zonas:
            zonas.append(z)
    d.zonas = zonas

    m = re.search(r"macrozona\s+(?:de\s+|da\s+)?([\wÀ-ú ]{3,60}?)(?:[,.;\n]|$)", texto, re.I)
    d.macrozona = m.group(1).strip() if m else None

    m = re.search(rf"lote\s+m[íi]nimo[^\d]{{0,40}}({NUM})\s*(?:m²|m2|metros\s+quadrados)", texto, re.I)
    d.lote_minimo_m2 = parse_numero_br(m.group(1)) if m else None
    m = re.search(rf"(?:testada|frente)\s+m[íi]nima[^\d]{{0,40}}({NUM})\s*m\b", texto, re.I)
    d.testada_minima_m = parse_numero_br(m.group(1)) if m else None

    for m in re.finditer(
        rf"({NUM})\s*%\s*(?:\([^)]*\)\s*)?(?:da\s+[áa]rea\s+(?:total|lote[áa]vel|da\s+gleba)\s+)?(?:para|de|destinad[oa]s?\s+(?:a|para))?\s*"
        r"(?:[áa]reas?\s+)?(institucional|verde|de\s+lazer|p[úu]blica|sistema\s+vi[áa]rio|equipamentos?\s+\w+|espa[çc]os?\s+livres)",
        texto, re.I,
    ):
        chave = re.sub(r"\s+", "_", m.group(2).lower().replace("de ", ""))
        d.percentuais_areas[chave] = parse_numero_br(m.group(1))

    for m in re.finditer(rf"(?:caixa|largura)\s+(?:de\s+via\s+|total\s+|m[íi]nima\s+)?(?:de\s+)?({NUM})\s*(?:m\b|metros)", texto, re.I):
        v = parse_numero_br(m.group(1))
        if 6 <= v <= 80 and v not in d.larguras_vias_m:
            d.larguras_vias_m.append(v)

    for m in re.finditer(
        rf"faixa\s+([\wÀ-ú\s]{{3,40}}?)\s+(?:de\s+|com\s+)?(?:no\s+m[íi]nimo\s+)?({NUM})\s*(?:m\b|metros)", texto, re.I
    ):
        d.faixas_m.append({"descricao": m.group(1).strip(), "largura_m": parse_numero_br(m.group(2))})

    frases = _frases(texto)
    for tema, padrao in TEMAS.items():
        achados = [f for f in frases if re.search(padrao, f, re.I)]
        if achados:
            d.trechos_por_tema[tema] = achados[:15]

    if not d.zonas:
        d.alertas.append("Nenhuma zona identificada — confira o zoneamento no mapa oficial (SIGLON/IPPUL).")
    if "ambiental" in d.trechos_por_tema:
        d.alertas.append("Há diretrizes ambientais (fundo de vale/APP/drenagem): delimitar faixas antes do estudo de massa.")
    if "licenciamento" in d.trechos_por_tema:
        d.alertas.append("Há menção a licenciamento (IAT/EIV/outorga): incluir prazos e custos no cronograma.")
    if "restricoes" in d.trechos_por_tema:
        d.alertas.append("Há restrições (faixas não edificáveis/rodovia/linha de transmissão): descontar da área aproveitável.")
    p = d.parametros
    if p.get("faixa_transicao_m") and any(z.upper().startswith("ZI") for z in d.zonas):
        d.alertas.append(f"Zona industrial incidente: parcelamento residencial exige faixa de transição de {p['faixa_transicao_m']:.0f} m junto às divisas.")
    if p.get("areas_publicas_min_pct"):
        d.alertas.append(f"Áreas públicas (praça + institucional): mínimo de {p['areas_publicas_min_pct']:.0f}% da área computável.")
    if d.vias:
        d.alertas.append("Diretrizes viárias: " + "; ".join(f"{v['via']} {v['hierarquia'].lower()} {v['largura_total_m']:.0f} m" for v in d.vias) + ".")
    if p.get("validade_dias"):
        d.alertas.append(f"Consulta válida por {p['validade_dias']:.0f} dias a partir da expedição (prorrogável por igual período).")
    return d
