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

ZONA_RE = re.compile(r"\b(Z[A-Z]{1,4}[\s\-]?\d{0,2}[A-Z]?|ZEIS[\s\-]?\d?|ZEPP?|ZUE|ZEU|MZ[A-Z]{1,3})\b")

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


def analisar_consulta_parcelamento(texto: str) -> DiretrizesParcelamento:
    d = DiretrizesParcelamento()
    m = re.search(r"(?:consulta|diretriz(?:es)?|protocolo|processo)\s*(?:pr[ée]via\s*)?(?:n[º°o.]*\s*)?[:\-]?\s*([\d./\-]{4,})", texto, re.I)
    d.numero_consulta = m.group(1).strip(".-/") if m else None

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
    return d
