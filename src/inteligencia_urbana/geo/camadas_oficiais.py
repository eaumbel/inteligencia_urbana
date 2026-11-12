"""Camadas oficiais (WMS/WFS) e cruzamentos com o perímetro da matrícula.

Serviços verificados em 12/11/2026:
- SICAR (CAR): https://geoserver.car.gov.br/geoserver/sicar  — camada sicar:sicar_imoveis_<uf>
- IBGE BC250 2025: https://geoservicos.ibge.gov.br/geoserver — drenagem, massas d'água, municípios

IBGE: o navegador consulta direto (CORS liberado) e envia as feições para a API.
SICAR: o servidor só negocia troca de chaves RSA (TLS 1.2 sem forward secrecy),
recusada pelo Chrome atual e pelo OpenSSL 3 com a configuração padrão. Por isso o
CAR passa pelo proxy da API (`/api/proxy/car-wms` e `/api/proxy/car-wfs`). Ver
`contexto_ssl()` e a seção "SICAR" do README.

Os dados do IBGE estão na escala 1:250.000 (erro posicional da ordem de 125 m):
servem para triagem. A posição real de córregos e nascentes, e portanto da APP,
deve vir do levantamento planialtimétrico.
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass

from shapely.geometry import Polygon, shape

from .coordenadas import EPSG_WGS84, _transformer

CAR_WMS = "https://geoserver.car.gov.br/geoserver/sicar/wms"
CAR_WFS = "https://geoserver.car.gov.br/geoserver/sicar/wfs"
IBGE_WMS = "https://geoservicos.ibge.gov.br/geoserver/wms"
IBGE_WFS = "https://geoservicos.ibge.gov.br/geoserver/wfs"

CAMADA_CAR_PR = "sicar:sicar_imoveis_pr"
CAMADA_DRENAGEM = "CCAR:BC250_2025_hid_trecho_drenagem_l"
CAMADA_MASSA_DAGUA = "CCAR:BC250_2025_hid_massa_dagua_a"
CAMADA_MUNICIPIOS = "CCAR:BC250_2025_lml_municipio_a"

CAMADAS_WMS = [
    {"id": "car", "nome": "CAR — imóveis rurais (SICAR)", "url": "/api/proxy/car-wms", "wfs": "/api/proxy/car-wfs",
     "url_oficial": CAR_WMS, "layers": CAMADA_CAR_PR,
     "opacidade": 0.55, "consultavel": True, "fonte": "SICAR/SFB", "escala": "declaratório"},
    {"id": "drenagem", "nome": "Hidrografia — cursos d'água (IBGE)", "url": IBGE_WMS, "wfs": IBGE_WFS, "layers": CAMADA_DRENAGEM,
     "opacidade": 1.0, "consultavel": True, "fonte": "IBGE BC250 2025", "escala": "1:250.000"},
    {"id": "massa_dagua", "nome": "Hidrografia — massas d'água (IBGE)", "url": IBGE_WMS, "layers": CAMADA_MASSA_DAGUA,
     "opacidade": 0.8, "consultavel": False, "fonte": "IBGE BC250 2025", "escala": "1:250.000"},
    {"id": "municipios", "nome": "Limites municipais (IBGE)", "url": IBGE_WMS, "layers": CAMADA_MUNICIPIOS,
     "opacidade": 1.0, "consultavel": False, "fonte": "IBGE BC250 2025", "escala": "1:250.000"},
]

TIMEOUT = 60


# Hosts autorizados a negociar TLS com troca de chaves RSA (sem forward secrecy).
# Autorizado pelo responsável do projeto em 12/11/2026, somente para o SICAR, cujo
# servidor não oferece outra opção. Dados públicos; certificado e hostname continuam
# verificados. Não adicione outros hosts sem nova avaliação.
HOSTS_TLS_LEGADO = {"geoserver.car.gov.br"}


def contexto_ssl(host: str | None = None):
    """Contexto TLS das chamadas a serviços públicos (verificação de certificado sempre ativa)."""
    import ssl

    ctx = ssl.create_default_context()
    if host in HOSTS_TLS_LEGADO:
        # Lista padrão do OpenSSL, que ainda inclui as suítes RSA (ex.: AES256-GCM-SHA384)
        ctx.set_ciphers("DEFAULT")
    return ctx


def baixar(url: str, params: dict) -> tuple[bytes, str]:
    """GET simples; retorna (corpo, content-type)."""
    full = url + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(full, headers={"User-Agent": "inteligencia-urbana/0.1"})
    host = urllib.parse.urlsplit(url).hostname
    with urllib.request.urlopen(req, timeout=TIMEOUT, context=contexto_ssl(host)) as r:
        return r.read(), r.headers.get_content_type()


def _get_json(url: str, params: dict) -> dict:
    corpo, _ = baixar(url, params)
    try:
        return json.loads(corpo)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Serviço respondeu sem JSON: {corpo[:200]!r}") from e


def wfs_bbox(url: str, camada: str, bbox_lonlat: tuple[float, float, float, float], limite: int = 500) -> list[dict]:
    """Feições de uma camada WFS dentro do bbox (lon_min, lat_min, lon_max, lat_max), em lon/lat."""
    x0, y0, x1, y1 = bbox_lonlat
    dados = _get_json(url, {
        "service": "WFS", "version": "2.0.0", "request": "GetFeature", "typeNames": camada,
        "outputFormat": "application/json", "srsName": "EPSG:4326", "count": limite,
        # WFS 2.0 com URN usa ordem lat,lon no bbox
        "bbox": f"{y0},{x0},{y1},{x1},urn:ogc:def:crs:EPSG::4326",
    })
    return dados.get("features", [])


def wms_info_ponto(url: str, camada: str, lon: float, lat: float, raio_graus: float = 0.0005) -> list[dict]:
    """GetFeatureInfo no ponto (lon, lat) — retorna as feições GeoJSON clicadas."""
    dados = _get_json(url, {
        "service": "WMS", "version": "1.1.1", "request": "GetFeatureInfo", "layers": camada, "query_layers": camada,
        "styles": "", "srs": "EPSG:4326", "width": 101, "height": 101, "x": 50, "y": 50,
        "bbox": f"{lon - raio_graus},{lat - raio_graus},{lon + raio_graus},{lat + raio_graus}",
        "info_format": "application/json", "feature_count": 10,
    })
    return dados.get("features", [])


def _poligono_utm(vertices_utm: list[tuple[float, float]]) -> Polygon:
    return Polygon(vertices_utm).buffer(0)


def _bbox_lonlat(poly_utm: Polygon, epsg: int, margem_m: float) -> tuple[float, float, float, float]:
    tr = _transformer(epsg, EPSG_WGS84)
    x0, y0, x1, y1 = poly_utm.buffer(margem_m).bounds
    lons, lats = tr.transform([x0, x1, x0, x1], [y0, y0, y1, y1])
    return min(lons), min(lats), max(lons), max(lats)


def _para_utm(geom_lonlat, epsg: int):
    import numpy as np
    import shapely

    tr = _transformer(EPSG_WGS84, epsg)
    return shapely.transform(geom_lonlat, lambda xy: np.column_stack(tr.transform(xy[:, 0], xy[:, 1])))


@dataclass
class SobreposicaoCAR:
    cod_imovel: str
    condicao: str | None
    status: str | None
    area_car_ha: float | None
    area_sobreposta_m2: float
    pct_da_matricula: float
    pct_do_car: float


def cruzar_car(vertices_utm: list[tuple[float, float]], epsg: int, camada: str = CAMADA_CAR_PR,
               feicoes: list[dict] | None = None) -> dict:
    """Imóveis do CAR que se sobrepõem ao perímetro da matrícula.

    `feicoes` permite injetar o resultado do WFS (testes / cache).
    """
    poly = _poligono_utm(vertices_utm)
    feicoes = feicoes if feicoes is not None else wfs_bbox(CAR_WFS, camada, _bbox_lonlat(poly, epsg, 50))
    res: list[SobreposicaoCAR] = []
    geo_out = []
    for f in feicoes:
        if not f.get("geometry"):
            continue
        g = _para_utm(shape(f["geometry"]), epsg).buffer(0)
        inter = g.intersection(poly).area
        if inter < 1:
            continue
        p = f.get("properties", {})
        item = SobreposicaoCAR(
            cod_imovel=p.get("cod_imovel", "—"), condicao=p.get("condicao"), status=p.get("status_imovel"),
            area_car_ha=p.get("area"), area_sobreposta_m2=round(inter, 2),
            pct_da_matricula=round(inter / poly.area * 100, 2) if poly.area else 0,
            pct_do_car=round(inter / g.area * 100, 2) if g.area else 0,
        )
        res.append(item)
        geo_out.append({"type": "Feature", "geometry": f["geometry"], "properties": asdict(item)})
    res.sort(key=lambda s: s.area_sobreposta_m2, reverse=True)

    alertas = []
    if not res:
        alertas.append("Nenhum CAR sobreposto. Imóvel rural precisa de inscrição no CAR (Lei 12.651/2012, art. 29).")
    else:
        principal = res[0]
        if principal.pct_da_matricula < 90:
            alertas.append(f"O CAR com maior sobreposição cobre só {principal.pct_da_matricula:.1f}% da matrícula: confira se o CAR corresponde a este imóvel.")
        if len(res) > 1:
            alertas.append(f"{len(res)} CARs se sobrepõem ao perímetro: possível sobreposição de declarações a sanar no SICAR.")
        for s in res:
            if s.status and s.status.upper() in ("CA", "SU", "PE"):
                alertas.append(f"CAR {s.cod_imovel} com status '{s.status}' (cancelado/suspenso/pendente).")
    return {"sobreposicoes": [asdict(s) for s in res], "features": geo_out, "alertas": alertas,
            "fonte": "SICAR — dados declaratórios, consultados em tempo real"}


def drenagem_proxima(vertices_utm: list[tuple[float, float]], epsg: int, raio_m: float = 300,
                     feicoes: list[dict] | None = None) -> dict:
    """Cursos d'água do IBGE (BC250) que cortam o imóvel ou passam a até `raio_m` dele."""
    poly = _poligono_utm(vertices_utm)
    feicoes = feicoes if feicoes is not None else wfs_bbox(IBGE_WFS, CAMADA_DRENAGEM, _bbox_lonlat(poly, epsg, raio_m))
    cursos, geo_out = [], []
    for f in feicoes:
        if not f.get("geometry"):
            continue
        g = _para_utm(shape(f["geometry"]), epsg)
        dist = g.distance(poly)
        if dist > raio_m:
            continue
        p = f.get("properties", {})
        linhas = [g] if g.geom_type == "LineString" else list(getattr(g, "geoms", []))
        info = {
            "nome": p.get("nome") or "Curso d'água sem nome",
            "regime": p.get("regime"),
            "distancia_m": round(dist, 1),
            "corta_o_imovel": g.intersects(poly),
            "extensao_no_imovel_m": round(g.intersection(poly).length, 1),
        }
        cursos.append({**info, "linhas_utm": [[(round(x, 2), round(y, 2)) for x, y in l.coords] for l in linhas]})
        geo_out.append({"type": "Feature", "geometry": f["geometry"], "properties": info})
    cursos.sort(key=lambda c: c["distancia_m"])
    alertas = [
        "Hidrografia do IBGE em 1:250.000 (erro da ordem de 100 m): use só para triagem. A APP definitiva depende "
        "do levantamento topográfico e da largura real do leito (Código Florestal, art. 4º)."
    ]
    if any(c["corta_o_imovel"] for c in cursos):
        alertas.append("Há curso d'água cortando o imóvel: prever APP mínima de 30 m por margem (leito < 10 m).")
    return {"cursos": cursos, "features": geo_out, "alertas": alertas, "fonte": "IBGE BC250 2025"}
