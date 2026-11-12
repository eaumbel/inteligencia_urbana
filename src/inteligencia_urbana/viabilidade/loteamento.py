"""Estudo de viabilidade de loteamento (horizontal)."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from pydantic import BaseModel, Field

from .financeiro import distribuir, indicadores, receber_vendas


class PremissasLoteamento(BaseModel):
    area_gleba_m2: float = Field(..., gt=0)
    area_app_m2: float = Field(0, ge=0, description="APP, fundos de vale, faixas não edificáveis")
    pct_sistema_viario: float = Field(20, ge=0, le=60)
    pct_institucional: float = Field(5, ge=0, le=30)
    pct_area_verde: float = Field(10, ge=0, le=40)
    area_media_lote_m2: float = Field(250, gt=0)
    preco_m2_lote: float = Field(..., gt=0, description="R$/m² de lote urbanizado")
    custo_terreno: float = Field(0, ge=0, description="Aquisição da gleba (R$). Use 0 em permuta")
    permuta_pct_lotes: float = Field(0, ge=0, le=80, description="% de lotes entregues ao proprietário em permuta física")
    custo_infra_m2_loteavel: float = Field(110, ge=0, description="Urbanização (terraplenagem, redes, pavimento) por m² de área loteável")
    custo_projetos_aprovacoes: float = Field(0, ge=0)
    pct_comissao: float = Field(5, ge=0, le=15)
    pct_marketing: float = Field(2, ge=0, le=10)
    pct_administracao: float = Field(3, ge=0, le=15)
    pct_impostos: float = Field(6.73, ge=0, le=20, description="Lucro presumido ≈ 6,73% sobre receita (PIS/COFINS/IRPJ/CSLL)")
    meses_aprovacao: int = Field(12, ge=0, le=60)
    meses_obra: int = Field(18, ge=1, le=60)
    meses_vendas: int = Field(24, ge=1, le=120)
    entrada_pct: float = Field(10, ge=0, le=100)
    parcelas: int = Field(120, ge=1, le=240, description="Parcelas mensais do saldo (1 = à vista)")
    tma_anual_pct: float = Field(15, ge=0, le=100)


@dataclass
class ResultadoLoteamento:
    quadro_areas: dict
    numero_lotes: int
    lotes_venda: int
    lotes_permuta: int
    vgv: float
    vgv_liquido_empreendedor: float
    custos: dict
    indicadores: dict
    alertas: list[str] = field(default_factory=list)


def estudar_loteamento(p: PremissasLoteamento) -> ResultadoLoteamento:
    alertas = []
    area_util = max(p.area_gleba_m2 - p.area_app_m2, 0)
    viario = area_util * p.pct_sistema_viario / 100
    inst = area_util * p.pct_institucional / 100
    verde = area_util * p.pct_area_verde / 100
    loteavel = max(area_util - viario - inst - verde, 0)
    n_lotes = int(loteavel // p.area_media_lote_m2)
    n_permuta = round(n_lotes * p.permuta_pct_lotes / 100)
    n_venda = n_lotes - n_permuta

    vgv = n_lotes * p.area_media_lote_m2 * p.preco_m2_lote
    vgv_emp = n_venda * p.area_media_lote_m2 * p.preco_m2_lote

    infra = loteavel * p.custo_infra_m2_loteavel
    comissao = vgv_emp * p.pct_comissao / 100
    marketing = vgv_emp * p.pct_marketing / 100
    adm = vgv_emp * p.pct_administracao / 100
    impostos = vgv_emp * p.pct_impostos / 100

    inicio_obra = p.meses_aprovacao
    inicio_vendas = p.meses_aprovacao  # lançamento após registro
    horizonte = inicio_vendas + p.meses_vendas + p.parcelas + 1
    horizonte = max(horizonte, inicio_obra + p.meses_obra + 1)

    saidas = [0.0] * horizonte
    saidas[0] += p.custo_terreno
    for i, v in enumerate(distribuir(p.custo_projetos_aprovacoes, 0, max(p.meses_aprovacao, 1), horizonte)):
        saidas[i] += v
    for i, v in enumerate(distribuir(infra, inicio_obra, p.meses_obra, horizonte)):
        saidas[i] += v
    for i, v in enumerate(distribuir(adm, 0, inicio_obra + p.meses_obra, horizonte)):
        saidas[i] += v
    for i, v in enumerate(distribuir(marketing, max(inicio_vendas - 2, 0), p.meses_vendas, horizonte)):
        saidas[i] += v

    vendas = distribuir(vgv_emp, inicio_vendas, p.meses_vendas, horizonte)
    receb = receber_vendas(vendas, p.entrada_pct, p.parcelas, horizonte)
    for i, v in enumerate(vendas):
        saidas[i] += v * p.pct_comissao / 100  # comissão paga na venda
    for i, v in enumerate(receb):
        saidas[i] += v * p.pct_impostos / 100  # impostos sobre recebimento (regime de caixa)

    ind = indicadores(receb, saidas, vgv_emp, p.tma_anual_pct)

    if p.area_media_lote_m2 < 125:
        alertas.append("Lote médio abaixo de 125 m² (mínimo da Lei 6.766/79, salvo interesse social).")
    if p.pct_sistema_viario + p.pct_institucional + p.pct_area_verde < 30:
        alertas.append("Áreas públicas somam menos de 30% — confira os percentuais exigidos na diretriz municipal.")
    if ind.margem_sobre_vgv_pct < 20:
        alertas.append(f"Margem sobre VGV de {ind.margem_sobre_vgv_pct:.1f}% — abaixo da referência usual de 25–35% para loteamentos.")
    if p.parcelas > 1:
        alertas.append("Parcelas sem correção monetária/juros no fluxo — cenário conservador para o recebível.")

    return ResultadoLoteamento(
        quadro_areas={
            "gleba_m2": round(p.area_gleba_m2, 2),
            "app_e_restricoes_m2": round(p.area_app_m2, 2),
            "area_util_m2": round(area_util, 2),
            "sistema_viario_m2": round(viario, 2),
            "institucional_m2": round(inst, 2),
            "area_verde_m2": round(verde, 2),
            "area_loteavel_m2": round(loteavel, 2),
            "aproveitamento_pct": round(loteavel / p.area_gleba_m2 * 100, 2),
        },
        numero_lotes=n_lotes,
        lotes_venda=n_venda,
        lotes_permuta=n_permuta,
        vgv=round(vgv, 2),
        vgv_liquido_empreendedor=round(vgv_emp, 2),
        custos={
            "terreno": round(p.custo_terreno, 2),
            "projetos_aprovacoes": round(p.custo_projetos_aprovacoes, 2),
            "infraestrutura": round(infra, 2),
            "comissao": round(comissao, 2),
            "marketing": round(marketing, 2),
            "administracao": round(adm, 2),
            "impostos": round(impostos, 2),
            "custo_por_lote": round((infra + p.custo_terreno + p.custo_projetos_aprovacoes) / n_lotes, 2) if n_lotes else None,
        },
        indicadores=asdict(ind),
        alertas=alertas,
    )
