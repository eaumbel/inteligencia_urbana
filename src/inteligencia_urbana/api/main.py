"""API HTTP (FastAPI) da Inteligência Urbana.

Executar:  uvicorn inteligencia_urbana.api.main:app --reload
Documentação interativa: http://localhost:8000/docs
"""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

from ..documentos.consulta_ippul import analisar_consulta_parcelamento
from ..documentos.matricula import analisar_matricula
from ..documentos.pdf import extrair_texto_pdf, normalizar_texto
from ..geo import camadas_oficiais as co
from ..geo.kml import features_para_kml, kml_para_kmz, perimetro_para_kml
from ..legislacao import federal
from ..legislacao.zoneamento import analisar_vocacao, carregar_cidade, cidades_disponiveis, parametros_zona
from ..masterplan.gerador import ParametrosMasterplan, gerar_masterplan
from ..viabilidade.incorporacao import PremissasIncorporacao, estudar_incorporacao
from ..viabilidade.loteamento import PremissasLoteamento, estudar_loteamento

WEB = Path(__file__).resolve().parents[3] / "web"

app = FastAPI(
    title="Inteligência Urbana",
    description="Matrícula, diretrizes de parcelamento, zoneamento, viabilidade e masterplan.",
    version="0.1.0",
)

PREFIXO = "/incorporacao"


@app.middleware("http")
async def remover_prefixo(request, call_next):
    """Permite servir o app em eaumbel.com.br/incorporacao/ sem mudar as rotas.

    /incorporacao (sem barra) redireciona para /incorporacao/, para que os caminhos
    relativos da interface (api/...) fiquem dentro da subpasta.
    """
    from fastapi.responses import RedirectResponse

    caminho = request.scope["path"]
    if caminho == PREFIXO:
        return RedirectResponse(PREFIXO + "/", status_code=308)
    if caminho.startswith(PREFIXO + "/"):
        request.scope["path"] = caminho[len(PREFIXO):]
    return await call_next(request)


async def _texto(arquivo: UploadFile | None, texto: str | None) -> str:
    if arquivo is not None and arquivo.filename:
        dados = await arquivo.read()
        if arquivo.filename.lower().endswith(".pdf"):
            t = extrair_texto_pdf(dados)
            if not t.strip():
                raise HTTPException(422, "PDF sem camada de texto (escaneado). Será necessário OCR — cole o texto por enquanto.")
            return normalizar_texto(t)
        return normalizar_texto(dados.decode("utf-8", errors="replace"))
    if texto:
        return normalizar_texto(texto)
    raise HTTPException(400, "Envie um arquivo (PDF/TXT) ou o texto.")


# ------------------------------------------------------------------ documentos

@app.post("/api/matricula/analisar", tags=["Documentos"])
async def api_matricula(arquivo: UploadFile | None = File(None), texto: str | None = Form(None), epsg: int | None = Form(None)):
    return analisar_matricula(await _texto(arquivo, texto), epsg).to_dict()


@app.post("/api/diretrizes/analisar", tags=["Documentos"])
async def api_diretrizes(arquivo: UploadFile | None = File(None), texto: str | None = Form(None)):
    """Texto (lido no navegador ou extraído aqui) + croqui vetorial do PDF, quando houver."""
    dados = await arquivo.read() if arquivo is not None and arquivo.filename else None
    if texto:
        conteudo = normalizar_texto(texto)
    elif dados is not None:
        await arquivo.seek(0)
        conteudo = await _texto(arquivo, None)
    else:
        raise HTTPException(400, "Envie um arquivo (PDF/TXT) ou o texto.")
    d = analisar_consulta_parcelamento(conteudo)
    area = d.caracterizacao.get("area_total_m2")
    if dados and area and (arquivo.filename or "").lower().endswith(".pdf"):
        from ..documentos.croqui import extrair_croqui_pdf

        try:
            d.croqui = extrair_croqui_pdf(dados, area)
        except Exception as e:  # PDF sem croqui vetorial: segue sem ele
            d.alertas.append(f"Não foi possível ler o croqui do PDF ({type(e).__name__}).")
    if dados and area and not d.croqui:
        d.alertas.append("Croqui vetorial do lote não encontrado no PDF: contorne a área manualmente no mapa.")
    return d.to_dict()


# ------------------------------------------------------------------ analisador de matrícula

class PaginaEntrada(BaseModel):
    numero: int = Field(..., ge=1)
    texto: str = ""
    metodo: str = Field("texto", pattern="^(texto|ocr)$")
    confianca: float | None = Field(None, ge=0, le=100)


class PedidoAnalisador(BaseModel):
    arquivo: str | None = None
    paginas: list[PaginaEntrada] = Field(..., min_length=1, max_length=500)


@app.post("/api/analisador/extrair", tags=["Analisador de matrícula"])
def api_analisador_extrair(p: PedidoAnalisador):
    """Fases 2–3: identificação, atos R-/AV- com página, data e trecho original, sequência e legibilidade.
    O texto é lido no navegador (PDF ou OCR); nenhum arquivo é armazenado no servidor."""
    from ..analisador.extracao import Pagina, extrair

    from ..analisador.regras import analisar

    ext = extrair([Pagina(x.numero, x.texto, x.metodo, x.confianca) for x in p.paginas])
    return {**ext.to_dict(), "analise": analisar(ext).to_dict()}


@app.post("/api/analisador/relatorio", tags=["Analisador de matrícula"])
def api_analisador_relatorio(p: PedidoAnalisador):
    """Relatório em PDF, em linguagem simples, com referências a ato e página."""
    import re as _re

    from ..analisador.extracao import Pagina, extrair
    from ..analisador.regras import analisar
    from ..analisador.relatorio import gerar_pdf

    ext = extrair([Pagina(x.numero, x.texto, x.metodo, x.confianca) for x in p.paginas])
    pdf = gerar_pdf(ext, analisar(ext), p.arquivo)
    num = _re.sub(r"\D", "", ext.identificacao["numero_matricula"].valor or "") or "sem-numero"
    return Response(pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="relatorio-matricula-{num}.pdf"'})


# ------------------------------------------------------------------ geo / Google Earth

class PedidoKML(BaseModel):
    nome: str = "Imóvel"
    epsg: int = 31982
    vertices: list[dict] = Field(..., min_length=3)
    segmentos: list[dict] | None = None
    info: dict | None = None
    kmz: bool = False


@app.post("/api/geo/kml", tags=["Google Earth"])
def api_kml(p: PedidoKML):
    kml = perimetro_para_kml(p.vertices, p.segmentos, p.nome, p.epsg, p.info)
    return _download_kml(kml, p.nome, p.kmz)


class PedidoPoligono(BaseModel):
    coords_lonlat: list[tuple[float, float]] = Field(..., min_length=3, description="Vértices em (longitude, latitude)")
    area_referencia_m2: float | None = Field(None, description="Área da matrícula para comparar")


@app.post("/api/geo/poligono", tags=["Google Earth"])
def api_poligono(p: PedidoPoligono):
    """Converte um contorno desenhado no mapa em vértices UTM, lados, área e perímetro."""
    from ..geo.coordenadas import epsg_sirgas_utm_sul, geo_para_utm
    from ..geo.poligono import Perimetro, Vertice, segmentos_de_vertices

    epsg = epsg_sirgas_utm_sul(p.coords_lonlat[0][0])
    vertices = []
    for i, (lon, lat) in enumerate(p.coords_lonlat, start=1):
        e, n = geo_para_utm(lon, lat, epsg)
        vertices.append(Vertice(f"P{i}", round(e, 3), round(n, 3)))
    per = Perimetro(vertices, segmentos_de_vertices(vertices), epsg)
    if not per.poligono().is_valid:
        raise HTTPException(422, "O contorno se cruza. Desenhe os cantos em sequência, contornando o terreno.")
    area = per.area_m2
    dif = (area - p.area_referencia_m2) / p.area_referencia_m2 * 100 if p.area_referencia_m2 else None
    return {
        "epsg": epsg,
        "vertices": [asdict(v) for v in vertices],
        "segmentos": [asdict(s) for s in per.segmentos],
        "area_m2": round(area, 2),
        "perimetro_m": round(per.perimetro_m, 2),
        "diferenca_pct": round(dif, 2) if dif is not None else None,
        "geojson": per.geojson(),
    }


class PedidoFeaturesKML(BaseModel):
    nome: str = "Masterplan"
    features: list[dict]
    kmz: bool = False


@app.post("/api/geo/kml-features", tags=["Google Earth"])
def api_kml_features(p: PedidoFeaturesKML):
    return _download_kml(features_para_kml(p.features, p.nome), p.nome, p.kmz)


def _download_kml(kml: str, nome: str, kmz: bool) -> Response:
    import unicodedata

    ascii_ = unicodedata.normalize("NFKD", nome).encode("ascii", "ignore").decode()
    arq = "".join(c if c.isalnum() else "_" for c in ascii_)[:60] or "imovel"
    if kmz:
        return Response(kml_para_kmz(kml), media_type="application/vnd.google-earth.kmz",
                        headers={"Content-Disposition": f'attachment; filename="{arq}.kmz"'})
    return Response(kml, media_type="application/vnd.google-earth.kml+xml",
                    headers={"Content-Disposition": f'attachment; filename="{arq}.kml"'})


# ------------------------------------------------------------------ camadas oficiais

@app.get("/api/camadas", tags=["Camadas oficiais"])
def api_camadas():
    return {"wms": co.CAMADAS_WMS}


# Proxy só para serviços fixos (nunca uma URL vinda do cliente)
PROXIES = {"car-wms": co.CAR_WMS, "car-wfs": co.CAR_WFS}


@app.get("/api/proxy/{servico}", tags=["Camadas oficiais"])
def api_proxy(servico: str, request: Request):
    url = PROXIES.get(servico)
    if not url:
        raise HTTPException(404, "Serviço não disponível no proxy")
    try:
        corpo, tipo = co.baixar(url, dict(request.query_params))
    except Exception as e:
        raise HTTPException(502, f"SICAR não respondeu: {e}")
    return Response(corpo, media_type=tipo, headers={"Cache-Control": "public, max-age=86400"})


class PedidoPerimetro(BaseModel):
    vertices_utm: list[tuple[float, float]] = Field(..., min_length=3)
    epsg: int = 31982
    raio_m: float = Field(300, ge=0, le=5000)
    feicoes: list[dict] | None = Field(None, description="Feições GeoJSON (lon/lat) já obtidas do WFS pelo navegador")


@app.post("/api/camadas/car-sobreposicao", tags=["Camadas oficiais"])
def api_car(p: PedidoPerimetro):
    try:
        return co.cruzar_car(p.vertices_utm, p.epsg, feicoes=p.feicoes)
    except Exception as e:
        raise HTTPException(502, f"SICAR não respondeu: {e}")


@app.post("/api/camadas/drenagem", tags=["Camadas oficiais"])
def api_drenagem(p: PedidoPerimetro):
    try:
        return co.drenagem_proxima(p.vertices_utm, p.epsg, p.raio_m, feicoes=p.feicoes)
    except Exception as e:
        raise HTTPException(502, f"IBGE não respondeu: {e}")


# ------------------------------------------------------------------ legislação

@app.get("/api/zoneamento", tags=["Legislação"])
def api_cidades():
    return {"cidades": cidades_disponiveis()}


@app.get("/api/zoneamento/{cidade}", tags=["Legislação"])
def api_cidade(cidade: str):
    try:
        return carregar_cidade(cidade)
    except KeyError as e:
        raise HTTPException(404, str(e))


class PedidoVocacao(BaseModel):
    cidade: str
    zona: str
    area_terreno_m2: float = Field(..., gt=0)
    area_app_m2: float = 0


@app.post("/api/vocacao", tags=["Legislação"])
def api_vocacao(p: PedidoVocacao):
    try:
        z = parametros_zona(p.cidade, p.zona)
    except KeyError as e:
        raise HTTPException(404, str(e))
    return {"zona": z, "vocacao": asdict(analisar_vocacao(p.area_terreno_m2, z, p.area_app_m2))}


class PedidoReurb(BaseModel):
    baixa_renda_predominante: bool
    nucleo_consolidado_ate_2016: bool
    area_publica: bool = False
    em_app: bool = False
    em_area_de_risco: bool = False


@app.post("/api/reurb/classificar", tags=["Legislação"])
def api_reurb(p: PedidoReurb):
    return asdict(federal.classificar_reurb(**p.model_dump()))


@app.get("/api/legislacao/federal", tags=["Legislação"])
def api_federal():
    return {
        "lote_minimo_m2": federal.LOTE_MINIMO_FEDERAL_M2,
        "testada_minima_m": federal.TESTADA_MINIMA_FEDERAL_M,
        "faixa_nao_edificavel_rodovia_m": federal.FAIXA_NAO_EDIFICAVEL_RODOVIA_M,
        "declividade_maxima_sem_exigencias_pct": federal.DECLIVIDADE_MAXIMA_SEM_EXIGENCIAS_PCT,
        "app_nascente_raio_m": federal.APP_NASCENTE_RAIO_M,
        "app_cursos_dagua": [{"leito_ate_m": l, "faixa_m": federal.app_curso_dagua(l - 0.01)} for l in (10, 50, 200, 600)],
        "checklist_loteamento": federal.CHECKLIST_LOTEAMENTO,
        "checklist_incorporacao": federal.CHECKLIST_INCORPORACAO,
    }


# ------------------------------------------------------------------ viabilidade e masterplan

@app.post("/api/viabilidade/loteamento", tags=["Viabilidade"])
def api_loteamento(p: PremissasLoteamento):
    return asdict(estudar_loteamento(p))


@app.post("/api/viabilidade/incorporacao", tags=["Viabilidade"])
def api_incorporacao(p: PremissasIncorporacao):
    return asdict(estudar_incorporacao(p))


@app.post("/api/masterplan", tags=["Masterplan"])
def api_masterplan(p: ParametrosMasterplan):
    return asdict(gerar_masterplan(p))


# ------------------------------------------------------------------ interface web

from fastapi.staticfiles import StaticFiles  # noqa: E402

app.mount("/assets", StaticFiles(directory=WEB / "assets"), name="assets")


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(WEB / "index.html")
