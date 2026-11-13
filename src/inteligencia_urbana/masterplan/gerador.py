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

import numpy as np

from typing import Literal

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
    tracado: Literal["organico", "ortogonal"] = Field("organico", description="Orgânico: ruas acompanham o relevo; ortogonal: malha reta")
    usar_relevo: bool = Field(True, description="Baixar a elevação do terreno (SRTM) para traçado e declividade")
    declividade_maxima_pct: float = Field(30, ge=5, le=100, description="Declividade a partir da qual não se parcela (Lei 6.766/79)")
    vias_previstas: list[ViaPrevista] = Field(default_factory=list, description="Diretrizes viárias (ex.: croqui do IPPUL)")
    fundo_vale_utm: list[list[tuple[float, float]]] = Field(default_factory=list, description="Polígonos de fundo de vale")
    hidrografia_utm: list[list[tuple[float, float]]] = Field(default_factory=list, description="Cursos d'água (linhas ou polígonos)")


@dataclass
class Masterplan:
    features: list[dict]
    resumo: dict
    svg: str
    curvas_nivel: list[dict] = field(default_factory=list)
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


def _ortogonal(util, p):
    """Malha reta orientada pelo maior lado do retângulo envolvente (em coordenadas giradas)."""
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
    return quadras, vias, ang, origem


def _chaikin(coords, iteracoes=2):
    pts = list(coords)
    for _ in range(iteracoes):
        novo = [pts[0]]
        for a, b in zip(pts, pts[1:]):
            novo += [(0.75 * a[0] + 0.25 * b[0], 0.75 * a[1] + 0.25 * b[1]), (0.25 * a[0] + 0.75 * b[0], 0.25 * a[1] + 0.75 * b[1])]
        novo.append(pts[-1])
        pts = novo
    return pts


def _linhas(g):
    if g.is_empty:
        return []
    if g.geom_type == "LineString":
        return [g]
    if g.geom_type == "LinearRing":
        return [LineString(g.coords)]
    return [x for x in getattr(g, "geoms", []) if x.geom_type == "LineString"]


def _normal(linha: LineString, s: float):
    p = linha.interpolate(s)
    a, b = linha.interpolate(max(s - 1, 0)), linha.interpolate(min(s + 1, linha.length))
    tx, ty = b.x - a.x, b.y - a.y
    n = math.hypot(tx, ty) or 1
    return (p.x, p.y), (-ty / n, tx / n)  # normal à esquerda


def _organico(util, p, mde):
    """Ruas principais paralelas às curvas de nível (ou ao contorno do terreno), lotes perpendiculares à rua."""
    W, F, prof, Lq = p.largura_via_m, p.frente_lote_m, p.profundidade_lote_m, p.comprimento_quadra_m
    D = 2 * prof + W  # distância entre eixos de ruas paralelas (duas fileiras de lotes)
    x0, y0, x1, y1 = util.bounds
    diag = math.hypot(x1 - x0, y1 - y0)
    espinhas, transversais, modo = [], [], "forma"

    base = None
    if mde is not None and mde.amplitude > 4:
        from ..geo.relevo import curvas_de_nivel

        c = util.representative_point()
        nivel = float(mde.amostrar(c.x, c.y))
        candidatas = [ln for ln in curvas_de_nivel(mde, nivel) if ln.intersects(util)]
        if candidatas:
            ln = max(candidatas, key=lambda g: g.intersection(util.buffer(D)).length)
            # suavização forte: raio de curvatura grande o bastante para as paralelas não se dobrarem
            ln = LineString(_chaikin(ln.simplify(D * 0.6).coords, 4))
            # prolonga as pontas na direção da tangente para cobrir toda a área com as paralelas
            (ax, ay), (bx, by) = ln.coords[0], ln.coords[1]
            (cx, cy), (dx, dy) = ln.coords[-2], ln.coords[-1]
            na, nb = math.hypot(ax - bx, ay - by) or 1, math.hypot(dx - cx, dy - cy) or 1
            base = LineString([(ax + (ax - bx) / na * diag, ay + (ay - by) / na * diag), *ln.coords,
                               (dx + (dx - cx) / nb * diag, dy + (dy - cy) / nb * diag)])
            modo = "relevo"
    if base is not None:
        k_max = int(diag / D) + 2
        por_k = {}
        area_ref = util.buffer(D)
        for k in range(-k_max, k_max + 1):
            off = base if k == 0 else base.offset_curve(k * D, quad_segs=8, join_style="round")
            linhas_k = [LineString(_chaikin(l.simplify(2).coords, 2)) for l in _linhas(off) if l.length > 3 * F]
            linhas_k = [l for l in linhas_k if l.intersects(area_ref)]
            if linhas_k:
                por_k[k] = max(linhas_k, key=lambda l: l.intersection(area_ref).length)
        espinhas = list(por_k.values())
        # transversais descendo a encosta: a partir de pontos da curva-base, liga cada paralela à seguinte
        # pelo ponto mais próximo (caminho de maior declive), sem retas longas que se cruzam
        passo = Lq + W
        trecho = base.intersection(area_ref)
        trecho = max(_linhas(trecho), key=lambda l: l.length) if _linhas(trecho) else base
        s = (trecho.length % passo) / 2
        while s < trecho.length:
            p0 = trecho.interpolate(s)
            for sentido in (1, -1):
                pts, atual, k = [(p0.x, p0.y)], p0, 0
                while (k + sentido) in por_k:
                    k += sentido
                    linha = por_k[k]
                    prox = linha.interpolate(linha.project(atual))
                    if prox.distance(atual) > 1.8 * D:  # paralela interrompida: para aqui
                        break
                    pts.append((prox.x, prox.y)); atual = prox
                if len(pts) > 1:
                    transversais.append(LineString(pts))
            s += passo
    else:
        # terreno plano: anéis acompanhando o contorno do terreno
        d = prof + W / 2
        while True:
            anel = util.buffer(-d, join_style="round")
            if anel.is_empty or anel.area < prof * F:
                break
            for pg in _poligonos(anel):
                espinhas += [LineString(pg.exterior.coords)] + [LineString(i.coords) for i in pg.interiors]
            d += D
        c = util.centroid
        if espinhas:
            n_radiais = max(2, int(espinhas[0].length / (Lq + W)))
            for i in range(n_radiais):
                t = 2 * math.pi * i / n_radiais
                transversais.append(LineString([(c.x, c.y), (c.x + math.cos(t) * diag, c.y + math.sin(t) * diag)]))

    pecas = [g for e in espinhas for g in _linhas(e.intersection(util)) if g.length > 3 * F]
    eixos = pecas + [g for t in transversais for g in _linhas(t.intersection(util)) if g.length > W]
    vias = unary_union([e.buffer(W / 2, cap_style="flat") for e in eixos]).intersection(util) if eixos else Polygon()
    livre = util.difference(vias)

    lotes, ocupado = [], Polygon()
    a, b = W / 2, W / 2 + prof
    for linha in pecas:
        n_lotes = int(linha.length // F)
        if n_lotes < 1:
            continue
        sobra = (linha.length - n_lotes * F) / 2
        for lado in (1, -1):
            pontos = [_normal(linha, sobra + i * F) for i in range(n_lotes + 1)]
            for (p1, n1), (p2, n2) in zip(pontos, pontos[1:]):
                quad = Polygon([(p1[0] + lado * n1[0] * a, p1[1] + lado * n1[1] * a), (p2[0] + lado * n2[0] * a, p2[1] + lado * n2[1] * a),
                                (p2[0] + lado * n2[0] * b, p2[1] + lado * n2[1] * b), (p1[0] + lado * n1[0] * b, p1[1] + lado * n1[1] * b)]).buffer(0)
                lote = quad.intersection(livre)
                if lote.is_empty:
                    continue
                lote = max(_poligonos(lote), key=lambda g: g.area) if lote.geom_type != "Polygon" else lote
                if lote.area < p.lote_minimo_m2 or lote.area < 0.7 * F * prof:
                    continue
                if not ocupado.is_empty and lote.intersection(ocupado).area > 0.05 * lote.area:
                    continue
                lote = lote.difference(ocupado) if not ocupado.is_empty else lote
                lotes.append(lote)
                ocupado = unary_union([ocupado, lote])

    quadras = []
    for bloco in _poligonos(livre):
        ls = [l for l in lotes if bloco.contains(l.representative_point())]
        sobra = bloco.difference(unary_union(ls)) if ls else bloco
        quadras.append({"geom": bloco, "lotes": ls, "sobras": [x for x in _poligonos(sobra) if x.area > 1]})
    return quadras, vias, modo


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
    # relevo: declividade acima do limite fica fora dos lotes (Lei 6.766/79, art. 3º, III)
    mde, relevo, declive = None, {}, Polygon()
    if p.usar_relevo:
        try:
            from ..geo.relevo import areas_acima_declividade, obter_mde

            mde = obter_mde(gleba.bounds, p.epsg)
            dec = mde.declividade_pct()
            relevo = {"cota_min_m": round(float(mde.z.min()), 1), "cota_max_m": round(float(mde.z.max()), 1),
                      "declividade_media_pct": round(float(dec.mean()), 1), "declividade_max_pct": round(float(dec.max()), 1),
                      "fonte": "SRTM/Terrarium (~30 m) — preliminar"}
            declive = areas_acima_declividade(mde, p.declividade_maxima_pct, gleba).difference(app)
            if not declive.is_empty and declive.area > 1:
                alertas.append(f"{declive.area:,.0f} m² com declividade ≥ {p.declividade_maxima_pct:.0f}% ficaram fora dos lotes.".replace(",", "."))
                app = unary_union([app, declive])
        except Exception as e:  # sem rede ou fora da cobertura: segue sem relevo
            alertas.append(f"Relevo indisponível ({type(e).__name__}); traçado feito sem topografia.")
            mde = None
    util = gleba.difference(unary_union([app, vias_prev_uniao])) if not (app.is_empty and vias_prev_uniao.is_empty) else gleba

    if p.tracado == "organico":
        quadras, vias, modo = _organico(util, p, mde)
        ang, origem = 0.0, util.centroid
        alertas.append("Traçado orgânico: " + ("ruas principais acompanhando as curvas de nível." if modo == "relevo"
                                              else "ruas acompanhando o formato do terreno (relevo plano ou indisponível)."))
    else:
        quadras, vias, ang, origem = _ortogonal(util, p)

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
        "tracado": p.tracado,
        "area_declividade_excessiva_m2": round(declive.area, 2) if not declive.is_empty else 0,
        "relevo": relevo,
    }
    for k in ("lotes", "vias", "verde", "institucional"):
        chave = {"lotes": "area_lotes_m2", "vias": "area_vias_m2", "verde": "area_verde_m2", "institucional": "area_institucional_m2"}[k]
        resumo[f"pct_{k}"] = round(resumo[chave] / gleba.area * 100, 2) if gleba.area else 0
    if resumo["pct_vias"] > 30:
        alertas.append("Sistema viário acima de 30% da gleba — ajuste comprimento de quadra ou orientação da malha.")
    if n == 0:
        alertas.append("Nenhum lote gerado — revise dimensões de lote/quadra frente ao tamanho da gleba.")

    curvas = []
    if mde is not None:
        from ..geo.relevo import curvas_intervalo

        intervalo, linhas = curvas_intervalo(mde, gleba.buffer(80))
        relevo["intervalo_curvas_m"] = intervalo
        for nivel, ln in linhas:
            geo = _transformar(ln, tr)
            curvas.append({"type": "Feature", "geometry": mapping(geo),
                           "properties": {"cota_m": nivel, "mestra": abs(nivel / intervalo) % 5 < 1e-6}})
    return Masterplan(features=features, resumo=resumo, svg=_svg(feats_utm, gleba, resumo), alertas=alertas, curvas_nivel=curvas)


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
