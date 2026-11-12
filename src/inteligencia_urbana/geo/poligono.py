"""Geometria de perímetros: área, perímetro, azimutes e fechamento de poligonais."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field

from shapely.geometry import Polygon

from .coordenadas import EPSG_SIRGAS2000_UTM22S, utm_para_geo


@dataclass
class Vertice:
    nome: str
    e: float
    n: float


@dataclass
class Segmento:
    de: str
    para: str
    azimute_graus: float
    distancia_m: float
    confrontante: str | None = None


@dataclass
class Fechamento:
    erro_linear_m: float
    perimetro_m: float
    precisao: float | None  # 1:X  (None quando o erro é zero)
    aceitavel: bool

    @property
    def precisao_txt(self) -> str:
        return "fechamento perfeito" if self.precisao is None else f"1:{self.precisao:,.0f}".replace(",", ".")


@dataclass
class Perimetro:
    vertices: list[Vertice]
    segmentos: list[Segmento] = field(default_factory=list)
    epsg: int = EPSG_SIRGAS2000_UTM22S

    @property
    def pontos(self) -> list[tuple[float, float]]:
        return [(v.e, v.n) for v in self.vertices]

    @property
    def area_m2(self) -> float:
        return area_shoelace(self.pontos)

    @property
    def perimetro_m(self) -> float:
        return perimetro(self.pontos)

    def poligono(self) -> Polygon:
        return Polygon(self.pontos)

    def para_geo(self) -> list[tuple[float, float]]:
        """Vértices em (lon, lat) WGS84."""
        return [utm_para_geo(e, n, self.epsg) for e, n in self.pontos]

    def geojson(self) -> dict:
        coords = self.para_geo()
        if coords and coords[0] != coords[-1]:
            coords.append(coords[0])
        return {
            "type": "Feature",
            "geometry": {"type": "Polygon", "coordinates": [[list(c) for c in coords]]},
            "properties": {
                "area_m2": round(self.area_m2, 2),
                "perimetro_m": round(self.perimetro_m, 2),
                "vertices": [asdict(v) for v in self.vertices],
                "segmentos": [asdict(s) for s in self.segmentos],
                "epsg": self.epsg,
            },
        }


def azimute(e1: float, n1: float, e2: float, n2: float) -> float:
    """Azimute (graus, a partir do Norte, sentido horário) de P1 para P2."""
    return math.degrees(math.atan2(e2 - e1, n2 - n1)) % 360


def distancia(e1: float, n1: float, e2: float, n2: float) -> float:
    return math.hypot(e2 - e1, n2 - n1)


def area_shoelace(pontos: list[tuple[float, float]]) -> float:
    if len(pontos) < 3:
        return 0.0
    s = 0.0
    for (x1, y1), (x2, y2) in zip(pontos, pontos[1:] + pontos[:1]):
        s += x1 * y2 - x2 * y1
    return abs(s) / 2


def perimetro(pontos: list[tuple[float, float]]) -> float:
    if len(pontos) < 2:
        return 0.0
    return sum(distancia(*a, *b) for a, b in zip(pontos, pontos[1:] + pontos[:1]))


def segmentos_de_vertices(vertices: list[Vertice], confrontantes: list[str | None] | None = None) -> list[Segmento]:
    segs = []
    for i, v in enumerate(vertices):
        w = vertices[(i + 1) % len(vertices)]
        conf = confrontantes[i] if confrontantes and i < len(confrontantes) else None
        segs.append(Segmento(v.nome, w.nome, azimute(v.e, v.n, w.e, w.n), distancia(v.e, v.n, w.e, w.n), conf))
    return segs


def poligonal_por_azimutes(
    inicio: tuple[float, float],
    lances: list[tuple[float, float]],
    nomes: list[str] | None = None,
) -> tuple[list[Vertice], Fechamento]:
    """Calcula vértices a partir de um ponto inicial e lances (azimute°, distância m).

    Retorna os vértices (sem repetir o inicial) e o fechamento linear da poligonal.
    """
    e, n = inicio
    pts = [(e, n)]
    for az, d in lances:
        r = math.radians(az)
        e += d * math.sin(r)
        n += d * math.cos(r)
        pts.append((e, n))
    erro = distancia(*pts[0], *pts[-1])
    per = sum(d for _, d in lances)
    nomes = nomes or [f"P{i + 1}" for i in range(len(pts) - 1)]
    vertices = [Vertice(nomes[i] if i < len(nomes) else f"P{i + 1}", x, y) for i, (x, y) in enumerate(pts[:-1])]
    return vertices, avaliar_fechamento(erro, per)


def avaliar_fechamento(erro_linear: float, perim: float, tolerancia: float = 10_000) -> Fechamento:
    """Precisão relativa 1:X. Por padrão aceita 1:10.000 (levantamentos urbanos usuais)."""
    precisao = None if erro_linear < 1e-6 else perim / erro_linear
    return Fechamento(erro_linear, perim, precisao, precisao is None or precisao >= tolerancia)
