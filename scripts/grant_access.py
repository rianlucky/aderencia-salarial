"""Concede (ou remove) acesso à mesma tabela `app_users` usada por todos os
apps do usuário no Neon "Central de Gente & Dados".

Até 2026-09-15 este painel usava uma tabela própria (`posicionamento_app_users`),
separada de `app_users`, porque expõe salário pessoa a pessoa e o acesso
precisava ser concedido de forma independente do Headcount. Decisão do
usuário nessa data: unificar em `app_users` — mesma senha em todos os
dashboards — com segregação de acesso por painel prevista pra depois (ainda
não implementada). Enquanto isso, conceder acesso aqui concede acesso a
TODOS os apps que leem `app_users`, não só a este painel.

Não cadastra senha nenhuma — a própria pessoa cria a senha dela no primeiro
login (ver auth.py). Roda direto contra o mesmo Neon, lendo
`.streamlit/secrets.toml` — não precisa do Streamlit rodando.

Uso:
    python scripts/grant_access.py
"""

from __future__ import annotations

import sys
import tomllib
from pathlib import Path

import psycopg2

SECRETS_PATH = Path(__file__).resolve().parent.parent / ".streamlit" / "secrets.toml"

USERS_TABLE = "app_users"

CREATE_TABLE_SQL = f"""
CREATE TABLE IF NOT EXISTS {USERS_TABLE} (
    email TEXT PRIMARY KEY,
    name TEXT,
    password_hash TEXT,
    failed_attempts INTEGER NOT NULL DEFAULT 0,
    locked_until TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
)
"""

GRANT_SQL = f"""
INSERT INTO {USERS_TABLE} (email, name)
VALUES (%s, %s)
ON CONFLICT (email) DO UPDATE SET name = EXCLUDED.name, updated_at = now()
"""

REVOKE_SQL = f"DELETE FROM {USERS_TABLE} WHERE email = %s"


ETL_ENV_PATH = Path(__file__).resolve().parents[1] / "etl" / ".env"


def _database_url() -> str:
    """Escrita = usuário de carga `etl_loader`, lido de etl/.env (migrações 003/004).
    O .streamlit/secrets.toml agora tem o usuário do painel, que só lê — por isso
    este script não usa mais o secrets.toml. Aceita também a variável de ambiente."""
    import os
    url = os.getenv("NEON_DATABASE_URL")
    if not url and ETL_ENV_PATH.exists():
        for line in ETL_ENV_PATH.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("NEON_DATABASE_URL="):
                url = line.split("=", 1)[1].strip().strip('"').strip("'")
    if not url:
        raise SystemExit(f"NEON_DATABASE_URL (usuário etl_loader) não encontrada em {ETL_ENV_PATH}")
    return url


def grant(conn, email: str, name: str) -> None:
    with conn.cursor() as cur:
        # etl_loader não tem CREATE em public; a tabela já existe (migrações).
        cur.execute("SELECT to_regclass('public.app_users')")
        if cur.fetchone()[0] is None:
            cur.execute(CREATE_TABLE_SQL)
        cur.execute(GRANT_SQL, (email.strip().lower(), name.strip()))
    conn.commit()


def revoke(conn, email: str) -> None:
    with conn.cursor() as cur:
        cur.execute(REVOKE_SQL, (email.strip().lower(),))
    conn.commit()


def main() -> None:
    conn = psycopg2.connect(_database_url())
    print("Conceder acesso a app_users (todos os dashboards, sem segregação por painel ainda) — deixe o e-mail em branco e aperte Enter para parar.")
    print("(a pessoa define a própria senha no primeiro login; não se cadastra senha aqui)\n")
    try:
        while True:
            entry = input("E-mail (ou 'remover:email@empresa.com' para tirar o acesso): ").strip()
            if not entry:
                break
            if entry.lower().startswith("remover:"):
                alvo = entry.split(":", 1)[1].strip()
                revoke(conn, alvo)
                print(f"-> acesso de {alvo.lower()} removido.\n")
                continue
            name = input("Nome de exibição: ").strip()
            grant(conn, entry, name)
            print(f"-> acesso concedido para {entry.strip().lower()}.\n")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
