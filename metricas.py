"""Cálculo dos indicadores do painel Aderência Salarial — sem Streamlit, para testar e validar.

Entradas (Neon): core_view.funcionario_ativo (quadro ativo na data da base, regra única da
Central) e mercado.mercado_salarial_muller (referência Carreira Muller por cargo e base de pesquisa).

Regras:
  - Fora do painel: Diretor, Presidente e Conselheiro (níveis de topo, pouco comparáveis na pesquisa).
  - Cargo interno casado com a pesquisa pelo nome (descricao_cargo = cargo_empresa). Com uma lista de
    bases ("Personalizado"), cada cargo usa a PRIMEIRA base da lista que tem referência para ele.
  - Compa-ratio (mercado) = salário ÷ salário adequado da pesquisa. Faixa ideal: 80% a 120%.
  - Mínimo/máximo de mercado: os da pesquisa; sem eles, 80% e 120% do adequado.
  - Penetração na faixa = (salário − mínimo) ÷ (máximo − mínimo): 0% no mínimo, 100% no máximo.
  - Custo de enquadramento = quanto falta para levar ao alvo (80% ou 100% do adequado) quem está
    abaixo dele; anual = mensal × 13,33 (12 salários + 13º + 1/3 de férias), sem encargos.
  - Compressão: no mesmo cargo, mediana de quem entrou nos últimos 12 meses x de quem tem mais tempo.
"""
from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

NAO_INFORMADO = "Não informado"
PISO_IDEAL, TETO_IDEAL = 80, 120
FUNCOES_EXCLUIDAS = ["Diretor", "Presidente", "Conselheiro"]
FATOR_ANUAL = 13 + 1 / 3
NIVEL_GERENCIAMENTO = {"Gerente de Vendas": "Gerente", "Gerente Executivo de Obras": "Gerente Executivo",
                       "Gerente Executivo Estadual de Obras": "Gerente Executivo", "Coordenador de Obras": "Coordenador/Especialista",
                       "Diretor de Obras": "Diretor"}
FAIXAS_TEMPO = [(365, "Até 1 ano"), (730, "1 a 2 anos"), (1095, "2 a 3 anos"), (1826, "3 a 5 anos"), (3652, "5 a 10 anos")]
ORDEM_TEMPO = ["Até 1 ano", "1 a 2 anos", "2 a 3 anos", "3 a 5 anos", "5 a 10 anos", "+ 10 anos"]


def _faixa_tempo(dias) -> str:
    if dias is None or pd.isna(dias):
        return NAO_INFORMADO
    for limite, nome in FAIXAS_TEMPO:
        if dias < limite:
            return nome
    return "+ 10 anos"


def classificar(pct):
    return np.select([pct < PISO_IDEAL, pct > TETO_IDEAL], ["Abaixo", "Acima"], default="Dentro")


def preparar_pessoas(p: pd.DataFrame, ref: date) -> pd.DataFrame:
    p = p[~p["funcao_cargo"].isin(FUNCOES_EXCLUIDAS)].copy()
    for c in ("diretoria", "area", "categoria_atribuicao", "funcao_cargo"):
        p[c] = p[c].fillna(NAO_INFORMADO)
    p["nivel"] = p["gerenciamento_nivel_cargo"].replace(NIVEL_GERENCIAMENTO).fillna(NAO_INFORMADO)
    p["descricao_cargo"] = p["descricao_cargo"].str.strip()
    p["data_admissao"] = pd.to_datetime(p["data_admissao"]).dt.date
    p["tempo_casa_dias"] = [(ref - d).days if pd.notna(d) else None for d in p["data_admissao"]]
    p["faixa_tempo"] = p["tempo_casa_dias"].map(_faixa_tempo)
    cc = p["centro_de_custo"].astype(str)
    nome = p["nome_centro_custo"].fillna("").str.strip()
    p["cc_texto"] = np.where(nome != "", cc + " · " + nome, cc)
    return p


def referencia(mercado: pd.DataFrame, bases: str | list[str]) -> pd.DataFrame:
    """Uma linha por cargo: a referência da primeira base da lista (em ordem de prioridade) que tem o cargo."""
    bases = [bases] if isinstance(bases, str) else list(bases)
    ref = mercado[mercado["base_pesquisa"].isin(bases) & (mercado["salario_adequado"] > 0)].copy()
    ref["cargo_empresa"] = ref["cargo_empresa"].str.strip()
    ref["prioridade"] = ref["base_pesquisa"].map({b: i for i, b in enumerate(bases)})
    ref = ref.sort_values(["cargo_empresa", "prioridade"]).drop_duplicates("cargo_empresa")
    return ref.rename(columns={"base_pesquisa": "base_usada"})


def cruzar(pessoas: pd.DataFrame, mercado: pd.DataFrame, bases: str | list[str]) -> tuple[pd.DataFrame, int]:
    """Pessoas com referência (+ compa-ratio, penetração, base usada) e quantas ficaram sem."""
    ref = referencia(mercado, bases)
    m = pessoas.merge(ref[["cargo_empresa", "cargo_pesquisa", "salario_adequado", "salario_minimo", "salario_maximo", "base_usada"]],
                      left_on="descricao_cargo", right_on="cargo_empresa", how="left")
    m = m[m["salario_adequado"].notna() & (m["salario_adequado"] > 0)].copy()
    m["minimo"] = m["salario_minimo"].fillna(m["salario_adequado"] * PISO_IDEAL / 100)
    m["maximo"] = m["salario_maximo"].fillna(m["salario_adequado"] * TETO_IDEAL / 100)
    m["pct"] = m["salario"] / m["salario_adequado"] * 100
    amplitude = (m["maximo"] - m["minimo"]).where(lambda s: s > 0)
    m["penetracao"] = (m["salario"] - m["minimo"]) / amplitude * 100
    m["classificacao"] = classificar(m["pct"])
    return m, len(pessoas) - len(m)


def resumo(m: pd.DataFrame) -> dict:
    n = len(m)
    vc = m["classificacao"].value_counts()
    return {"n": n, "dentro": vc.get("Dentro", 0) / n if n else None, "abaixo": vc.get("Abaixo", 0) / n if n else None,
            "acima": vc.get("Acima", 0) / n if n else None, "compa_mediano": m["pct"].median() / 100 if n else None,
            "penetracao_mediana": m["penetracao"].median() / 100 if n else None}


def custo_enquadramento(m: pd.DataFrame, alvo_pct: int = PISO_IDEAL) -> pd.DataFrame:
    """Por pessoa abaixo do alvo: quanto falta por mês para chegar a `alvo_pct`% do adequado."""
    alvo = m["salario_adequado"] * alvo_pct / 100
    c = m[m["salario"] < alvo].assign(alvo=alvo, falta=lambda x: x["alvo"] - x["salario"])
    c["falta_anual"] = c["falta"] * FATOR_ANUAL
    return c


def custo_por(c: pd.DataFrame, coluna: str) -> pd.DataFrame:
    t = c.groupby(coluna).agg(pessoas=("id_funcionario", "size"), mensal=("falta", "sum"), anual=("falta_anual", "sum"),
                              aumento_medio=("falta", "mean")).reset_index()
    return t.sort_values("mensal", ascending=False)


def matriz(m: pd.DataFrame, linhas: str, colunas: str) -> pd.DataFrame:
    """% dentro da faixa ideal e nº de pessoas em cada cruzamento."""
    t = m.groupby([linhas, colunas]).agg(pessoas=("id_funcionario", "size"),
                                         dentro=("classificacao", lambda s: (s == "Dentro").mean()),
                                         compa=("pct", "median")).reset_index()
    return t


def compressao(m: pd.DataFrame, recente_dias: int = 365, minimo: int = 2) -> pd.DataFrame:
    """Cargos com pelo menos `minimo` recém-contratados (<= 12 meses) e `minimo` veteranos: mediana de cada
    grupo e a razão recém ÷ veteranos (>= 100% = quem acabou de entrar ganha igual ou mais)."""
    x = m.assign(grupo=np.where(m["tempo_casa_dias"] <= recente_dias, "recentes", "veteranos"))
    g = x.groupby(["descricao_cargo", "grupo"])["salario"].agg(["median", "size"]).unstack("grupo")
    g.columns = [f"{a}_{b}" for a, b in g.columns]
    for col in ("median_recentes", "median_veteranos", "size_recentes", "size_veteranos"):
        if col not in g:
            g[col] = np.nan
    g = g[(g["size_recentes"] >= minimo) & (g["size_veteranos"] >= minimo)].copy()
    g["razao"] = g["median_recentes"] / g["median_veteranos"]
    return g.reset_index().sort_values("razao", ascending=False)


def por_tempo_casa(m: pd.DataFrame) -> pd.DataFrame:
    t = m.groupby("faixa_tempo").agg(pessoas=("id_funcionario", "size"), compa=("pct", "median"),
                                     dentro=("classificacao", lambda s: (s == "Dentro").mean())).reset_index()
    return t.set_index("faixa_tempo").reindex([f for f in ORDEM_TEMPO if f in set(t["faixa_tempo"])]).reset_index()


def job_matching(pessoas: pd.DataFrame, mercado: pd.DataFrame, bases: str | list[str]) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Cargos com e sem equivalente na pesquisa (base ou lista de bases em cascata), com a faixa paga internamente."""
    st_ = pessoas.groupby("descricao_cargo").agg(qtd=("salario", "size"), sal_min=("salario", "min"),
                                                 sal_mediana=("salario", "median"), sal_max=("salario", "max")).reset_index()
    ref = referencia(mercado, bases)[["cargo_empresa", "cargo_pesquisa", "salario_adequado", "salario_minimo", "salario_maximo", "base_usada"]]
    j = st_.merge(ref, left_on="descricao_cargo", right_on="cargo_empresa", how="left")
    com = j[j["salario_adequado"].notna()].copy()
    com["minimo"] = com["salario_minimo"].fillna(com["salario_adequado"] * PISO_IDEAL / 100)
    com["maximo"] = com["salario_maximo"].fillna(com["salario_adequado"] * TETO_IDEAL / 100)
    com["aderencia"] = com["sal_mediana"] / com["salario_adequado"] * 100
    com["classificacao"] = classificar(com["aderencia"])
    return com, j[j["salario_adequado"].isna()].copy()
