"""Relevo do terreno: elevação, declividade e curvas de nível.

Fonte: blocos "Terrarium" (Mapzen/AWS Open Data — SRTM/ASTER e outras bases; no Brasil,
resolução nativa ~30 m). Altitude = R*256 + G + B/256 - 32768 (metros).
Serve para estudo preliminar; o projeto exige levantamento planialtimétrico.
"""

from __future__ import annotations

import io
import math
import urllib.request
from dataclasses import dataclass
from functools import lru_cache

import numpy as np
from shapely.geometry import LineString, MultiLineString, box
from shapely.ops import linemerge, unary_union

from .coordenadas import EPSG_WGS84, _transformer

URL_TERRARIUM = "https://elevation-tiles-prod.s3.amazonaws.com/terrarium/{z}/{x}/{y}.png"
ZOOM = 15


def _tile_xy(lon, lat, z: int):
    n = 2**z
    s = np.sin(np.radians(lat))
    return (np.asarray(lon) + 180) / 360 * n, (0.5 - np.log((1 + s) / (1 - s)) / (4 * math.pi)) * n


@lru_cache(maxsize=64)
def _tile(z: int, x: int, y: int) -> np.ndarray:
    from PIL import Image

    req = urllib.request.Request(URL_TERRARIUM.format(z=z, x=x, y=y), headers={"User-Agent": "inteligencia-urbana/0.1"})
    with urllib.request.urlopen(req, timeout=30) as r:
        im = Image.open(io.BytesIO(r.read())).convert("RGB")
    a = np.asarray(im, dtype=np.float64)
    return a[..., 0] * 256 + a[..., 1] + a[..., 2] / 256 - 32768


@dataclass
class MDE:
    """Grade de elevação em UTM (x0, y0 = canto inferior esquerdo; passo em metros)."""
    x0: float
    y0: float
    passo: float
    z: np.ndarray  # [linha (y), coluna (x)]

    def amostrar(self, x, y):
        """Elevação bilinear em pontos UTM (aceita arrays)."""
        fx = (np.asarray(x) - self.x0) / self.passo
        fy = (np.asarray(y) - self.y0) / self.passo
        i0 = np.clip(np.floor(fy).astype(int), 0, self.z.shape[0] - 2)
        j0 = np.clip(np.floor(fx).astype(int), 0, self.z.shape[1] - 2)
        ty, tx = np.clip(fy - i0, 0, 1), np.clip(fx - j0, 0, 1)
        z = self.z
        return (z[i0, j0] * (1 - tx) * (1 - ty) + z[i0, j0 + 1] * tx * (1 - ty)
                + z[i0 + 1, j0] * (1 - tx) * ty + z[i0 + 1, j0 + 1] * tx * ty)

    def declividade_pct(self) -> np.ndarray:
        gy, gx = np.gradient(self.z, self.passo)
        return np.hypot(gx, gy) * 100

    @property
    def amplitude(self) -> float:
        return float(np.nanmax(self.z) - np.nanmin(self.z))


def obter_mde(bounds_utm: tuple[float, float, float, float], epsg: int, passo: float = 5.0, margem: float = 60.0) -> MDE:
    """Baixa a elevação e reamostra numa grade UTM regular cobrindo bounds (+ margem)."""
    x0, y0, x1, y1 = bounds_utm
    x0, y0, x1, y1 = x0 - margem, y0 - margem, x1 + margem, y1 + margem
    xs = np.arange(x0, x1 + passo, passo)
    ys = np.arange(y0, y1 + passo, passo)
    gx, gy = np.meshgrid(xs, ys)
    lon, lat = _transformer(epsg, EPSG_WGS84).transform(gx.ravel(), gy.ravel())
    tx, ty = _tile_xy(np.asarray(lon), np.asarray(lat), ZOOM)
    z = np.empty(tx.shape)
    for tile_x in np.unique(np.floor(tx).astype(int)):
        for tile_y in np.unique(np.floor(ty).astype(int)):
            sel = (np.floor(tx).astype(int) == tile_x) & (np.floor(ty).astype(int) == tile_y)
            if not sel.any():
                continue
            t = _tile(ZOOM, int(tile_x), int(tile_y))
            px, py = (tx[sel] - tile_x) * 256 - 0.5, (ty[sel] - tile_y) * 256 - 0.5
            j0 = np.clip(np.floor(px).astype(int), 0, 254); i0 = np.clip(np.floor(py).astype(int), 0, 254)
            fx, fy = np.clip(px - j0, 0, 1), np.clip(py - i0, 0, 1)
            z[sel] = (t[i0, j0] * (1 - fx) * (1 - fy) + t[i0, j0 + 1] * fx * (1 - fy)
                      + t[i0 + 1, j0] * (1 - fx) * fy + t[i0 + 1, j0 + 1] * fx * fy)
    grade = z.reshape(gx.shape)
    # suaviza o degrau do SRTM (média 3x3)
    p = np.pad(grade, 1, mode="edge")
    grade = sum(p[i:i + grade.shape[0], j:j + grade.shape[1]] for i in range(3) for j in range(3)) / 9
    return MDE(float(xs[0]), float(ys[0]), passo, grade)


def curvas_de_nivel(mde: MDE, nivel: float) -> list[LineString]:
    """Curva de nível (marching squares) no nível pedido, em UTM."""
    z = mde.z
    segs = []
    ny, nx = z.shape
    for i in range(ny - 1):
        for j in range(nx - 1):
            c = [z[i, j], z[i, j + 1], z[i + 1, j + 1], z[i + 1, j]]
            acima = [v >= nivel for v in c]
            if all(acima) or not any(acima):
                continue
            cantos = [(j, i), (j + 1, i), (j + 1, i + 1), (j, i + 1)]
            pts = []
            for k in range(4):
                a, b = k, (k + 1) % 4
                if acima[a] != acima[b]:
                    t = (nivel - c[a]) / (c[b] - c[a])
                    (xa, ya), (xb, yb) = cantos[a], cantos[b]
                    pts.append((mde.x0 + (xa + t * (xb - xa)) * mde.passo, mde.y0 + (ya + t * (yb - ya)) * mde.passo))
            for k in range(0, len(pts) - 1, 2):
                segs.append(LineString([pts[k], pts[k + 1]]))
    if not segs:
        return []
    g = linemerge(MultiLineString(segs))
    return [g] if g.geom_type == "LineString" else list(g.geoms)


def curvas_intervalo(mde: MDE, area, intervalo: float | None = None) -> tuple[float, list[tuple[float, LineString]]]:
    """Curvas de nível dentro de `area`, com intervalo automático (1, 2 ou 5 m)."""
    zmin, zmax = float(mde.z.min()), float(mde.z.max())
    intervalo = intervalo or (1.0 if zmax - zmin < 25 else 2.0 if zmax - zmin < 60 else 5.0)
    out = []
    for nivel in np.arange(math.ceil(zmin / intervalo) * intervalo, zmax, intervalo):
        for ln in curvas_de_nivel(mde, float(nivel)):
            g = ln.simplify(1.5).intersection(area)
            for parte in ([g] if g.geom_type == "LineString" else list(getattr(g, "geoms", []))):
                if parte.geom_type == "LineString" and parte.length > 10:
                    out.append((float(nivel), parte))
    return intervalo, out


def areas_acima_declividade(mde: MDE, limite_pct: float, area):
    """Polígono das áreas com declividade >= limite (células da grade), recortado na área."""
    d = mde.declividade_pct()
    ii, jj = np.nonzero(d >= limite_pct)
    if not len(ii):
        return box(0, 0, 0, 0).buffer(0)
    h = mde.passo / 2
    celulas = [box(mde.x0 + j * mde.passo - h, mde.y0 + i * mde.passo - h, mde.x0 + j * mde.passo + h, mde.y0 + i * mde.passo + h)
               for i, j in zip(ii, jj)]
    return unary_union(celulas).buffer(mde.passo * 0.5).buffer(-mde.passo * 0.5).intersection(area)
