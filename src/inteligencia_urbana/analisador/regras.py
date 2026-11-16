"""Motor de regras: cadeia de proprietários, ônus × cancelamentos, explicações simples, riscos e situação.

Regras de confiabilidade:
- só se afirma o que está escrito no documento, sempre com ato e página;
- ônus só é BAIXADO quando há ato de cancelamento que o cita (número do ato);
  cancelamento sem número citado → vínculo inferido pelo tipo = PENDENTE DE CONFIRMAÇÃO;
- quitação financeira mencionada não é cancelamento registral;
- explicações simples são INTERPRETAÇÕES geradas por regras a partir dos fatos extraídos.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import date

from ..documentos.matricula import NOME_PESSOA
from .extracao import NAO_IDENTIFICADO, Ato, Extracao

# natureza principal do ato: o primeiro termo que aparece no início do texto (onde fica o título do ato)
NATUREZAS = [
    ("cancelamento", r"cancelament|cancela-se|fica\s+cancelad|baixa\s+d[ae]"),
    ("compra e venda", r"compra\s+e\s+venda|venda\s+e\s+compra"),
    ("doação", r"\bdoa[çc][ãa]o"),
    ("partilha/inventário", r"partilha|invent[áa]rio|formal\s+de|adjudica[çc][ãa]o\s+(?:em|por)\s+invent"),
    ("permuta", r"\bpermuta"),
    ("arrematação", r"arremata"),
    ("adjudicação", r"adjudica"),
    ("usucapião", r"usucapi"),
    ("integralização/fusão societária", r"integraliza[çc][ãa]o|cis[ãa]o|fus[ãa]o\s+(?:de|da|das)\s+(?:empresa|sociedade)"),
    ("alienação fiduciária", r"aliena[çc][ãa]o\s+fiduci"),
    ("hipoteca", r"hipoteca"),
    ("penhora", r"penhora"),
    ("arresto/sequestro", r"arresto|sequestro"),
    ("indisponibilidade", r"indisponibilidade"),
    ("usufruto", r"usufruto"),
    ("servidão", r"servid[ãa]o"),
    ("promessa de compra e venda", r"promessa\s+de\s+compra|compromisso\s+de\s+compra"),
    ("cessão de direitos", r"cess[ãa]o\s+de\s+direitos"),
    ("cláusulas restritivas", r"inalienabilidade|impenhorabilidade|incomunicabilidade"),
    ("ação/averbação premonitória", r"a[çc][ãa]o\s+(?:de\s+execu|ajuizad)|art\.?\s*828|premonit"),
    ("construção", r"constru[çc][ãa]o|habite-se|edifica[çc][ãa]o\s+de"),
    ("demolição", r"demoli"),
    ("desmembramento", r"desmembr"),
    ("unificação", r"unifica|fus[ãa]o\s+de\s+matr"),
    ("retificação", r"retifica"),
    ("georreferenciamento", r"georreferenc|sigef"),
    ("reserva legal / CAR", r"reserva\s+legal|cadastro\s+ambiental\s+rural|\bCAR\b"),
    ("casamento/estado civil", r"casamento|div[óo]rcio|separa[çc][ãa]o\s+judicial|[óo]bito|regime\s+de\s+bens"),
    ("atualização de dados", r"inclus[ãa]o\s+d[aoe]|altera[çc][ãa]o\s+de\s+(?:nome|endere)|registro\s+cont[íi]nuo|C\.?E\.?P"),
    ("incorporação imobiliária", r"incorpora[çc][ãa]o\s+(?:imobili|registrad)|memorial\s+de\s+incorpora|patrim[ôo]nio\s+de\s+afeta"),
    ("instituição de condomínio", r"institui[çc][ãa]o\s+de\s+condom|especifica[çc][ãa]o\s+de\s+condom"),
]
TRANSMISSOES = {"compra e venda", "doação", "partilha/inventário", "permuta", "arrematação", "adjudicação", "usucapião",
                "integralização/fusão societária"}
ONUS = {"alienação fiduciária", "hipoteca", "penhora", "arresto/sequestro", "indisponibilidade", "usufruto", "servidão",
        "promessa de compra e venda", "cessão de direitos", "cláusulas restritivas", "ação/averbação premonitória"}
GARANTIAS = {"alienação fiduciária", "hipoteca"}
GRAVE = {"penhora", "arresto/sequestro", "indisponibilidade", "ação/averbação premonitória"}

ROT_ADQ = r"(?:ADQUIRENTES?|DONAT[ÁA]RI[OA]S?|COMPRADOR(?:A|ES|AS)?|OUTORGAD[OA]S?(?:\s+COMPRADOR\w*)?|HERDEIR[OA]S?|ARREMATANTES?|ADJUDICAT[ÁA]RI[OA]S?|NOME\s+D[AO]S?\s+ADQUIRENTES?)"
ROT_TRA = r"(?:TRANSMITENTES?|DOADOR(?:A|ES|AS)?|VENDEDOR(?:A|ES|AS)?|OUTORGANTES?(?:\s+VENDEDOR\w*)?|ESP[ÓO]LIO\s+DE|DE\s+CUJUS|NOME\s+D[AO]S?\s+TRANSMITENTES?)"
FIM_BLOCO = r"(?=(?i:T[ÍI]TULO|FORMA\s+E\s+DATA|VALOR\s*:|CONDI[ÇC][ÕO]ES|DOCUMENTOS|NOME\s+D[AO]S?\s+INTERVENIENTE|INTERVENIENTE|" + ROT_ADQ + r"|" + ROT_TRA + r")|$)"
NAO_NOMES = re.compile(r"^(?:RG|CPF|CNPJ|CIC|SSP|RUA|AV|AVENIDA|BRASIL|PARAN[ÁA]|CEP|ITBI|LTDA)\b")


@dataclass
class Explicacao:
    tecnica: str
    simples: str


@dataclass
class AtoAnalisado:
    id: str
    tipo: str
    numero: int
    data: str | None
    data_origem: str | None
    paginas: list[int]
    natureza: str
    explicacao: Explicacao
    pessoas: dict
    valor: str | None
    trecho: str


@dataclass
class Transmissao:
    ato: str
    data: str | None
    paginas: list[int]
    natureza: str
    de: list[str]
    para: list[str]
    fracao: str | None
    valor: str | None
    explicacao: str


@dataclass
class Onus:
    tipo: str
    ato: str
    data: str | None
    paginas: list[int]
    credor: str | None
    devedor: str | None
    valor: str | None
    processo: str | None
    vara: str | None
    situacao: str  # ATIVA, BAIXADA/CANCELADA, PARCIALMENTE CANCELADA, PENDENTE DE CONFIRMAÇÃO, HISTÓRICA
    ato_baixa: str | None
    data_baixa: str | None
    quitacao_mencionada: bool
    explicacao: str
    observacao: str = ""


@dataclass
class Risco:
    nivel: str  # CRÍTICO, ALTO, MODERADO, INFORMATIVO
    titulo: str
    onde: str
    porque: str
    documento: str
    verificar: str


@dataclass
class Analise:
    atos: list[AtoAnalisado]
    proprietario_inicial: dict | None
    transmissoes: list[Transmissao]
    proprietarios_atuais: list[str]
    cadeia_completa: bool
    alertas_cadeia: list[str]
    onus: list[Onus]
    averbacoes: list[AtoAnalisado]
    ultimos_atos: list[AtoAnalisado]
    atualidade: dict
    riscos: list[Risco]
    situacao: dict
    resumo: list[str]
    documentos_recomendados: list[str]
    contagens: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------- utilidades

def dbr(iso: str | None) -> str:
    return "/".join(reversed(iso.split("-"))) if iso else "data não identificada"


def _plano(t: str) -> str:
    return re.sub(r"\s+", " ", t or "").strip()


def natureza(ato: Ato) -> str:
    inicio = _plano(ato.texto_original)[:320]
    achados = []
    for nome, padrao in NATUREZAS:
        m = re.search(padrao, inicio, re.I)
        if m:
            achados.append((m.start(), nome))
    if not achados:
        return "outro"
    achados.sort()
    # citação de ônus dentro de cancelamento ("cancelada a hipoteca") não muda a natureza
    return achados[0][1]


def _nomes(segmento: str) -> list[str]:
    nomes = []
    for m in NOME_PESSOA.finditer(segmento):
        n = re.sub(r"\s+", " ", m.group(1)).strip()
        antes = segmento[max(0, m.start() - 45):m.start()].lower()
        if len(n) < 6 or NAO_NOMES.match(n) or re.search(r"\b(com|c[ôo]njuge|esposa|marido|mulher|anu[êe]ncia|representad[oa]\s+por|procurador)\b", antes):
            continue
        if n not in nomes:
            nomes.append(n)
    if not nomes:  # nomes em caixa normal: "Transmitente: José Fictício."
        m = re.match(r"\s*:?-?\s*((?:[A-ZÀ-Ú][\wÀ-ú'.&-]*\s*){2,8}?)(?=[,.;(]|\s+brasileir|\s+inscrit|$)", segmento)
        if m:
            n = m.group(1).strip(" .")
            if 5 <= len(n) <= 90 and not re.search(r"\d", n) and not NAO_NOMES.match(n.upper()):
                nomes.append(n)
    return nomes[:6]


def _pessoas(texto: str, rotulo: str) -> list[str]:
    t = _plano(texto)
    out = []
    for m in re.finditer(r"(?i:" + rotulo + r")\s*:?-?\s*(.{0,600}?)" + FIM_BLOCO, t):
        for n in _nomes(m.group(1)):
            if n not in out:
                out.append(n)
    return out


def _primeiro(rx: str, texto: str, grupo: int = 1) -> str | None:
    m = re.search(rx, _plano(texto), re.I)
    if not m:
        return None
    v = m.group(grupo).strip(" ,.;:-")
    return v + "." if re.search(r"\bS\.A$", v) else v


def _valor(texto: str) -> str | None:
    v = _primeiro(r"VALOR[^R]{0,25}R\$\.?\s*([\d.]+,\d{2})", texto) or _primeiro(r"valor\s+(?:de\s+)?R\$\.?\s*([\d.]+,\d{2})", texto)
    return f"R$ {v}" if v else None


def _refs(texto: str) -> list[str]:
    """Atos citados no texto ("objeto do R-2", "registro nº 2", "AV.5")."""
    refs = []
    for m in re.finditer(r"\b(R|AV|Av)\s*[\.\-–]?\s*0*(\d{1,3})(?!\d|[.,]\d)", texto):
        refs.append(f"{m.group(1).upper()}-{int(m.group(2))}")
    for m in re.finditer(r"registro\s+(?:n[º°o.]*\s*)?0*(\d{1,3})\b(?!\s*/\s*\d|[.,]\d)", texto, re.I):
        refs.append(f"R-{int(m.group(1))}")
    for m in re.finditer(r"averba[çc][ãa]o\s+(?:n[º°o.]*\s*)?0*(\d{1,3})\b(?![.,]\d)", texto, re.I):
        refs.append(f"AV-{int(m.group(1))}")
    return list(dict.fromkeys(refs))


# ---------------------------------------------------------------- explicações

def _lista(nomes: list[str]) -> str:
    if not nomes:
        return "pessoa não identificada no texto lido"
    return nomes[0] if len(nomes) == 1 else ", ".join(nomes[:-1]) + " e " + nomes[-1]


def _v(nomes: list[str], sing: str, plur: str) -> str:
    return plur if len(nomes) > 1 else sing


def explicar(a: Ato, nat: str, de: list[str], para: list[str], valor: str | None, extra: dict) -> Explicacao:
    quando = f"Em {dbr(a.data)}" if a.data else "Em data não identificada"
    ref = f"({a.id}, pág. {', '.join(map(str, a.paginas))})"
    tec = f"{'Registro' if a.tipo == 'R' else 'Averbação'} {a.id} — natureza identificada: {nat}. {ref}"
    v = f" O valor informado foi {valor}." if valor else ""
    s = {
        "compra e venda": f"{quando}, {_lista(de) if de else 'o dono anterior'} {_v(de, 'vendeu', 'venderam')} o imóvel para {_lista(para)}.{v} A partir daí, quem comprou passou a ser dono.",
        "doação": f"{quando}, {_lista(de) if de else 'o dono anterior'} {_v(de, 'deu', 'deram')} o imóvel de presente (doação) para {_lista(para)}. Doar é passar o imóvel para outra pessoa sem ela pagar por ele.",
        "partilha/inventário": f"{quando}, depois do falecimento ou da separação de quem era dono, o imóvel foi dividido entre {_lista(para)}. Isso se chama partilha.",
        "permuta": f"{quando}, o imóvel foi trocado (permuta). Quem recebeu o imóvel foi {_lista(para)}.",
        "arrematação": f"{quando}, o imóvel foi vendido em leilão da Justiça e quem arrematou foi {_lista(para)}.",
        "adjudicação": f"{quando}, a Justiça passou o imóvel para {_lista(para)} (adjudicação), normalmente para pagar uma dívida.",
        "usucapião": f"{quando}, a Justiça reconheceu que {_lista(para)} virou dono por ter ocupado o imóvel por muitos anos (usucapião).",
        "integralização/fusão societária": f"{quando}, o imóvel passou para a empresa {_lista(para)}, por uma operação entre empresas ou sócios.",
        "hipoteca": f"{quando}, o imóvel foi dado como garantia de uma dívida{(' com ' + extra['credor']) if extra.get('credor') else ''}. É como deixar o imóvel 'de caução': enquanto a hipoteca estiver na matrícula, o imóvel continua ligado a essa dívida.",
        "alienação fiduciária": f"{quando}, o imóvel foi usado como garantia de um financiamento{(' com ' + extra['credor']) if extra.get('credor') else ''}. Enquanto essa garantia não for cancelada na matrícula, o credor tem direitos sobre o imóvel.",
        "penhora": f"{quando}, um juiz mandou separar o imóvel para garantir o pagamento de uma dívida em um processo{(' (' + extra['processo'] + ')') if extra.get('processo') else ''}. Imóvel penhorado pode ir a leilão se a dívida não for paga.",
        "arresto/sequestro": f"{quando}, a Justiça prendeu o imóvel (arresto/sequestro) para garantir um processo. Ele fica preso até ordem contrária.",
        "indisponibilidade": f"{quando}, a Justiça bloqueou o imóvel: ele não pode ser vendido nem dado em garantia enquanto o bloqueio existir.",
        "usufruto": f"{quando}, foi registrado um usufruto: alguém ganhou o direito de usar o imóvel ou receber o aluguel dele, mesmo sem ser o dono.",
        "servidão": f"{quando}, foi registrada uma servidão: outra pessoa ou empresa pode usar parte do imóvel para algo específico (por exemplo, passagem ou rede de energia).",
        "promessa de compra e venda": f"{quando}, foi registrada uma promessa de venda: o dono se comprometeu a vender o imóvel para {_lista(para)}.",
        "cessão de direitos": f"{quando}, direitos sobre o imóvel foram passados para outra pessoa (cessão de direitos).",
        "cláusulas restritivas": f"{quando}, o imóvel recebeu regras que limitam o que o dono pode fazer (por exemplo, não poder vender ou não poder ser penhorado).",
        "ação/averbação premonitória": f"{quando}, foi anotado que existe um processo na Justiça que pode atingir o imóvel. É um aviso para quem pensa em comprar.",
        "cancelamento": f"{quando}, foi cancelada {('a anotação ' + ', '.join(extra['refs'])) if extra.get('refs') else 'uma anotação anterior'}. Cancelar quer dizer que ela deixou de valer.",
        "construção": f"{quando}, foi anotado que existe uma construção no terreno.",
        "demolição": f"{quando}, foi anotado que uma construção foi demolida.",
        "desmembramento": f"{quando}, o terreno foi dividido em partes menores (desmembramento).",
        "unificação": f"{quando}, este imóvel foi juntado com outro (unificação).",
        "retificação": f"{quando}, uma informação da matrícula foi corrigida (por exemplo, área, medidas ou nomes).",
        "georreferenciamento": f"{quando}, as divisas do imóvel foram medidas com GPS e cadastradas (georreferenciamento).",
        "reserva legal / CAR": f"{quando}, foi anotada a área de mata que precisa ser preservada (reserva legal) ou o cadastro ambiental do imóvel (CAR).",
        "casamento/estado civil": f"{quando}, foi anotada uma mudança na vida de um dono (casamento, divórcio, falecimento ou regime de bens). O dono do imóvel não muda só por isso.",
        "atualização de dados": f"{quando}, foram atualizados dados da matrícula (como CEP, documentos ou nomes). Isso não muda quem é o dono.",
        "incorporação imobiliária": f"{quando}, foi registrado o projeto de um prédio ou condomínio a ser construído no terreno (incorporação).",
        "instituição de condomínio": f"{quando}, o prédio ou condomínio foi oficialmente dividido em unidades (apartamentos, salas ou lotes).",
    }.get(nat, f"{quando}, foi feita uma anotação na matrícula que o sistema não conseguiu resumir. Leia o texto original para entender.")
    return Explicacao(tec, s)


# ---------------------------------------------------------------- análise

def analisar(ext: Extracao, hoje: date | None = None) -> Analise:
    hoje = hoje or date.today()
    atos_a: list[AtoAnalisado] = []
    transm: list[Transmissao] = []
    onus: list[Onus] = []
    cancelamentos: list[tuple[Ato, list[str], str]] = []

    for a in ext.atos:
        nat = natureza(a)
        de = _pessoas(a.texto_original, ROT_TRA) if nat in TRANSMISSOES | {"promessa de compra e venda"} else []
        para = _pessoas(a.texto_original, ROT_ADQ) if nat in TRANSMISSOES | {"promessa de compra e venda"} else []
        valor = _valor(a.texto_original)
        texto = _plano(a.texto_original)
        extra = {
            "credor": _primeiro(r"(?:em\s+favor\s+d[oa]s?|credor[ae]?s?\s*:?|credora\s*:|fiduci[áa]ri[oa]\s*:)\s*(?:o\s+|a\s+)?([A-ZÀ-Ú][\wÀ-ú.&\- ]{2,80}?)(?=,|;|\.\s|\s+-|\s+valor|\s+no\s+valor|$)", texto),
            "devedor": _primeiro(r"(?:devedor[ae]?s?|executad[oa]s?|fiduciante|emitente|mutu[áa]ri[oa])\s*:?\s*([A-ZÀ-Ú][\wÀ-ú. ]{2,80}?)(?=,|;|\.\s|$)", texto),
            "processo": _primeiro(r"\b(\d{7}-\d{2}\.\d{4}\.\d\.\d{2}\.\d{4})\b", texto) or _primeiro(r"autos\s+(?:n[º°o.]*\s*)?([\d./\-]{5,})", texto),
            "vara": _primeiro(r"(\d{1,2}[ªa]?\s*Vara[^,.;]{0,60})", texto),
            "refs": [r for r in _refs(texto) if r != a.id] if nat == "cancelamento" else [],
        }
        exp = explicar(a, nat, de, para, valor, extra)
        atos_a.append(AtoAnalisado(a.id, a.tipo, a.numero, a.data, a.data_origem, a.paginas, nat, exp,
                                   {"de": de, "para": para, "credor": extra["credor"], "devedor": extra["devedor"]}, valor, a.fonte.trecho))

        if nat in TRANSMISSOES:
            frac = _primeiro(r"parte\s+ideal\s+(?:de|correspondente\s+a)\s*(\d+(?:[,.]\d+)?\s*%)", texto) or \
                _primeiro(r"fra[çc][ãa]o\s+ideal\s+de\s*(\d+(?:[,.]\d+)?\s*%)", texto)
            transm.append(Transmissao(a.id, a.data, a.paginas, nat, de, para, frac, valor, exp.simples))
        if nat in ONUS:
            onus.append(Onus(nat, a.id, a.data, a.paginas, extra["credor"], extra["devedor"], valor, extra["processo"], extra["vara"],
                             "ATIVA", None, None, bool(re.search(r"quita[çc][ãa]o|quitad", texto, re.I)), exp.simples))
        if nat == "cancelamento":
            parcial = "parcial" if re.search(r"cancelamento\s+parcial|parcialmente|em\s+parte|libera[çc][ãa]o\s+parcial", texto, re.I) else "total"
            cancelamentos.append((a, extra["refs"], parcial))

    # vínculo ônus ↔ cancelamento
    por_id = {o.ato: o for o in onus}
    for c, refs, parcial in cancelamentos:
        alvos = [por_id[r] for r in refs if r in por_id]
        if alvos:
            for o in alvos:
                o.situacao = "PARCIALMENTE CANCELADA" if parcial == "parcial" else "BAIXADA/CANCELADA"
                o.ato_baixa, o.data_baixa = c.id, c.data
                o.explicacao += f" Depois, o ato {c.id} ({dbr(c.data)}) cancelou essa anotação{' em parte' if parcial == 'parcial' else ''}."
                for x in atos_a:
                    if x.id == o.ato:
                        x.explicacao.simples += f" Essa anotação foi cancelada depois pelo ato {c.id}."
        else:
            texto = _plano(c.texto_original).lower()
            candidatos = [o for o in onus if o.situacao == "ATIVA" and o.tipo.split("/")[0].split()[0][:6] in texto and _antes(o.ato, c.id)]
            if candidatos:
                o = candidatos[-1]
                o.situacao = "PENDENTE DE CONFIRMAÇÃO"
                o.ato_baixa, o.data_baixa = c.id, c.data
                o.observacao = f"O ato {c.id} cancela um(a) {o.tipo}, mas não cita o número do ato; o vínculo com {o.ato} foi deduzido pelo tipo e precisa ser confirmado."
    for o in onus:
        if o.situacao == "ATIVA":
            o.observacao = "Não foi encontrado ato de cancelamento na matrícula analisada."
            if o.quitacao_mencionada:
                o.observacao += " Há menção a quitação, mas quitar a dívida não cancela o registro: é preciso averbar o cancelamento."
            o.explicacao += " Não encontramos, nesta matrícula, nenhum ato cancelando isso."

    # cadeia de proprietários
    prop_ini = None
    m_prop = re.search(r"PROPRIET[ÁA]RI[OA]S?\s*:?-?\s*(.{0,400})", _plano(ext.abertura))
    if m_prop and _nomes(m_prop.group(1)):
        prop_ini = {"nomes": _nomes(m_prop.group(1)), "trecho": m_prop.group(0)[:200]}
    alertas_cadeia = []
    atuais: list[str] = list(prop_ini["nomes"]) if prop_ini else []
    for t in transm:
        if not t.para:
            alertas_cadeia.append(f"No ato {t.ato} ({t.natureza}) não foi possível identificar o nome de quem recebeu o imóvel.")
        if atuais and t.de and not set(map(str.upper, t.de)) & set(map(str.upper, atuais)):
            alertas_cadeia.append(f"No ato {t.ato}, quem transmitiu ({_lista(t.de)}) não aparece como dono no ato anterior ({_lista(atuais)}). Pode faltar um ato ou os nomes podem estar escritos de outro jeito.")
        if t.fracao and t.para:
            # parte ideal: quem recebeu entra; quem transmitiu pode ter ficado com outra parte (não se deduz)
            atuais = list(dict.fromkeys(atuais + t.para))
            alertas_cadeia.append(f"No ato {t.ato}, {_lista(t.de) if t.de else 'o transmitente'} passou {t.fracao} do imóvel para {_lista(t.para)}. "
                                  "Pelo texto lido não dá para garantir se quem passou ainda tem alguma parte; por isso os dois aparecem como donos.")
        elif t.para:
            atuais = t.para
    cadeia_ok = bool(transm) and not alertas_cadeia
    if not transm:
        alertas_cadeia.append("Nenhuma transmissão (venda, doação, partilha etc.) foi identificada no texto lido.")

    averb = [x for x in atos_a if x.tipo == "AV"]
    ultimos = sorted(atos_a, key=lambda x: x.numero, reverse=True)[:5]

    # atualidade
    emi = ext.identificacao["data_emissao"].valor
    dias = (hoje - date.fromisoformat(emi)).days if emi else None
    atualidade = {
        "data_emissao": emi, "dias_desde_emissao": dias,
        "ultimo_ato": ultimos[0].id if ultimos else None, "data_ultimo_ato": ext.sequencia.get("ultima_data"),
        "atos_nao_localizados": ext.sequencia.get("faltantes", []),
        "texto": ("Esta análise considera o documento enviado e a data de sua emissão. Para uma negociação ou operação "
                  "imobiliária, recomenda-se solicitar uma certidão atualizada ao Registro de Imóveis competente."),
    }

    riscos = _riscos(ext, onus, transm, alertas_cadeia, dias)
    niveis = {r.nivel for r in riscos}
    leitura_fraca = not ext.identificacao["numero_matricula"].valor or not ext.atos or \
        (ext.estatisticas.get("confianca_media_ocr") or 100) < 60
    if leitura_fraca:
        sit = ("ANÁLISE INCONCLUSIVA", "Faltam informações ou a leitura do documento ficou ruim. Não dá para concluir com segurança.")
    elif niveis & {"CRÍTICO", "ALTO"}:
        sit = ("DOCUMENTAÇÃO COM RISCOS RELEVANTES", "Encontramos situações que precisam ser esclarecidas antes de qualquer negócio.")
    elif "MODERADO" in niveis:
        sit = ("DOCUMENTAÇÃO COM PONTOS DE ATENÇÃO", "Não encontramos impedimentos graves, mas há pontos que precisam ser conferidos.")
    else:
        sit = ("DOCUMENTAÇÃO APARENTEMENTE REGULAR", "No documento analisado não encontramos ônus ativos nem pontos de atenção. Isso não substitui a análise de um profissional nem uma certidão atualizada.")

    ativos = [o for o in onus if o.situacao == "ATIVA"]
    resumo = [
        f"Este é o imóvel da matrícula nº {ext.identificacao['numero_matricula'].valor}" + (f", do {ext.identificacao['cartorio'].valor}" if ext.identificacao["cartorio"].valor else "") + "."
        if ext.identificacao["numero_matricula"].valor else "O número da matrícula não foi identificado no documento.",
        (f"Pelo documento, hoje o imóvel pertence a {_lista(atuais)} ({transm[-1].ato})." if atuais else "Não foi possível identificar com segurança quem é o dono atual."),
        f"Encontramos {len(ext.atos)} atos na matrícula: {ext.estatisticas['registros']} registros e {ext.estatisticas['averbacoes']} averbações.",
        (f"Há {len(ativos)} ônus sem cancelamento na matrícula: " + ", ".join(f"{o.tipo} ({o.ato})" for o in ativos) + "." if ativos
         else "Não encontramos ônus ativos na matrícula analisada." if onus else "Não encontramos ônus (dívidas ou impedimentos) registrados no texto lido."),
        f"Situação geral: {sit[0].lower()}.",
    ]
    if emi:
        resumo.append(f"A certidão foi emitida em {dbr(emi)}" + (f", há {dias} dias." if dias is not None else "."))

    docs = ["Certidão de inteiro teor atualizada da matrícula (emitida perto da data do negócio)."]
    if ativos:
        docs.append("Documento de quitação e pedido de cancelamento (baixa) de cada ônus ativo, averbado no Registro de Imóveis.")
    if any(o.tipo in GRAVE for o in onus):
        docs.append("Certidão do processo judicial citado (para saber se ainda existe e se a constrição foi levantada).")
    if any(t.fracao for t in transm):
        docs.append("Documentos que comprovem a parte (fração) de cada dono e a concordância de todos com o negócio.")
    docs += ["Certidões pessoais dos donos (ações cíveis, trabalhistas, protestos e débitos fiscais).",
             "Certidão negativa de débitos municipais (IPTU) do imóvel."]
    if alertas_cadeia:
        docs.append("Matrículas ou registros anteriores que expliquem a passagem do imóvel entre os donos.")

    contagens = {"onus": len(onus), "onus_baixados": sum(o.situacao == "BAIXADA/CANCELADA" for o in onus),
                 "onus_ativos": len(ativos), "onus_pendentes": sum(o.situacao.startswith(("PENDENTE", "PARCIAL")) for o in onus)}
    return Analise(atos_a, prop_ini, transm, atuais, cadeia_ok, alertas_cadeia, onus, averb, ultimos, atualidade, riscos,
                   {"classe": sit[0], "texto": sit[1]}, resumo, docs, contagens)


def _antes(ato_onus: str, ato_cancel: str) -> bool:
    n = lambda s: int(s.split("-")[1])
    return n(ato_onus) < n(ato_cancel)


def _riscos(ext: Extracao, onus: list[Onus], transm: list[Transmissao], alertas_cadeia: list[str], dias: int | None) -> list[Risco]:
    rs: list[Risco] = []
    for o in onus:
        onde = f"{o.ato}, pág. {', '.join(map(str, o.paginas))}"
        if o.situacao == "ATIVA" and o.tipo in GRAVE:
            rs.append(Risco("CRÍTICO", f"{o.tipo.capitalize()} sem cancelamento", onde, "Pode impedir a venda ou levar o imóvel a leilão.",
                            "Certidão do processo e averbação do cancelamento na matrícula.", "Se o processo terminou e se a baixa foi averbada."))
        elif o.situacao == "ATIVA" and o.tipo in GARANTIAS:
            rs.append(Risco("ALTO", f"{o.tipo.capitalize()} sem cancelamento", onde, "O imóvel continua servindo de garantia de uma dívida.",
                            "Termo de quitação do credor e averbação do cancelamento.", "Se a dívida foi paga e se o cancelamento foi registrado."))
        elif o.situacao == "ATIVA":
            rs.append(Risco("ALTO" if o.tipo in {"usufruto", "cláusulas restritivas"} else "MODERADO", f"{o.tipo.capitalize()} sem cancelamento", onde,
                            "Limita o uso ou a venda do imóvel.", "Documento que extinga ou cancele o direito, averbado na matrícula.", "Se o direito ainda existe."))
        elif o.situacao.startswith(("PENDENTE", "PARCIAL")):
            rs.append(Risco("ALTO", f"{o.tipo.capitalize()}: baixa não confirmada", onde, o.observacao or "Cancelamento parcial ou sem vínculo claro.",
                            "Certidão do ato de cancelamento e esclarecimento do Registro de Imóveis.", "Se o cancelamento atinge todo o ônus."))
        if o.quitacao_mencionada and o.situacao == "ATIVA":
            rs.append(Risco("MODERADO", "Quitação mencionada sem cancelamento", onde, "Pagar a dívida não apaga o registro sozinho.",
                            "Averbação do cancelamento.", "Se o cancelamento foi pedido ao cartório."))
    for t in alertas_cadeia:
        rs.append(Risco("MODERADO", "Cadeia de proprietários", "transmissões", t, "Registros anteriores e documentos dos donos.", "A sequência de donos."))
    if dias is not None and dias > 30:
        rs.append(Risco("INFORMATIVO", "Certidão emitida há mais de 30 dias", "data de emissão",
                        f"Podem ter ocorrido atos depois de {dbr(ext.identificacao['data_emissao'].valor)}.", "Certidão atualizada.", "Se houve atos novos."))
    for a in ext.alertas:
        nivel = {"ALTO": "ALTO", "MODERADO": "MODERADO"}.get(a["nivel"], "INFORMATIVO")
        rs.append(Risco(nivel, "Leitura do documento", a["onde"], a["texto"], "Documento original ou certidão mais legível.", "O trecho no documento original."))
    ordem = {"CRÍTICO": 0, "ALTO": 1, "MODERADO": 2, "INFORMATIVO": 3}
    return sorted(rs, key=lambda r: ordem[r.nivel])
