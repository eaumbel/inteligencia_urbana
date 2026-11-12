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
