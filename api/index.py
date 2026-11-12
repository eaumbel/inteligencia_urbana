"""Ponto de entrada da Vercel (função Python serverless).

A Vercel procura um objeto ASGI chamado `app`. O pacote fica em src/,
então ele é colocado no caminho de importação antes de importar a API.
"""

import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "src"))

from inteligencia_urbana.api.main import app  # noqa: E402

__all__ = ["app"]
