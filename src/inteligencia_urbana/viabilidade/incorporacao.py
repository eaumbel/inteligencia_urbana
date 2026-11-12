"""Estudo de viabilidade de incorporação (vertical ou horizontal) com base no CUB.

O CUB/m² (NBR 12.721) é publicado mensalmente pelo Sinduscon-PR (Norte do Paraná
tem tabela própria — confirme a praça). O valor deve ser informado pelo usuário;
o app não fixa CUB no código para não ficar desatualizado.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from pydantic import BaseModel, Field

from .financeiro import distribuir, indicadores, receber_vendas


class PremissasIncorporacao(BaseModel):
    area_terreno_m2: float = Field(..., gt=0)
    coeficiente_aproveitamento: float = Field(..., gt=0, description="CA aplicável (básico ou máximo com outorga)")
    outorga_onerosa: float = Field(0, ge=0, description="Custo de outorga onerosa (R$), se usar CA acima do básico")
    fator_area_nao_computavel: float = Field(0.45, ge=0, le=2, description="Garagens, áreas comuns etc. sobre a área computável")
    eficiencia_privativa: float = Field(0.80, gt=0, le=1, description="Área privativa / área computável")
    area_media_unidade_m2: float = Field(70, gt=0)
    cub_m2: float = Field(..., gt=0, description="CUB vigente (R$/m²) — padrão do projeto, ex. R8-N")
    fator_custo_sobre_cub: float = Field(1.30, ge=1, le=2.5, description="Itens fora do CUB: fundações, elevadores, BDI etc.")
    preco_m2_privativo: float = Field(..., gt=0)
    custo_terreno: float = Field(0, ge=0)
    permuta_pct_unidades: float = Field(0, ge=0, le=60)
    custo_projetos_aprovacoes_pct_obra: float = Field(4, ge=0, le=15)
    pct_comissao: float = Field(5, ge=0, le=10)
    pct_marketing: float = Field(2.5, ge=0, le=10)
    pct_administracao: float = Field(3, ge=0, le=15)
    pct_impostos: float = Field(4, ge=0, le=20, description="RET com patrimônio de afetação = 4% (1% HIS elegível)")
    meses_pre_obra: int = Field(6, ge=0, le=36)
    meses_obra: int = Field(30, ge=1, le=72)
    vendas_pct_lancamento: float = Field(30, ge=0, le=100, description="% das unidades vendidas no lançamento")
    meses_vendas: int = Field(30, ge=1, le=120)
    pct_pago_ate_chaves: float = Field(30, ge=0, le=100, description="Recebido durante a obra; saldo no repasse/chaves")
    tma_anual_pct: float = Field(15, ge=0, le=100)


@dataclass
class ResultadoIncorporacao:
    quadro_areas: dict
    unidades: int
    unidades_venda: int
    unidades_permuta: int
    vgv: float
    vgv_liquido_empreendedor: float
    custos: dict
    indicadores: dict
    alertas: list[str] = field(default_factory=list)


def estudar_incorporacao(p: PremissasIncorporacao) -> ResultadoIncorporacao:
    alertas = []
    computavel = p.area_terreno_m2 * p.coeficiente_aproveitamento
    construida = computavel * (1 + p.fator_area_nao_computavel)
    privativa = computavel * p.eficiencia_privativa
    unidades = int(privativa // p.area_media_unidade_m2)
    u_perm = round(unidades * p.permuta_pct_unidades / 100)
    u_venda = unidades - u_perm
    area_venda = u_venda * p.area_media_unidade_m2

    vgv = unidades * p.area_media_unidade_m2 * p.preco_m2_privativo
    vgv_emp = area_venda * p.preco_m2_privativo

    obra = construida * p.cub_m2 * p.fator_custo_sobre_cub
    projetos = obra * p.custo_projetos_aprovacoes_pct_obra / 100
    comissao = vgv_emp * p.pct_comissao / 100
    marketing = vgv_emp * p.pct_marketing / 100
    adm = vgv_emp * p.pct_administracao / 100
    impostos = vgv_emp * p.pct_impostos / 100

    ini_obra = p.meses_pre_obra
    fim_obra = ini_obra + p.meses_obra
    horizonte = max(fim_obra, ini_obra + p.meses_vendas) + 2

    saidas = [0.0] * horizonte
    saidas[0] += p.custo_terreno + p.outorga_onerosa
    for serie in (
        distribuir(projetos, 0, max(p.meses_pre_obra, 1), horizonte),
        distribuir(obra, ini_obra, p.meses_obra, horizonte),
        distribuir(adm, 0, fim_obra + 1, horizonte),
        distribuir(marketing, max(ini_obra - 2, 0), min(p.meses_vendas, p.meses_obra), horizonte),
    ):
        for i, v in enumerate(serie):
            saidas[i] += v

    vendas = [0.0] * horizonte
    vendas[ini_obra] += vgv_emp * p.vendas_pct_lancamento / 100
    for i, v in enumerate(distribuir(vgv_emp * (1 - p.vendas_pct_lancamento / 100), ini_obra + 1, p.meses_vendas, horizonte)):
        vendas[i] += v

    receb = [0.0] * horizonte
    for m, v in enumerate(vendas):
        if not v:
            continue
        durante = v * p.pct_pago_ate_chaves / 100
        if m < fim_obra:
            meses_rest = fim_obra - m
            for i, x in enumerate(receber_vendas([0.0] * m + [durante], 0, meses_rest, horizonte)):
                receb[i] += x
            receb[min(fim_obra, horizonte - 1)] += v - durante  # repasse/financiamento nas chaves
        else:
            receb[m] += v
    for i in range(horizonte):
        saidas[i] += vendas[i] * p.pct_comissao / 100 + receb[i] * p.pct_impostos / 100

    ind = indicadores(receb, saidas, vgv_emp, p.tma_anual_pct)

    custo_m2_priv = (obra + p.custo_terreno) / privativa if privativa else 0
    if ind.margem_sobre_vgv_pct < 15:
        alertas.append(f"Margem sobre VGV de {ind.margem_sobre_vgv_pct:.1f}% — abaixo da referência usual de 15–25% para incorporação.")
    if p.custo_terreno and p.custo_terreno / vgv > 0.2:
        alertas.append("Terreno acima de 20% do VGV — avaliar permuta ou renegociação.")
    if p.pct_impostos == 4:
        alertas.append("Impostos pelo RET (4%) pressupõem patrimônio de afetação averbado na matrícula.")

    return ResultadoIncorporacao(
        quadro_areas={
            "terreno_m2": round(p.area_terreno_m2, 2),
            "area_computavel_m2": round(computavel, 2),
            "area_construida_total_m2": round(construida, 2),
            "area_privativa_m2": round(privativa, 2),
            "area_privativa_venda_m2": round(area_venda, 2),
        },
        unidades=unidades,
        unidades_venda=u_venda,
        unidades_permuta=u_perm,
        vgv=round(vgv, 2),
        vgv_liquido_empreendedor=round(vgv_emp, 2),
        custos={
            "terreno": round(p.custo_terreno, 2),
            "outorga_onerosa": round(p.outorga_onerosa, 2),
            "obra": round(obra, 2),
            "obra_por_m2_construido": round(obra / construida, 2) if construida else None,
            "projetos_aprovacoes": round(projetos, 2),
            "comissao": round(comissao, 2),
            "marketing": round(marketing, 2),
            "administracao": round(adm, 2),
            "impostos": round(impostos, 2),
            "custo_por_m2_privativo": round(custo_m2_priv, 2),
        },
        indicadores=asdict(ind),
        alertas=alertas,
    )
