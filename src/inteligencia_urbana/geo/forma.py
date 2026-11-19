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
4. Rumos por direção ("S - N - 100,00 metros", "W - E") com um trecho em curva de comprimento conhecido
   ("curva de 100,26 metros"): forma exata; o lado para onde a curva se volta é o que reproduz a área declarada.
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


def _raio_do_arco(s: float, c: float) -> float | None:
    """Raio R tal que um arco de comprimento s tenha corda c (2R·sen(s/2R) = c). None se s ≤ c (reta)."""
    if s <= c * 1.0000001 or c <= 0:
        return None
    lo, hi = s / (2 * math.pi) + 1e-9, 1e9  # arco menor que uma volta
    lo = max(lo, s / math.pi * 0.5)  # θ ≤ 2π
    for _ in range(200):
        m = (lo + hi) / 2
        if 2 * m * math.sin(s / (2 * m)) > c:
            hi = m
        else:
            lo = m
    return (lo + hi) / 2


def _br(v: float, casas: int = 2) -> str:
    return f"{v:,.{casas}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _pontos_do_arco(a, b, R: float, lado: int, n: int = 48) -> list[tuple[float, float]]:
    """Pontos internos do arco menor de A até B, com raio R, abaulado para o lado (+1 esquerda / -1 direita de A→B)."""
    (ax, ay), (bx, by) = a, b
    c = math.dist(a, b)
    mx, my = (ax + bx) / 2, (ay + by) / 2
    nx, ny = -(by - ay) / c, (bx - ax) / c  # normal à esquerda de A→B
    dc = math.sqrt(max(R * R - (c / 2) ** 2, 0))
    cx, cy = mx - lado * nx * dc, my - lado * ny * dc  # centro do lado oposto ao abaulamento
    ta, tb = math.atan2(ay - cy, ax - cx), math.atan2(by - cy, bx - cx)
    dt = (tb - ta + math.pi) % (2 * math.pi) - math.pi  # arco menor
    return [(cx + R * math.cos(ta + dt * k / n), cy + R * math.sin(ta + dt * k / n)) for k in range(1, n)]


def forma_por_rumos_com_curva(itens: list[dict], area_declarada: float | None = None) -> dict | None:
    """itens na ordem do memorial: {"tipo": "reta", "az": graus, "d": m} ou {"tipo": "curva", "s": m, "raio": m|None}.

    Exatamente um trecho em curva: os trechos retos antes dela partem da origem e os de depois chegam de volta à
    origem; a curva liga as duas pontas. Sem raio informado, o raio sai do comprimento da curva e da corda, e o lado
    para onde ela se volta é escolhido pela área declarada (quando houver).
    """
    curvas = [i for i, it in enumerate(itens) if it["tipo"] == "curva"]
    if len(curvas) != 1 or len(itens) < 3:
        return None
    k = curvas[0]
    vet = lambda it: (it["d"] * math.sin(math.radians(it["az"])), it["d"] * math.cos(math.radians(it["az"])))
    antes = [(0.0, 0.0)]
    for it in itens[:k]:
        dx, dy = vet(it); antes.append((antes[-1][0] + dx, antes[-1][1] + dy))
    depois = [(0.0, 0.0)]  # caminha de trás para a frente a partir da origem
    for it in reversed(itens[k + 1:]):
        dx, dy = vet(it); depois.append((depois[-1][0] - dx, depois[-1][1] - dy))
    depois = list(reversed(depois))  # depois[0] = fim da curva, depois[-1] = origem
    A, B = antes[-1], depois[0]
    c, s = math.dist(A, B), itens[k]["s"]
    avisos, perimetro = [], sum(it.get("d") or it.get("s") for it in itens)
    R = itens[k].get("raio") or _raio_do_arco(s, c)
    if R and R < c / 2:
        R = None
    candidatos = []
    if R:
        for lado in (1, -1):
            pts = antes + _pontos_do_arco(A, B, R, lado) + depois[:-1]
            candidatos.append((lado, pts, _area(pts)))
    reta = antes + depois[:-1]
    if not candidatos:
        avisos.append(f"O trecho em curva ({_br(s)} m) não é maior que a distância reta entre suas pontas ({_br(c)} m): "
                      "a curva foi desenhada como reta.")
        pts, area, lado_txt = reta, _area(reta), None
    elif area_declarada:
        lado, pts, area = min(candidatos, key=lambda x: abs(x[2] - area_declarada))
        outro = [x for x in candidatos if x[0] != lado][0]
        lado_txt = "para dentro" if area < _area(reta) else "para fora"
        avisos.append(f"A matrícula não diz para que lado a curva se volta nem o raio. Raio calculado de {_br(R, 1)} m pelo comprimento "
                      f"da curva ({_br(s)} m) e pela distância entre suas pontas ({_br(c)} m); a curva foi desenhada {lado_txt} do terreno, "
                      f"o lado que reproduz a área da matrícula (o outro lado daria {_br(outro[2])} m²).")
    else:
        pts, area, lado_txt = reta, _area(reta), None
        avisos.append("Sem área declarada para decidir o lado da curva: o trecho em curva foi desenhado como reta.")
    if area_declarada and abs(area - area_declarada) / area_declarada > 0.02:
        avisos.append(f"Área da forma montada ({_br(area)} m²) difere da área da matrícula ({_br(area_declarada)} m²).")
    avisos.append("Os rumos estão só como direção (S–N, W–E etc.), sem graus: a forma considera ângulos exatos entre os lados.")
    return {"pontos_m": [[round(x, 3), round(y, 3)] for x, y in pts], "orientacao": "fixa",
            "fonte": "rumos e distâncias da matrícula, com trecho em curva", "area_m2": round(area, 2),
            "perimetro_m": round(perimetro, 2), "curva": {"comprimento_m": s, "corda_m": round(c, 3), "raio_m": round(R, 1) if R else None,
                                                         "lado": lado_txt},
            "avisos": avisos}
