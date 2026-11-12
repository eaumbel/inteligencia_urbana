"""Parâmetros de zoneamento por município e análise de vocação da área.

Os parâmetros ficam em arquivos YAML em `dados/zoneamento/<cidade>.yaml`, para que
sejam mantidos por técnicos sem mexer no código. Cada zona tem o campo `validado`:
enquanto for `false`, o app sinaliza que o valor é ilustrativo e deve ser
conferido com a lei municipal vigente e o mapa oficial de zoneamento.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml

PASTA = Path(__file__).resolve().parent.parent / "dados" / "zoneamento"


def _slug(nome: str) -> str:
    s = unicodedata.normalize("NFKD", nome).encode("ascii", "ignore").decode().lower()
    return s.strip().replace(" ", "_")


@lru_cache(maxsize=None)
def carregar_cidade(cidade: str) -> dict:
    caminho = PASTA / f"{_slug(cidade)}.yaml"
    if not caminho.exists():
        raise KeyError(f"Município sem base de zoneamento: {cidade}. Disponíveis: {', '.join(cidades_disponiveis())}")
    with caminho.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def cidades_disponiveis() -> list[str]:
    return sorted(p.stem for p in PASTA.glob("*.yaml"))


def parametros_zona(cidade: str, zona: str) -> dict:
    dados = carregar_cidade(cidade)
    zonas = dados.get("zonas", {})
    chave = zona.upper().replace(" ", "").replace("-", "")
    for k, v in zonas.items():
        if k.upper().replace("-", "") == chave:
            return {"codigo": k, **v}
    raise KeyError(f"Zona {zona} não cadastrada para {cidade}. Cadastradas: {', '.join(zonas)}")


@dataclass
class Vocacao:
    produtos: list[dict] = field(default_factory=list)  # [{"produto", "aderencia", "motivo"}]
    potencial_construtivo_m2: float | None = None
    projecao_maxima_m2: float | None = None
    observacoes: list[str] = field(default_factory=list)


def analisar_vocacao(area_terreno_m2: float, zona: dict, area_app_m2: float = 0.0) -> Vocacao:
    """Sugere produtos imobiliários aderentes ao zoneamento e ao porte da área."""
    v = Vocacao()
    util = max(area_terreno_m2 - area_app_m2, 0)
    ca = zona.get("ca_maximo") or zona.get("ca_basico")
    to = zona.get("taxa_ocupacao")
    if ca:
        v.potencial_construtivo_m2 = round(util * ca, 2)
    if to:
        v.projecao_maxima_m2 = round(util * to, 2)

    cat = (zona.get("categoria") or "").lower()
    gab = zona.get("gabarito_pavimentos") or 0
    lote_min = zona.get("lote_minimo_m2") or 0
    usos = " ".join(zona.get("usos_permitidos", [])).lower()

    def add(prod: str, ader: str, motivo: str) -> None:
        v.produtos.append({"produto": prod, "aderencia": ader, "motivo": motivo})

    gleba = area_terreno_m2 >= 20_000
    if "industrial" in cat or "logist" in usos:
        add("Loteamento industrial / condomínio logístico" if gleba else "Galpão logístico/industrial", "alta",
            "Zona industrial/logística")
    if "zeis" in cat or "interesse social" in cat:
        add("Loteamento de interesse social / MCMV", "alta", "ZEIS — admite parâmetros especiais")
    if "residencial" in cat or "misto" in cat:
        if gleba:
            add("Loteamento aberto residencial", "alta" if lote_min and lote_min <= 360 else "média",
                f"Gleba de {area_terreno_m2 / 10_000:.2f} ha em zona residencial; lote mínimo {lote_min or '—'} m²")
            add("Condomínio de lotes (Lei 13.465/2017, art. 1.358-A do CC)", "média", "Alternativa ao loteamento aberto, com controle de acesso")
        if ca and ca >= 2 and (gab == 0 or gab >= 4):
            add("Incorporação vertical residencial", "alta" if ca >= 3 else "média", f"CA {ca} permite verticalização")
        elif not gleba:
            add("Condomínio horizontal (casas) / sobrados", "média", f"CA {ca or '—'} e gabarito {gab or '—'} favorecem baixa densidade")
    if "comercial" in cat or "misto" in cat or "servi" in cat or "corredor" in cat:
        add("Uso misto (comércio no térreo + residencial)" if ca and ca >= 2 else "Centro comercial / strip mall", "média",
            "Zona com usos comerciais/serviços")
    if not v.produtos:
        add("Avaliar caso a caso", "baixa", "Categoria de zona sem regra de vocação cadastrada")
    if not zona.get("validado", False):
        v.observacoes.append("Parâmetros da zona marcados como NÃO VALIDADOS — confirme com a lei municipal antes de decidir.")
    if area_app_m2:
        v.observacoes.append(f"Descontados {area_app_m2:,.2f} m² de APP/faixas não edificáveis.")
    return v
