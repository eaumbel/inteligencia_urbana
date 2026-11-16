import math

import pytest

from inteligencia_urbana.geo.coordenadas import (
    decimal_para_dms,
    dms_para_decimal,
    geo_para_utm,
    parse_numero_br,
    rumo_para_azimute,
    utm_para_geo,
)
from inteligencia_urbana.geo.kml import perimetro_para_kml
from inteligencia_urbana.geo.poligono import area_shoelace, azimute, poligonal_por_azimutes


@pytest.mark.parametrize("txt,esperado", [
    ("7.421.234,56", 7421234.56), ("482.345", 482345), ("45,32", 45.32), ("45.32", 45.32), ("1.200", 1200), ("0.500", 0.5),
])
def test_parse_numero_br(txt, esperado):
    assert parse_numero_br(txt) == pytest.approx(esperado)


def test_dms():
    assert dms_para_decimal("23°18'00\"S") == pytest.approx(-23.3)
    assert dms_para_decimal("125°30'00\"") == pytest.approx(125.5)
    assert decimal_para_dms(-23.3, "lat").startswith("23°18'00")


def test_rumo():
    assert rumo_para_azimute("45°00'00\" NE") == pytest.approx(45)
    assert rumo_para_azimute("45°00'00\" SE") == pytest.approx(135)
    assert rumo_para_azimute("45°00'00\" SO") == pytest.approx(225)
    assert rumo_para_azimute("45°00'00\" NO") == pytest.approx(315)


def test_ida_e_volta_utm():
    lon, lat = -51.1628, -23.3045  # Londrina
    e, n = geo_para_utm(lon, lat)
    assert 400_000 < e < 600_000 and 7_400_000 < n < 7_450_000
    lon2, lat2 = utm_para_geo(e, n)
    assert lon2 == pytest.approx(lon, abs=1e-8) and lat2 == pytest.approx(lat, abs=1e-8)


def test_poligonal_fechada():
    verts, fech = poligonal_por_azimutes((0, 0), [(90, 100), (180, 50), (270, 100), (0, 50)])
    assert area_shoelace([(v.e, v.n) for v in verts]) == pytest.approx(5000)
    assert fech.erro_linear_m == pytest.approx(0, abs=1e-6) and fech.aceitavel


def test_azimute():
    assert azimute(0, 0, 1, 1) == pytest.approx(45)
    assert azimute(0, 0, -1, 0) == pytest.approx(270)


def test_kml_valido():
    from xml.dom import minidom

    kml = perimetro_para_kml(
        [{"nome": "V1", "e": 480000, "n": 7418000}, {"nome": "V2", "e": 480100, "n": 7418000}, {"nome": "V3", "e": 480100, "n": 7417900}],
        [{"de": "V1", "para": "V2", "azimute_graus": 90, "distancia_m": 100, "confrontante": "Rua A & B"}],
    )
    doc = minidom.parseString(kml.encode())
    assert len(doc.getElementsByTagName("Placemark")) == 5


def test_tls_legado_so_para_sicar():
    from inteligencia_urbana.geo.camadas_oficiais import HOSTS_TLS_LEGADO, contexto_ssl

    assert HOSTS_TLS_LEGADO == {"geoserver.car.gov.br"}
    rsa = lambda ctx: any(c["name"] == "AES256-GCM-SHA384" for c in ctx.get_ciphers())
    assert rsa(contexto_ssl("geoserver.car.gov.br"))
    assert not rsa(contexto_ssl("geoservicos.ibge.gov.br")) and not rsa(contexto_ssl(None))
    assert contexto_ssl("geoserver.car.gov.br").check_hostname
