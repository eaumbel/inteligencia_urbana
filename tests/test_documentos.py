from pathlib import Path

import pytest

from inteligencia_urbana.documentos.consulta_ippul import analisar_consulta_parcelamento
from inteligencia_urbana.documentos.matricula import analisar_matricula

EX = Path(__file__).parent / "exemplos"


def test_matricula_gleba_georreferenciada():
    r = analisar_matricula((EX / "matricula_gleba.txt").read_text(encoding="utf-8"))
    assert r.numero == "45.678"
    assert r.tipo_imovel == "rural"
    assert r.area_declarada_m2 == pytest.approx(4.84 * 24_200)
    assert [v.nome for v in r.vertices] == ["PFE-M-0001", "PFE-M-0002", "PFE-M-0003", "PFE-M-0004"]
    assert r.area_calculada_m2 == pytest.approx(120_000)
    assert r.segmentos[2].confrontante == "Córrego Água Fria"
    hipoteca = next(a for a in r.atos if a.numero == 2)
    penhora = next(a for a in r.atos if a.numero == 5)
    assert hipoteca.situacao == "possivelmente cancelado"
    assert penhora.situacao.startswith("ativo")
    assert any("penhora" in a for a in r.alertas)


def test_matricula_por_azimutes_sem_coordenadas():
    txt = (
        "MATRÍCULA 1.234. Lote 7 da Quadra 3, área de 500,00 m². Partindo do ponto P1, segue com azimute de "
        "90°00'00\" e distância de 20,00 m confrontando com a Rua das Flores; segue com azimute de 180°00'00\" e "
        "distância de 25,00 m confrontando com o lote 8; segue com azimute de 270°00'00\" e distância de 20,00 m "
        "confrontando com o lote 12; segue com azimute de 0°00'00\" e distância de 25,00 m confrontando com o lote 6."
    )
    r = analisar_matricula(txt)
    assert r.tipo_imovel == "urbano" and r.lote == "7" and r.quadra == "3"
    assert r.area_calculada_m2 == pytest.approx(500)
    assert r.fechamento["aceitavel"]
    assert r.segmentos[0].confrontante == "Rua das Flores"


def test_matricula_lat_long():
    txt = (
        "MATRÍCULA Nº 999. vértice V1, Latitude 23°18'00,000\"S e Longitude 51°10'00,000\"W; vértice V2, "
        "Latitude 23°18'00,000\"S e Longitude 51°09'50,000\"W; vértice V3, Latitude 23°18'10,000\"S e "
        "Longitude 51°09'50,000\"W."
    )
    r = analisar_matricula(txt)
    assert len(r.vertices) == 3
    assert r.area_calculada_m2 > 0
    assert r.to_dict()["geojson"]["geometry"]["type"] == "Polygon"


def test_diretrizes():
    txt = (
        "CONSULTA PRÉVIA Nº 123/2026. Imóvel inserido na ZR3 e parcialmente na ZEIS. Lote mínimo de 250,00 m² e "
        "testada mínima de 10,00 m. Deverão ser destinados 5% para área institucional e 10% para área verde. "
        "Respeitar a diretriz viária da via arterial com caixa de via de 30,00 m. Faixa de preservação do fundo de vale "
        "de 30,00 m ao longo do córrego. Licença Prévia junto ao IAT."
    )
    d = analisar_consulta_parcelamento(txt)
    assert "ZR3" in d.zonas and "ZEIS" in d.zonas
    assert d.lote_minimo_m2 == 250 and d.testada_minima_m == 10
    assert d.percentuais_areas == {"institucional": 5, "verde": 10}
    assert 30 in d.larguras_vias_m
    assert {"ambiental", "licenciamento", "sistema_viario"} <= set(d.trechos_por_tema)


def test_matricula_apartamento_escaneada_ocr():
    """Formato comum em Londrina (ficha datilografada + registro contínuo), lido por OCR."""
    r = analisar_matricula((EX / "matricula_apartamento_ocr.txt").read_text(encoding="utf-8"))
    assert r.texto_ocr
    assert r.numero == "99.001" and r.tipo_imovel == "urbano"
    assert r.comarca == "LONDRINA"
    assert (r.lote, r.quadra, r.loteamento) == ("4", "12", "JARDIM EXEMPLO")  # "Data de terras" = lote
    assert r.endereco == "Rua das Acácias nº 250"
    assert r.area_declarada_m2 == pytest.approx(98.5)
    u = r.unidade_autonoma
    assert u["edificio"] == "RESIDENCIAL FICTÍCIO" and u["unidade"] == "Apartamento 101"
    assert u["area_privativa_m2"] == pytest.approx(61.2) and u["fracao_ideal_terreno_m2"] == pytest.approx(20.1)
    assert u["participacao_condominio_pct"] == pytest.approx(2.5) and u["area_terreno_condominio_m2"] == pytest.approx(800)
    assert u["vagas"] == ["7"]
    # atos de outras matrículas (registro anterior) não entram; "REGISTRO n.º 1" vira R-1
    assert [(a.tipo, a.numero) for a in r.atos] == [("R", 1), ("AV", 2), ("AV", 3), ("R", 4)]
    assert next(a for a in r.atos if a.numero == 2).situacao == "possivelmente cancelado"
    assert {m.lado for m in r.medidas} == {"Leste", "Sul", "Oeste", "Norte"}
    assert next(m for m in r.medidas if m.lado == "Oeste").confrontacao == "o apartamento 102"
    t = {x["ato"]: x for x in r.transmissoes}
    assert t["R-1"]["adquirentes"] == ["MARIA FICTÍCIA EXEMPLO"] and t["R-1"]["valor"] == 150000
    assert t["R-4"]["fracao_pct"] == 50 and t["R-4"]["adquirentes"] == ["JOÃO FICTÍCIO EXEMPLO"]
    assert r.ultimo_ato_certificado == 4 and r.datum is None
    assert not any("SAD-69" in a for a in r.alertas)


def test_ocr_numero_com_travessao_e_area_com_hifen_solto():
    txt = (EX / "matricula_apartamento_ocr.txt").read_text(encoding="utf-8")
    txt = txt.replace("= MATRÍCULA Nº. 99.001.", "= MATRÍCULANº — 99.001.-").replace("área bruta E", "área bruta -")
    r = analisar_matricula(txt)
    assert r.numero == "99.001" and r.area_declarada_m2 == pytest.approx(98.5)
    # cabeçalho ilegível: o número vem dos próprios atos
    r2 = analisar_matricula(txt.replace("MATRÍCULANº — 99.001.-", "MATRÍCULA ilegível"))
    assert r2.numero == "99.001" and len(r2.atos) == 4
