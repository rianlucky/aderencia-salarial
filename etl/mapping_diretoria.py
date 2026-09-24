"""Resolução de diretoria/área — lida do Neon (`core.mapeamento_diretoria`
e `core.mapeamento_diretoria_especial`), não mais de JSON local.

Decisão do usuário em 2026-09-18: o painel de Aderência Salarial quebrou no
deploy porque o mapeamento vivia só num JSON gitignored — sem esse arquivo no
clone do Streamlit Cloud, a resolução de diretoria falhava antes até da tela
de login aparecer. Subir pro Neon (`etl/upload_mapeamento_diretoria.py`)
remove essa dependência de arquivo: mesmo banco em qualquer ambiente.

Fallback em cascata se o Neon não responder: tenta os JSONs locais em
`etl/data/` (cópias antigas, se existirem) e, sem isso, cai num dict vazio —
nunca derruba o app, só mostra "Não informado" pra Diretoria/Área.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent / "data"

NAO_INFORMADO = "Não informado"


def _database_url() -> str | None:
    try:
        import streamlit as st

        return st.secrets["neon"]["database_url"]
    except Exception:
        return os.getenv("NEON_DATABASE_URL")


def _load_from_neon() -> tuple[dict, dict] | None:
    database_url = _database_url()
    if not database_url:
        return None
    try:
        import psycopg2
        import psycopg2.extras

        with psycopg2.connect(database_url) as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT centro_de_custo, diretoria, area FROM core.mapeamento_diretoria")
            cc_mapping = {r["centro_de_custo"]: {"diretoria": r["diretoria"], "area": r["area"]} for r in cur.fetchall()}

            cur.execute("SELECT centro_de_custo, tipo, chave, diretoria, area FROM core.mapeamento_diretoria_especial")
            special_mappings: dict = {}
            for r in cur.fetchall():
                bloco = special_mappings.setdefault(r["centro_de_custo"], {"by_position": {}, "by_person": {}})
                bloco[r["tipo"]][r["chave"]] = {"diretoria": r["diretoria"], "area": r["area"]}
        return cc_mapping, special_mappings
    except Exception as exc:  # noqa: BLE001
        print(f"[mapping_diretoria] Falha lendo o Neon, tentando fallback local: {exc}")
        return None


def _load_from_local_json() -> tuple[dict, dict]:
    def _read(filename: str) -> dict:
        path = ROOT / filename
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        return {}

    return _read("cc_mapping.json"), _read("special_mappings.json")


_loaded = _load_from_neon()
if _loaded is None:
    _loaded = _load_from_local_json()
    if not _loaded[0]:
        print("[mapping_diretoria] Sem Neon e sem JSON local — diretoria/área ficam 'Não informado' até um dos dois existir.")
CC_MAPPING, SPECIAL_MAPPINGS = _loaded


def resolve_diretoria_area(cc: str | None, descricao_posicao: str | None, id_funcionario) -> tuple[str, str]:
    """Resolve diretoria/área de uma pessoa: SPECIAL_MAPPINGS (por pessoa, depois por
    cargo) tem prioridade sobre o default do CC_MAPPING. Sem entrada em nenhum dos
    dois, cai em NAO_INFORMADO (nunca quebra por CC novo/desconhecido)."""
    special = SPECIAL_MAPPINGS.get(cc) if cc is not None else None
    if special:
        by_person = special.get("by_person", {}).get(str(id_funcionario))
        if by_person:
            return by_person["diretoria"], by_person["area"]
        position = (descricao_posicao or "").rsplit(" - ", 1)[0].strip()
        by_position = special.get("by_position", {}).get(position)
        if by_position:
            return by_position["diretoria"], by_position["area"]
    default = CC_MAPPING.get(cc) if cc is not None else None
    if isinstance(default, dict):
        return default["diretoria"], default["area"]
    return NAO_INFORMADO, NAO_INFORMADO
