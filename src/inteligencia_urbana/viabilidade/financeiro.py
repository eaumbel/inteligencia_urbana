"""Indicadores financeiros sobre fluxo de caixa mensal."""

from __future__ import annotations

from dataclasses import dataclass


def taxa_anual_para_mensal(taxa_anual_pct: float) -> float:
    return (1 + taxa_anual_pct / 100) ** (1 / 12) - 1


def vpl(fluxo: list[float], taxa_mensal: float) -> float:
    return sum(v / (1 + taxa_mensal) ** t for t, v in enumerate(fluxo))


def tir_mensal(fluxo: list[float]) -> float | None:
    """TIR mensal por bisseção (None se o fluxo não troca de sinal)."""
    if not (any(v < 0 for v in fluxo) and any(v > 0 for v in fluxo)):
        return None
    lo, hi = -0.99, 1.0
    f_lo = vpl(fluxo, lo)
    for _ in range(300):
        mid = (lo + hi) / 2
        f_mid = vpl(fluxo, mid)
        if abs(f_mid) < 1e-6:
            return mid
        if (f_lo < 0) == (f_mid < 0):
            lo, f_lo = mid, f_mid
        else:
            hi = mid
    return (lo + hi) / 2


def payback_mes(fluxo: list[float]) -> int | None:
    acum = 0.0
    negativo = False
    for t, v in enumerate(fluxo):
        acum += v
        negativo = negativo or acum < 0
        if negativo and acum >= 0:
            return t
    return None


@dataclass
class Indicadores:
    receita_total: float
    custo_total: float
    lucro: float
    margem_sobre_vgv_pct: float
    roi_pct: float
    vpl: float
    tir_mensal_pct: float | None
    tir_anual_pct: float | None
    payback_meses: int | None
    exposicao_maxima: float
    fluxo_mensal: list[float]
    fluxo_acumulado: list[float]


def indicadores(entradas: list[float], saidas: list[float], vgv: float, tma_anual_pct: float) -> Indicadores:
    fluxo = [e - s for e, s in zip(entradas, saidas)]
    receita = sum(entradas)
    custo = sum(saidas)
    lucro = receita - custo
    acum, s = [], 0.0
    for v in fluxo:
        s += v
        acum.append(round(s, 2))
    t = tir_mensal(fluxo)
    return Indicadores(
        receita_total=round(receita, 2),
        custo_total=round(custo, 2),
        lucro=round(lucro, 2),
        margem_sobre_vgv_pct=round(lucro / vgv * 100, 2) if vgv else 0.0,
        roi_pct=round(lucro / custo * 100, 2) if custo else 0.0,
        vpl=round(vpl(fluxo, taxa_anual_para_mensal(tma_anual_pct)), 2),
        tir_mensal_pct=round(t * 100, 3) if t is not None else None,
        tir_anual_pct=round(((1 + t) ** 12 - 1) * 100, 2) if t is not None else None,
        payback_meses=payback_mes(fluxo),
        exposicao_maxima=round(-min(acum + [0.0]), 2),
        fluxo_mensal=[round(v, 2) for v in fluxo],
        fluxo_acumulado=acum,
    )


def distribuir(total: float, inicio: int, meses: int, horizonte: int) -> list[float]:
    """Distribui um valor linearmente em `meses` a partir de `inicio`."""
    out = [0.0] * horizonte
    meses = max(meses, 1)
    for m in range(inicio, min(inicio + meses, horizonte)):
        out[m] += total / meses
    return out


def receber_vendas(vendas_mes: list[float], entrada_pct: float, parcelas: int, horizonte: int) -> list[float]:
    """Converte vendas mensais em recebimentos (entrada + parcelas mensais iguais, sem correção)."""
    out = [0.0] * horizonte
    for m, v in enumerate(vendas_mes):
        if not v:
            continue
        ent = v * entrada_pct / 100
        out[m] += ent
        saldo = v - ent
        n = max(parcelas, 1)
        for k in range(1, n + 1):
            if m + k < horizonte:
                out[m + k] += saldo / n
    return out
