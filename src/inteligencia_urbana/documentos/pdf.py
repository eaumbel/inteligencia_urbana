"""Extração de texto de PDFs (matrículas, certidões, consultas prévias)."""

from __future__ import annotations

import io


def extrair_texto_pdf(conteudo: bytes) -> str:
    """Extrai o texto de um PDF com camada de texto.

    PDFs escaneados (imagem) retornam texto vazio — nesses casos é preciso OCR
    (ver docs/ROADMAP.md, item OCR com Tesseract).
    """
    import pdfplumber

    paginas = []
    with pdfplumber.open(io.BytesIO(conteudo)) as pdf:
        for p in pdf.pages:
            paginas.append(p.extract_text() or "")
    return "\n".join(paginas)


def normalizar_texto(texto: str) -> str:
    """Une hifenizações de quebra de linha e normaliza espaços."""
    import re

    t = texto.replace("\r", "")
    t = re.sub(r"(\w)-\n(\w)", r"\1\2", t)
    t = re.sub(r"[ \t]+", " ", t)
    return t
