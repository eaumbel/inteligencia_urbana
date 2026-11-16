"""Analisador de matrícula — Fases 2 e 3 (extração rastreável). Documentos fictícios."""

import pytest
from fastapi.testclient import TestClient

from inteligencia_urbana.analisador.extracao import NAO_IDENTIFICADO, Pagina, extrair
from inteligencia_urbana.api.main import app

PAGINAS = [
    Pagina(1, """REGISTRO DE IMÓVEIS DA COMARCA DE MARINGÁ - PR
2º SERVIÇO DE REGISTRO DE IMÓVEIS DE MARINGÁ - PR
MATRÍCULA Nº 12.345
DATA 05 de março de 1.998
IMÓVEL: Lote nº 7 da Quadra 3, com a área de 450,00 m².
PROPRIETÁRIO: JOSÉ FICTÍCIO.
REGISTRO n.º 1/12.345 - COMPRA E VENDA. Transmitente: José Fictício. Adquirente: ANA EXEMPLO, brasileira.
Valor R$ 50.000,00."""),
    Pagina(2, """REPÚBLICA FEDERATIVA DO BRASIL
2º SERVIÇO DE REGISTRO DE IMÓVEIS DE MARINGÁ - PR
R-2/12.345 - Em 10/03/2015. HIPOTECA em favor do Banco Fictício S.A., valor R$ 30.000,00, conforme
escritura lavrada em 02/03/2015.
AV-3/12.345 - Em 20/01/2019. CANCELAMENTO. Fica cancelada a hipoteca objeto do R-2, por autorização do credor.""",
           "ocr", 91.0),
    Pagina(3, """AV-5/12.345, de 28 de outubro de 2023, Prenotação nº 1.000 de 19 de outubro de 2023. PENHORA dos
direitos sobre o imóvel, extraída dos autos nº 0001234-56.2023.8.16.0017, da 3ª Vara Cível de Maringá.""",
           "ocr", 55.0),
    Pagina(4, """CERTIDÃO Nº 999
CERTIFICO que a presente é reprodução da matrícula nº 12.345 (sendo último ato nº 6/12.345).
Maringá, 10 de novembro de 2026. O referido é verdade e dou fé."""),
]


@pytest.fixture(scope="module")
def ext():
    return extrair(PAGINAS)


def test_identificacao_com_fonte(ext):
    i = ext.identificacao
    assert i["numero_matricula"].valor == "12.345" and i["numero_matricula"].fonte.pagina == 1
    assert i["comarca"].valor.upper() == "MARINGÁ"
    assert (i["municipio"].valor, i["uf"].valor) == ("Maringá", "PR")
    assert i["data_emissao"].valor == "2026-11-10" and i["data_emissao"].fonte.pagina == 4
    assert i["data_abertura"].valor == "1998-03-05"


def test_registros_e_averbacoes_separados_com_pagina(ext):
    atos = {a.id: a for a in ext.atos}
    assert list(atos) == ["R-1", "R-2", "AV-3", "AV-5"]  # "objeto do R-2" não vira ato
    assert [a.tipo for a in ext.atos] == ["R", "R", "AV", "AV"]
    assert atos["R-1"].paginas == [1] and atos["R-2"].paginas == [2] and atos["AV-5"].paginas == [3]
    assert "hipoteca" in atos["R-2"].categorias and "cancelamento" in atos["AV-3"].categorias
    assert atos["R-2"].fonte.trecho.startswith("R-2/12.345")
    assert atos["AV-5"].metodo == "ocr" and atos["AV-5"].confianca == 55.0


def test_datas_com_origem_declarada(ext):
    atos = {a.id: a for a in ext.atos}
    assert (atos["R-1"].data, atos["R-1"].data_origem) == ("1998-03-05", "cabeçalho da ficha")
    assert (atos["R-2"].data, atos["R-2"].data_origem) == ("2015-03-10", "texto do ato")  # não a data da escritura
    assert (atos["AV-5"].data, atos["AV-5"].data_origem) == ("2023-10-28", "texto do ato")


def test_data_de_prenotacao_nao_vira_data_do_ato():
    e = extrair([Pagina(1, "MATRÍCULA Nº 7.777\nAV.4/7.777, de 28 de outubro de 20 renotação nº 1 de 19 de outubro de 2026. Inclusão do CEP.")])
    a = e.atos[0]
    assert a.data == "2026-10-19" and a.data_origem.startswith("data da prenotação")


def test_sequencia_lacunas_e_alertas(ext):
    s = ext.sequencia
    assert s["numeracao"].startswith("contínua") and s["faltantes"] == [4, 6]
    assert s["ultimo_ato_certificado"] == 6 and s["ultimo_ato_lido"] == 5
    textos = " | ".join(a["texto"] for a in ext.alertas)
    assert "Atos não localizados na sequência: 4, 6" in textos
    assert "último ato nº 6" in textos
    assert any(l["pagina"] == 3 for l in ext.legibilidade)  # OCR com 55% de confiança
    assert ext.estatisticas == {"paginas": 4, "paginas_ocr": 2, "confianca_media_ocr": 73.0, "registros": 2,
                                "averbacoes": 2, "caracteres": ext.estatisticas["caracteres"]}


def test_nada_inventado_quando_ausente():
    e = extrair([Pagina(1, "Documento sem identificação, apenas texto qualquer sem atos registrais legíveis aqui.")])
    assert e.identificacao["numero_matricula"].valor is None and e.atos == []
    assert e.identificacao["data_emissao"].valor is None
    assert any("não identificad" in a["texto"].lower() for a in e.alertas)
    assert NAO_IDENTIFICADO == "Não identificado no documento analisado."


def test_api_extrair():
    c = TestClient(app)
    r = c.post("/api/analisador/extrair", json={"arquivo": "teste.pdf", "paginas": [
        {"numero": p.numero, "texto": p.texto, "metodo": p.metodo, "confianca": p.confianca} for p in PAGINAS]}).json()
    assert r["identificacao"]["numero_matricula"]["valor"] == "12.345"
    assert [a["id"] for a in r["atos"]] == ["R-1", "R-2", "AV-3", "AV-5"]
    assert c.post("/api/analisador/extrair", json={"paginas": []}).status_code == 422


# ---------------------------------------------------------------- regras e relatório (documentos fictícios)

from datetime import date  # noqa: E402

from inteligencia_urbana.analisador.regras import analisar  # noqa: E402
from inteligencia_urbana.analisador.relatorio import gerar_pdf  # noqa: E402

CADEIA = [Pagina(1, """REGISTRO DE IMÓVEIS DA COMARCA DE LONDRINA - PR
1º SERVIÇO DE REGISTRO DE IMÓVEIS DE LONDRINA - PR
MATRÍCULA Nº 50.001
DATA 10 de janeiro de 2000
IMÓVEL: Lote nº 12 da Quadra 8, com a área de 300,00 m².
PROPRIETÁRIO: CARLOS FICTÍCIO, brasileiro.
R-1/50.001 - Em 05/05/2005. COMPRA E VENDA. TRANSMITENTE: CARLOS FICTÍCIO, brasileiro. ADQUIRENTE: MARIA EXEMPLO, brasileira. VALOR: R$ 80.000,00.
R-2/50.001 - Em 06/06/2010. HIPOTECA em favor do Banco Exemplo S.A., valor R$ 40.000,00.
AV-3/50.001 - Em 07/07/2012. Consta quitação da dívida da hipoteca do R-2, conforme declaração do credor.
R-4/50.001 - Em 08/08/2015. COMPRA E VENDA. TRANSMITENTE: MARIA EXEMPLO, brasileira. ADQUIRENTES: PEDRO TESTE, brasileiro, e PAULA TESTE, brasileira. VALOR: R$ 150.000,00.
AV-5/50.001 - Em 09/09/2020. PENHORA extraída dos autos nº 0009999-11.2020.8.16.0014, da 2ª Vara Cível de Londrina.
AV-6/50.001 - Em 10/10/2021. CANCELAMENTO. Fica cancelada a penhora objeto da AV-5, por ordem judicial.
CERTIDÃO Nº 1
CERTIFICO que a presente é reprodução da matrícula nº 50.001 (sendo último ato nº 6/50.001).
Londrina, 01 de agosto de 2026.""")]


@pytest.fixture(scope="module")
def an_cadeia():
    e = extrair(CADEIA)
    return e, analisar(e, date(2026, 11, 16))


def test_cadeia_de_proprietarios(an_cadeia):
    _, an = an_cadeia
    assert an.proprietario_inicial["nomes"] == ["CARLOS FICTÍCIO"]
    assert [(t.ato, t.de, t.para) for t in an.transmissoes] == [
        ("R-1", ["CARLOS FICTÍCIO"], ["MARIA EXEMPLO"]), ("R-4", ["MARIA EXEMPLO"], ["PEDRO TESTE", "PAULA TESTE"])]
    assert an.proprietarios_atuais == ["PEDRO TESTE", "PAULA TESTE"]
    assert an.cadeia_completa


def test_onus_so_baixa_com_ato_de_cancelamento(an_cadeia):
    _, an = an_cadeia
    onus = {o.ato: o for o in an.onus}
    penhora, hipoteca = onus["AV-5"], onus["R-2"]
    assert penhora.situacao == "BAIXADA/CANCELADA" and penhora.ato_baixa == "AV-6"
    assert penhora.processo == "0009999-11.2020.8.16.0014"
    # quitação não é cancelamento registral
    assert hipoteca.situacao == "ATIVA" and hipoteca.ato_baixa is None
    assert "Banco Exemplo" in hipoteca.credor
    assert any(r.nivel == "ALTO" and "Hipoteca" in r.titulo for r in an.riscos)
    assert not any(r.nivel == "CRÍTICO" for r in an.riscos)
    assert an.situacao["classe"] == "DOCUMENTAÇÃO COM RISCOS RELEVANTES"


def test_atualidade_e_explicacao_simples(an_cadeia):
    _, an = an_cadeia
    assert an.atualidade["dias_desde_emissao"] == 107
    assert "certidão atualizada" in an.atualidade["texto"]
    assert any(r.nivel == "INFORMATIVO" and "30 dias" in r.titulo for r in an.riscos)
    r4 = next(x for x in an.atos if x.id == "R-4")
    assert "MARIA EXEMPLO vendeu o imóvel para PEDRO TESTE e PAULA TESTE" in r4.explicacao.simples


def test_cancelamento_sem_numero_fica_pendente():
    e = extrair([Pagina(1, """MATRÍCULA Nº 60.002
R-1/60.002 - Em 01/02/2010. HIPOTECA em favor do Banco Exemplo S.A.
AV-2/60.002 - Em 01/02/2015. CANCELAMENTO da hipoteca, a pedido do credor.""")])
    o = analisar(e).onus[0]
    assert o.situacao == "PENDENTE DE CONFIRMAÇÃO" and o.ato_baixa == "AV-2"


def test_relatorio_pdf(an_cadeia):
    e, an = an_cadeia
    pdf = gerar_pdf(e, an, "ficticia.pdf", date(2026, 11, 16))
    assert pdf.startswith(b"%PDF") and len(pdf) > 5000


def test_api_relatorio_pdf():
    c = TestClient(app)
    r = c.post("/api/analisador/relatorio", json={"arquivo": "f.pdf", "paginas": [{"numero": 1, "texto": CADEIA[0].texto}]})
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf"
    assert 'relatorio-matricula-50001.pdf' in r.headers["content-disposition"] and r.content.startswith(b"%PDF")
    d = c.post("/api/analisador/extrair", json={"paginas": [{"numero": 1, "texto": CADEIA[0].texto}]}).json()
    assert d["analise"]["proprietarios_atuais"] == ["PEDRO TESTE", "PAULA TESTE"]
