"""Forma do terreno a partir da metragem da matrícula (sem coordenadas).

Gera os cantos em metros num sistema local, para a interface posicionar pelo endereço:
- "rua": x ao longo da frente (0 → frente), y para dentro do lote; a interface gira
  a forma para alinhar a frente com a rua.
- "fixa": x = Leste, y = Norte (azimutes do memorial); só falta transladar.

Casos:
1. Azimutes e distâncias → forma exata, orientação fixa.
2. Frente / fundos / laterais → quadrilátero com a lateral esquerda perpendicular à
   frente; a lateral direita é ajustada para fechar com os fundos informados.
3. Só a área → quadrado de mesma área (forma real desconhecida).
"""

from __future__ import annotations

import math


def _canto_direito(F: float, L: float, R: float, B: float) -> tuple[float, float] | None:
    """Ponto P com |P-(F,0)| = R e |P-(0,L)| = B, do lado de dentro (y > 0)."""
    x0, y0, r0 = F, 0.0, R
    x1, y1, r1 = 0.0, L, B
    d = math.hypot(x1 - x0, y1 - y0)
    if d == 0 or d > r0 + r1 or d < abs(r0 - r1):
        return None
    a = (r0**2 - r1**2 + d**2) / (2 * d)
    h = math.sqrt(max(r0**2 - a**2, 0))
    xm, ym = x0 + a * (x1 - x0) / d, y0 + a * (y1 - y0) / d
    candidatos = [(xm + h * (y1 - y0) / d, ym - h * (x1 - x0) / d), (xm - h * (y1 - y0) / d, ym + h * (x1 - x0) / d)]
    candidatos = [c for c in candidatos if c[1] > 0]
    # prefere o mais próximo do retângulo (x ≈ F)
    return min(candidatos, key=lambda c: abs(c[0] - F)) if candidatos else None


def _area(pts):
    return abs(sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(pts, pts[1:] + pts[:1]))) / 2


def dimensoes(medidas: list[dict]) -> dict:
    """Frente, fundos, lateral esquerda e direita a partir das medidas lineares lidas."""
    d: dict[str, float] = {}
    laterais = []
    for m in medidas:
        v, lado = m.get("medida_m"), (m.get("lado") or "").lower()
        if not v:
            continue
        if "frente aos fundos" in lado or "profundidade" in lado:
            d.setdefault("esquerda", v); d.setdefault("direita", v)
        elif "frente" in lado:
            d.setdefault("frente", v)
        elif "fundo" in lado:
            d.setdefault("fundos", v)
        elif "direit" in lado:
            d.setdefault("direita", v)
        elif "esquerd" in lado:
            d.setdefault("esquerda", v)
        elif "lado" in lado or "lateral" in lado or "divisa" in lado:
            laterais.append(v)
    for v in laterais:  # "de um lado" / "do outro lado" / "laterais"
        if "direita" not in d:
            d["direita"] = v
        elif "esquerda" not in d:
            d["esquerda"] = v
    if "direita" in d and "esquerda" not in d and len(laterais) <= 1:
        d["esquerda"] = d["direita"]  # "laterais de 30 m"
    if "esquerda" in d and "direita" not in d:
        d["direita"] = d["esquerda"]
    return d


def forma_do_terreno(medidas: list[dict], area_declarada: float | None = None,
                     lances: list[tuple[float, float]] | None = None) -> dict | None:
    avisos: list[str] = []
    if lances and len(lances) >= 3:
        x = y = 0.0
        pts = [(0.0, 0.0)]
        for az, dist in lances[:-1]:
            x += dist * math.sin(math.radians(az)); y += dist * math.cos(math.radians(az))
            pts.append((x, y))
        return {"pontos_m": [list(map(lambda v: round(v, 3), p)) for p in pts], "orientacao": "fixa", "fonte": "azimutes e distâncias da matrícula",
                "area_m2": round(_area(pts), 2), "avisos": ["Forma exata pelo memorial; a posição vem do endereço e deve ser conferida."]}

    d = dimensoes(medidas)
    F = d.get("frente")
    L, R, B = d.get("esquerda"), d.get("direita"), d.get("fundos")
    if F and (L or R):
        L = L or R; R = R or L
        pts = [(0.0, 0.0), (F, 0.0)]
        P = _canto_direito(F, L, R, B) if B else None
        if P:
            pts += [P, (0.0, L)]
        else:
            pts += [(F, R), (0.0, L)]
            if B and abs(math.dist((F, R), (0, L)) - B) > max(0.1, 0.02 * B):
                avisos.append(f"Os fundos informados ({B:.2f} m) não fecham com frente e laterais; usado lote retangular.")
        fonte = "frente, laterais e fundos da matrícula"
    elif area_declarada and area_declarada > 0:
        lado = math.sqrt(area_declarada)
        if F:
            lado_y = area_declarada / F
            pts = [(0.0, 0.0), (F, 0.0), (F, lado_y), (0.0, lado_y)]
            fonte = "frente e área da matrícula (profundidade calculada)"
        else:
            pts = [(0.0, 0.0), (lado, 0.0), (lado, lado), (0.0, lado)]
            fonte = "área da matrícula (quadrado de mesma área)"
            avisos.append("A matrícula não informa as medidas dos lados: o contorno é um quadrado de mesma área, só para referência. "
                          "Ajuste girando, movendo ou redesenhe sobre o satélite.")
    else:
        return None

    area = _area(pts)
    if area_declarada and abs(area - area_declarada) / area_declarada > 0.02:
        avisos.append(f"Área da forma montada ({area:,.2f} m²) difere da área da matrícula ({area_declarada:,.2f} m²)."
                      .replace(",", "X").replace(".", ",").replace("X", "."))
    return {"pontos_m": [[round(x, 3), round(y, 3)] for x, y in pts], "orientacao": "rua", "fonte": fonte,
            "area_m2": round(area, 2), "dimensoes": d, "avisos": avisos}
