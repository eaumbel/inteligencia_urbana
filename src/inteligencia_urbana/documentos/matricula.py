"""Análise de matrícula de imóvel (Registro de Imóveis).

Extrai, por heurísticas de texto:
- identificação (nº da matrícula, cartório, lote/quadra, inscrição, área declarada);
- atos registrais (R-n / AV-n) com classificação e alerta de ônus/gravames;
- memorial descritivo: vértices (UTM ou lat/long), azimutes, distâncias e confrontantes;
- medidas lineares de lotes urbanos ("12,00 m de frente para a Rua X");
- conferência da área calculada x área declarada e do fechamento da poligonal.

IMPORTANTE: o resultado é um apoio à due diligence e NÃO substitui a leitura
integral da certidão de inteiro teor pelo profissional responsável.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field

from ..geo.coordenadas import (
    EPSG_SAD69_UTM22S,
    EPSG_SIRGAS2000_UTM22S,
    coordenada_utm_valida,
    dms_para_decimal,
    geo_para_utm,
    parse_numero_br,
    rumo_para_azimute,
)
from ..geo.poligono import (
    Perimetro,
    Segmento,
    Vertice,
    avaliar_fechamento,
    poligonal_por_azimutes,
    segmentos_de_vertices,
)

ALQUEIRE_PAULISTA_M2 = 24_200.0

NUM = r"\d[\d.]*(?:,\d+)?"
ANG = r"\d{1,3}\s*[°º]\s*\d{1,2}\s*['′’]\s*\d{1,2}(?:[.,]\d+)?\s*(?:\"|″|”|''|'’)?"

# Palavras-chave → (categoria, é ônus/gravame?)
CLASSIFICACAO_ATOS: list[tuple[str, str, bool]] = [
    (r"cancelament|cancela-se|fica cancelad", "cancelamento", False),
    (r"aliena[çc][ãa]o fiduci[áa]ria", "alienação fiduciária", True),
    (r"hipoteca", "hipoteca", True),
    (r"penhora", "penhora", True),
    (r"arresto|sequestro", "arresto/sequestro", True),
    (r"indisponibilidade", "indisponibilidade", True),
    (r"usufruto", "usufruto", True),
    (r"servid[ãa]o", "servidão", True),
    (r"inalienabilidade|impenhorabilidade|incomunicabilidade", "cláusulas restritivas", True),
    (r"a[çc][ãa]o (?:de execu|ajuizad)|art\.?\s*828|premonit[óo]ri|ajuizamento", "averbação premonitória/ação", True),
    (r"tombament", "tombamento", True),
    (r"enfiteuse|aforamento|laud[êe]mio", "enfiteuse/aforamento", True),
    (r"promessa de compra|compromisso de compra", "compromisso de compra e venda", True),
    (r"compra e venda|comprad", "compra e venda", False),
    (r"doa[çc][ãa]o", "doação", False),
    (r"partilha|invent[áa]rio|formal de", "partilha/inventário", False),
    (r"permuta", "permuta", False),
    (r"desmembr", "desmembramento", False),
    (r"unifica[çc]|fus[ãa]o", "unificação", False),
    (r"loteamento", "loteamento", False),
    (r"incorpora[çc][ãa]o", "incorporação", False),
    (r"patrim[ôo]nio de afeta", "patrimônio de afetação", False),
    (r"constru[çc][ãa]o|habite-se", "averbação de construção", False),
    (r"georreferenc|certifica[çc][ãa]o.*incra|sigef", "georreferenciamento", False),
    (r"retifica[çc]", "retificação", False),
    (r"reserva legal", "reserva legal", False),
    (r"cadastro ambiental rural|\bCAR\b", "CAR", False),
    (r"ccir|incra|nirf|\bITR\b", "cadastro rural", False),
    (r"reurb|regulariza[çc][ãa]o fundi[áa]ria|legitima[çc][ãa]o fundi[áa]ria", "REURB", False),
    (r"casamento|div[óo]rcio|[óo]bito|altera[çc][ãa]o de nome", "alteração pessoal", False),
]


@dataclass
class AtoRegistral:
    tipo: str  # "R" ou "AV"
    numero: int
    categorias: list[str]
    onus: bool
    texto: str
    situacao: str = ""  # para ônus: "ativo (verificar)" / "possivelmente cancelado"


@dataclass
class MedidaLinear:
    lado: str
    medida_m: float
    confrontacao: str


@dataclass
class ResultadoMatricula:
    numero: str | None = None
    cartorio: str | None = None
    comarca: str | None = None
    tipo_imovel: str = "indefinido"  # urbano / rural / indefinido
    lote: str | None = None
    quadra: str | None = None
    loteamento: str | None = None
    inscricao_imobiliaria: str | None = None
    ccir: str | None = None
    car: str | None = None
    area_declarada_m2: float | None = None
    area_declarada_txt: str | None = None
    datum: str | None = None
    epsg: int = EPSG_SIRGAS2000_UTM22S
    atos: list[AtoRegistral] = field(default_factory=list)
    vertices: list[Vertice] = field(default_factory=list)
    segmentos: list[Segmento] = field(default_factory=list)
    medidas: list[MedidaLinear] = field(default_factory=list)
    area_calculada_m2: float | None = None
    perimetro_m: float | None = None
    fechamento: dict | None = None
    alertas: list[str] = field(default_factory=list)

    def perimetro(self) -> Perimetro | None:
        if len(self.vertices) < 3:
            return None
        return Perimetro(self.vertices, self.segmentos, self.epsg)

    def to_dict(self) -> dict:
        d = asdict(self)
        per = self.perimetro()
        d["geojson"] = per.geojson() if per else None
        return d


# ---------------------------------------------------------------- identificação

def _primeiro(padrao: str, texto: str, flags=re.I) -> str | None:
    m = re.search(padrao, texto, flags)
    return m.group(1).strip(" .,;:") if m else None


def _area_declarada(texto: str) -> tuple[float | None, str | None]:
    m = re.search(
        rf"[áa]rea\s+(?:total\s+|superficial\s+|de\s+terreno\s+)?(?:de\s+|com\s+|:\s*|=\s*)?({NUM})\s*"
        r"(m²|m2|metros\s+quadrados|ha\b|hectares?|alqueires?(?:\s+paulistas?)?)",
        texto, re.I,
    )
    if not m:
        return None, None
    valor = parse_numero_br(m.group(1))
    un = m.group(2).lower()
    if un.startswith("ha") or un.startswith("hect"):
        valor *= 10_000
    elif un.startswith("alq"):
        valor *= ALQUEIRE_PAULISTA_M2
    return valor, m.group(0)


def _datum(texto: str) -> tuple[str | None, int]:
    t = texto.upper()
    fuso = 23 if re.search(r"(?:FUSO|ZONA)\s*23|MC\s*[-–]?\s*45", t) else 22
    if "SAD" in t and "69" in t and "SIRGAS" not in t:
        return "SAD-69", EPSG_SAD69_UTM22S
    if "SIRGAS" in t:
        return f"SIRGAS 2000 / UTM {fuso}S", 31960 + fuso
    return None, EPSG_SIRGAS2000_UTM22S


# ---------------------------------------------------------------- atos

ATO_RE = re.compile(r"(?<![A-Za-z])(R|AV|Av)\s*[\.\-–]?\s*(\d{1,3})(?=\s*[\-–/:.]|\s+(?:em|-|de)\b)")


def _atos(texto: str) -> list[AtoRegistral]:
    marcas = list(ATO_RE.finditer(texto))
    atos: list[AtoRegistral] = []
    vistos = set()
    for i, m in enumerate(marcas):
        tipo = m.group(1).upper()
        num = int(m.group(2))
        if (tipo, num) in vistos:
            continue
        fim = marcas[i + 1].start() if i + 1 < len(marcas) else len(texto)
        trecho = texto[m.start():fim].strip()
        # descarta referências internas curtas ("conforme R-1") — o ato real tem corpo
        if len(trecho) < 25:
            continue
        vistos.add((tipo, num))
        cats, onus = [], False
        for padrao, cat, eh_onus in CLASSIFICACAO_ATOS:
            if re.search(padrao, trecho, re.I):
                cats.append(cat)
                onus = onus or eh_onus
        if "cancelamento" in cats:
            onus = False
        atos.append(AtoRegistral(tipo, num, cats or ["não classificado"], onus, trecho[:600]))

    for ato in atos:
        if not ato.onus:
            continue
        ref = re.compile(rf"\b{ato.tipo}\s*[\.\-–]?\s*0*{ato.numero}\b", re.I)
        cancelado = any(
            "cancelamento" in o.categorias and ref.search(o.texto) and (o.tipo, o.numero) != (ato.tipo, ato.numero)
            for o in atos
        )
        ato.situacao = "possivelmente cancelado" if cancelado else "ativo (verificar)"
    return atos


# ---------------------------------------------------------------- memorial descritivo

NOME_VERTICE_RE = re.compile(
    r"(?i:v[ée]rtice|ponto|marco|estaca)\s+(?:denominad[oa]\s+|n[º°o.]*\s*)?"
    r"(?P<nome>[A-Za-z]{0,6}[\-_.]?[A-Za-z]{0,3}[\-_.]?\d[\w\-]*)"
)
UTM_NE_RE = re.compile(
    rf"(?:\bN|\bY)\s*[=:]?\s*(?P<n>{NUM})\s*m?\s*(?:e|,|;)?\s*(?:\bE|\bX)\s*[=:]?\s*(?P<e>{NUM})"
)
UTM_EN_RE = re.compile(
    rf"(?:\bE|\bX)\s*[=:]?\s*(?P<e>{NUM})\s*m?\s*(?:e|,|;)?\s*(?:\bN|\bY)\s*[=:]?\s*(?P<n>{NUM})"
)
GEO_RE = re.compile(
    rf"(?i:lat(?:itude)?)\.?\s*[=:]?\s*(?P<lat>-?\s*{ANG}\s*[NS]?)\s*(?:e|,|;)?\s*"
    rf"(?i:long(?:itude)?)\.?\s*[=:]?\s*(?P<lon>-?\s*{ANG}\s*[EWLO]?)"
)
LANCE_RE = re.compile(
    rf"(?P<tipo>(?i:azimute|rumo))\s*(?:de\s*)?(?P<ang>{ANG}(?:\s*[NS]\s*[EOWL])?)\s*(?:e|,|;)?\s*"
    rf"(?:(?i:a|na|numa|com)\s+)?(?i:dist[âa]ncia|extens[ãa]o)\s*(?:de\s*)?(?P<d>{NUM})\s*(?:m\b|metros)"
)
CONFRONT_RE = re.compile(
    r"(?i:confront\w*|divis\w*|limit\w*)\s+(?:com\s+|por\s+)?(?:o\s+|a\s+|os\s+|as\s+)?"
    r"(?P<c>.+?)(?=;|\.\s|\.$|,\s*(?i:deste|daí|dai|segue|até|ate)\b|$)",
    re.S,
)


def _coord_na_janela(janela: str, epsg: int) -> tuple[float, float] | None:
    for rx in (UTM_NE_RE, UTM_EN_RE):
        m = rx.search(janela)
        if m:
            try:
                e, n = parse_numero_br(m["e"]), parse_numero_br(m["n"])
            except ValueError:
                continue
            if not coordenada_utm_valida(e, n) and coordenada_utm_valida(n, e):
                e, n = n, e
            if coordenada_utm_valida(e, n):
                return e, n
    m = GEO_RE.search(janela)
    if m:
        lat = dms_para_decimal(m["lat"])
        lon = dms_para_decimal(m["lon"])
        # no Brasil (hemisférios S/W) — corrige sinais ausentes
        lat = -abs(lat) if lat > 0 and "N" not in m["lat"].upper() else lat
        lon = -abs(lon)
        return geo_para_utm(lon, lat, epsg)
    return None


def _vertices(texto: str, epsg: int) -> list[Vertice]:
    marcas = list(NOME_VERTICE_RE.finditer(texto))
    vertices: list[Vertice] = []
    nomes = set()
    for i, m in enumerate(marcas):
        fim = marcas[i + 1].start() if i + 1 < len(marcas) else len(texto)
        janela = texto[m.end(): min(fim, m.end() + 300)]
        nome = m["nome"].strip("-_.")
        if nome in nomes:
            continue
        c = _coord_na_janela(janela, epsg)
        if c:
            nomes.add(nome)
            vertices.append(Vertice(nome, round(c[0], 3), round(c[1], 3)))
    return vertices


def _lances(texto: str) -> list[tuple[float, float, str | None, int]]:
    """Retorna [(azimute, distância, confrontante, posição)] na ordem do texto."""
    marcas = list(LANCE_RE.finditer(texto))
    out = []
    for i, m in enumerate(marcas):
        ang = m["ang"]
        az = rumo_para_azimute(ang) if m["tipo"].lower() == "rumo" else abs(dms_para_decimal(ang))
        d = parse_numero_br(m["d"])
        inicio_prox = marcas[i + 1].start() if i + 1 < len(marcas) else len(texto)
        # confrontante pode vir antes (".. confrontando com X, segue com azimute ..") ou depois
        depois = texto[m.end():inicio_prox]
        c = CONFRONT_RE.search(depois)
        conf = re.sub(r"\s+", " ", c["c"]).strip(" ,.;") if c else None
        out.append((az, d, conf[:160] if conf else None, m.start()))
    return out


def _medidas_lineares(texto: str) -> list[MedidaLinear]:
    padrao = re.compile(
        rf"(?P<m>{NUM})\s*(?:m\b|metros)\s+(?:de\s+|na\s+|pela\s+|para\s+a\s+)?"
        r"(?P<lado>frente|fundos?|lateral\s+direita|lateral\s+esquerda|lado\s+direito|lado\s+esquerdo|"
        r"divisa\s+direita|divisa\s+esquerda|laterais?)"
        r"(?P<resto>[^;.]{0,160})",
        re.I,
    )
    out = []
    for m in padrao.finditer(texto):
        resto = m["resto"]
        c = re.search(r"(?:confront\w+\s+com|com|para|divisando\s+com)\s+(?:o\s+|a\s+)?(.+)", resto, re.I)
        try:
            out.append(MedidaLinear(m["lado"].lower(), parse_numero_br(m["m"]), (c.group(1) if c else resto).strip(" ,")))
        except ValueError:
            continue
    return out


# ---------------------------------------------------------------- principal

def analisar_matricula(texto: str, epsg: int | None = None) -> ResultadoMatricula:
    r = ResultadoMatricula()
    r.numero = _primeiro(r"matr[íi]cula\s*(?:n[º°o.]*\s*|sob\s+o\s+n[º°o.]*\s*)?[:\-]?\s*(\d[\d.]*)", texto)
    r.cartorio = _primeiro(r"(\d+\s*[º°ªo]?\s*(?:of[íi]cio|servi[çc]o|registro)[^\n]{0,60}?registro\s+de\s+im[óo]veis)", texto)
    r.comarca = _primeiro(r"comarca\s+de\s+([A-ZÀ-Úa-zà-ú\s]+?)(?:\s*[-–/,.\n]|\s+estado)", texto)
    r.lote = _primeiro(r"\blote\s+(?:de\s+terreno\s+)?(?:urbano\s+)?(?:n[º°o.]*\s*|sob\s+n[º°o.]*\s*)?([\w\-/]*\d[\w\-/]*)", texto)
    r.quadra = _primeiro(r"\bquadra\s+(?:n[º°o.]*\s*)?([\w\-/]*\d[\w\-/]*|[A-Z]\b)", texto)
    r.loteamento = _primeiro(r"(?:loteamento|jardim|conjunto|residencial|parque|vila)\s+(?:denominado\s+)?[\"“]?([A-ZÀ-Ú][\wÀ-ú ]{2,50}?)[\"”]?(?:[,.;\n]|\s+-)", texto)
    r.inscricao_imobiliaria = _primeiro(r"inscri[çc][ãa]o\s+(?:imobili[áa]ria|municipal|cadastral)\s*(?:n[º°o.]*\s*)?[:\-]?\s*([\d.\-/]+)", texto)
    r.ccir = _primeiro(r"CCIR\s*(?:n[º°o.]*\s*)?[:\-]?\s*([\d.\-/]+)", texto)
    r.car = _primeiro(r"\bCAR\b\s*(?:n[º°o.]*\s*)?[:\-]?\s*(PR-[\w.\-]+)", texto)
    r.area_declarada_m2, r.area_declarada_txt = _area_declarada(texto)

    rural = re.search(r"\b(ccir|incra|gleba|ch[áa]cara|s[íi]tio|fazenda|im[óo]vel rural|alqueires?|\bITR\b|reserva legal)\b", texto, re.I)
    urbano = re.search(r"\b(lote\s|quadra\s|inscri[çc][ãa]o imobili[áa]ria|zona urbana|per[íi]metro urbano)", texto, re.I)
    r.tipo_imovel = "rural" if rural and not urbano else "urbano" if urbano else "rural" if rural else "indefinido"

    r.datum, epsg_detectado = _datum(texto)
    r.epsg = epsg or epsg_detectado

    r.atos = _atos(texto)
    r.vertices = _vertices(texto, r.epsg)
    lances = _lances(texto)
    r.medidas = _medidas_lineares(texto)

    if len(r.vertices) >= 3:
        confs = [lan[2] for lan in lances] if len(lances) == len(r.vertices) else None
        r.segmentos = segmentos_de_vertices(r.vertices, confs)
        per = r.perimetro()
        r.area_calculada_m2 = round(per.area_m2, 2)
        r.perimetro_m = round(per.perimetro_m, 2)
        if lances:
            # confere distâncias descritas x calculadas
            for seg, (_, d, _, _) in zip(r.segmentos, lances):
                if abs(seg.distancia_m - d) > max(0.05, d * 0.002):
                    r.alertas.append(
                        f"Lance {seg.de}→{seg.para}: distância descrita {d:.2f} m ≠ calculada pelas coordenadas {seg.distancia_m:.2f} m."
                    )
    elif lances and len(lances) >= 3:
        # Sem coordenadas de todos os vértices: monta poligonal local a partir do 1º vértice (ou origem arbitrária)
        inicio = (r.vertices[0].e, r.vertices[0].n) if r.vertices else (0.0, 0.0)
        verts, fech = poligonal_por_azimutes(inicio, [(a, d) for a, d, _, _ in lances])
        r.vertices = verts if r.vertices else []
        pts = [(v.e, v.n) for v in verts]
        from ..geo.poligono import area_shoelace

        r.area_calculada_m2 = round(area_shoelace(pts), 2)
        r.perimetro_m = round(fech.perimetro_m, 2)
        r.fechamento = {**asdict(fech), "precisao_txt": fech.precisao_txt}
        r.segmentos = [Segmento(f"P{i + 1}", f"P{(i + 1) % len(lances) + 1}", a, d, c) for i, (a, d, c, _) in enumerate(lances)]
        if not r.vertices:
            r.alertas.append(
                "Memorial com azimutes/distâncias mas sem coordenada de amarração: área calculada em sistema local; "
                "informe a coordenada de um vértice para georreferenciar."
            )
        if not fech.aceitavel:
            r.alertas.append(f"Erro de fechamento da poligonal: {fech.erro_linear_m:.3f} m ({fech.precisao_txt}).")

    if r.vertices and len(r.vertices) >= 3 and r.fechamento is None:
        r.fechamento = {**asdict(avaliar_fechamento(0, r.perimetro_m or 0)), "precisao_txt": "polígono por coordenadas"}

    _alertas(r)
    return r


def _alertas(r: ResultadoMatricula) -> None:
    if not r.numero:
        r.alertas.append("Número da matrícula não identificado.")
    onus_ativos = [a for a in r.atos if a.onus and a.situacao.startswith("ativo")]
    for a in onus_ativos:
        r.alertas.append(f"Ônus/gravame em {a.tipo}-{a.numero}: {', '.join(a.categorias)} — {a.situacao}.")
    if r.area_declarada_m2 and r.area_calculada_m2:
        dif = (r.area_calculada_m2 - r.area_declarada_m2) / r.area_declarada_m2 * 100
        if abs(dif) > 5:
            r.alertas.append(
                f"Divergência de área: declarada {r.area_declarada_m2:,.2f} m² x calculada {r.area_calculada_m2:,.2f} m² ({dif:+.1f}%). "
                "Avaliar retificação (art. 212/213 da Lei 6.015/1973)."
            )
    if r.tipo_imovel == "rural":
        if not r.ccir:
            r.alertas.append("Imóvel rural sem CCIR identificado na matrícula.")
        if not any("georreferenciamento" in a.categorias for a in r.atos):
            r.alertas.append(
                "Imóvel rural sem averbação de georreferenciamento identificada (Lei 10.267/2001 — exigível para "
                "desmembramento, parcelamento e transferência conforme prazos do Decreto 4.449/2002)."
            )
        if not any(c in ("reserva legal", "CAR") for a in r.atos for c in a.categorias) and not r.car:
            r.alertas.append("Sem menção a CAR/Reserva Legal — verificar no SICAR antes de parcelar/converter para uso urbano.")
        r.alertas.append(
            "Para parcelamento urbano de gleba rural: exige inclusão em perímetro urbano/expansão urbana por lei municipal "
            "e descaracterização junto ao INCRA (art. 53 da Lei 6.766/1979)."
        )
    if r.datum == "SAD-69":
        r.alertas.append("Coordenadas em SAD-69: convertidas a partir do EPSG:29192; confirme os parâmetros de transformação.")
