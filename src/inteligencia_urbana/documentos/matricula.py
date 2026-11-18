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
# "m²" como o OCR costuma ler: m?, m”, mº, m°, m2...
M2 = r"(?:m²|m2|m\?|m”|m\"|mº|m°|metros\s+quadrados)"

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
    (r"registro\s+cont[íi]nuo", "registro contínuo", False),
    (r"inclus[ãa]o\s+do\s+C\.?\s?E\.?\s?P", "inclusão de CEP", False),
    (r"inclus[ãa]o\s+d[ao]s?\s+(?:C\.?\s?I|RG|CPF)", "atualização cadastral", False),
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
    medida_m: float | None
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
    endereco: str | None = None
    cep: str | None = None
    unidade_autonoma: dict | None = None
    transmissoes: list[dict] = field(default_factory=list)
    ultimo_ato_certificado: int | None = None
    texto_ocr: bool = False
    forma: dict | None = None  # contorno montado pela metragem (sem coordenadas)
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
        rf"[áa]rea\s+(?:total\s+|superficial\s+|bruta\s+|real\s+total\s+|de\s+terreno\s+)?(?:de\s+|com\s+|:\s*|=\s*)?({NUM})\s*"
        rf"({M2}|ha\b|hectares?|alqueires?(?:\s+paulistas?)?)",
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
    if re.search(r"\bSAD[\s\-]?69\b", t) and "SIRGAS" not in t:
        return "SAD-69", EPSG_SAD69_UTM22S
    if "SIRGAS" in t:
        return f"SIRGAS 2000 / UTM {fuso}S", 31960 + fuso
    return None, EPSG_SIRGAS2000_UTM22S


# ---------------------------------------------------------------- atos

ATO_RE = re.compile(
    r"(?<![A-Za-z])(?:(R|AV|Av)\s*[\.\-–=]{0,2}\s*(\d{1,3})|(?i:REGISTRO)\s+(?i:n)\.?\s*[º°o]\.?\s*\.?\s*(\d{1,3})(?=\s*/))"
    # sufixo com o nº da matrícula: "R-1/32.185" ou "R-1-284" (hífen colado; nunca uma data "R-2 - 10/03/2015")
    r"(?:(?:\s*/\s*|\s?[\-–]\s?)(\d[\d.,]*\d)(?![/\d]))?"
    r"(?=\s*[\-–—=/:.,;|(]|\s+(?:em|-|de)\b|\s*$)",
    re.M,
)


REFERENCIA_RE = re.compile(
    r"(?:objeto|conforme|refer\w*|constante|nos?\s+termos|cancel\w*|vide|pelo|pela|ao)\s+(?:d[oa]s?\s+|n[oa]s?\s+|ao?\s+)?$",
    re.I,
)


def _digitos(v: str | None) -> str:
    return re.sub(r"\D", "", v or "")


def _atos(texto: str, numero_matricula: str | None = None) -> tuple[list[AtoRegistral], int | None]:
    """Atos R/AV da matrícula. Retorna (atos, posição do primeiro ato no texto).

    Atos citados de outras matrículas (ex.: "R. 4/9.502" no registro anterior) são
    descartados quando o número após a barra não é o desta matrícula.
    """
    alvo = _digitos(numero_matricula)
    todas = list(ATO_RE.finditer(texto))
    # se a certidão numera os atos com o nº da matrícula ("AV-3/45.678"), menções sem
    # esse sufixo ("objeto do R-2") são só referências, não atos
    com_sufixo = bool(alvo) and any(_digitos(m.group(4)) == alvo for m in todas)
    marcas = []
    for m in todas:
        antes = texto[max(0, m.start() - 40):m.start()]
        if REFERENCIA_RE.search(antes):  # "objeto da AV.2/...", "conforme R-1" — citação, não ato
            continue
        sufixo = _digitos(m.group(4))
        if sufixo and alvo and sufixo != alvo:
            continue
        if not sufixo and (com_sufixo or (alvo and m.group(3))):
            continue
        tipo = (m.group(1) or "R").upper()
        num = int(m.group(2) or m.group(3))
        marcas.append((m.start(), tipo, num))

    por_chave: dict[tuple[str, int], AtoRegistral] = {}
    textos: dict[tuple[str, int], str] = {}
    primeiro = None
    for i, (ini, tipo, num) in enumerate(marcas):
        fim = marcas[i + 1][0] if i + 1 < len(marcas) else len(texto)
        trecho = texto[ini:fim].strip()
        if len(trecho) < 25:  # referência curta ("conforme R-1"), não é o ato
            continue
        primeiro = ini if primeiro is None else primeiro
        chave = (tipo, num)
        textos[chave] = (textos.get(chave, "") + "\n" + trecho).strip()  # continuação em outra folha

    for (tipo, num), corpo in textos.items():
        cats, onus = [], False
        for padrao, cat, eh_onus in CLASSIFICACAO_ATOS:
            if re.search(padrao, corpo, re.I):
                cats.append(cat)
                onus = onus or eh_onus
        if "cancelamento" in cats:
            onus = False
        por_chave[(tipo, num)] = AtoRegistral(tipo, num, cats or ["não classificado"], onus, corpo[:1500])

    atos = sorted(por_chave.values(), key=lambda a: a.numero)
    for ato in atos:
        if not ato.onus:
            continue
        ref = re.compile(rf"\b{ato.tipo}\s*[\.\-–]?\s*0*{ato.numero}\b", re.I)
        cancelado = any(
            "cancelamento" in o.categorias and ref.search(o.texto) and (o.tipo, o.numero) != (ato.tipo, ato.numero)
            for o in atos
        )
        ato.situacao = "possivelmente cancelado" if cancelado else "ativo (verificar)"
    return atos, primeiro


ROTULO_ADQUIRENTE = re.compile(
    r"(?:ADQUIRENTES?|DONAT[ÁA]RI[OA]S?|NOME\s+D[OA]S?\s+ADQUIRENTES?|OUTORGAD[OA]S?\s+COMPRADOR(?:A|ES|AS)?|HERDEIR[OA]S?|ARREMATANTES?)"
    r"\s*:?\s*-?\s*(.{0,700}?)(?=T[ÍI]TULO|FORMA\s+E\s+DATA|VALOR\s*:|CONDI[ÇC][ÕO]ES|DOCUMENTOS\s+APRESENTADOS|$)",
    re.S,
)
NOME_PESSOA = re.compile(r"\b([A-ZÀ-Ú][A-ZÀ-Ú'\-]+(?:\s+(?:D[AEO]S?|E)?\s*[A-ZÀ-Ú][A-ZÀ-Ú'\-]+){1,6})\s*,")


def _transmissoes(atos: list[AtoRegistral]) -> list[dict]:
    """Cadeia de transmissões: atos de compra e venda, doação, partilha, permuta etc."""
    tipos = {"compra e venda", "doação", "partilha/inventário", "permuta"}
    out = []
    for a in atos:
        if a.tipo != "R" or not (tipos & set(a.categorias)):
            continue
        m = ROTULO_ADQUIRENTE.search(re.sub(r"\s+", " ", a.texto))
        nomes = []
        if m:
            for n in NOME_PESSOA.findall(m.group(1)):
                n = n.strip()
                if len(n) > 6 and n not in nomes and not re.match(r"(?:RG|CPF|CNPJ|CIC|SSP|RUA|AV)\b", n):
                    nomes.append(n)
        frac = re.search(r"parte\s+ideal\s+de\s*(\d+(?:[,.]\d+)?)\s*%", a.texto, re.I)
        valor = re.search(rf"VALOR\s*:?-?\s*R\$\.?\s*({NUM})", a.texto)
        out.append({
            "ato": f"R-{a.numero}",
            "natureza": ", ".join(c for c in a.categorias if c in tipos),
            "adquirentes": nomes[:4],
            "fracao_pct": parse_numero_br(frac.group(1)) if frac else None,
            "valor": parse_numero_br(valor.group(1)) if valor else None,
        })
    return out


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
        rf"(?P<m>{NUM})\s*(?:m\b|mts?\.?|metros(?:\s+lineares)?)\s*,?\s+(?:de\s+|d[oa]s?\s+|na\s+|nos?\s+|pela\s+|pelos?\s+|para\s+a\s+|em\s+)?"
        r"(?P<lado>da\s+frente\s+aos\s+fundos|frente|fundos?|lateral\s+direita|lateral\s+esquerda|lado\s+direito|lado\s+esquerdo|"
        r"divisa\s+direita|divisa\s+esquerda|laterais?|um\s+lado|outro\s+lado|profundidade)"
        r"(?P<resto>(?:(?!\d[\d.]*(?:,\d+)?\s*(?:m\b|mts?\.?|metros))[^;.]){0,160})",
        re.I,
    )
    out = []
    for m in padrao.finditer(texto):
        resto = m["resto"]
        c = re.search(r"(?:confront\w+\s+com|com|para|divisando\s+com)\s+(?:o\s+|a\s+)?(.+)", resto, re.I)
        try:
            conf = re.sub(r"^(?:e|,)$", "", (c.group(1) if c else resto).strip(" ,"))
            out.append(MedidaLinear(m["lado"].lower(), parse_numero_br(m["m"]), conf))
        except ValueError:
            continue
    return out


# ---------------------------------------------------------------- OCR e unidade autônoma

CARIMBO_RE = re.compile(
    r"consultar\s+a\s+autenticidade|aripar\.org|e-validador|c[óo]digo\s+de\s+verifica|consulta\s+dispon[íi]vel|"
    r"^\s*p[áa]gina\s*:?\s*\d*\s*/?\s*\d*\s*$|valide\s+aqui|assinado\s+digitalmente|verificar\s+a\s+autenticidade|"
    r"documento\s+assinado|CPF:?\s*[\d.\-]{11,14}\s+em\s+\d|^\s*[A-Z0-9]{18,}\s*$|"
    r"registradores\.onr|digite\s+o\s+hash|^\s*este\s+documento\s*$|sptth|rb\.gro|^\s*\S{1,10}\s*$",
    re.I,
)


def parece_ocr(texto: str) -> bool:
    linhas = [l for l in texto.splitlines() if len(l.strip()) > 25]
    if len(linhas) < 10:
        return False
    ruido = sum(1 for l in linhas if re.match(r"^\s*\S{1,3}\s+\S", l))
    return ruido / len(linhas) > 0.3


def limpar_texto(texto: str) -> tuple[str, bool]:
    """Remove o carimbo de autenticidade das certidões digitais e, em texto de OCR,
    as letras soltas da margem (texto vertical) no início das linhas."""
    ocr = parece_ocr(texto)
    out = []
    for l in texto.splitlines():
        if CARIMBO_RE.search(l):
            continue
        if ocr and len(l.strip()) > 12:
            l = re.sub(r"^\s*(?:[^\wÀ-ú\s]{1,3}|\(\w{1,2}\)|[\wÀ-ú]{1,2}[)\]|.,»”]?)\s+(?=\S)", "", l)
            l = re.sub(r"\s+(?:[A-Z]|[|=_~»—\-\]\[])\s*$", "", l)
        out.append(l)
    return "\n".join(out), ocr


def _unidade_autonoma(texto: str) -> dict | None:
    t = re.sub(r"\s+", " ", texto)
    edif = re.search(r"Edif[íi]cio\s+[\"“”'’]*([A-ZÀ-Ú0-9][^\"“”',;]{2,60}?)[\"“”'’]", t)
    unid = re.search(r"\b(Apartamento|Apto\.?|Sala|Loja|Conjunto\s+comercial|Unidade)\s+(?:n[º°o.]*\s*)?(\d+[A-Z]?)", t, re.I)
    if not (edif or re.search(r"fra[çc][ãa]o\s+ideal|condom[íi]nio\s+edil", t, re.I)):
        return None

    def num(padrao):
        m = re.search(padrao, t, re.I)
        return parse_numero_br(m.group(1)) if m else None

    return {
        "edificio": edif.group(1).strip() if edif else None,
        "unidade": f"{unid.group(1).capitalize()} {unid.group(2)}" if unid else None,
        "area_total_m2": num(rf"[áa]rea\s+(?:bruta|total|real\s+total)\s+(?:de\s+)?({NUM})\s*{M2}"),
        "area_privativa_m2": num(rf"({NUM})\s*{M2}\s*de\s+[áa]rea\s+(?:de\s+uso\s+)?privativ|[áa]rea\s+(?:de\s+uso\s+)?privativa\s+(?:de\s+)?({NUM})"),
        "fracao_ideal_terreno_m2": num(rf"fra[çc][ãa]o\s+ideal\s+(?:de\s+terreno\s+)?(?:de\s+)?({NUM})\s*{M2}"),
        "participacao_condominio_pct": num(rf"participa[çc][ãa]o\s+no\s+condom[íi]nio\s+de\s+({NUM})\s*%"),
        "area_terreno_condominio_m2": num(rf"(?:data|lote)\s+de\s+terras?.{{0,160}}?com\s+a\s+[áa]rea\s+de\s+({NUM})\s*{M2}"),
        "vagas": list(dict.fromkeys(re.findall(r"vaga\s+de\s+garagem\s+n[º°o.]*\s*(\d+)", t, re.I))) or None,
    }


DIRECOES = r"Norte|Sul|Leste|Este|Oeste|Nordeste|Noroeste|Sudeste|Sudoeste"
CARDEAL_RE = re.compile(
    rf"\b({DIRECOES})\b\s*,?\s*(?:-\s*)?(?:com|confronta(?:ndo)?\s+com|divisa(?:ndo)?\s+com|limita(?:ndo)?-se\s+com)\s+(?:-\s*)?(.+?)"
    rf"(?=\s*,?\s*(?:e\s+)?(?:a|ao|pelo|pela|na|no)\s+(?:{DIRECOES})\b|[\"”]|\.-|\.\s|;|$)",
    re.I,
)


def _confrontacoes_cardeais(texto: str) -> list[MedidaLinear]:
    t = re.sub(r"\s+", " ", texto)
    out = []
    for m in CARDEAL_RE.finditer(t):
        lado = m.group(1).capitalize().replace("Este", "Leste") if m.group(1).lower() == "este" else m.group(1).capitalize()
        conf = re.sub(r"\s*-\s*", " ", m.group(2)).strip(" ,.-")
        conf = re.sub(r"^((?:o|a|os|as)\b)\s*,\s*", r"\1 ", conf)
        if conf:
            out.append(MedidaLinear(lado, None, conf[:160]))
    return out


# ---------------------------------------------------------------- principal

def analisar_matricula(texto: str, epsg: int | None = None) -> ResultadoMatricula:
    r = ResultadoMatricula()
    texto, r.texto_ocr = limpar_texto(texto)
    r.numero = _primeiro(r"matr[íi]cula\s*(?:n[º°o.]*\s*|sob\s+o\s+n[º°o.]*\s*)?[:\-–—]?\s*(\d{1,3}(?:[.,\s]\d{3})+|\d+)\b", texto)
    # OCR ruim no cabeçalho: o nº da matrícula também aparece nos atos ("AV.2/32.185")
    sufixos = [_digitos(m.group(4)) for m in ATO_RE.finditer(texto) if m.group(4)]
    if sufixos:
        mais_comum = max(set(sufixos), key=sufixos.count)
        if sufixos.count(mais_comum) >= 2 and _digitos(r.numero) != mais_comum:
            r.numero = mais_comum
    if _digitos(r.numero):  # formato único: 32.185 (OCR pode trazer 32,185 ou 32 185)
        r.numero = f"{int(_digitos(r.numero)):,}".replace(",", ".")
    r.cartorio = _primeiro(r"(\d+\s*[º°ªo]?\s*(?:of[íi]cio|servi[çc]o|registro)[^\n]{0,60}?registro\s+de\s+im[óo]veis)", texto)
    r.comarca = _primeiro(r"comarca\s+de\s+([A-ZÀ-Úa-zà-ú\s]+?)(?:\s*[-–/,.\n]|\s+estado)", texto) or _primeiro(
        r"registro\s+de\s+im[óo]veis\s+de\s+([A-ZÀ-Ú][A-ZÀ-Úa-zà-ú ]{2,40}?)\s*[-–/]\s*[A-Z]{2}\b", texto)
    r.lote = _primeiro(r"\blote\s+(?:de\s+terr(?:eno|as)\s+)?(?:urbano\s+|rural\s+)?(?:n[º°o.]*\s*|sob\s+n[º°o.]*\s*)?([\w\-/]*\d[\w\-/]*)", texto)
    # em Londrina e região, "Data de terras" é o lote
    r.lote = r.lote or _primeiro(r"\bdata\s+(?:de\s+terras?\s*,?\s*)?(?:sob\s+)?n[º°o.]*\s*(\d+[A-Z]?)", texto)
    r.quadra = _primeiro(r"\bquadra\s+(?:n[º°o.]*\s*)?([\w\-/]*\d[\w\-/]*|[A-Z]\b)", texto)
    r.loteamento = _primeiro(r"situad[oa]\s+n[oa]\s+[\"“”']+([^\"“”'\n]{3,60})[\"“”']", texto) or _primeiro(r"(?:loteamento|jardim|conjunto|residencial|parque|vila)\s+(?:denominado\s+)?[\"“]?([A-ZÀ-Ú][\wÀ-ú ]{2,50}?)[\"”]?(?:[,.;\n]|\s+-)", texto)
    r.inscricao_imobiliaria = _primeiro(r"inscri[çc][ãa]o\s+(?:imobili[áa]ria|municipal|cadastral)\s*(?:n[º°o.]*\s*)?[:\-]?\s*([\d.\-/]+)", texto)
    r.ccir = _primeiro(r"CCIR\s*(?:n[º°o.]*\s*)?[:\-]?\s*([\d.\-/]+)", texto)
    r.car = _primeiro(r"\bCAR\b\s*(?:n[º°o.]*\s*)?[:\-]?\s*(PR-[\w.\-]+)", texto)
    r.area_declarada_m2, r.area_declarada_txt = _area_declarada(texto)
    r.endereco = _primeiro(
        r"(?:si\s*)?tuad[oa]\s+(?:à|a|na|no)\s+((?:Rua|Avenida|Av\.|Alameda|Travessa|Rodovia|Estrada|Pra[çc]a)\s[^,;\n]{2,60}?n[º°oe]\.?\s*\d+)", texto)
    if r.endereco:
        r.endereco = re.sub(r"\s+n[eo°]\.?\s*(?=\d)", " nº ", r.endereco)
    r.cep = _primeiro(r"C\.?\s?E\.?\s?P\.?\s+do\s+im[óo]vel[^\d]{0,80}(\d{2}\.?\d{3}-\d{3})", texto)
    m_ult = re.search(r"[úu]ltimo\s+ato\s+n[º°o.]*\s*(\d{1,3})", texto, re.I)
    r.ultimo_ato_certificado = int(m_ult.group(1)) if m_ult else None

    r.atos, pos_primeiro_ato = _atos(texto, r.numero)
    m_ini = re.search(r"IDENTIFICA[ÇC][ÃA]O\s+DO\s+IM[ÓO]VEL|IM[ÓO]VEL\s*:", texto, re.I) or re.search(r"matr[íi]cula", texto, re.I)
    ini = m_ini.start() if m_ini and (not pos_primeiro_ato or m_ini.start() < pos_primeiro_ato) else 0
    identificacao = texto[ini:pos_primeiro_ato] if pos_primeiro_ato else texto[ini:]
    r.unidade_autonoma = _unidade_autonoma(identificacao)

    rural = re.search(r"\b(ccir|incra|gleba|ch[áa]cara|s[íi]tio|fazenda|im[óo]vel rural|alqueires?|\bITR\b|reserva legal)\b", identificacao, re.I)
    urbano = re.search(r"\b(lote\s|quadra\s|data\s+de\s+terras|apartamento|edif[íi]cio|condom[íi]nio|inscri[çc][ãa]o imobili[áa]ria|zona urbana|per[íi]metro urbano)", identificacao, re.I)
    r.tipo_imovel = "rural" if rural and not urbano else "urbano" if urbano else "rural" if rural else "indefinido"
    # CCIR/INCRA/ITR na matrícula (abertura ou atos) indicam cadastro rural, salvo unidade de edifício
    if re.search(r"\bccir\b|\bincra\b|im[óo]vel\s+rural|\bITR\b", texto, re.I) and not re.search(r"apartamento|unidade\s+aut[ôo]noma", identificacao, re.I):
        r.tipo_imovel = "rural"

    r.datum, epsg_detectado = _datum(texto)
    r.epsg = epsg or epsg_detectado

    r.transmissoes = _transmissoes(r.atos)
    r.vertices = _vertices(texto, r.epsg)
    lances = _lances(texto)
    r.medidas = _medidas_lineares(identificacao) + _confrontacoes_cardeais(identificacao)

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

    if not r.vertices:
        from ..geo.forma import forma_do_terreno

        area_ref = (r.unidade_autonoma or {}).get("area_terreno_condominio_m2") or r.area_declarada_m2
        r.forma = forma_do_terreno([asdict(m) for m in r.medidas], area_ref, [(a, d) for a, d, _, _ in lances] if len(lances) >= 3 else None)

    if r.vertices and len(r.vertices) >= 3 and r.fechamento is None:
        r.fechamento = {**asdict(avaliar_fechamento(0, r.perimetro_m or 0)), "precisao_txt": "polígono por coordenadas"}

    _alertas(r)
    return r


def _alertas(r: ResultadoMatricula) -> None:
    if r.texto_ocr:
        r.alertas.append("Texto obtido por OCR (certidão escaneada): confira números, nomes e áreas com o documento original.")
    if r.ultimo_ato_certificado and r.atos and max(a.numero for a in r.atos) < r.ultimo_ato_certificado:
        r.alertas.append(
            f"A certidão informa último ato nº {r.ultimo_ato_certificado}, mas só foram lidos atos até o nº "
            f"{max(a.numero for a in r.atos)}: algum ato pode não ter sido reconhecido."
        )
    if any(t["fracao_pct"] for t in r.transmissoes):
        r.alertas.append("Há transmissão de parte ideal: o imóvel tem ou teve mais de um titular (condomínio civil). Confira a titularidade atual.")
    if r.unidade_autonoma:
        r.alertas.append(
            "Unidade autônoma em condomínio edilício: não cabe parcelamento do solo; estudos de viabilidade se aplicam ao "
            "terreno do condomínio como um todo (incorporação/retrofit)."
        )
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
