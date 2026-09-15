"""Atualiza um ou mais recortes da pesquisa de mercado (Carreira Muller) direto
dos xlsx originais da pesquisa — não do CSV consolidado manual
(`base_mercado_carreira_muller_consolidado.csv`), que só trazia o "Adequado".

Descoberta lendo os xlsx atualizados em 2026-09-15: o export original da
pesquisa TEM mínimo e máximo (bloco "Total Dinheiro" > Inicial/Final, colunas
18 e 22 — "Adequado" é a coluna 20), só não foram trazidos pro CSV consolidado
quando ele foi montado (só guardou `Total_Dinheiro_Adequado`). A linha 3 (0-based)
de cada planilha também traz quem/quando o relatório foi retirado do Carreira
Muller (formato "NOME DE QUEM RETIROU DD/MM/AAAA") — só a data é extraída
aqui como `data_retirada`, o nome não é lido nem gravado.

`openpyxl` não consegue abrir esses xlsx ("could not read stylesheet" — cor de
fonte inválida no XML gerado pela ferramenta de origem); usa o engine
`calamine` (python-calamine, já instalado, bem mais tolerante a XML malformado).

Atualiza SÓ os recortes listados em RECORTES (por Base_Pesquisa) — os demais
recortes em `interno.mercado_salarial_muller` continuam como estão (com
`salario_minimo`/`salario_maximo`/`data_retirada` NULL até serem atualizados
também). Não é truncate + reload da tabela inteira como o
`upload_faixas_salariais.py` original — é um DELETE + INSERT só das linhas do
recorte que está sendo atualizado.

Uso:
    python etl/atualizar_recorte_mercado.py
"""

from __future__ import annotations

import logging
import re
import sys
import tomllib
from datetime import date, datetime
from pathlib import Path

import pandas as pd
import psycopg2
from psycopg2.extras import execute_values

ROOT = Path(__file__).resolve().parent.parent
SECRETS_PATH = ROOT / ".streamlit" / "secrets.toml"
ASSETS_DIR = (
    ROOT.parent / ".Assets" / "Faixas Salariais Carreira Muller" / "Filtros Carreira"
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", stream=sys.stdout)
log = logging.getLogger("atualizar_recorte_mercado")

TABLE = "mercado_salarial_muller"

# (arquivo em ASSETS_DIR, Base_Pesquisa exata — já usada em interno.mercado_salarial_muller)
RECORTES: list[tuple[str, str]] = [
    ("20260915_grheciregiaograndesaopaulo.xlsx", "GRH ECI - Região Grande São Paulo"),
    ("20260915_industria da construção.xlsx", "Indústria da Construção"),
]

ALTER_SQL = f"""
ALTER TABLE interno.{TABLE}
    ADD COLUMN IF NOT EXISTS salario_minimo NUMERIC,
    ADD COLUMN IF NOT EXISTS salario_maximo NUMERIC,
    ADD COLUMN IF NOT EXISTS data_retirada DATE
"""


def _database_url() -> str:
    with SECRETS_PATH.open("rb") as f:
        secrets = tomllib.load(f)
    return secrets["neon"]["database_url"]


def _extract(xlsx_path: Path, base_pesquisa: str) -> tuple[pd.DataFrame, date | None]:
    """Lê 1 xlsx de recorte: linha 3 tem a data de retirada, linha 6 tem o
    cabeçalho, dado começa na linha 7 (todos 0-based) — layout confirmado
    programaticamente (linha 5 = grupo, linha 6 = subcoluna) nos 2 arquivos
    novos."""
    raw = pd.read_excel(xlsx_path, engine="calamine", header=None)
    data = raw.iloc[7:].rename(
        columns={0: "cargo_empresa", 1: "cargo_pesquisa", 18: "salario_minimo", 20: "salario_adequado", 22: "salario_maximo"}
    )[["cargo_empresa", "cargo_pesquisa", "salario_minimo", "salario_adequado", "salario_maximo"]].copy()
    data = data.dropna(subset=["cargo_empresa"])
    data["cargo_empresa"] = data["cargo_empresa"].astype(str).str.strip()
    data["cargo_pesquisa"] = data["cargo_pesquisa"].astype(str).str.strip()
    # célula sem comparação de mercado pro cargo vem como "-" (texto), não vazia
    for col in ("salario_minimo", "salario_adequado", "salario_maximo"):
        data[col] = pd.to_numeric(data[col], errors="coerce")

    # mesma checagem do upload_faixas_salariais.py original: cargo repete 1 linha
    # por pessoa, o valor de referência tem que ser igual em todas as linhas dele.
    divergencias = data.groupby("cargo_empresa")[["salario_minimo", "salario_adequado", "salario_maximo"]].nunique()
    divergentes = divergencias[(divergencias > 1).any(axis=1)]
    if len(divergentes):
        log.warning(
            "%d cargo(s) com valores divergentes entre linhas nesse recorte — mantendo a primeira ocorrência: %s",
            len(divergentes), list(divergentes.index)[:5],
        )
    data = data.drop_duplicates(subset=["cargo_empresa"], keep="first")
    data["base_pesquisa"] = base_pesquisa

    match = re.search(r"(\d{2}/\d{2}/\d{4})", str(raw.iloc[3, 0]))
    data_retirada = datetime.strptime(match.group(1), "%d/%m/%Y").date() if match else None
    return data, data_retirada


def main() -> int:
    connection = psycopg2.connect(_database_url())
    try:
        with connection.cursor() as cursor:
            cursor.execute(ALTER_SQL)
        connection.commit()

        for filename, base_pesquisa in RECORTES:
            xlsx_path = ASSETS_DIR / filename
            if not xlsx_path.exists():
                log.error("Não encontrei %s — pulando esse recorte.", xlsx_path)
                continue

            data, data_retirada = _extract(xlsx_path, base_pesquisa)
            log.info("%s: %d cargos, relatório retirado em %s", base_pesquisa, len(data), data_retirada)

            rows = [
                (
                    r.cargo_empresa, r.cargo_pesquisa, base_pesquisa,
                    None if pd.isna(r.salario_adequado) else float(r.salario_adequado),
                    None if pd.isna(r.salario_minimo) else float(r.salario_minimo),
                    None if pd.isna(r.salario_maximo) else float(r.salario_maximo),
                    data_retirada,
                )
                for r in data.itertuples(index=False)
            ]
            with connection.cursor() as cursor:
                cursor.execute(f"DELETE FROM interno.{TABLE} WHERE base_pesquisa = %s", (base_pesquisa,))
                execute_values(
                    cursor,
                    f"""INSERT INTO interno.{TABLE}
                        (cargo_empresa, cargo_pesquisa, base_pesquisa, salario_adequado, salario_minimo, salario_maximo, data_retirada)
                        VALUES %s""",
                    rows,
                    page_size=500,
                )
            connection.commit()
            log.info("%s: %d linhas gravadas em interno.%s", base_pesquisa, len(rows), TABLE)
    finally:
        connection.close()
    log.info("Recortes atualizados com sucesso")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
