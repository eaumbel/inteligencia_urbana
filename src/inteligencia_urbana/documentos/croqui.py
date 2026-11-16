"""Extração do croqui vetorial das Consultas de Parcelamento do Solo (IPPUL).

O "Mapa vinculado" da consulta é um desenho vetorial, com norte para cima e "sem
escala". O lote de interesse é um polígono cinza (legenda "IDENTIFICAÇÃO DO LOTE").
Como a consulta informa a área total do lote, a escala sai da razão entre essa
área e a área do polígono no desenho; com ela, o croqui inteiro (vias previstas,
hidrografia, fundo de vale, linha férrea, base cadastral) vira metros em relação
ao lote. A posição no terreno não consta do documento e é ajustada no mapa.
"""

from __future__ import annotations

import io
import math

# cores do padrão de mapas do IPPUL (RGB 0–1) → categoria
CATEGORIAS = [
    ((0.8588, 0.8588, 0.8588), "lote"),
    ((1.0, 0.498, 0.0), "via_coletora"),
    ((1.0, 0.0, 0.0), "via_arterial"),
    ((0.4627, 0.4627, 0.4627), "via_local_ferrovia"),
    ((0.0, 0.498, 1.0), "hidrografia"),
    ((0.3608, 0.7216, 0.451), "fundo_de_vale"),
    ((0.8275, 0.8863, 0.6667), "fundo_de_vale"),
    ((0.7294, 0.7294, 0.7294), "base_cadastral"),
]


def _categoria(cor) -> str | None:
    if not cor or len(cor) != 3:
        return None
    for ref, nome in CATEGORIAS:
        if all(abs(a - b) < 0.02 for a, b in zip(cor, ref)):
            return nome
    return None


def _area(pts):
    return abs(sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(pts, pts[1:] + pts[:1]))) / 2


def _caixa(cat, pts):
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    return cat, round(min(xs)), round(min(ys)), round(max(xs)), round(max(ys))


def _dentro(p, poly):
    x, y = p
    dentro = False
    for (x1, y1), (x2, y2) in zip(poly, poly[1:] + poly[:1]):
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            dentro = not dentro
    return dentro


def montar_croqui(formas: list[dict], area_total_m2: float, rotulo_lote: tuple[float, float] | None = None,
                  limite_y: float | None = None) -> dict | None:
    """formas: [{"pts": [(x, y_topo)...], "fill": cor|None, "stroke": cor|None, "fechada": bool}] em pontos do PDF
    (y crescendo para baixo). Retorna o lote e as feições em metros (x = Leste, y = Norte) relativos ao centro
    dos vértices do lote."""
    lotes = []
    for f in formas:
        if _categoria(f.get("fill")) == "lote" and len(f["pts"]) >= 3:
            pts = f["pts"][:-1] if f["pts"][0] == f["pts"][-1] else f["pts"]
            if limite_y is not None and min(p[1] for p in pts) > limite_y:
                continue  # amostra da legenda
            lotes.append(pts)
    if not lotes or not area_total_m2:
        return None
    if rotulo_lote:
        com_rotulo = [p for p in lotes if _dentro(rotulo_lote, p)]
        lotes = com_rotulo or lotes
    lote = max(lotes, key=_area)
    escala = math.sqrt(area_total_m2 / _area(lote))  # metros por ponto do PDF
    cx = sum(p[0] for p in lote) / len(lote)
    cy = sum(p[1] for p in lote) / len(lote)
    conv = lambda p: [round((p[0] - cx) * escala, 2), round(-(p[1] - cy) * escala, 2)]

    feicoes = []
    # caixas das formas preenchidas: o contorno separado da mesma forma não é repetido
    vistos = {_caixa(_categoria(f["fill"]), f["pts"]) for f in formas if f.get("fill") is not None and _categoria(f["fill"])}
    for f in formas:
        pts = f["pts"]
        if len(pts) < 2 or (limite_y is not None and min(p[1] for p in pts) > limite_y):
            continue
        if f.get("fill") is not None:
            cat = _categoria(f["fill"])
            if not cat or cat == "lote":
                continue
            if _area(pts) * escala**2 < (40 if cat == "fundo_de_vale" else 1):  # textura (pontilhado do fundo de vale)
                continue
            feicoes.append({"tipo": cat, "geom": "poligono", "pts": [conv(p) for p in pts]})
        elif f.get("stroke") is not None:
            cat = _categoria(f["stroke"])
            comprimento = sum(math.dist(a, b) for a, b in zip(pts, pts[1:]))
            if not cat or cat == "lote" or comprimento * escala < 2:  # descarta pontilhado miúdo
                continue
            if cat != "fundo_de_vale" and _caixa(cat, pts) in vistos:  # contorno da mesma forma já preenchida
                continue
            feicoes.append({"tipo": cat, "geom": "linha", "pts": [conv(p) for p in pts]})
    # fundo de vale: área desenhada como textura de tracinhos/pontos verdes → polígono contínuo
    textura = []
    for f in formas:
        cor = f.get("stroke") or f.get("fill")
        if _categoria(cor) == "fundo_de_vale" and (limite_y is None or min(p[1] for p in f["pts"]) <= limite_y):
            xs, ys = [p[0] for p in f["pts"]], [p[1] for p in f["pts"]]
            if max(max(xs) - min(xs), max(ys) - min(ys)) * escala < 4:
                textura.append(((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2))
    if len(textura) >= 30:
        from shapely.geometry import Point
        from shapely.ops import unary_union

        raio = 6 / escala * 1.4111  # ~6 pt na escala usual do IPPUL, em pontos do desenho
        g = unary_union([Point(x, y).buffer(raio, 4) for x, y in textura]).buffer(-raio * 0.6).simplify(raio * 0.3)
        for pg in ([g] if g.geom_type == "Polygon" else list(getattr(g, "geoms", []))):
            if pg.area * escala**2 >= 500:
                feicoes.append({"tipo": "fundo_de_vale_area", "geom": "poligono", "pts": [conv(p) for p in list(pg.exterior.coords)[:-1]]})
    return {
        "lote_m": [conv(p) for p in lote],
        "escala_m_por_pt": round(escala, 4),
        "feicoes": feicoes,
        "aviso": "Croqui 'sem escala' do IPPUL: escala calculada pela área total do lote; posição e eventual rotação "
                 "precisam ser conferidas sobre o satélite.",
    }


def extrair_croqui_pdf(conteudo: bytes, area_total_m2: float) -> dict | None:
    """Procura a página do mapa vinculado e extrai o croqui."""
    import pdfplumber

    with pdfplumber.open(io.BytesIO(conteudo)) as pdf:
        for pagina in reversed(pdf.pages):
            objs = pagina.curves + pagina.rects + pagina.lines
            if len(objs) < 50:
                continue
            palavras = pagina.extract_words()
            legenda = next((w["top"] for w in palavras if w["text"].upper().startswith("LEGENDA")), None)
            rot = None
            for i, w in enumerate(palavras):
                if w["text"].upper() == "LOTE" and (legenda is None or w["top"] < legenda):
                    rot = ((w["x0"] + w["x1"]) / 2, (w["top"] + w["bottom"]) / 2)
                    break
            formas = []
            for o in objs:
                pts = o.get("pts") or [(o["x0"], o["top"]), (o["x1"], o["top"]), (o["x1"], o["bottom"]), (o["x0"], o["bottom"])]
                formas.append({
                    "pts": [(float(x), float(y)) for x, y in pts],
                    "fill": tuple(o["non_stroking_color"]) if o.get("fill") and isinstance(o.get("non_stroking_color"), (list, tuple)) else None,
                    "stroke": tuple(o["stroking_color"]) if o.get("stroke") and isinstance(o.get("stroking_color"), (list, tuple)) else None,
                })
            croqui = montar_croqui(formas, area_total_m2, rot, legenda)
            if croqui:
                croqui["pagina"] = pagina.page_number
                return croqui
    return None
