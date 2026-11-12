"""Exportação para Google Earth (KML/KMZ) — perímetro, vértices e confrontações."""

from __future__ import annotations

import io
import zipfile
from html import escape
from xml.sax.saxutils import escape as xesc

from .coordenadas import decimal_para_dms, utm_para_geo

# Cores KML são aabbggrr
ESTILOS = {
    "perimetro": ("ff00a5ff", "4000a5ff", 3),
    "lote": ("ffffffff", "8066ccff", 1),
    "via": ("ff808080", "80c0c0c0", 1),
    "area_verde": ("ff00aa00", "8000cc00", 1),
    "institucional": ("ffcc6600", "80ff9933", 1),
    "app": ("ff006600", "a0009900", 2),
    "remanescente": ("ff999999", "40999999", 1),
}


def _coords(geo: list[tuple[float, float]], fechar: bool = True) -> str:
    pts = list(geo)
    if fechar and pts and pts[0] != pts[-1]:
        pts.append(pts[0])
    return " ".join(f"{lon:.9f},{lat:.9f},0" for lon, lat in pts)


def _estilos_xml() -> str:
    out = []
    for nome, (linha, fundo, largura) in ESTILOS.items():
        out.append(
            f'<Style id="{nome}"><LineStyle><color>{linha}</color><width>{largura}</width></LineStyle>'
            f"<PolyStyle><color>{fundo}</color></PolyStyle></Style>"
        )
    out.append(
        '<Style id="vertice"><IconStyle><scale>0.7</scale><Icon>'
        "<href>http://maps.google.com/mapfiles/kml/shapes/placemark_circle.png</href></Icon></IconStyle>"
        "<LabelStyle><scale>0.8</scale></LabelStyle></Style>"
    )
    out.append('<Style id="confrontacao"><LineStyle><color>ff0000ff</color><width>2</width></LineStyle></Style>')
    return "".join(out)


def _tabela_html(linhas: list[tuple[str, str]]) -> str:
    rows = "".join(f"<tr><td><b>{escape(k)}</b></td><td>{escape(str(v))}</td></tr>" for k, v in linhas)
    return f"<![CDATA[<table border='1' cellpadding='3' style='border-collapse:collapse'>{rows}</table>]]>"


def perimetro_para_kml(
    vertices: list[dict],
    segmentos: list[dict] | None = None,
    nome: str = "Imóvel",
    epsg: int = 31982,
    info: dict | None = None,
) -> str:
    """Gera KML de um perímetro.

    vertices: [{"nome","e","n"}] em UTM (epsg informado).
    segmentos: [{"de","para","azimute_graus","distancia_m","confrontante"}] opcionais.
    """
    geo = [utm_para_geo(v["e"], v["n"], epsg) for v in vertices]
    linhas_info = [(k, str(v)) for k, v in (info or {}).items()]
    partes = [
        f"<Placemark><name>{xesc(nome)}</name><description>{_tabela_html(linhas_info)}</description>"
        f"<styleUrl>#perimetro</styleUrl><Polygon><tessellate>1</tessellate><outerBoundaryIs><LinearRing>"
        f"<coordinates>{_coords(geo)}</coordinates></LinearRing></outerBoundaryIs></Polygon></Placemark>"
    ]
    vert_xml = []
    for v, (lon, lat) in zip(vertices, geo):
        desc = _tabela_html([
            ("E (UTM)", f"{v['e']:.3f}"), ("N (UTM)", f"{v['n']:.3f}"),
            ("Latitude", decimal_para_dms(lat, "lat")), ("Longitude", decimal_para_dms(lon, "lon")),
            ("EPSG", str(epsg)),
        ])
        vert_xml.append(
            f"<Placemark><name>{xesc(v['nome'])}</name><description>{desc}</description><styleUrl>#vertice</styleUrl>"
            f"<Point><coordinates>{lon:.9f},{lat:.9f},0</coordinates></Point></Placemark>"
        )
    partes.append(f"<Folder><name>Vértices</name>{''.join(vert_xml)}</Folder>")

    if segmentos:
        idx = {v["nome"]: g for v, g in zip(vertices, geo)}
        seg_xml = []
        for s in segmentos:
            a, b = idx.get(s["de"]), idx.get(s["para"])
            if not a or not b:
                continue
            titulo = f"{s['de']} → {s['para']}"
            desc = _tabela_html([
                ("Azimute", decimal_para_dms(s["azimute_graus"], "lat").rstrip("NS")),
                ("Distância", f"{s['distancia_m']:.2f} m"),
                ("Confrontante", s.get("confrontante") or "—"),
            ])
            seg_xml.append(
                f"<Placemark><name>{xesc(s.get('confrontante') or titulo)}</name><description>{desc}</description>"
                f"<styleUrl>#confrontacao</styleUrl><LineString><tessellate>1</tessellate>"
                f"<coordinates>{_coords([a, b], fechar=False)}</coordinates></LineString></Placemark>"
            )
        partes.append(f"<Folder><name>Confrontações</name>{''.join(seg_xml)}</Folder>")

    return _documento(nome, "".join(partes))


def features_para_kml(features: list[dict], nome: str = "Masterplan") -> str:
    """Converte features GeoJSON (lon/lat) com properties.tipo em KML, agrupadas por tipo."""
    pastas: dict[str, list[str]] = {}
    for f in features:
        geom = f["geometry"]
        props = f.get("properties", {})
        tipo = props.get("tipo", "remanescente")
        polys = [geom["coordinates"]] if geom["type"] == "Polygon" else geom["coordinates"] if geom["type"] == "MultiPolygon" else []
        for poly in polys:
            ext = [tuple(c) for c in poly[0]]
            furos = "".join(
                f"<innerBoundaryIs><LinearRing><coordinates>{_coords([tuple(c) for c in h])}</coordinates></LinearRing></innerBoundaryIs>"
                for h in poly[1:]
            )
            desc = _tabela_html([(k, str(v)) for k, v in props.items()])
            pastas.setdefault(tipo, []).append(
                f"<Placemark><name>{xesc(str(props.get('nome', tipo)))}</name><description>{desc}</description>"
                f"<styleUrl>#{tipo if tipo in ESTILOS else 'remanescente'}</styleUrl><Polygon><tessellate>1</tessellate>"
                f"<outerBoundaryIs><LinearRing><coordinates>{_coords(ext)}</coordinates></LinearRing></outerBoundaryIs>{furos}</Polygon></Placemark>"
            )
    corpo = "".join(f"<Folder><name>{xesc(t)}</name>{''.join(p)}</Folder>" for t, p in pastas.items())
    return _documento(nome, corpo)


def _documento(nome: str, corpo: str) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<kml xmlns="http://www.opengis.net/kml/2.2"><Document>'
        f"<name>{xesc(nome)}</name>{_estilos_xml()}{corpo}</Document></kml>"
    )


def kml_para_kmz(kml: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("doc.kml", kml)
    return buf.getvalue()
