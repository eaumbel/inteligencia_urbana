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
    return analisar_consulta_parcelamento(await _texto(arquivo, texto)).to_dict()


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

@app.get("/", include_in_schema=False)
def index():
    return FileResponse(WEB / "index.html")
