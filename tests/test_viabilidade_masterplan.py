import pytest
from fastapi.testclient import TestClient

from inteligencia_urbana.api.main import app
from inteligencia_urbana.legislacao.federal import app_curso_dagua, classificar_reurb
from inteligencia_urbana.legislacao.zoneamento import analisar_vocacao, cidades_disponiveis, parametros_zona
from inteligencia_urbana.masterplan.gerador import ParametrosMasterplan, gerar_masterplan
from inteligencia_urbana.viabilidade.financeiro import tir_mensal, vpl
from inteligencia_urbana.viabilidade.incorporacao import PremissasIncorporacao, estudar_incorporacao
from inteligencia_urbana.viabilidade.loteamento import PremissasLoteamento, estudar_loteamento

RET = [(480000, 7418000), (480400, 7418000), (480400, 7417700), (480000, 7417700)]


def test_tir_vpl():
    fluxo = [-1000, 0, 0, 1331]
    assert tir_mensal(fluxo) == pytest.approx(0.10, abs=1e-6)
    assert vpl(fluxo, 0.10) == pytest.approx(0, abs=1e-6)


def test_loteamento_fecha_receita():
    r = estudar_loteamento(PremissasLoteamento(area_gleba_m2=120_000, area_app_m2=12_000, preco_m2_lote=450, custo_terreno=3e6))
    assert r.quadro_areas["area_loteavel_m2"] == pytest.approx(108_000 * 0.65)
    assert r.indicadores["receita_total"] == pytest.approx(r.vgv_liquido_empreendedor, rel=1e-6)
    assert r.indicadores["lucro"] > 0


def test_incorporacao():
    r = estudar_incorporacao(PremissasIncorporacao(area_terreno_m2=1500, coeficiente_aproveitamento=4, cub_m2=2500,
                                                   preco_m2_privativo=9000, custo_terreno=2.5e6))
    assert r.quadro_areas["area_computavel_m2"] == 6000
    assert r.unidades == int(6000 * 0.8 // 70)
    assert r.indicadores["receita_total"] == pytest.approx(r.vgv_liquido_empreendedor, rel=1e-6)


def test_masterplan_respeita_app_e_areas_publicas():
    m = gerar_masterplan(ParametrosMasterplan(perimetro_utm=RET, cursos_dagua_utm=[[(479990, 7417700), (480410, 7417700)]]))
    r = m.resumo
    assert r["area_app_m2"] == pytest.approx(400 * 30, rel=1e-3)
    assert r["numero_lotes"] > 100
    assert r["area_verde_m2"] >= r["area_util_m2"] * 0.10 - 1
    assert r["area_institucional_m2"] >= r["area_util_m2"] * 0.05 - 1
    soma = sum(r[k] for k in ("area_lotes_m2", "area_vias_m2", "area_verde_m2", "area_institucional_m2", "area_remanescente_m2", "area_app_m2"))
    assert soma == pytest.approx(r["area_gleba_m2"], rel=1e-3)
    assert all(f["properties"]["area_m2"] >= 250 for f in m.features if f["properties"]["tipo"] == "lote")
    assert m.svg.startswith("<svg")


def test_legislacao():
    assert app_curso_dagua(5) == 30 and app_curso_dagua(30) == 50 and app_curso_dagua(700) == 500
    assert classificar_reurb(True, True).modalidade.startswith("Reurb-S")
    assert {"londrina", "cambe", "rolandia", "ibipora"} <= set(cidades_disponiveis())
    v = analisar_vocacao(120_000, parametros_zona("Londrina", "ZR3"))
    assert any("Loteamento" in p["produto"] for p in v.produtos)


def test_api_fluxo_completo():
    c = TestClient(app)
    texto = open("tests/exemplos/matricula_gleba.txt", encoding="utf-8").read()
    r = c.post("/api/matricula/analisar", data={"texto": texto}).json()
    assert r["geojson"] is not None
    k = c.post("/api/geo/kml", json={"vertices": r["vertices"], "segmentos": r["segmentos"], "kmz": True})
    assert k.status_code == 200 and k.content[:2] == b"PK"
    m = c.post("/api/masterplan", json={"perimetro_utm": [[v["e"], v["n"]] for v in r["vertices"]]}).json()
    assert m["resumo"]["numero_lotes"] > 0
    assert c.post("/api/geo/kml-features", json={"features": m["features"]}).status_code == 200
    assert c.get("/").status_code == 200
    assert c.post("/api/vocacao", json={"cidade": "Cambé", "zona": "ZR3", "area_terreno_m2": 5000}).status_code == 200


def _quadrado_lonlat(lon, lat, d):
    return {"type": "Polygon", "coordinates": [[[lon - d, lat - d], [lon + d, lat - d], [lon + d, lat + d], [lon - d, lat + d], [lon - d, lat - d]]]}


def test_cruzar_car_e_drenagem_offline():
    from inteligencia_urbana.geo import camadas_oficiais as co
    from inteligencia_urbana.geo.coordenadas import geo_para_utm

    lon, lat = -51.19, -23.33
    e, n = geo_para_utm(lon, lat)
    verts = [(e - 100, n - 100), (e + 100, n - 100), (e + 100, n + 100), (e - 100, n + 100)]
    car = [
        {"type": "Feature", "geometry": _quadrado_lonlat(lon, lat, 0.002), "properties": {"cod_imovel": "PR-A", "status_imovel": "AT", "area": 18.0}},
        {"type": "Feature", "geometry": _quadrado_lonlat(lon + 0.01, lat, 0.0005), "properties": {"cod_imovel": "PR-LONGE"}},
    ]
    r = co.cruzar_car(verts, 31982, feicoes=car)
    assert [s["cod_imovel"] for s in r["sobreposicoes"]] == ["PR-A"]
    assert r["sobreposicoes"][0]["pct_da_matricula"] == pytest.approx(100, abs=0.5)

    rio = {"type": "Feature", "properties": {"nome": "Córrego Teste"},
           "geometry": {"type": "LineString", "coordinates": [[lon - 0.01, lat], [lon + 0.01, lat]]}}
    d = co.drenagem_proxima(verts, 31982, 300, feicoes=[rio])
    assert d["cursos"][0]["corta_o_imovel"] and d["cursos"][0]["extensao_no_imovel_m"] == pytest.approx(200, abs=2)
    m = gerar_masterplan(ParametrosMasterplan(perimetro_utm=RET, cursos_dagua_utm=[[(480000, 7417850), (480400, 7417850)]]))
    assert m.resumo["area_app_m2"] == pytest.approx(400 * 60, rel=1e-3)


def test_subpasta_incorporacao():
    c = TestClient(app)
    r = c.get("/incorporacao", follow_redirects=False)
    assert r.status_code == 308 and r.headers["location"] == "/incorporacao/"
    assert c.get("/incorporacao/").status_code == 200
    assert "londrina" in c.get("/incorporacao/api/zoneamento").json()["cidades"]
    assert c.get("/").status_code == 200


def test_api_poligono_desenhado():
    c = TestClient(app)
    # quadrado de ~30 m em Londrina, desenhado em lon/lat
    from inteligencia_urbana.geo.coordenadas import geo_para_utm, utm_para_geo
    e, n = geo_para_utm(-51.1525, -23.3270)
    pts = [utm_para_geo(x, y) for x, y in [(e, n), (e + 30, n), (e + 30, n - 30), (e, n - 30)]]
    r = c.post("/api/geo/poligono", json={"coords_lonlat": pts, "area_referencia_m2": 1000}).json()
    assert r["area_m2"] == pytest.approx(900, abs=0.5) and r["perimetro_m"] == pytest.approx(120, abs=0.1)
    assert r["diferenca_pct"] == pytest.approx(-10, abs=0.1)
    assert [round(s["distancia_m"], 1) for s in r["segmentos"]] == [30.0, 30.0, 30.0, 30.0]
    cruzado = [pts[0], pts[2], pts[1], pts[3]]
    assert c.post("/api/geo/poligono", json={"coords_lonlat": cruzado}).status_code == 422


def test_masterplan_com_diretrizes():
    from inteligencia_urbana.masterplan.gerador import ViaPrevista

    # via coletora norte-sul no meio da gleba (traços de 4 m de largura, com falhas) e fundo de vale a leste
    tracos = [[(480198, y), (480202, y), (480202, y - 10), (480198, y - 10)] for y in range(7418000, 7417700, -14)]
    fv = [(480350, 7418000), (480400, 7418000), (480400, 7417700), (480350, 7417700)]
    m = gerar_masterplan(ParametrosMasterplan(
        perimetro_utm=RET, vias_previstas=[ViaPrevista(largura_m=20, hierarquia="Coletora", partes_utm=tracos)],
        fundo_vale_utm=[fv]))
    r = m.resumo
    assert r["area_vias_diretriz_m2"] == pytest.approx(20 * 300, rel=0.03)  # faixa contínua de 20 m
    assert r["area_app_m2"] == pytest.approx(50 * 300, rel=0.01)
    prevista = [f for f in m.features if f["properties"].get("diretriz")]
    assert prevista and prevista[0]["properties"]["nome"] == "Coletora prevista (20 m)"
    # nenhum lote sobre a via prevista nem no fundo de vale
    from shapely.geometry import shape, box
    from inteligencia_urbana.geo.coordenadas import utm_para_geo
    lon0, lat0 = utm_para_geo(480190, 7418000); lon1, lat1 = utm_para_geo(480210, 7417700)
    faixa = box(min(lon0, lon1), min(lat0, lat1), max(lon0, lon1), max(lat0, lat1))
    lotes = [shape(f["geometry"]) for f in m.features if f["properties"]["tipo"] == "lote"]
    assert lotes and all(l.intersection(faixa).area < 1e-10 for l in lotes)
