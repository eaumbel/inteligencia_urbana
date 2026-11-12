"""Conversões de coordenadas e leitura de números/ângulos no padrão brasileiro.

Referência padrão: SIRGAS 2000 / UTM fuso 22S (EPSG:31982), que cobre Londrina,
Cambé, Rolândia e Ibiporã (meridiano central 51° W).
Matrículas antigas podem estar em SAD-69 (EPSG:29192) ou Córrego Alegre — sempre
confira o datum declarado no memorial descritivo.
"""

from __future__ import annotations

import re
from functools import lru_cache

from pyproj import Transformer

EPSG_SIRGAS2000_UTM22S = 31982
EPSG_SIRGAS2000_UTM23S = 31983
EPSG_SAD69_UTM22S = 29192
EPSG_SIRGAS2000_GEO = 4674
EPSG_WGS84 = 4326

DATUMS_CONHECIDOS = {
    "SIRGAS2000_UTM22S": EPSG_SIRGAS2000_UTM22S,
    "SIRGAS2000_UTM23S": EPSG_SIRGAS2000_UTM23S,
    "SAD69_UTM22S": EPSG_SAD69_UTM22S,
}

_NUM = r"\d[\d.]*(?:,\d+)?"

DMS_RE = re.compile(
    r"(?P<sinal>-)?\s*(?P<g>\d{1,3})\s*[°º]\s*(?P<m>\d{1,2})\s*['′’]\s*"
    r"(?P<s>\d{1,2}(?:[.,]\d+)?)\s*(?:\"|″|”|''|'’)?\s*(?P<h>[NSEWLO](?![a-zà-ú]))?",
)


def parse_numero_br(texto: str) -> float:
    """Converte número no formato brasileiro ("7.421.234,56") para float.

    Regras: havendo vírgula, ela é o separador decimal; sem vírgula, mais de um ponto
    indica milhar; um único ponto seguido de exatamente 3 dígitos (e parte inteira ≠ 0)
    é tratado como milhar ("482.345" → 482345).
    """
    s = texto.strip().replace(" ", "").rstrip(".,;")
    if not s:
        raise ValueError("número vazio")
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    elif s.count(".") > 1:
        s = s.replace(".", "")
    elif "." in s:
        inteiro, dec = s.split(".")
        if len(dec) == 3 and inteiro.lstrip("-") not in ("", "0"):
            s = inteiro + dec
    return float(s)


def dms_para_decimal(texto: str) -> float:
    """Converte ângulo em graus/minutos/segundos para graus decimais.

    Aceita "23°18'45,32\"S", "-51°09'12,345\"", "125°30'15\"".
    Hemisférios S, W e O (oeste) resultam em valor negativo.
    """
    m = DMS_RE.search(texto)
    if not m:
        raise ValueError(f"ângulo não reconhecido: {texto!r}")
    graus = int(m["g"]) + int(m["m"]) / 60 + parse_numero_br(m["s"]) / 3600
    negativo = bool(m["sinal"]) or (m["h"] or "").upper() in ("S", "W", "O")
    return -graus if negativo else graus


def decimal_para_dms(valor: float, eixo: str = "lat", casas: int = 3) -> str:
    """Formata graus decimais como DMS com hemisfério (eixo 'lat' ou 'lon')."""
    hem = ("N" if valor >= 0 else "S") if eixo == "lat" else ("E" if valor >= 0 else "W")
    v = abs(valor)
    g = int(v)
    m_total = (v - g) * 60
    m = int(m_total)
    s = round((m_total - m) * 60, casas)
    if s >= 60:
        s -= 60
        m += 1
    if m >= 60:
        m -= 60
        g += 1
    s_txt = f"{s:0{3 + casas}.{casas}f}".replace(".", ",")
    return f"{g}°{m:02d}'{s_txt}\"{hem}"


def rumo_para_azimute(texto: str) -> float:
    """Converte rumo ("45°30'00\" NE", "12°00'00\" SO") em azimute (0–360°)."""
    ang = abs(dms_para_decimal(texto))
    q = re.search(r"\b(N\s*E|S\s*E|S\s*[OW]|N\s*[OW])\b", texto.upper())
    if not q:
        raise ValueError(f"quadrante do rumo não encontrado: {texto!r}")
    quad = q.group(1).replace(" ", "").replace("O", "W")
    return {"NE": ang, "SE": 180 - ang, "SW": 180 + ang, "NW": 360 - ang}[quad] % 360


def fuso_utm(longitude: float) -> int:
    return int((longitude + 180) // 6) + 1


def epsg_sirgas_utm_sul(longitude: float) -> int:
    """EPSG SIRGAS 2000 / UTM hemisfério sul para a longitude informada."""
    return 31960 + fuso_utm(longitude)


@lru_cache(maxsize=32)
def _transformer(origem: int, destino: int) -> Transformer:
    return Transformer.from_crs(origem, destino, always_xy=True)


def utm_para_geo(e: float, n: float, epsg: int = EPSG_SIRGAS2000_UTM22S) -> tuple[float, float]:
    """UTM → (longitude, latitude) em WGS84 (usado pelo Google Earth)."""
    lon, lat = _transformer(epsg, EPSG_WGS84).transform(e, n)
    return lon, lat


def geo_para_utm(lon: float, lat: float, epsg: int | None = None, epsg_origem: int = EPSG_WGS84) -> tuple[float, float]:
    """(longitude, latitude) → (E, N) em UTM SIRGAS 2000 (fuso automático se epsg=None)."""
    epsg = epsg or epsg_sirgas_utm_sul(lon)
    return _transformer(epsg_origem, epsg).transform(lon, lat)


def coordenada_utm_valida(e: float, n: float) -> bool:
    return 100_000 <= e <= 900_000 and 1_000_000 <= n <= 10_000_000
