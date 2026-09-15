"""Sobe a referência de mercado (Carreira Muller) pro Neon, schema `interno`.

Fonte: `etl/data/base_mercado_carreira_muller_consolidado.csv` — export manual
consolidado a partir dos 5 recortes de pesquisa de mercado em
`.Assets/Faixas Salariais Carreira Muller/Filtros Carreira/*.xlsx` (os xlsx
originais ficam como arquivos "somente na nuvem" no OneDrive e não são lidos
direto por este script; o CSV consolidado é o que existe hoje pronto pra uso).
Colunas do CSV: `Cargo_Empresa` (cargo interno, casa com `descricao_cargo` de
`interno.fato_funcionario_ativo`), `Cargo_Pesquisa` (cargo equivalente na
pesquisa), `Total_Dinheiro_Adequado` (valor de referência "adequado" — usado
como 100% na régua do painel), `Base_Pesquisa` (um dos 5 recortes de mercado).

Truncate + reload completo a cada execução — a base é pequena (~1200 linhas
depois de deduplicar) e não tem granularidade de pessoa, só cargo x recorte.

**Atenção (2026-09-15):** `etl/atualizar_recorte_mercado.py` lê alguns
recortes direto do xlsx original (via `calamine`, que abre esses arquivos
mesmo com o bug de stylesheet do openpyxl) e preenche `salario_minimo`,
`salario_maximo` e `data_retirada` — colunas que este script AINDA NÃO
preenche (só tem o Adequado no CSV consolidado). Rodar este script de novo
faz truncate da tabela inteira e **apaga** esses 3 campos pros recortes já
atualizados — depois de rodar, reexecute `atualizar_recorte_mercado.py` pros
recortes que já tinham essa informação, ou ela fica perdida até a próxima vez.

Uso:
    python etl/upload_faixas_salariais.py
    python etl/upload_faixas_salariais.py --input caminho/outro_export.csv
"""

from __future__ import annotations

import argparse
import logging
import sys
import tomllib
from pathlib import Path

import pandas as pd
import psycopg2
from psycopg2.extras import execute_values

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_INPUT = Path(__file__).resolve().parent / "data" / "base_mercado_carreira_muller_consolidado.csv"
SECRETS_PATH = ROOT / ".streamlit" / "secrets.toml"

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", stream=sys.stdout)
log = logging.getLogger("upload_faixas_salariais")

TABLE = "mercado_salarial_muller"

CREATE_TABLE_SQL = f"""
CREATE SCHEMA IF NOT EXISTS interno;
CREATE TABLE IF NOT EXISTS interno.{TABLE} (
    cargo_empresa TEXT NOT NULL,
    cargo_pesquisa TEXT,
    base_pesquisa TEXT NOT NULL,
    salario_adequado NUMERIC,
    salario_minimo NUMERIC,
    salario_maximo NUMERIC,
    data_retirada DATE,
    loaded_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (cargo_empresa, base_pesquisa)
)
"""


def _database_url() -> str:
    with SECRETS_PATH.open("rb") as f:
        secrets = tomllib.load(f)
    return secrets["neon"]["database_url"]


def load_reference(csv_path: Path) -> pd.DataFrame:
    """Lê o export consolidado e deduplica pra 1 linha por (cargo, recorte).

    O CSV original tem uma linha por combinação (pessoa x recorte) — o mesmo
    cargo se repete uma vez por colaborador que o ocupa. O valor de referência
    é sempre o mesmo para um mesmo (Cargo_Empresa, Base_Pesquisa) — conferido
    manualmente (0 combinações com valores divergentes) — então dedup é seguro.
    """
    data = pd.read_csv(csv_path, encoding="utf-8-sig")
    data["Cargo_Empresa"] = data["Cargo_Empresa"].str.strip()
    data["Cargo_Pesquisa"] = data["Cargo_Pesquisa"].str.strip()
    data["Base_Pesquisa"] = data["Base_Pesquisa"].str.strip()
    return data.drop_duplicates(subset=["Cargo_Empresa", "Base_Pesquisa"])[
        ["Cargo_Empresa", "Cargo_Pesquisa", "Base_Pesquisa", "Total_Dinheiro_Adequado"]
    ]


def upload(connection, data: pd.DataFrame) -> None:
    rows = [
        (row.Cargo_Empresa, row.Cargo_Pesquisa, row.Base_Pesquisa, None if pd.isna(row.Total_Dinheiro_Adequado) else float(row.Total_Dinheiro_Adequado))
        for row in data.itertuples(index=False)
    ]
    with connection.cursor() as cursor:
        cursor.execute(CREATE_TABLE_SQL)
        cursor.execute(f"TRUNCATE TABLE interno.{TABLE}")
        execute_values(
            cursor,
            f"INSERT INTO interno.{TABLE} (cargo_empresa, cargo_pesquisa, base_pesquisa, salario_adequado) VALUES %s",
            rows,
            page_size=500,
        )
    connection.commit()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT, help="CSV consolidado de referência de mercado")
    args = parser.parse_args()

    if not args.input.exists():
        log.error("Não encontrei %s. Exporte o consolidado do Carreira Muller e salve nesse caminho (ou use --input).", args.input)
        return 1

    data = load_reference(args.input)
    log.info("%d combinações (cargo x recorte) lidas de %s", len(data), args.input.name)
    log.info("%d combinações sem valor de mercado (cargo não coberto por aquele recorte)", data["Total_Dinheiro_Adequado"].isna().sum())

    connection = psycopg2.connect(_database_url())
    try:
        upload(connection, data)
    finally:
        connection.close()
    log.info("Referência de mercado gravada em interno.%s", TABLE)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
