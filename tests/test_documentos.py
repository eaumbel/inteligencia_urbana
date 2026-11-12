from pathlib import Path

import pytest

from inteligencia_urbana.documentos.consulta_ippul import analisar_consulta_parcelamento
from inteligencia_urbana.documentos.matricula import analisar_matricula

EX = Path(__file__).parent / "exemplos"


def test_matricula_gleba_georreferenciada():
    r = analisar_matricula((EX / "matricula_gleba.txt").read_text(encoding="utf-8"))
    assert r.numero == "45.678"
    assert r.tipo_imovel == "rural"
    assert r.area_declarada_m2 == pytest.approx(4.84 * 24_200)
    assert [v.nome for v in r.vertices] == ["PFE-M-0001", "PFE-M-0002", "PFE-M-0003", "PFE-M-0004"]
    assert r.area_calculada_m2 == pytest.approx(120_000)
    assert r.segmentos[2].confrontante == "Córrego Água Fria"
    hipoteca = next(a for a in r.atos if a.numero == 2)
    penhora = next(a for a in r.atos if a.numero == 5)
    assert hipoteca.situacao == "possivelmente cancelado"
    assert penhora.situacao.startswith("ativo")
    assert any("penhora" in a for a in r.alertas)


def test_matricula_por_azimutes_sem_coordenadas():
    txt = (
        "MATRÍCULA 1.234. Lote 7 da Quadra 3, área de 500,00 m². Partindo do ponto P1, segue com azimute de "
        "90°00'00\" e distância de 20,00 m confrontando com a Rua das Flores; segue com azimute de 180°00'00\" e "
        "distância de 25,00 m confrontando com o lote 8; segue com azimute de 270°00'00\" e distância de 20,00 m "
        "confrontando com o lote 12; segue com azimute de 0°00'00\" e distância de 25,00 m confrontando com o lote 6."
    )
    r = analisar_matricula(txt)
    assert r.tipo_imovel == "urbano" and r.lote == "7" and r.quadra == "3"
    assert r.area_calculada_m2 == pytest.approx(500)
    assert r.fechamento["aceitavel"]
    assert r.segmentos[0].confrontante == "Rua das Flores"


def test_matricula_lat_long():
    txt = (
        "MATRÍCULA Nº 999. vértice V1, Latitude 23°18'00,000\"S e Longitude 51°10'00,000\"W; vértice V2, "
        "Latitude 23°18'00,000\"S e Longitude 51°09'50,000\"W; vértice V3, Latitude 23°18'10,000\"S e "
        "Longitude 51°09'50,000\"W."
    )
    r = analisar_matricula(txt)
    assert len(r.vertices) == 3
    assert r.area_calculada_m2 > 0
    assert r.to_dict()["geojson"]["geometry"]["type"] == "Polygon"


def test_diretrizes():
    txt = (
        "CONSULTA PRÉVIA Nº 123/2026. Imóvel inserido na ZR3 e parcialmente na ZEIS. Lote mínimo de 250,00 m² e "
        "testada mínima de 10,00 m. Deverão ser destinados 5% para área institucional e 10% para área verde. "
        "Respeitar a diretriz viária da via arterial com caixa de via de 30,00 m. Faixa de preservação do fundo de vale "
        "de 30,00 m ao longo do córrego. Licença Prévia junto ao IAT."
    )
    d = analisar_consulta_parcelamento(txt)
    assert "ZR3" in d.zonas and "ZEIS" in d.zonas
    assert d.lote_minimo_m2 == 250 and d.testada_minima_m == 10
    assert d.percentuais_areas == {"institucional": 5, "verde": 10}
    assert 30 in d.larguras_vias_m
    assert {"ambiental", "licenciamento", "sistema_viario"} <= set(d.trechos_por_tema)


def test_matricula_apartamento_escaneada_ocr():
    """Formato comum em Londrina (ficha datilografada + registro contínuo), lido por OCR."""
    r = analisar_matricula((EX / "matricula_apartamento_ocr.txt").read_text(encoding="utf-8"))
    assert r.texto_ocr
    assert r.numero == "99.001" and r.tipo_imovel == "urbano"
    assert r.comarca == "LONDRINA"
    assert (r.lote, r.quadra, r.loteamento) == ("4", "12", "JARDIM EXEMPLO")  # "Data de terras" = lote
    assert r.endereco == "Rua das Acácias nº 250"
    assert r.area_declarada_m2 == pytest.approx(98.5)
    u = r.unidade_autonoma
    assert u["edificio"] == "RESIDENCIAL FICTÍCIO" and u["unidade"] == "Apartamento 101"
    assert u["area_privativa_m2"] == pytest.approx(61.2) and u["fracao_ideal_terreno_m2"] == pytest.approx(20.1)
    assert u["participacao_condominio_pct"] == pytest.approx(2.5) and u["area_terreno_condominio_m2"] == pytest.approx(800)
    assert u["vagas"] == ["7"]
    # atos de outras matrículas (registro anterior) não entram; "REGISTRO n.º 1" vira R-1
    assert [(a.tipo, a.numero) for a in r.atos] == [("R", 1), ("AV", 2), ("AV", 3), ("R", 4)]
    assert next(a for a in r.atos if a.numero == 2).situacao == "possivelmente cancelado"
    assert {m.lado for m in r.medidas} == {"Leste", "Sul", "Oeste", "Norte"}
    assert next(m for m in r.medidas if m.lado == "Oeste").confrontacao == "o apartamento 102"
    t = {x["ato"]: x for x in r.transmissoes}
    assert t["R-1"]["adquirentes"] == ["MARIA FICTÍCIA EXEMPLO"] and t["R-1"]["valor"] == 150000
    assert t["R-4"]["fracao_pct"] == 50 and t["R-4"]["adquirentes"] == ["JOÃO FICTÍCIO EXEMPLO"]
    assert r.ultimo_ato_certificado == 4 and r.datum is None
    assert not any("SAD-69" in a for a in r.alertas)


def test_ocr_numero_com_travessao_e_area_com_hifen_solto():
    txt = (EX / "matricula_apartamento_ocr.txt").read_text(encoding="utf-8")
    txt = txt.replace("= MATRÍCULA Nº. 99.001.", "= MATRÍCULANº — 99.001.-").replace("área bruta E", "área bruta -")
    r = analisar_matricula(txt)
    assert r.numero == "99.001" and r.area_declarada_m2 == pytest.approx(98.5)
    # cabeçalho ilegível: o número vem dos próprios atos
    r2 = analisar_matricula(txt.replace("MATRÍCULANº — 99.001.-", "MATRÍCULA ilegível"))
    assert r2.numero == "99.001" and len(r2.atos) == 4


def test_forma_pela_metragem():
    lote = analisar_matricula(
        "MATRÍCULA Nº 5.000. Data de terras nº 7 da quadra 3, com a área de 450,00 m², medindo 15,00 metros de frente "
        "para a Rua das Flores; 30,00 metros de um lado, confrontando com a data 6; 30,00 metros do outro lado, "
        "confrontando com a data 8; e 15,00 metros nos fundos, confrontando com a data 12."
    )
    assert [(m.lado, m.medida_m) for m in lote.medidas] == [("frente", 15), ("um lado", 30), ("outro lado", 30), ("fundos", 15)]
    assert lote.forma["pontos_m"] == [[0, 0], [15, 0], [15, 30], [0, 30]] and lote.forma["orientacao"] == "rua"

    irregular = analisar_matricula(
        "MATRÍCULA 6.000. Lote 3 da quadra 9 com a área de 360,00 m², medindo 12,00 m de frente, 12,50 m nos fundos, "
        "30,00 m do lado direito e 29,00 m do lado esquerdo."
    ).forma
    assert irregular["area_m2"] == pytest.approx(360, rel=0.01) and not irregular["avisos"]

    prof = analisar_matricula("MATRÍCULA 7.000. Data 4 da quadra 2, área de 500,00 m², medindo 12,50 m de frente por 40,00 m da frente aos fundos.").forma
    assert prof["pontos_m"][2] == [12.5, 40]

    so_area = analisar_matricula((EX / "matricula_apartamento_ocr.txt").read_text(encoding="utf-8")).forma
    assert so_area["area_m2"] == pytest.approx(800) and "quadrado" in so_area["fonte"]

    com_coordenadas = analisar_matricula((EX / "matricula_gleba.txt").read_text(encoding="utf-8"))
    assert com_coordenadas.forma is None  # já tem vértices georreferenciados


def test_consulta_ippul_modelo_2026():
    d = analisar_consulta_parcelamento((EX / "consulta_ippul_ficticia.txt").read_text(encoding="utf-8"))
    assert d.numero_consulta == "099/2026" and d.processo_sei == "84.000000/2026-00"
    c = d.caracterizacao
    assert (c["lote"], c["gleba"], c["area_total_m2"], c["lote_origem"]) == ("12-A", "Ribeirão Exemplo", 35000, "12")
    assert c["modalidade"] == "Loteamento Aberto, Condomínio Urbanístico" and c["finalidade"] == "Residencial"
    assert d.zonas == ["ZR-3", "ZI-2"]  # "ZONA" não é zona
    assert [(v["via"], v["hierarquia"], v["largura_total_m"]) for v in d.vias] == [("VIA 01", "Coletora", 20), ("VIA 02", "Local", 15)]
    p = d.parametros
    assert (p["faixa_transicao_m"], p["quadra_max_m"], p["areas_publicas_min_pct"], p["declividade_max_pct"], p["validade_dias"]) == (100, 250, 12, 30, 180)
    assert "Secretaria Municipal do Ambiente - SEMA" in d.orgaos_consultar
    assert any("faixa de transição de 100 m" in a for a in d.alertas)


def test_croqui_vetorial_escala_pela_area():
    from inteligencia_urbana.documentos.croqui import montar_croqui

    cinza, laranja, azul = (0.8588, 0.8588, 0.8588), (1.0, 0.498, 0.0), (0.0, 0.498, 1.0)
    formas = [
        {"pts": [(100, 100), (200, 100), (200, 120), (100, 120), (100, 100)], "fill": cinza, "stroke": None},  # lote 100 x 20 pt
        {"pts": [(300, 600), (320, 600), (320, 608), (300, 608)], "fill": cinza, "stroke": None},  # amostra da legenda
        {"pts": [(100, 130), (200, 130)], "fill": None, "stroke": laranja},  # via 10 pt ao sul do lote
        {"pts": [(150, 50), (150, 200)], "fill": None, "stroke": azul},  # córrego norte-sul
        {"pts": [(10, 10), (10.5, 10)], "fill": None, "stroke": azul},  # traço miúdo (descartado)
    ]
    c = montar_croqui(formas, area_total_m2=8000, rotulo_lote=(150, 110), limite_y=550)  # 2000 pt² → 2 m/pt
    assert c["escala_m_por_pt"] == pytest.approx(2)
    assert c["lote_m"] == [[-100, 20], [100, 20], [100, -20], [-100, -20]]  # norte para cima
    tipos = [(f["tipo"], f["pts"]) for f in c["feicoes"]]
    assert ("via_coletora", [[-100, -40], [100, -40]]) in tipos
    assert ("hidrografia", [[0, 120], [0, -180]]) in tipos
    assert len(c["feicoes"]) == 2
