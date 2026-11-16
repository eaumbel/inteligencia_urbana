"""Fases 2 e 3: leitura integral por página e separação dos atos (R-/AV-) com rastreabilidade.

Nada aqui é presumido: cada valor vem com a fonte (página, trecho, método de leitura e confiança).
O que não foi encontrado fica `None` e a interface mostra "Não identificado no documento analisado.".
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field

from ..documentos.matricula import (
    ATO_RE,
    CLASSIFICACAO_ATOS,
    REFERENCIA_RE,
    _digitos,
    analisar_matricula,
    limpar_texto,
)

NAO_IDENTIFICADO = "Não identificado no documento analisado."
CONFIANCA_BAIXA = 70.0  # % (OCR)
# linhas de cabeçalho/rodapé repetidas em cada folha (não contam como conteúdo do ato)
CABECALHO_RE = re.compile(r"REP[ÚU]BLICA\s+FEDERATIVA|SERVI[ÇC]O\s+DE\s+REGISTRO|REGISTRO\s+(?:GERAL|DE\s+IM[ÓO]VEIS)|OFICIAL|TITULAR|"
                          r"Rua\s|Fone|Sala\s+\d|Andar|FOLHA|FICHA|MATR[ÍI]CULA\s*(?:N|:)|CONTINUA|CNM\s|Valide|documento|"
                          r"CIRCUNSCRI|ESTADO\s+DO|COMARCA|^\W{0,3}\S{0,12}\W{0,3}$", re.I)

MESES = {"janeiro": 1, "fevereiro": 2, "marco": 3, "março": 3, "abril": 4, "maio": 5, "junho": 6, "julho": 7,
         "agosto": 8, "setembro": 9, "outubro": 10, "novembro": 11, "dezembro": 12}
DATA_EXTENSO = re.compile(r"\b(\d{1,2})(?:º|°)?\s+de\s+(" + "|".join(MESES) + r")\s+de\s+(\d)\.?(\d{3})\b", re.I)
DATA_NUM = re.compile(r"\b(\d{1,2})[/.](\d{1,2})[/.](\d{4}|\d{2})\b")
UF_POR_ESTADO = {"PARANÁ": "PR", "PARANA": "PR", "SÃO PAULO": "SP", "SAO PAULO": "SP", "SANTA CATARINA": "SC",
                 "MATO GROSSO DO SUL": "MS", "MINAS GERAIS": "MG", "RIO GRANDE DO SUL": "RS"}


# ---------------------------------------------------------------- estruturas

@dataclass
class Pagina:
    numero: int
    texto: str
    metodo: str = "texto"  # "texto" (camada do PDF) ou "ocr"
    confianca: float | None = None  # % (OCR); None quando o texto veio do próprio PDF


@dataclass
class Fonte:
    pagina: int | None
    trecho: str
    metodo: str
    confianca: float | None


@dataclass
class Campo:
    valor: str | None
    fonte: Fonte | None = None


@dataclass
class Ato:
    id: str  # "R-1", "AV-2"
    tipo: str  # "R" (registro) ou "AV" (averbação)
    numero: int
    data: str | None  # AAAA-MM-DD
    data_texto: str | None
    data_origem: str | None  # "texto do ato" ou "cabeçalho da ficha"
    paginas: list[int]
    categorias: list[str]
    texto_original: str
    metodo: str
    confianca: float | None
    fonte: Fonte


@dataclass
class Extracao:
    identificacao: dict[str, Campo]
    atos: list[Ato]
    estatisticas: dict
    sequencia: dict
    legibilidade: list[dict]
    alertas: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------- utilidades

def _data_iso(m: re.Match) -> str | None:
    try:
        if m.re is DATA_EXTENSO:
            d, mes, a1, a2 = int(m.group(1)), MESES[m.group(2).lower()], m.group(3), m.group(4)
            ano = int(a1 + a2)
        else:
            d, mes, ano = int(m.group(1)), int(m.group(2)), int(m.group(3))
            ano = ano + (2000 if ano < 50 else 1900) if ano < 100 else ano
        if not (1 <= d <= 31 and 1 <= mes <= 12 and 1850 <= ano <= 2100):
            return None
        return f"{ano:04d}-{mes:02d}-{d:02d}"
    except (KeyError, ValueError):
        return None


def _data_do_ato(corpo: str) -> tuple[str | None, str | None, str | None]:
    """Data do ato com a origem declarada. Uma data precedida de 'prenotação/protocolo' não é apresentada como
    data do ato: vira 'data da prenotação/protocolo'."""
    achados = sorted([m for rx in (DATA_EXTENSO, DATA_NUM) for m in rx.finditer(corpo[:260])], key=lambda m: m.start())
    for m in achados:
        iso = _data_iso(m)
        if not iso:
            continue
        antes = corpo[max(0, m.start() - 45):m.start()]
        if re.search(r"nota[çc][ãa]o|prenot|protocol", antes, re.I):
            return iso, m.group(0), "data da prenotação/protocolo (data do ato não legível)" if m.start() > 40 else "data da prenotação/protocolo"
        if re.search(r"escritura|instrumento|contrato|certid[ãa]o|t[íi]tulo|lavrad|datad", antes, re.I):
            continue  # data de documento citado, não do ato
        return iso, m.group(0), "texto do ato"
    return None, None, None


def _primeira_data(trecho: str) -> tuple[str | None, str | None]:
    achados = sorted([m for rx in (DATA_EXTENSO, DATA_NUM) for m in rx.finditer(trecho)], key=lambda m: m.start())
    for m in achados:
        iso = _data_iso(m)
        if iso:
            return iso, m.group(0)
    return None, None


class _Documento:
    """Texto integral com o mapa posição → página."""

    def __init__(self, paginas: list[Pagina]):
        self.paginas = paginas
        partes, self.limites, pos = [], [], 0
        self.ocr = False
        for p in paginas:
            limpo, ocr = limpar_texto(p.texto)
            self.ocr = self.ocr or ocr or p.metodo == "ocr"
            partes.append(limpo)
            self.limites.append((pos, pos + len(limpo), p))
            pos += len(limpo) + 1
        self.texto = "\n".join(partes)

    def pagina_de(self, pos: int) -> Pagina | None:
        for ini, fim, p in self.limites:
            if ini <= pos <= fim:
                return p
        return self.limites[-1][2] if self.limites else None

    def paginas_entre(self, ini: int, fim: int) -> list[int]:
        return [p.numero for a, b, p in self.limites if a < fim and b > ini] or ([self.pagina_de(ini).numero] if self.pagina_de(ini) else [])

    def caracteres_na_pagina(self, ini: int, fim: int, numero: int) -> int:
        for a, b, p in self.limites:
            if p.numero == numero:
                linhas = [l for l in self.texto[max(a, ini):min(b, fim)].splitlines() if not CABECALHO_RE.search(l)]
                return len(re.sub(r"\s", "", "".join(linhas)))
        return 0

    def fonte(self, pos: int, trecho: str) -> Fonte:
        p = self.pagina_de(pos)
        return Fonte(p.numero if p else None, re.sub(r"\s+", " ", trecho).strip()[:300], p.metodo if p else "texto", p.confianca if p else None)

    def campo(self, valor: str | None, padrao_busca: str | None = None) -> Campo:
        if not valor:
            return Campo(None)
        alvo = padrao_busca or re.escape(valor)
        m = re.search(alvo, self.texto, re.I)
        if not m:
            return Campo(valor)
        return Campo(valor, self.fonte(m.start(), self.texto[m.start():m.end() + 80]))


# ---------------------------------------------------------------- extração

def _identificacao(doc: _Documento, base) -> dict[str, Campo]:
    t = doc.texto
    ident = {
        "numero_matricula": doc.campo(base.numero, r"matr[íi]cula[^\d]{0,15}" + r"[\s.,]?".join(_digitos(base.numero)) if base.numero else None),
        "cartorio": doc.campo(base.cartorio),
        "comarca": doc.campo(base.comarca),
    }
    m = re.search(r"(?i:im[óo]veis\s+(?:da\s+comarca\s+)?d[eao])\s+([A-ZÀ-Ú][A-Za-zÀ-ú' ]{2,40}?)\s*[-–/]\s*([A-Z]{2})\b", t)
    municipio, uf = (m.group(1).strip().title(), m.group(2)) if m else (None, None)
    if not uf:
        e = re.search(r"ESTADO\s+D[OE]\s+([A-ZÀ-Ú ]{4,25})", t)
        uf = UF_POR_ESTADO.get(e.group(1).strip()) if e else None
    municipio = municipio or (base.comarca.title() if base.comarca else None)
    ident["municipio"] = doc.campo(municipio, re.escape(municipio) if municipio else None)
    ident["uf"] = Campo(uf, ident["municipio"].fonte if uf and m else None)

    # data de emissão: data do bloco de certificação (a última data após "CERTIDÃO"/"CERTIFICO")
    emissao = None
    blocos = list(re.finditer(r"CERTID[ÃA]O\s+N|CERT[IÍ]FICO|certid[ãa]o\s+(?:emitida|expedida)|data\s+da\s+emiss[ãa]o|emitida\s+em", t, re.I))
    for bl in reversed(blocos):  # o bloco de certificação fica no fim; usa o último que contém data
        trecho = t[bl.start():bl.start() + 1500]
        datas = [m for rx in (DATA_EXTENSO, DATA_NUM) for m in rx.finditer(trecho) if _data_iso(m)]
        if datas:
            ult = max(datas, key=lambda m: m.start())
            pos = bl.start() + ult.start()
            emissao = Campo(_data_iso(ult), doc.fonte(pos, t[pos:pos + len(ult.group(0)) + 40]))
            break
    ident["data_emissao"] = emissao or Campo(None)

    m = re.search(r"matr[íi]cula[^\n]{0,40}?datada\s+de\s+", t, re.I)
    abertura = None
    if m:
        iso, txt = _primeira_data(t[m.end():m.end() + 40])
        abertura = Campo(iso, doc.fonte(m.start(), t[m.start():m.end() + 40])) if iso else None
    if not abertura:
        m = re.search(r"\bDATA\b[\s.:]*", t)
        if m:
            iso, txt = _primeira_data(t[m.end():m.end() + 40])
            if iso:
                abertura = Campo(iso, doc.fonte(m.start(), t[m.start():m.end() + 40]))
    ident["data_abertura"] = abertura or Campo(None)
    return ident


def _atos(doc: _Documento, numero: str | None) -> list[Ato]:
    t, alvo = doc.texto, _digitos(numero)
    todas = list(ATO_RE.finditer(t))
    com_sufixo = bool(alvo) and any(_digitos(m.group(4)) == alvo for m in todas)
    marcas = []
    for m in todas:
        if REFERENCIA_RE.search(t[max(0, m.start() - 40):m.start()]):
            continue
        suf = _digitos(m.group(4))
        if (suf and alvo and suf != alvo) or (not suf and (com_sufixo or (alvo and m.group(3)))):
            continue
        marcas.append((m.start(), (m.group(1) or "R").upper(), int(m.group(2) or m.group(3))))

    # o último ato termina onde começa o bloco de certificação da certidão
    fim_atos = len(t)
    if marcas:
        cert = re.search(r"CERTID[ÃA]O\s+N[º°o.]|CERT[IÍ]FICO\s+(?:nos\s+termos|que)|certifica-se", t[marcas[-1][0]:], re.I)
        if cert:
            fim_atos = marcas[-1][0] + cert.start()
    blocos: dict[tuple[str, int], list[tuple[int, int]]] = {}
    for i, (ini, tipo, num) in enumerate(marcas):
        fim = marcas[i + 1][0] if i + 1 < len(marcas) else fim_atos
        if fim - ini < 25:
            continue
        blocos.setdefault((tipo, num), []).append((ini, fim))

    atos = []
    for (tipo, num), trechos in blocos.items():
        ini0 = trechos[0][0]
        corpo = "\n".join(t[a:b].strip() for a, b in trechos)
        paginas = sorted({pg for a, b in trechos for pg in doc.paginas_entre(a, b) if pg == doc.pagina_de(a).numero
                          or doc.caracteres_na_pagina(a, b, pg) >= 150})
        data, data_txt, origem = _data_do_ato(corpo)
        if not data:  # ficha antiga: a data fica no cabeçalho, antes de "REGISTRO n.º"
            antes = t[max(0, ini0 - 300):ini0]
            m = re.search(r"\bDATA\b[\s.:]*(.{0,40})", antes)
            if m:
                data, data_txt = _primeira_data(m.group(1))
                origem = "cabeçalho da ficha" if data else None
        cats = [c for padrao, c, _ in CLASSIFICACAO_ATOS if re.search(padrao, corpo, re.I)] or ["não classificado"]
        confs = [p.confianca for p in doc.paginas if p.numero in paginas and p.confianca is not None]
        metodo = "ocr" if any(p.metodo == "ocr" for p in doc.paginas if p.numero in paginas) or doc.ocr else "texto"
        atos.append(Ato(
            id=f"{tipo}-{num}", tipo=tipo, numero=num, data=data, data_texto=data_txt, data_origem=origem,
            paginas=paginas, categorias=cats, texto_original=corpo[:4000], metodo=metodo,
            confianca=min(confs) if confs else None, fonte=doc.fonte(ini0, corpo[:300]),
        ))
    return sorted(atos, key=lambda a: (a.numero, a.tipo != "R"))


def _sequencia(atos: list[Ato], ultimo_certificado: int | None) -> dict:
    nums = [a.numero for a in atos]
    numeracao_unica = len(nums) == len(set(nums))  # registro contínuo: R-1, AV-2, R-3...
    faltantes = []
    if atos and numeracao_unica:
        topo = max(max(nums), ultimo_certificado or 0)
        faltantes = [n for n in range(1, topo + 1) if n not in set(nums)]
    elif atos:
        for tipo in ("R", "AV"):
            ns = sorted(a.numero for a in atos if a.tipo == tipo)
            if ns:
                faltantes += [f"{tipo}-{n}" for n in range(1, ns[-1] + 1) if n not in ns]
    datas = [a.data for a in atos if a.data]
    fora_de_ordem = [b.id for a, b in zip(atos, atos[1:]) if a.data and b.data and b.data < a.data]
    return {
        "numeracao": "contínua (R e AV na mesma sequência)" if numeracao_unica else "separada por tipo",
        "faltantes": faltantes,
        "ultimo_ato_certificado": ultimo_certificado,
        "ultimo_ato_lido": max(nums) if nums else None,
        "datas_fora_de_ordem": fora_de_ordem,
        "primeira_data": min(datas) if datas else None,
        "ultima_data": max(datas) if datas else None,
    }


def extrair(paginas: list[Pagina]) -> Extracao:
    doc = _Documento(paginas)
    base = analisar_matricula(doc.texto)  # reaproveita o leitor calibrado para identificação
    ident = _identificacao(doc, base)
    atos = _atos(doc, base.numero)
    seq = _sequencia(atos, base.ultimo_ato_certificado)

    legib = []
    for p in paginas:
        uteis = len(re.sub(r"\s", "", p.texto))
        if p.confianca is not None and p.confianca < CONFIANCA_BAIXA:
            legib.append({"pagina": p.numero, "confianca": p.confianca, "aviso": "Leitura por OCR com baixa confiança: conferir no documento original."})
        if uteis < 80:
            legib.append({"pagina": p.numero, "confianca": p.confianca, "aviso": "Página com pouco ou nenhum texto legível."})

    alertas = []
    if not ident["numero_matricula"].valor:
        alertas.append({"nivel": "ALTO", "texto": "Número da matrícula não identificado.", "onde": "documento inteiro"})
    if seq["faltantes"]:
        alertas.append({"nivel": "MODERADO", "onde": "sequência de atos",
                        "texto": f"Atos não localizados na sequência: {', '.join(map(str, seq['faltantes']))}. Pode haver página ausente, ilegível ou numeração própria do cartório."})
    if seq["ultimo_ato_certificado"] and seq["ultimo_ato_lido"] and seq["ultimo_ato_lido"] < seq["ultimo_ato_certificado"]:
        alertas.append({"nivel": "ALTO", "onde": "certidão",
                        "texto": f"A certidão informa último ato nº {seq['ultimo_ato_certificado']}, mas o último ato lido é o nº {seq['ultimo_ato_lido']}."})
    if seq["datas_fora_de_ordem"]:
        alertas.append({"nivel": "INFORMATIVO", "onde": ", ".join(seq["datas_fora_de_ordem"]),
                        "texto": "Ato com data anterior ao ato precedente: conferir a data lida (pode ser data de título citado no ato)."})
    if not ident["data_emissao"].valor:
        alertas.append({"nivel": "MODERADO", "onde": "certidão", "texto": "Data de emissão da certidão não identificada."})
    for l in legib:
        alertas.append({"nivel": "MODERADO", "onde": f"página {l['pagina']}", "texto": l["aviso"]})
    sem_data = [a.id for a in atos if not a.data]
    if sem_data:
        alertas.append({"nivel": "INFORMATIVO", "onde": ", ".join(sem_data), "texto": "Data do ato não identificada no texto lido."})

    confs = [p.confianca for p in paginas if p.confianca is not None]
    stats = {
        "paginas": len(paginas),
        "paginas_ocr": sum(1 for p in paginas if p.metodo == "ocr"),
        "confianca_media_ocr": round(sum(confs) / len(confs), 1) if confs else None,
        "registros": sum(1 for a in atos if a.tipo == "R"),
        "averbacoes": sum(1 for a in atos if a.tipo == "AV"),
        "caracteres": len(doc.texto),
    }
    return Extracao(ident, atos, stats, seq, legib, alertas)
