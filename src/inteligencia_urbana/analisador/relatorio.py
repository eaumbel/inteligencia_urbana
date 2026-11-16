"""Relatório da matrícula em PDF, em linguagem simples (leitura de quinta série).

Organização: primeiro o que importa (situação, resumo, dono, dívidas, pontos de atenção), depois os detalhes
(cada ato com a versão simples e o trecho original). Toda afirmação traz ato e página. As explicações simples
são marcadas como interpretação do sistema; o trecho original é o que o documento comprova.
"""

from __future__ import annotations

import io
from datetime import date
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (Image, KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle)

from .extracao import NAO_IDENTIFICADO, Extracao
from .regras import Analise, dbr

LOGO = Path(__file__).resolve().parents[3] / "web" / "assets" / "logo.png"

PRIMARIA = colors.HexColor("#142D3A")
SECUNDARIA = colors.HexColor("#315568")
FUNDO = colors.HexColor("#F4F5F2")
DESTAQUE = colors.HexColor("#C6A66B")
SUCESSO = colors.HexColor("#27866A")
ALERTA = colors.HexColor("#D49A3A")
PERIGO = colors.HexColor("#C65353")
CINZA = colors.HexColor("#5F6B72")
LINHA = colors.HexColor("#DCDFDA")

COR_NIVEL = {"CRÍTICO": PERIGO, "ALTO": colors.HexColor("#B8743A"), "MODERADO": ALERTA, "INFORMATIVO": SECUNDARIA}
COR_SITUACAO = {
    "DOCUMENTAÇÃO APARENTEMENTE REGULAR": SUCESSO,
    "DOCUMENTAÇÃO COM PONTOS DE ATENÇÃO": ALERTA,
    "DOCUMENTAÇÃO COM RISCOS RELEVANTES": PERIGO,
    "ANÁLISE INCONCLUSIVA": SECUNDARIA,
}
COR_ONUS = {"ATIVA": PERIGO, "BAIXADA/CANCELADA": SUCESSO, "PARCIALMENTE CANCELADA": ALERTA,
            "PENDENTE DE CONFIRMAÇÃO": ALERTA, "HISTÓRICA": CINZA}
PALAVRA_SITUACAO = {"ATIVA": "AINDA VALE", "BAIXADA/CANCELADA": "CANCELADA", "PARCIALMENTE CANCELADA": "CANCELADA EM PARTE",
                    "PENDENTE DE CONFIRMAÇÃO": "CONFERIR", "HISTÓRICA": "HISTÓRICA"}
PALAVRA_NIVEL = {"CRÍTICO": "MUITO IMPORTANTE", "ALTO": "IMPORTANTE", "MODERADO": "ATENÇÃO", "INFORMATIVO": "PARA SABER"}

GLOSSARIO = [
    ("Matrícula", "É como a certidão de nascimento do imóvel. Tudo o que acontece com ele fica anotado ali, em ordem."),
    ("Registro (R)", "Anotação de algo importante: venda, doação, herança, hipoteca, penhora."),
    ("Averbação (AV)", "Anotação de uma mudança ou correção: construção, casamento do dono, cancelamento, CEP."),
    ("Ônus", "Algo que \"pesa\" sobre o imóvel: dívida garantida por ele, bloqueio da Justiça ou direito de outra pessoa."),
    ("Hipoteca / alienação fiduciária", "O imóvel serve de garantia de um empréstimo ou financiamento."),
    ("Penhora", "A Justiça separa o imóvel para pagar uma dívida. Ele pode ir a leilão."),
    ("Cancelamento (baixa)", "Anotação que diz que um ônus deixou de valer. Pagar a dívida não basta: é preciso anotar o cancelamento."),
    ("Fração ideal", "Parte do imóvel que pertence a cada dono quando há mais de um (por exemplo, 50%)."),
]


def _estilos():
    base = dict(fontName="Helvetica", fontSize=10.5, leading=15, textColor=colors.HexColor("#1E2A30"), alignment=TA_LEFT)
    return {
        "titulo": ParagraphStyle("titulo", **{**base, "fontName": "Helvetica-Bold", "fontSize": 20, "leading": 25, "textColor": PRIMARIA}),
        "sub": ParagraphStyle("sub", **{**base, "fontSize": 11, "textColor": SECUNDARIA}),
        "h1": ParagraphStyle("h1", **{**base, "fontName": "Helvetica-Bold", "fontSize": 14, "leading": 19, "textColor": PRIMARIA,
                                      "spaceBefore": 14, "spaceAfter": 6}),
        "h2": ParagraphStyle("h2", **{**base, "fontName": "Helvetica-Bold", "fontSize": 11.5, "leading": 16, "textColor": SECUNDARIA,
                                      "spaceBefore": 8, "spaceAfter": 3}),
        "p": ParagraphStyle("p", **base),
        "bullet": ParagraphStyle("bullet", **{**base, "leftIndent": 12, "bulletIndent": 2, "spaceAfter": 3}),
        "cel": ParagraphStyle("cel", **{**base, "fontSize": 9.5, "leading": 13}),
        "celb": ParagraphStyle("celb", **{**base, "fontName": "Helvetica-Bold", "fontSize": 9.5, "leading": 13}),
        "cab": ParagraphStyle("cab", **{**base, "fontName": "Helvetica-Bold", "fontSize": 8.5, "leading": 11, "textColor": CINZA}),
        "nota": ParagraphStyle("nota", **{**base, "fontSize": 8.5, "leading": 12, "textColor": CINZA}),
        "orig": ParagraphStyle("orig", **{**base, "fontName": "Courier", "fontSize": 7.8, "leading": 10.5, "textColor": colors.HexColor("#3A464C")}),
        "selo": ParagraphStyle("selo", **{**base, "fontName": "Helvetica-Bold", "fontSize": 8.5, "leading": 11, "textColor": colors.white}),
        "grande": ParagraphStyle("grande", **{**base, "fontName": "Helvetica-Bold", "fontSize": 13, "leading": 17, "textColor": colors.white}),
        "grande_txt": ParagraphStyle("grande_txt", **{**base, "fontSize": 10.5, "leading": 15, "textColor": colors.white}),
    }


def _e(t) -> str:
    return escape(str(t)) if t not in (None, "") else NAO_IDENTIFICADO


def _selo(texto: str, cor, st) -> Table:
    t = Table([[Paragraph(escape(texto), st["selo"])]], hAlign="LEFT")
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), cor), ("LEFTPADDING", (0, 0), (-1, -1), 5),
                           ("RIGHTPADDING", (0, 0), (-1, -1), 5), ("TOPPADDING", (0, 0), (-1, -1), 2),
                           ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]))
    return t


def _tabela(linhas: list[list], larguras: list[float], st, cabecalho: list[str] | None = None) -> Table:
    dados = []
    if cabecalho:
        dados.append([Paragraph(escape(c.upper()), st["cab"]) for c in cabecalho])
    for l in linhas:
        dados.append([c if not isinstance(c, str) else Paragraph(c, st["cel"]) for c in l])
    t = Table(dados, colWidths=larguras, repeatRows=1 if cabecalho else 0, hAlign="LEFT")
    estilo = [("VALIGN", (0, 0), (-1, -1), "TOP"), ("LINEBELOW", (0, 0), (-1, -1), 0.5, LINHA),
              ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
              ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 6)]
    if cabecalho:
        estilo += [("BACKGROUND", (0, 0), (-1, 0), FUNDO), ("LINEBELOW", (0, 0), (-1, 0), 0.8, SECUNDARIA)]
    t.setStyle(TableStyle(estilo))
    return t


def _caixa(conteudo: list, fundo, borda=None, largura: float = 170 * mm) -> Table:
    t = Table([[conteudo]], colWidths=[largura], hAlign="LEFT")
    estilo = [("BACKGROUND", (0, 0), (-1, -1), fundo), ("LEFTPADDING", (0, 0), (-1, -1), 10),
              ("RIGHTPADDING", (0, 0), (-1, -1), 10), ("TOPPADDING", (0, 0), (-1, -1), 8), ("BOTTOMPADDING", (0, 0), (-1, -1), 9)]
    if borda is not None:
        estilo.append(("LINEBEFORE", (0, 0), (0, -1), 3, borda))
    t.setStyle(TableStyle(estilo))
    return t


def _onde(f) -> str:
    if not f or not getattr(f, "pagina", None):
        return "—"
    return f"pág. {f.pagina}"


def gerar_pdf(ext: Extracao, an: Analise, arquivo: str | None = None, hoje: date | None = None) -> bytes:
    hoje = hoje or date.today()
    st = _estilos()
    buf = io.BytesIO()
    num = ext.identificacao["numero_matricula"].valor
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=20 * mm, rightMargin=20 * mm, topMargin=18 * mm, bottomMargin=18 * mm,
                            title=f"Relatório da matrícula {num or ''}".strip(), author="Inteligência Urbana",
                            subject="Análise de matrícula em linguagem simples")
    L = []

    # ------------------------------------------------------------ capa
    cab = []
    if LOGO.exists():
        cab.append(Image(str(LOGO), width=34 * mm, height=34 * mm * 685 / 994))
    titulo = [Paragraph("Relatório da matrícula", st["titulo"]),
              Paragraph("Explicado de um jeito simples, para qualquer pessoa entender", st["sub"])]
    t = Table([[cab or "", titulo]], colWidths=[40 * mm, 130 * mm], hAlign="LEFT")
    t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
    L += [t, Spacer(1, 6)]
    info = [
        ["Matrícula nº", f"<b>{_e(num)}</b>"],
        ["Cartório", _e(ext.identificacao["cartorio"].valor)],
        ["Cidade", _e(" - ".join(x for x in (ext.identificacao["municipio"].valor, ext.identificacao["uf"].valor) if x) or None)],
        ["Certidão emitida em", _e(dbr(an.atualidade["data_emissao"]) if an.atualidade["data_emissao"] else None)],
        ["Relatório feito em", hoje.strftime("%d/%m/%Y")],
    ]
    if arquivo:
        info.append(["Arquivo analisado", _e(arquivo)])
    L.append(_tabela([[Paragraph(escape(a), st["celb"]), b] for a, b in info], [45 * mm, 125 * mm], st))
    L.append(Spacer(1, 10))

    cor = COR_SITUACAO.get(an.situacao["classe"], SECUNDARIA)
    L.append(_caixa([Paragraph("Situação geral", st["grande_txt"]), Paragraph(escape(an.situacao["classe"]), st["grande"]),
                     Spacer(1, 3), Paragraph(escape(an.situacao["texto"]), st["grande_txt"])], cor))

    # ------------------------------------------------------------ resumo
    L.append(Paragraph("1. Resumo em poucas palavras", st["h1"]))
    for frase in an.resumo:
        L.append(Paragraph(escape(frase), st["bullet"], bulletText="•"))

    # ------------------------------------------------------------ glossário
    L.append(Paragraph("2. Palavras que aparecem neste relatório", st["h1"]))
    L.append(_tabela([[Paragraph(f"<b>{escape(a)}</b>", st["cel"]), escape(b)] for a, b in GLOSSARIO], [45 * mm, 125 * mm], st))

    # ------------------------------------------------------------ imóvel
    L.append(Paragraph("3. Qual é o imóvel", st["h1"]))
    rotulos = [("tipo", "Tipo (urbano ou rural)"), ("area", "Tamanho (área)"), ("lote", "Lote"), ("quadra", "Quadra"),
               ("loteamento", "Loteamento / bairro"), ("endereco", "Endereço"), ("inscricao_imobiliaria", "Inscrição na prefeitura"),
               ("ccir", "CCIR (imóvel rural)"), ("car", "CAR (cadastro ambiental)")]
    linhas = []
    for k, rot in rotulos:
        c = ext.imovel.get(k)
        if c is None or (not c.valor and k in ("ccir", "car", "loteamento")):
            continue
        linhas.append([Paragraph(escape(rot), st["celb"]), _e(c.valor), _onde(c.fonte)])
    L.append(_tabela(linhas, [50 * mm, 95 * mm, 25 * mm], st, ["Informação", "O que diz o documento", "Onde"]))

    # ------------------------------------------------------------ dono
    L.append(Paragraph("4. Quem é o dono", st["h1"]))
    if an.proprietarios_atuais:
        ultimo = an.transmissoes[-1] if an.transmissoes else None
        L.append(_caixa([Paragraph("Pelo documento, hoje o imóvel pertence a:", st["p"]),
                         Paragraph("<b>" + escape(", ".join(an.proprietarios_atuais)) + "</b>", st["h2"]),
                         Paragraph(escape(f"Base: {ultimo.ato}, pág. {', '.join(map(str, ultimo.paginas))}." if ultimo else
                                          "Base: abertura da matrícula (nenhuma transmissão posterior identificada)."), st["nota"])],
                        FUNDO, DESTAQUE))
    elif an.cotitularidade:
        txt = [Paragraph("<b>O imóvel tem vários donos ao mesmo tempo, cada um com uma parte (condomínio).</b>", st["p"]),
               Paragraph("Por isso o sistema não monta sozinho a lista completa de donos atuais: ela precisa ser conferida no "
                         "Registro de Imóveis.", st["p"])]
        if an.ultimos_adquirentes:
            txt.append(Paragraph("Últimos que receberam uma parte, pelo texto lido:", st["nota"]))
            for u in reversed(an.ultimos_adquirentes):
                txt.append(Paragraph(escape(f"{dbr(u['data'])} — {', '.join(u['nomes'])}" + (f" ({u['fracao']})" if u['fracao'] else "")
                                            + f" — {u['ato']}"), st["nota"]))
        L.append(_caixa(txt, FUNDO, ALERTA))
    else:
        L.append(_caixa([Paragraph("Não foi possível identificar com segurança quem é o dono atual.", st["p"])], FUNDO, ALERTA))
    L.append(Paragraph("Como o imóvel passou de mão em mão", st["h2"]))
    linhas = []
    if an.proprietario_inicial:
        linhas.append(["Abertura", escape("Primeiro dono anotado na matrícula: " + ", ".join(an.proprietario_inicial["nomes"]) + "."), "abertura"])
    for t in an.transmissoes:
        linhas.append([escape(dbr(t.data)), escape(t.explicacao) + (f" <b>Parte transmitida: {escape(t.fracao)}.</b>" if t.fracao else ""),
                       escape(f"{t.ato}, pág. {', '.join(map(str, t.paginas))}")])
    if linhas:
        L.append(_tabela(linhas, [24 * mm, 116 * mm, 30 * mm], st, ["Quando", "O que aconteceu", "Onde"]))
    for a in an.alertas_cadeia:
        L.append(Paragraph("<b>Atenção:</b> " + escape(a), st["bullet"], bulletText="!"))

    # ------------------------------------------------------------ ônus
    L.append(Paragraph("5. Dívidas, garantias e bloqueios (ônus)", st["h1"]))
    if not an.onus:
        L.append(Paragraph("Não encontramos ônus no texto lido. Isso <b>não</b> quer dizer, sozinho, que o imóvel está livre: "
                           "confira a certidão atualizada e as certidões dos donos.", st["p"]))
    for o in an.onus:
        cor = COR_ONUS.get(o.situacao, SECUNDARIA)
        bloco = [_selo(PALAVRA_SITUACAO.get(o.situacao, o.situacao), cor, st), Spacer(1, 3),
                 Paragraph(f"<b>{escape(o.tipo.capitalize())}</b> — {escape(o.ato)}, pág. {', '.join(map(str, o.paginas))}", st["p"]),
                 Paragraph(escape(o.explicacao), st["p"])]
        det = []
        if o.credor:
            det.append(f"Credor (a quem se deve): {o.credor}")
        if o.valor:
            det.append(f"Valor: {o.valor}")
        if o.processo:
            det.append(f"Processo: {o.processo}")
        if o.vara:
            det.append(f"Onde corre: {o.vara}")
        if o.ato_baixa:
            det.append(f"Ato de cancelamento: {o.ato_baixa} ({dbr(o.data_baixa)})")
        if det:
            bloco.append(Paragraph(escape(" · ".join(det)), st["nota"]))
        if o.observacao:
            bloco.append(Paragraph("<b>Observação:</b> " + escape(o.observacao), st["nota"]))
        L += [KeepTogether(_caixa(bloco, FUNDO, cor)), Spacer(1, 6)]

    # ------------------------------------------------------------ riscos
    L.append(Paragraph("6. Pontos de atenção", st["h1"]))
    if not an.riscos:
        L.append(Paragraph("Nenhum ponto de atenção foi encontrado pelas regras do sistema no documento analisado.", st["p"]))
    for r in an.riscos:
        cor = COR_NIVEL[r.nivel]
        L += [KeepTogether(_caixa([
            _selo(PALAVRA_NIVEL[r.nivel], cor, st), Spacer(1, 3),
            Paragraph(f"<b>{escape(r.titulo)}</b>", st["p"]),
            Paragraph(f"<b>Por que importa:</b> {escape(r.porque)}", st["cel"]),
            Paragraph(f"<b>Onde:</b> {escape(r.onde)} &nbsp; <b>O que conferir:</b> {escape(r.verificar)}", st["cel"]),
            Paragraph(f"<b>Documento que resolve:</b> {escape(r.documento)}", st["cel"]),
        ], colors.white, cor)), Spacer(1, 5)]

    # ------------------------------------------------------------ atualidade
    L.append(Paragraph("7. Este documento está atualizado?", st["h1"]))
    at = an.atualidade
    if at["data_emissao"]:
        L.append(Paragraph(escape(f"A certidão foi emitida em {dbr(at['data_emissao'])}, há {at['dias_desde_emissao']} dias. "
                                  "Depois dessa data podem ter acontecido coisas que não aparecem aqui."), st["p"]))
    else:
        L.append(Paragraph("A data de emissão da certidão não foi identificada no documento.", st["p"]))
    if at["ultimo_ato"]:
        L.append(Paragraph(escape(f"Último ato lido: {at['ultimo_ato']}."), st["p"]))
    if at["atos_nao_localizados"]:
        L.append(Paragraph(escape("Atos que não encontramos na sequência: " + ", ".join(map(str, at["atos_nao_localizados"])) +
                                  ". Pode faltar página ou o texto estar ilegível."), st["p"]))
    L += [Spacer(1, 4), _caixa([Paragraph(escape(at["texto"]), st["p"])], FUNDO, DESTAQUE)]

    # ------------------------------------------------------------ documentos
    L.append(Paragraph("8. O que pedir antes de fechar negócio", st["h1"]))
    for d in an.documentos_recomendados:
        L.append(Paragraph(escape(d), st["bullet"], bulletText="-"))

    # ------------------------------------------------------------ atos
    L.append(Paragraph("9. Tudo o que aconteceu com o imóvel, ato por ato", st["h1"]))
    L.append(Paragraph("Para cada anotação: primeiro a explicação simples (feita pelo sistema) e, embaixo, o trecho "
                       "original do documento, que é o que vale.", st["nota"]))
    for x in an.atos:
        cor = SECUNDARIA if x.tipo == "AV" else PRIMARIA
        rotulo = f"{x.id} · {'Registro' if x.tipo == 'R' else 'Averbação'} · {x.natureza} · {dbr(x.data)} · pág. {', '.join(map(str, x.paginas))}"
        orig = x.trecho if len(x.trecho) <= 700 else x.trecho[:700] + " [...]"
        L += [KeepTogether([
            Paragraph(f"<b>{escape(rotulo)}</b>", st["h2"]),
            Paragraph("<b>Em palavras simples:</b> " + escape(x.explicacao.simples), st["p"]),
            Spacer(1, 2),
            _caixa([Paragraph("TEXTO ORIGINAL (versão técnica)", st["cab"]), Paragraph(escape(orig), st["orig"])], FUNDO, cor),
        ]), Spacer(1, 4)]
        if x.data_origem and x.data_origem != "texto do ato":
            L.append(Paragraph(escape(f"Data obtida de: {x.data_origem}."), st["nota"]))

    # ------------------------------------------------------------ limites
    L.append(Paragraph("10. Limites desta análise", st["h1"]))
    for t in [
        "Este relatório foi feito por um sistema automático que lê o documento enviado. Ele ajuda, mas não é um parecer jurídico.",
        "O que está no \"texto original\" é o que o documento comprova. As explicações simples são interpretação do sistema.",
        "Uma dívida só aparece como cancelada quando encontramos na matrícula o ato que a cancela. Pagar a dívida não é o mesmo que cancelar o registro.",
        "Não encontrar ônus não significa que o imóvel está totalmente regular: existem dívidas e processos que não aparecem na matrícula.",
        "Não existe um prazo único de validade para a certidão. Quem pede o documento (banco, cartório de notas, comprador) define o prazo aceito.",
        f"Quando uma informação não foi encontrada, escrevemos: \"{NAO_IDENTIFICADO}\"",
        "Para decidir uma compra, venda ou financiamento, consulte um advogado ou profissional habilitado.",
    ]:
        L.append(Paragraph(escape(t), st["bullet"], bulletText="•"))
    est = ext.estatisticas
    L.append(Spacer(1, 6))
    L.append(Paragraph(escape(f"Dados da leitura: {est['paginas']} página(s), {est['paginas_ocr']} lida(s) por OCR"
                              + (f" (confiança média {est['confianca_media_ocr']}%)" if est.get("confianca_media_ocr") else "")
                              + f"; {est['registros']} registros e {est['averbacoes']} averbações."), st["nota"]))

    def rodape(c, d):
        c.saveState()
        c.setStrokeColor(LINHA)
        c.line(20 * mm, 12 * mm, A4[0] - 20 * mm, 12 * mm)
        c.setFont("Helvetica", 7.5)
        c.setFillColor(CINZA)
        c.drawString(20 * mm, 8 * mm, f"Inteligência Urbana · Matrícula {num or 'não identificada'} · relatório de {hoje.strftime('%d/%m/%Y')}")
        c.drawRightString(A4[0] - 20 * mm, 8 * mm, f"Página {d.page}")
        c.restoreState()

    doc.build(L, onFirstPage=rodape, onLaterPages=rodape)
    return buf.getvalue()
