"""Gerador de masterplan preliminar (estudo de massa) para loteamentos.

Estratégia (traçado ortogonal):
1. Área aproveitável = perímetro − exclusões (APP, faixas não edificáveis).
2. Orienta a malha pelo lado maior do retângulo mínimo envolvente (ou ângulo informado).
3. Faixas alternadas: via (largura da caixa) + quadra com duas fileiras de lotes
   (profundidade × 2); vias transversais a cada `comprimento_quadra_m`.
4. Lotes recortados pelo perímetro só são mantidos se atenderem à área mínima.
5. Sobras viram área verde / institucional; se faltar área, quadras menos eficientes
   são convertidas até atingir os percentuais exigidos.

É um estudo preliminar para viabilidade — o projeto urbanístico definitivo deve
considerar topografia, drenagem, diretrizes viárias e normas municipais.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from pydantic import BaseModel, Field
from shapely import affinity
from shapely.geometry import LineString, MultiPolygon, Polygon, box, mapping
from shapely.ops import unary_union

from ..geo.coordenadas import EPSG_SIRGAS2000_UTM22S, _transformer, EPSG_WGS84

CORES = {
    "lote": "#f6d58e",
    "via": "#bdbdbd",
    "area_verde": "#7cc576",
    "institucional": "#f2a65a",
    "app": "#2e7d32",
    "remanescente": "#e0e0e0",
}


class ViaPrevista(BaseModel):
    largura_m: float = Field(..., gt=3, description="Largura total oficial da via (caixa)")
    hierarquia: str = "via prevista"
    partes_utm: list[list[tuple[float, float]]] = Field(..., description="Polígonos do traçado (traços do croqui)")


class ParametrosMasterplan(BaseModel):
    perimetro_utm: list[tuple[float, float]] = Field(..., min_length=3)
    epsg: int = EPSG_SIRGAS2000_UTM22S
    exclusoes_utm: list[list[tuple[float, float]]] = Field(default_factory=list, description="Polígonos de APP/restrições")
    cursos_dagua_utm: list[list[tuple[float, float]]] = Field(default_factory=list, description="Eixos de córregos (linhas)")
    largura_app_m: float = Field(30, ge=0)
    largura_via_m: float = Field(14, gt=4)
    frente_lote_m: float = Field(12, gt=3)
    profundidade_lote_m: float = Field(25, gt=8)
    comprimento_quadra_m: float = Field(150, gt=20)
    lote_minimo_m2: float = Field(250, gt=0)
    pct_area_verde: float = Field(10, ge=0, le=50)
    pct_institucional: float = Field(5, ge=0, le=50)
    largura_minima_area_publica_m: float = Field(10, ge=0, description="Sobras mais estreitas viram remanescente")
    angulo_graus: float | None = Field(None, description="Orientação da malha; None = automático")
    vias_previstas: list[ViaPrevista] = Field(default_factory=list, description="Diretrizes viárias (ex.: croqui do IPPUL)")
    fundo_vale_utm: list[list[tuple[float, float]]] = Field(default_factory=list, description="Polígonos de fundo de vale")
    hidrografia_utm: list[list[tuple[float, float]]] = Field(default_factory=list, description="Cursos d'água (linhas ou polígonos)")


@dataclass
class Masterplan:
    features: list[dict]
    resumo: dict
    svg: str
    alertas: list[str] = field(default_factory=list)


def _angulo_automatico(poly: Polygon) -> float:
    mrr = poly.minimum_rotated_rectangle
    pts = list(mrr.exterior.coords)
    melhor, ang = 0.0, 0.0
    for a, b in zip(pts, pts[1:]):
        d = math.dist(a, b)
        if d > melhor:
            melhor, ang = d, math.degrees(math.atan2(b[1] - a[1], b[0] - a[0]))
    return ang


def _poligonos(g) -> list[Polygon]:
    if g.is_empty:
        return []
    if isinstance(g, Polygon):
        return [g]
    if isinstance(g, MultiPolygon):
        return list(g.geoms)
    return [p for p in getattr(g, "geoms", []) if isinstance(p, Polygon)]


def gerar_masterplan(p: ParametrosMasterplan) -> Masterplan:
    alertas: list[str] = []
    gleba = Polygon(p.perimetro_utm).buffer(0)
    exclus = [Polygon(e).buffer(0) for e in p.exclusoes_utm]
    exclus += [LineString(c).buffer(p.largura_app_m, cap_style="flat") for c in p.cursos_dagua_utm if len(c) >= 2]
    exclus += [Polygon(f).buffer(0) for f in p.fundo_vale_utm if len(f) >= 3]
    for h in p.hidrografia_utm:  # leito desenhado (polígono) ou eixo (linha) + APP
        if len(h) >= 3 and Polygon(h).buffer(0).area > 1:
            exclus.append(Polygon(h).buffer(0).buffer(p.largura_app_m))
        elif len(h) >= 2:
            exclus.append(LineString(h).buffer(p.largura_app_m))
    app = unary_union(exclus).intersection(gleba) if exclus else Polygon()

    # vias previstas: os traços do croqui marcam o eixo; a faixa recebe a largura oficial
    vias_prev = []
    for v in p.vias_previstas:
        partes = [Polygon(pp).buffer(0) for pp in v.partes_utm if len(pp) >= 3]
        partes = [g for g in partes if g.area > 0]
        if not partes:
            continue
        largura_traco = sorted(min(math.dist(a, b) for a, b in zip(list(g.minimum_rotated_rectangle.exterior.coords)[:2],
                                                              list(g.minimum_rotated_rectangle.exterior.coords)[1:3])) for g in partes)[len(partes) // 2]
        faixa = unary_union(partes).buffer(max((v.largura_m - largura_traco) / 2, 0.5), join_style=1).intersection(gleba)
        if not faixa.is_empty:
            vias_prev.append((v, faixa.difference(app)))
    vias_prev_uniao = unary_union([f for _, f in vias_prev]) if vias_prev else Polygon()
    util = gleba.difference(unary_union([app, vias_prev_uniao])) if not (app.is_empty and vias_prev_uniao.is_empty) else gleba

    ang = p.angulo_graus if p.angulo_graus is not None else _angulo_automatico(util)
    origem = util.centroid
    u = affinity.rotate(util, -ang, origin=origem)
    minx, miny, maxx, maxy = u.bounds

    W, F, D, L = p.largura_via_m, p.frente_lote_m, p.profundidade_lote_m, p.comprimento_quadra_m
    quadras_rect = []
    y = miny + W  # começa com uma via na borda para dar frente aos lotes
    while y < maxy:
        x = minx
        while x < maxx:
            quadras_rect.append(box(x, y, min(x + L, maxx), y + 2 * D))
            x += L + W
        y += 2 * D + W

    lote_nominal = F * D
    quadras = []  # [{"geom", "lotes":[geom], "sobras":[geom]}]
    for qr in quadras_rect:
        q = qr.intersection(u)
        if q.is_empty or q.area < p.lote_minimo_m2:
            continue
        qx0, qy0, qx1, _ = qr.bounds
        lotes = []
        for fileira in (0, 1):
            y0 = qy0 + fileira * D
            x = qx0
            while x + F * 0.5 < qx1:
                lr = box(x, y0, min(x + F, qx1), y0 + D)
                lg = lr.intersection(u)
                if not lg.is_empty and lg.area >= p.lote_minimo_m2 and lg.area >= 0.75 * min(lote_nominal, lr.area):
                    lotes.append(lg)
                x += F
        sobra = q.difference(unary_union(lotes)) if lotes else q
        quadras.append({"geom": q, "lotes": lotes, "sobras": [s for s in _poligonos(sobra) if s.area > 1]})

    vias = u.difference(unary_union([qr for qr in quadras_rect])) if quadras_rect else Polygon()

    area_util = util.area
    req_verde = area_util * p.pct_area_verde / 100
    req_inst = area_util * p.pct_institucional / 100
    verde, inst, reman = [], [], []

    sobras = sorted((s for q in quadras for s in q["sobras"]), key=lambda g: g.area, reverse=True)
    a_verde = a_inst = 0.0
    for s in sobras:
        if s.buffer(-p.largura_minima_area_publica_m / 2).is_empty:
            reman.append(s)  # faixa estreita demais para uso público
        elif a_verde < req_verde:
            verde.append(s); a_verde += s.area
        elif a_inst < req_inst and s.area >= 360:
            inst.append(s); a_inst += s.area
        else:
            reman.append(s)

    # converte quadras menos eficientes se faltar área pública
    for q in sorted(quadras, key=lambda q: (sum(l.area for l in q["lotes"]) / q["geom"].area) if q["geom"].area else 0):
        if a_verde >= req_verde and a_inst >= req_inst:
            break
        if not q["lotes"]:
            continue
        g = unary_union(q["lotes"])
        if a_inst < req_inst:
            inst.append(g); a_inst += g.area
        else:
            verde.append(g); a_verde += g.area
        q["lotes"] = []

    feats_local: list[tuple[str, Polygon, dict]] = []
    n = 0
    for qi, q in enumerate([q for q in quadras if q["lotes"]], start=1):
        for li, lg in enumerate(sorted(q["lotes"], key=lambda g: (round(g.centroid.y), g.centroid.x)), start=1):
            n += 1
            feats_local.append(("lote", lg, {"nome": f"Q{qi:02d}-L{li:02d}", "quadra": f"Q{qi:02d}", "area_m2": round(lg.area, 2)}))
    for tipo, geoms in (("via", [vias]), ("area_verde", verde), ("institucional", inst), ("remanescente", reman)):
        for i, g in enumerate(geoms, start=1):
            for pg in _poligonos(g):
                feats_local.append((tipo, pg, {"nome": f"{tipo}-{i}", "area_m2": round(pg.area, 2)}))

    # volta para coordenadas UTM reais
    feats_utm = [(t, affinity.rotate(g, ang, origin=origem), pr) for t, g, pr in feats_local]
    for pg in _poligonos(app):
        feats_utm.append(("app", pg, {"nome": "APP / fundo de vale / restrição", "area_m2": round(pg.area, 2)}))
    for v, faixa in vias_prev:
        for pg in _poligonos(faixa):
            feats_utm.append(("via", pg, {"nome": f"{v.hierarquia} prevista ({v.largura_m:.0f} m)", "diretriz": True, "area_m2": round(pg.area, 2)}))

    tr = _transformer(p.epsg, EPSG_WGS84)
    features = []
    for tipo, g, props in feats_utm:
        geo = _transformar(g, tr)
        features.append({"type": "Feature", "geometry": mapping(geo), "properties": {"tipo": tipo, **props}})

    soma = lambda t: sum(g.area for tt, g, _ in feats_utm if tt == t)
    a_lotes = soma("lote")
    resumo = {
        "area_gleba_m2": round(gleba.area, 2),
        "area_app_m2": round(app.area, 2),
        "area_util_m2": round(area_util, 2),
        "numero_lotes": n,
        "area_lotes_m2": round(a_lotes, 2),
        "lote_medio_m2": round(a_lotes / n, 2) if n else 0,
        "area_vias_m2": round(soma("via"), 2),
        "area_vias_diretriz_m2": round(vias_prev_uniao.area, 2),
        "area_verde_m2": round(soma("area_verde"), 2),
        "area_institucional_m2": round(soma("institucional"), 2),
        "area_remanescente_m2": round(soma("remanescente"), 2),
        "angulo_malha_graus": round(ang, 2),
    }
    for k in ("lotes", "vias", "verde", "institucional"):
        chave = {"lotes": "area_lotes_m2", "vias": "area_vias_m2", "verde": "area_verde_m2", "institucional": "area_institucional_m2"}[k]
        resumo[f"pct_{k}"] = round(resumo[chave] / gleba.area * 100, 2) if gleba.area else 0
    if resumo["pct_vias"] > 30:
        alertas.append("Sistema viário acima de 30% da gleba — ajuste comprimento de quadra ou orientação da malha.")
    if n == 0:
        alertas.append("Nenhum lote gerado — revise dimensões de lote/quadra frente ao tamanho da gleba.")

    return Masterplan(features, resumo, _svg(feats_utm, gleba, resumo), alertas)


def _transformar(g, tr):
    import numpy as np
    import shapely

    return shapely.transform(g, lambda xy: np.column_stack(tr.transform(xy[:, 0], xy[:, 1])))


def _svg(feats, gleba: Polygon, resumo: dict, largura: int = 1100) -> str:
    minx, miny, maxx, maxy = gleba.bounds
    for _, g, _ in feats:
        a, b, c, d = g.bounds
        minx, miny, maxx, maxy = min(minx, a), min(miny, b), max(maxx, c), max(maxy, d)
    margem = 20
    area_desenho = largura - 300
    esc = (area_desenho - 2 * margem) / max(maxx - minx, maxy - miny, 1)
    altura = max(int((maxy - miny) * esc + 2 * margem), 520)

    def pts(coords):
        return " ".join(f"{(x - minx) * esc + margem:.1f},{(maxy - y) * esc + margem:.1f}" for x, y in coords)

    def path(pg: Polygon) -> str:
        d = "M" + pts(pg.exterior.coords) + "Z"
        for h in pg.interiors:
            d += "M" + pts(h.coords) + "Z"
        return d

    ordem = ["app", "via", "remanescente", "area_verde", "institucional", "lote"]
    partes = []
    for tipo in ordem:
        for t, g, props in feats:
            if t != tipo:
                continue
            for pg in _poligonos(g):
                partes.append(
                    f'<path d="{path(pg)}" fill="{CORES[t]}" stroke="#555" stroke-width="{0.4 if t == "lote" else 0.6}" '
                    f'fill-rule="evenodd"><title>{props.get("nome", t)} — {props.get("area_m2", 0):,.2f} m²</title></path>'
                )
    partes.append(f'<path d="{path(gleba)}" fill="none" stroke="#d35400" stroke-width="2.5"/>')

    lx = area_desenho + 10
    leg = [f'<rect x="{lx - 5}" y="10" width="285" height="{altura - 20}" fill="#fff" stroke="#ccc"/>',
           f'<text x="{lx + 5}" y="38" font-size="18" font-weight="bold">Masterplan preliminar</text>']
    yy = 70
    nomes = {"lote": "Lotes", "via": "Sistema viário", "area_verde": "Área verde", "institucional": "Institucional",
             "app": "APP / restrições", "remanescente": "Remanescente"}
    for t in ["lote", "via", "area_verde", "institucional", "app", "remanescente"]:
        leg.append(f'<rect x="{lx + 5}" y="{yy - 12}" width="18" height="14" fill="{CORES[t]}" stroke="#555"/>'
                   f'<text x="{lx + 30}" y="{yy}" font-size="13">{nomes[t]}</text>')
        yy += 22
    yy += 10
    linhas = [
        ("Gleba", f"{resumo['area_gleba_m2']:,.0f} m²"),
        ("Área útil", f"{resumo['area_util_m2']:,.0f} m²"),
        ("Lotes", f"{resumo['numero_lotes']}"),
        ("Lote médio", f"{resumo['lote_medio_m2']:,.0f} m²"),
        ("Lotes (% gleba)", f"{resumo['pct_lotes']:.1f}%"),
        ("Vias", f"{resumo['pct_vias']:.1f}%"),
        ("Verde", f"{resumo['pct_verde']:.1f}%"),
        ("Institucional", f"{resumo['pct_institucional']:.1f}%"),
    ]
    for k, v in linhas:
        leg.append(f'<text x="{lx + 5}" y="{yy}" font-size="13">{k}</text><text x="{lx + 270}" y="{yy}" font-size="13" text-anchor="end">{v.replace(",", ".")}</text>')
        yy += 20
    # norte (o desenho está em UTM, norte para cima) e escala gráfica
    leg.append(f'<g transform="translate({lx + 240},{altura - 90})"><polygon points="0,-25 8,5 0,0 -8,5" fill="#333"/>'
               f'<text x="0" y="22" font-size="14" text-anchor="middle">N</text></g>')
    passo = 10 ** math.floor(math.log10(max((maxx - minx) / 4, 1)))
    leg.append(f'<line x1="{lx + 5}" y1="{altura - 40}" x2="{lx + 5 + passo * esc}" y2="{altura - 40}" stroke="#333" stroke-width="3"/>'
               f'<text x="{lx + 5}" y="{altura - 25}" font-size="12">{passo:.0f} m</text>')

    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{largura}" height="{altura}" viewBox="0 0 {largura} {altura}" '
            f'font-family="Arial, sans-serif"><rect width="100%" height="100%" fill="#fafafa"/>{"".join(partes)}{"".join(leg)}</svg>')
