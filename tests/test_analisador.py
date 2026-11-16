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
