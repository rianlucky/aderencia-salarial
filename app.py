"""Painel Aderência Salarial — salário de cada colaborador frente à referência de mercado
(Carreira Muller) do cargo equivalente (Remuneração e Orçamento de Pessoas).

Fontes (Neon): core_view.funcionario_ativo (quadro ativo, regra única da Central) e
mercado.mercado_salarial_muller (etl/upload_faixas_salariais.py). Diretoria/área pelo mapeamento
oficial (etl/mapping_diretoria.py). Cálculos em metricas.py. Padrão visual: skill padrao-painel-streamlit.

    streamlit run app.py
"""
from __future__ import annotations

import html as html_lib
import io
import sys
from datetime import date, datetime
from pathlib import Path

import numpy as np
import pandas as pd
import psycopg2
import streamlit as st
from streamlit_sortables import sort_items

import auth
import metricas as m
import painel_padrao as pp

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "etl"))
import mapping_diretoria  # noqa: E402

ICONE = ROOT / "assets" / "icone-dispersao-salarial-transparente.png"
AZUL, AMARELO, VERMELHO, VERDE, LARANJA = "#064D66", "#FAB900", "#F02727", "#16A34A", "#EB6834"
AZUL_MEDIO, CINZA, CINZA_ESCURO = "#4A8FA8", "#6B7280", "#1F2937"
COR_CLASSE = {"Abaixo": VERMELHO, "Dentro": VERDE, "Acima": LARANJA}
FAIXA_MIN, FAIXA_MAX = 60, 140
SEM_DADOS = "Sem colaboradores com referência de mercado no filtro selecionado."
AJUDA_COMPA = ("Compa-ratio = salário ÷ salário adequado de mercado do cargo (Carreira Muller). Faixa ideal da "
               "Pacaembu Construtora: 0,80 a 1,20. Penetração = onde o salário está dentro da faixa de mercado do cargo: "
               "0,00 no mínimo, 1,00 no máximo.")
AJUDA_ENQ = ("Enquadramento = para cada pessoa com compa-ratio abaixo do alvo, a diferença entre o salário do alvo "
             "(adequado de mercado × 0,80 ou × 1,00) e o salário-base atual, somada no mês. Anual = mensal × 13,33 "
             "(12 salários + 13º + 1/3 de férias), sem encargos.")
TEXTO_ENQ = ("<b>Como ler este custo.</b> O valor mostra o esforço financeiro para aproximar os salários da referência "
             "de mercado escolhida; não significa que todos os casos precisem ser enquadrados. A Pacaembu Construtora "
             "pode adotar uma política ou dinâmica interna própria, com uma linha de referência inclusive abaixo do "
             "praticado pelo mercado, de acordo com a estratégia de remuneração e a abordagem definida pela diretoria. "
             "Use o número como base para priorização e orçamento, não como proposta de reajuste.")
LIMITE_TABELA = 200  # linhas desenhadas no detalhamento; o Excel leva todas
PERSONALIZADO = "Personalizado (em cascata)"
# ordem padrão do Personalizado (definida pelo time de Remuneração em 29/09/2026)
ORDEM_PADRAO = ["GRH ECI - Ramo Econômico", "GRH ECI - Acima de 1000 Colaboradores", "Indústria da Construção"]
CSS_ARRASTAR = """
.sortable-component { border: 1px solid #CBD8DE; border-radius: 10px; padding: 4px; background: #F5F8FA; }
.sortable-container { background: #FFFFFF; border-radius: 8px; margin: 4px 0; padding: 4px; counter-reset: item; }
.sortable-container-header { font-weight: 700; color: #064D66; font-size: .78rem; padding: 4px 6px; }
.sortable-item, .sortable-item:hover { background: #EAF4F7; color: #003244; border: 1px solid #CFE3EA; border-radius: 6px;
    font-size: .8rem; font-weight: 600; margin: 3px 4px; padding: 5px 8px; cursor: grab; }
"""

st.set_page_config(page_title="Aderência Salarial · Pacaembu Construtora", page_icon=str(ICONE), layout="wide")

# login antes de qualquer dado + matriz de acessos (painel restrito: salário nominal por pessoa)
auth.exigir_login()
auth.exigir_acesso_ao_painel("aderencia")

st.html(f"""<style>
.aviso-enq {{ background:#FFF8E1; border:1px solid #FBE3A0; border-left:4px solid #FAB900; border-radius:8px;
    color:#1F2937; font-size:.84rem; line-height:1.5; padding:.65rem .9rem; margin:.1rem 0 .7rem; }}
.aviso-enq b {{ color:#064D66; }}
.htbl-wrap {{ overflow:auto; border:1px solid #E3E6EA; border-radius:10px; background:#fff; }}
.htbl-row {{ display:flex; align-items:center; border-bottom:1px solid #EEF1F4; font-size:13px; }}
.htbl-row:last-child {{ border-bottom:none; }}
.htbl-head {{ background:#EDF1F3; font-weight:700; color:{CINZA_ESCURO}; position:sticky; top:0; z-index:1; }}
.htbl-cell {{ padding:7px 10px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }}
</style>""")


# ----------------------------------------------------------------------------- dados

@st.cache_data(ttl=600, show_spinner="Carregando dados…")
def carregar() -> tuple[pd.DataFrame, pd.DataFrame, datetime | None]:
    with psycopg2.connect(st.secrets["neon"]["database_url"], connect_timeout=10) as conn:
        pessoas = pd.read_sql("""SELECT id_funcionario, nome_funcionario, descricao_cargo, funcao_cargo, gerenciamento_nivel_cargo,
                                        centro_de_custo::text AS centro_de_custo, nome_centro_custo, descricao_posicao,
                                        categoria_atribuicao, salario, data_admissao, data_referencia
                                 FROM core_view.funcionario_ativo WHERE salario IS NOT NULL AND salario > 0""", conn)
        mercado = pd.read_sql("""SELECT cargo_empresa, cargo_pesquisa, base_pesquisa, salario_adequado, salario_minimo,
                                        salario_maximo, data_retirada, loaded_at FROM mercado.mercado_salarial_muller""", conn)
        try:
            carga = pd.read_sql("SELECT max(concluido_em) AS c FROM ops.v_ultima_carga WHERE schema_nome = 'core' AND tabela = 'fato_funcionario'", conn)["c"][0]
        except Exception:  # noqa: BLE001 — sem permissão no registro de cargas, usa a data da base
            carga = None
    res = [mapping_diretoria.resolve_diretoria_area(c, p, i) for c, p, i in
           zip(pessoas["centro_de_custo"], pessoas["descricao_posicao"], pessoas["id_funcionario"])]
    pessoas["diretoria"], pessoas["area"] = zip(*res) if res else ([], [])
    ref = pd.to_datetime(pessoas["data_referencia"]).max().date()
    return m.preparar_pessoas(pessoas, ref), mercado, carga


def _int(v) -> str:
    return "—" if v is None or pd.isna(v) else f"{int(round(v)):,}".replace(",", ".")


def _reais(v) -> str:
    return "—" if v is None or pd.isna(v) else "R$ " + f"{v:,.0f}".replace(",", ".")


def _reais_curto(v) -> str:
    if v is None or pd.isna(v):
        return "—"
    if abs(v) >= 1e6:
        return f"R$ {v / 1e6:.1f} mi".replace(".", ",")
    if abs(v) >= 1e3:
        return f"R$ {v / 1e3:.0f} mil".replace(".", ",")
    return _reais(v)


def _cr(pct) -> str:
    """Compa-ratio em razão, a partir do % do adequado (91 -> "0,91")."""
    return "—" if pct is None or pd.isna(pct) else f"{pct / 100:.2f}".replace(".", ",")


def _pct(v, casas=0) -> str:
    return "—" if v is None or pd.isna(v) else f"{v * 100:.{casas}f}%".replace(".", ",")


def _cor_ponto(pct: float) -> str:
    """Azul dentro da faixa ideal; fora dela, do azul ao vermelho conforme a distância."""
    if pd.isna(pct):
        return "#9AA3AE"
    if m.PISO_IDEAL <= pct <= m.TETO_IDEAL:
        return AZUL
    dist = max(m.PISO_IDEAL - pct, 0) + max(pct - m.TETO_IDEAL, 0)
    t = min(dist, 20) / 20
    a, b = (0x06, 0x4D, 0x66), (0xD0, 0x3B, 0x3B)
    return "#" + "".join(f"{round(x + (y - x) * t):02x}" for x, y in zip(a, b))


def _medidor(pct: float, largura: int = 130) -> str:
    """Barrinha de compa-ratio 0 a 2,00 com marcas em 0,80, 1,00 e 1,20 (mesma régua do gráfico)."""
    if pd.isna(pct):
        return "—"
    fill = max(0.0, min(100.0, pct / 200 * 100))
    marcas = "".join(f'<span style="position:absolute;left:{x / 2:.1f}%;top:50%;transform:translate(-50%,-50%);width:5px;height:5px;'
                     f'border-radius:50%;background:#94A3B8"></span>' for x in (80, 100, 120))
    return (f'<div style="display:flex;align-items:center;gap:8px"><div style="position:relative;width:{largura}px;height:6px;'
            f'background:#E3E6EA;border-radius:999px;flex-shrink:0"><div style="position:absolute;left:0;top:0;height:100%;'
            f'width:{fill:.1f}%;background:{_cor_ponto(pct)};border-radius:999px"></div>{marcas}</div>'
            f'<span style="font-size:12.5px;font-weight:700">{_cr(pct)}</span></div>')


def tabela_html(df: pd.DataFrame, colunas: list[tuple], altura: int = 420) -> None:
    """Tabela em HTML (a barrinha de compa-ratio não cabe no st.dataframe). colunas: (campo, rótulo, largura, tipo)."""
    def celula(v, tipo):
        if tipo == "barra":
            return _medidor(v)
        if tipo == "reais":
            return _reais(v)
        if tipo == "int":
            return _int(v)
        return html_lib.escape("—" if v is None or (isinstance(v, float) and pd.isna(v)) else str(v))
    def estilo(larg, tipo):
        return (f"flex:0 0 {larg}px;" if larg else "flex:1 1 0;min-width:150px;") + ("text-align:right;" if tipo in ("reais", "int") else "")
    cab = "".join(f'<div class="htbl-cell" style="{estilo(l, t)}">{html_lib.escape(r)}</div>' for _, r, l, t in colunas)
    linhas = "".join('<div class="htbl-row">' + "".join(f'<div class="htbl-cell" style="{estilo(l, t)}">{celula(row[c], t)}</div>'
                                                        for c, _, l, t in colunas) + "</div>" for _, row in df.iterrows())
    st.html(f'<div class="htbl-wrap" style="max-height:{altura}px"><div class="htbl-row htbl-head">{cab}</div>{linhas}</div>')


def excel(df: pd.DataFrame, rotulo: str, arquivo: str, key: str, filtros: dict) -> None:
    """Botão de exportação; a planilha só é montada quando alguém clica (não pesa nas outras interações)."""
    linhas = [(k, ", ".join(map(str, v)) if isinstance(v, (list, tuple)) else v) for k, v in filtros.items() if v]

    def gerar() -> bytes:
        buf = io.BytesIO()
        with pd.ExcelWriter(buf, engine="openpyxl") as xl:
            df.to_excel(xl, sheet_name="Dados", index=False)
            pd.DataFrame([("Gerado em", f"{datetime.now():%d/%m/%Y %H:%M}")] + linhas,
                         columns=["Filtro", "Valor"]).to_excel(xl, sheet_name="Filtros", index=False)
        return buf.getvalue()

    st.download_button(rotulo, gerar, arquivo, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                       key=key, icon=":material/download:")


# ----------------------------------------------------------------------------- gráficos

def dispersao(d: pd.DataFrame) -> dict:
    pts = d.assign(cor=[_cor_ponto(p) for p in d["pct"]], y=d["pct"].clip(FAIXA_MIN, FAIXA_MAX),
                   sal_txt=[_reais(v) for v in d["salario"]], adeq_txt=[_reais(v) for v in d["salario_adequado"]],
                   pct_txt=[_cr(v) for v in d["pct"]])[
        ["salario", "y", "cor", "nome_funcionario", "descricao_cargo", "diretoria", "area", "sal_txt", "adeq_txt", "pct_txt", "base_usada"]]
    y = {"field": "y", "type": "quantitative", "scale": {"domain": [FAIXA_MIN, FAIXA_MAX]},
         "axis": {"title": "Compa-ratio (salário ÷ adequado)", "labelExpr": "replace(format(datum.value / 100, '.2f'), '.', ',')", "grid": True}}
    return {"layer": [
        {"data": {"values": [{"y": 80}, {"y": 120}]}, "mark": {"type": "rule", "color": VERDE, "strokeWidth": 2},
         "encoding": {"y": {"field": "y", "type": "quantitative", "scale": {"domain": [FAIXA_MIN, FAIXA_MAX]}}}},
        {"data": {"values": [{"y": 100}]}, "mark": {"type": "rule", "color": CINZA, "strokeDash": [5, 4], "strokeWidth": 1.5},
         "encoding": {"y": {"field": "y", "type": "quantitative", "scale": {"domain": [FAIXA_MIN, FAIXA_MAX]}}}},
        {"data": {"values": pts.to_dict("records")}, "params": [{"name": "zoom", "select": "interval", "bind": "scales"}],
         "mark": {"type": "circle", "size": 60, "opacity": .75, "stroke": "#FFFFFF", "strokeWidth": .4},
         "encoding": {"x": {"field": "salario", "type": "quantitative", "scale": {"zero": False},
                            "axis": {"title": "Salário mensal", "grid": True, "labelExpr": "'R$ ' + replace(format(datum.value, ',.0f'), ',', '.')"}},
                      "y": y, "color": {"field": "cor", "type": "nominal", "scale": None},
                      "tooltip": [{"field": "nome_funcionario", "title": "Colaborador"}, {"field": "descricao_cargo", "title": "Cargo"},
                                  {"field": "diretoria", "title": "Diretoria"}, {"field": "area", "title": "Área"},
                                  {"field": "sal_txt", "title": "Salário"}, {"field": "adeq_txt", "title": "Adequado (mercado)"},
                                  {"field": "pct_txt", "title": "Compa-ratio"}, {"field": "base_usada", "title": "Base usada"}]}},
    ]}


def barras_classe(t: pd.DataFrame, campo: str) -> dict:
    """Barras 100% empilhadas Abaixo / Dentro / Acima, com o % em cada parte."""
    d = t.assign(ordem=t["classificacao"].map({"Abaixo": 0, "Dentro": 1, "Acima": 2}),
                 txt=[_pct(p) if p >= .06 else "" for p in t["pct"]], cor_txt="#FFFFFF")
    ordem_y = list(dict.fromkeys(d.sort_values("ordem_y")[campo])) if "ordem_y" in d else list(dict.fromkeys(d[campo]))
    y = {"field": campo, "type": "nominal", "sort": ordem_y, "axis": {"title": None, "labelLimit": 220}}
    xq = {"field": "pessoas", "type": "quantitative", "stack": "normalize"}
    return {"data": {"values": d.to_dict("records")}, "layer": [
        {"mark": {"type": "bar"}, "encoding": {"y": y, "x": {**xq, "axis": {"format": ".0%", "grid": True, "title": None}},
                                               "order": {"field": "ordem"},
                                               "color": {"field": "classificacao", "scale": {"domain": list(COR_CLASSE), "range": list(COR_CLASSE.values())},
                                                         "legend": {"orient": "top"}},
                                               "tooltip": [{"field": campo, "title": " "}, {"field": "classificacao", "title": "Classificação"},
                                                           {"field": "pessoas", "title": "Pessoas"}, {"field": "pct", "title": "%", "format": ".1%"}]}},
        {"mark": {"type": "text", "fontSize": 11, "fontWeight": 800, "color": "#FFFFFF"},
         "encoding": {"y": y, "x": {**xq, "bandPosition": .5}, "order": {"field": "ordem"}, "text": {"field": "txt"}}},
    ]}


def mapa_calor(t: pd.DataFrame, linhas: str, colunas: str, ordem_col: list[str]) -> dict:
    d = t.assign(txt=[_pct(p) for p in t["dentro"]], compa_txt=[_cr(v) for v in t["compa"]],
                 claro=[p < .45 or p > .8 for p in t["dentro"]])
    x = {"field": colunas, "type": "nominal", "sort": ordem_col, "axis": {"title": None, "labelAngle": 0, "labelLimit": 150, "orient": "top", "labelExpr": "split(replace(datum.label, '/', '/|'), '|')"}}
    y = {"field": linhas, "type": "nominal", "axis": {"title": None, "labelLimit": 220}}
    return {"data": {"values": d.to_dict("records")}, "layer": [
        {"mark": {"type": "rect", "stroke": "#FFFFFF", "strokeWidth": 2, "cornerRadius": 3},
         "encoding": {"x": x, "y": y, "color": {"field": "dentro", "type": "quantitative", "title": "% dentro da faixa",
                                                "scale": {"domain": [.3, .65, 1], "range": [VERMELHO, AMARELO, VERDE]},
                                                "legend": {"orient": "right", "format": ".0%"}},
                      "tooltip": [{"field": linhas, "title": "Diretoria"}, {"field": colunas, "title": "Nível"},
                                  {"field": "pessoas", "title": "Pessoas"}, {"field": "dentro", "title": "% dentro", "format": ".0%"},
                                  {"field": "compa_txt", "title": "Compa-ratio mediano"}]}},
        {"mark": {"type": "text", "fontSize": 12, "fontWeight": 800},
         "encoding": {"x": x, "y": y, "text": {"field": "txt"},
                      "color": {"condition": {"test": "datum.claro", "value": "#FFFFFF"}, "value": CINZA_ESCURO}}},
    ]}


def histograma_penetracao(d: pd.DataFrame) -> dict:
    faixas = [(-1e9, 0, "Abaixo do mínimo"), (0, 25, "0,00–0,25"), (25, 50, "0,25–0,50"), (50, 75, "0,50–0,75"), (75, 100, "0,75–1,00"), (100, 1e9, "Acima do máximo")]
    linhas = [{"faixa": r, "pessoas": int(((d["penetracao"] >= a) & (d["penetracao"] < b)).sum()), "ordem": i}
              for i, (a, b, r) in enumerate(faixas)]
    tot = sum(x["pessoas"] for x in linhas) or 1
    for x in linhas:
        x["txt"] = f"{_int(x['pessoas'])} ({_pct(x['pessoas'] / tot)})"
        x["cor"] = VERMELHO if x["ordem"] == 0 else LARANJA if x["ordem"] == 5 else AZUL
    xa = {"field": "faixa", "type": "nominal", "sort": [f[2] for f in faixas], "axis": {"labelAngle": 0, "title": None}}
    return {"data": {"values": linhas}, "layer": [
        {"mark": {"type": "bar", "cornerRadiusTopLeft": 4, "cornerRadiusTopRight": 4},
         "encoding": {"x": xa, "y": {"field": "pessoas", "type": "quantitative", "axis": {"grid": True, "title": None}},
                      "color": {"field": "cor", "type": "nominal", "scale": None}, "tooltip": [{"field": "faixa"}, {"field": "txt", "title": "Pessoas"}]}},
        {"mark": {"type": "text", "dy": -8, "fontSize": 11, "fontWeight": 700, "color": CINZA_ESCURO},
         "encoding": {"x": xa, "y": {"field": "pessoas", "type": "quantitative"}, "text": {"field": "txt"}}},
    ], "padding": {"top": 14}}


def barras_valor(t: pd.DataFrame, campo: str, valor: str, texto: str, cor: str = AZUL, limite: int = 230) -> dict:
    y = {"field": campo, "type": "nominal", "sort": list(t[campo]), "axis": {"title": None, "labelLimit": limite}}
    xq = {"field": valor, "type": "quantitative", "axis": None}
    return {"data": {"values": t.to_dict("records")}, "layer": [
        {"mark": {"type": "bar", "cornerRadiusEnd": 4, "color": cor}, "encoding": {"y": y, "x": xq, "tooltip": [{"field": campo, "title": " "}, {"field": texto, "title": "Valor"}]}},
        {"mark": {"type": "text", "align": "left", "dx": 5, "fontSize": 11, "fontWeight": 700, "color": cor}, "encoding": {"y": y, "x": xq, "text": {"field": texto}}},
    ], "padding": {"right": 60}}


def compa_tempo(t: pd.DataFrame) -> dict:
    d = t.assign(txt=[_cr(c) for c in t["compa"]], rot=[f"{f}|{_int(n)} pess." for f, n in zip(t["faixa_tempo"], t["pessoas"])])
    x = {"field": "rot", "type": "nominal", "sort": list(d["rot"]), "axis": {"labelAngle": 0, "title": None, "labelExpr": "split(datum.label, '|')"}}
    y = {"field": "compa", "type": "quantitative", "scale": {"domain": [0, 115]}, "axis": {"grid": True, "title": None, "labelExpr": "replace(format(datum.value / 100, '.2f'), '.', ',')"}}
    return {"layer": [
        {"data": {"values": [{"y": 80}]}, "mark": {"type": "rule", "color": VERDE, "strokeDash": [4, 4]}, "encoding": {"y": {"field": "y", "type": "quantitative", "scale": {"domain": [0, 115]}}}},
        {"data": {"values": d.to_dict("records")}, "mark": {"type": "bar", "color": AZUL, "cornerRadiusTopLeft": 4, "cornerRadiusTopRight": 4},
         "encoding": {"x": x, "y": y, "tooltip": [{"field": "faixa_tempo", "title": "Tempo de casa"}, {"field": "pessoas", "title": "Pessoas"},
                                                   {"field": "txt", "title": "Compa-ratio mediano"}]}},
        {"data": {"values": d.to_dict("records")}, "mark": {"type": "text", "dy": -8, "fontSize": 12, "fontWeight": 800, "color": CINZA_ESCURO},
         "encoding": {"x": x, "y": y, "text": {"field": "txt"}}},
    ], "padding": {"top": 14}}


def cobertura(pct_com: float) -> dict:
    d = [{"s": "Com referência", "ini": 0, "fim": pct_com, "meio": pct_com / 2, "txt": _pct(pct_com), "cor": AZUL},
         {"s": "Sem referência", "ini": pct_com, "fim": 1, "meio": (1 + pct_com) / 2, "txt": _pct(1 - pct_com), "cor": "#94A3B8"}]
    return {"data": {"values": d}, "height": 34, "layer": [
        {"mark": {"type": "bar", "height": 30, "cornerRadius": 4}, "encoding": {"x": {"field": "ini", "type": "quantitative", "scale": {"domain": [0, 1]}, "axis": None},
                                                                                  "x2": {"field": "fim"}, "color": {"field": "cor", "type": "nominal", "scale": None},
                                                                                  "tooltip": [{"field": "s", "title": " "}, {"field": "txt", "title": "%"}]}},
        {"mark": {"type": "text", "fontSize": 12, "fontWeight": 800, "color": "#FFFFFF"}, "encoding": {"x": {"field": "meio", "type": "quantitative"}, "text": {"field": "txt"}}},
    ]}


# ----------------------------------------------------------------------------- página

try:
    pessoas, mercado, carga = carregar()
except Exception as exc:  # noqa: BLE001
    st.error("Não consegui ler a base do Neon. Confira o bloco [neon] em .streamlit/secrets.toml.", icon=":material/error:")
    st.caption(type(exc).__name__)
    st.stop()

ref = pd.to_datetime(pessoas["data_referencia"]).max().date()
pp.logo(ICONE, "Aderência Salarial")
navegacao = st.navigation([
    st.Page(lambda: pagina_pessoas(), title="Analítico", icon=":material/scatter_plot:", url_path="analitico", default=True),
    st.Page(lambda: pagina_geral(), title="Defasagem e Enquadramento", icon=":material/insights:", url_path="defasagem-e-enquadramento"),
    st.Page(lambda: pagina_cargos(), title="Cargo e Mercado", icon=":material/work:", url_path="cargo-e-mercado"),
])
bases = sorted(mercado["base_pesquisa"].dropna().unique())
opcoes = lambda c: sorted(pessoas[c].dropna().unique())  # noqa: E731
mercado_em = mercado["loaded_at"].max() if len(mercado) else None

with pp.barra_lateral(fonte="Neon + Databricks + Carreira Muller", atualizado_em=carga or ref,
                      extra={"Mercado": pp._formatar(mercado_em) if mercado_em is not None and pd.notna(mercado_em) else "—"}):
    st.markdown("**Pesquisa de mercado**")
    base = st.selectbox("Base de pesquisa", [PERSONALIZADO] + bases, label_visibility="collapsed",
                        help="Personalizado: cada cargo usa a primeira base da lista que tem referência para ele.")
    if base == PERSONALIZADO:
        padrao_usar = [b for b in ORDEM_PADRAO if b in bases]
        caixas = sort_items([{"header": "Usar, nesta ordem (arraste)", "items": padrao_usar},
                             {"header": "Não usar", "items": [b for b in bases if b not in padrao_usar]}],
                            multi_containers=True, direction="vertical", custom_style=CSS_ARRASTAR, key="ordem_bases")
        ordem_bases = caixas[0]["items"] if caixas else padrao_usar
        if not ordem_bases:
            st.warning("Arraste ao menos uma base para \"Usar\".", icon=":material/warning:")
            ordem_bases = padrao_usar
        st.caption("Se a 1ª base não tem o cargo, usa a 2ª, e assim por diante.")
    else:
        ordem_bases = [base]
        retirada = mercado.loc[mercado["base_pesquisa"] == base, "data_retirada"].max()
        if pd.notna(retirada):
            st.caption(f"Relatório retirado em {pd.Timestamp(retirada):%d/%m/%Y}")
    st.markdown("**Filtros**")
    sel = {
        "diretoria": st.multiselect("Diretoria", opcoes("diretoria"), placeholder="Todas"),
        "area": st.multiselect("Área", opcoes("area"), placeholder="Todas"),
        "cc_texto": st.multiselect("Centro de custo", opcoes("cc_texto"), placeholder="Todos"),
        "nivel": st.multiselect("Nível de gerenciamento", list(pessoas["nivel"].value_counts().index), placeholder="Todos"),
        "categoria_atribuicao": st.multiselect("Categoria de atribuição", opcoes("categoria_atribuicao"), placeholder="Todas"),
        "funcao_cargo": st.multiselect("Função de cargo", opcoes("funcao_cargo"), placeholder="Todas"),
    }

rotulos = {"diretoria": "Diretoria", "area": "Área", "cc_texto": "Centro de custo", "nivel": "Nível",
           "categoria_atribuicao": "Categoria", "funcao_cargo": "Função"}
ABREV = {"Indústria da Construção": "Indústria", "GRH ECI - Acima de 1000 Colaboradores": "GRH > 1000",
         "GRH ECI - Ramo Econômico": "GRH Ramo", "GRH ECI - Região Grande São Paulo": "GRH Grande SP",
         "Sudeste SP - Grande São Paulo": "Sudeste SP"}
base_txt = base if base != PERSONALIZADO else "Personalizado: " + " → ".join(ABREV.get(b, b) for b in ordem_bases)
filtros_txt = {"Base de pesquisa": base_txt, **{rotulos[k]: v for k, v in sel.items()}}

base_p = pessoas
for col, vals in sel.items():
    if vals:
        base_p = base_p[base_p[col].isin(vals)]
cruz, sem_ref = m.cruzar(base_p, mercado, ordem_bases)

def _faixa(t: pd.DataFrame) -> list[str]:
    return [f"{_reais(a)} – {_reais(b)}" if round(a) != round(b) else "—" for a, b in zip(t["sal_min"], t["sal_max"])]


# ================================================================ páginas
def pagina_geral() -> None:
    r = m.resumo(cruz)
    enq80 = m.custo_enquadramento(cruz, 80)
    c = st.columns(6)
    with c[0]:
        pp.kpi("Colaboradores comparados", _int(r["n"]), f"{_int(sem_ref)} sem referência")
    with c[1]:
        pp.kpi("Dentro da faixa ideal", _pct(r["dentro"]), "compa-ratio 0,80 a 1,20", VERDE)
    with c[2]:
        pp.kpi("Abaixo da faixa", _pct(r["abaixo"]), "abaixo de 0,80", VERMELHO)
    with c[3]:
        pp.kpi("Acima da faixa", _pct(r["acima"]), "acima de 1,20", LARANJA)
    with c[4]:
        pp.kpi("Compa-ratio mediano", _cr(r["compa_mediano"] * 100), f"penetração {_cr(r['penetracao_mediana'] * 100)}", ajuda=AJUDA_COMPA)
    with c[5]:
        pp.kpi("Custo para enquadrar", _reais_curto(enq80["falta"].sum()), f"/mês · {_int(len(enq80))} pess.", ajuda=AJUDA_ENQ)

    pp.secao("1. Onde está a defasagem")
    niv = cruz.groupby(["nivel", "classificacao"]).size().rename("pessoas").reset_index()
    niv["pct"] = niv["pessoas"] / niv.groupby("nivel")["pessoas"].transform("sum")
    geral = cruz.groupby("classificacao").size().rename("pessoas").reset_index().assign(nivel="Geral")
    geral["pct"] = geral["pessoas"] / geral["pessoas"].sum()
    dentro_n = niv[niv["classificacao"] == "Dentro"].set_index("nivel")["pct"]
    ordem_n = ["Geral"] + list(dentro_n.sort_values(ascending=False).index) + [n for n in niv["nivel"].unique() if n not in dentro_n.index]
    t_niv = pd.concat([geral, niv]).assign(ordem_y=lambda x: x["nivel"].map({n: i for i, n in enumerate(ordem_n)}))
    g1, g2 = st.columns([4, 8])
    with g1:
        pp.grafico("Aderência por nível de gerenciamento", barras_classe(t_niv, "nivel"), 360, SEM_DADOS)
    with g2:
        mz = m.matriz(cruz, "diretoria", "nivel")
        pp.grafico("% dentro da faixa ideal: diretoria × nível", mapa_calor(mz, "diretoria", "nivel", list(cruz["nivel"].value_counts().index)), 400, SEM_DADOS)
        st.html('<div class="nota">Cada célula: % das pessoas daquele cruzamento dentro da faixa ideal (passe o mouse para ver quantas '
                'pessoas e o compa-ratio mediano). Vermelho = defasagem concentrada.</div>')

    pp.secao("2. Penetração na faixa e tempo de casa")
    h1, h2 = st.columns(2)
    with h1:
        pp.grafico("Penetração na faixa de mercado", histograma_penetracao(cruz), 300, SEM_DADOS)
        st.html('<div class="nota"><b>Penetração</b> = onde o salário cai entre o mínimo e o máximo de mercado do cargo '
                '(0,00 no mínimo, 1,00 no máximo; sem mínimo/máximo na pesquisa, 0,80 e 1,20 do adequado).</div>')
    with h2:
        pp.grafico("Compa-ratio mediano por tempo de casa", compa_tempo(m.por_tempo_casa(cruz)), 300, SEM_DADOS)
        st.html('<div class="nota">Compa-ratio mediano de cada faixa de tempo de casa. Valores mais baixos no início indicam '
                'contratação abaixo do mercado; queda nas faixas longas, salário que não acompanhou.</div>')

    with st.container(horizontal=True, vertical_alignment="center"):
        pp.secao("3. Custo de enquadramento")
        alvo_txt = st.segmented_control("Levar até", ["Compa-ratio 0,80", "Compa-ratio 1,00"], default="Compa-ratio 0,80",
                                        label_visibility="collapsed", key="alvo") or "Compa-ratio 0,80"
    alvo = 80 if alvo_txt.endswith("0,80") else 100
    st.html(f'<div class="aviso-enq">{TEXTO_ENQ}</div>')
    enq = m.custo_enquadramento(cruz, alvo)
    if enq.empty:
        st.info(f"Ninguém com compa-ratio abaixo de {_cr(alvo)} no filtro.", icon=":material/info:")
        st.stop()
    k = st.columns(4)
    with k[0]:
        pp.kpi("Pessoas abaixo do alvo", _int(len(enq)), f"de {_int(len(cruz))} comparados")
    with k[1]:
        pp.kpi("Custo mensal", _reais_curto(enq["falta"].sum()), "soma do que falta no salário-base", ajuda=AJUDA_ENQ)
    with k[2]:
        pp.kpi("Custo anual", _reais_curto(enq["falta_anual"].sum()), "12 salários + 13º + 1/3 de férias")
    with k[3]:
        pp.kpi("Aumento médio", _reais(enq["falta"].mean()), f"{_pct((enq['falta'] / enq['salario']).mean(), 1)} do salário")
    e1, e2 = st.columns(2)
    with e1:
        t = m.custo_por(enq, "diretoria").head(10).assign(txt=lambda x: [f"{_reais_curto(v)}/mês · {_int(n)} pess." for v, n in zip(x["mensal"], x["pessoas"])])
        pp.grafico("Por diretoria (custo mensal)", barras_valor(t, "diretoria", "mensal", "txt"), 320, SEM_DADOS)
    with e2:
        t = m.custo_por(enq, "descricao_cargo").head(10).assign(txt=lambda x: [f"{_reais_curto(v)}/mês · {_int(n)} pess." for v, n in zip(x["mensal"], x["pessoas"])])
        pp.grafico("10 cargos que mais pesam (custo mensal)", barras_valor(t, "descricao_cargo", "mensal", "txt", AZUL_MEDIO), 320, SEM_DADOS)
    st.html('<div class="nota">Quanto falta, por mês, para levar ao compa-ratio alvo quem está abaixo dele (salário-base, sem encargos).</div>')
    enq = enq.assign(pct=(enq["pct"] / 100).round(2))
    exp = enq[["nome_funcionario", "descricao_cargo", "diretoria", "area", "cc_texto", "salario", "salario_adequado", "pct", "alvo", "falta", "falta_anual", "base_usada"]].rename(
        columns={"nome_funcionario": "Colaborador", "descricao_cargo": "Cargo", "diretoria": "Diretoria", "area": "Área", "cc_texto": "Centro de custo",
                 "salario": "Salário", "salario_adequado": "Adequado", "pct": "Compa-ratio", "alvo": f"Salário alvo (compa {_cr(alvo)})",
                 "falta": "Falta por mês", "falta_anual": "Falta por ano", "base_usada": "Base usada"}).sort_values("Falta por mês", ascending=False)
    excel(exp, "Exportar lista de enquadramento (Excel)", f"enquadramento_{alvo}.xlsx", "x_enq", {**filtros_txt, "Alvo": alvo_txt})


def pagina_pessoas() -> None:
    with st.container(horizontal=True, vertical_alignment="center"):
        pp.secao("1. Posicionamento na tabela salarial")
        classes = st.pills("Classificação", ["Abaixo", "Dentro", "Acima"], selection_mode="multi", label_visibility="collapsed", key="classes")
    vista = cruz if not classes else cruz[cruz["classificacao"].isin(classes)]
    if vista.empty:
        st.info("Nenhum colaborador nessa classificação.", icon=":material/info:")
        st.stop()
    pp.grafico("Compa-ratio pessoa a pessoa", dispersao(vista), 520, SEM_DADOS)
    st.html('<div class="nota">Cada ponto é um colaborador. <b>Compa-ratio</b> = salário ÷ salário adequado da pesquisa para o '
            'cargo equivalente (1,00 = na referência; 0,91 = 9% abaixo). Azul dentro da faixa ideal (0,80 a 1,20, linhas verdes); '
            'quanto mais vermelho, mais longe dela. Linha tracejada = 1,00. Pontos fora de 0,60 a 1,40 ficam na borda. '
            'Arraste para dar zoom; duplo clique volta. A classificação escolhida vale para esta página inteira.</div>')

    pp.secao("2. Extremos e detalhamento")
    x1, x2 = st.columns(2)
    cols_top = [("nome_funcionario", "Colaborador", None, "txt"), ("descricao_cargo", "Cargo", None, "txt"), ("pct", "Compa-ratio", 190, "barra")]
    with x1:
        st.html('<div class="titulo-graf">5 mais abaixo do adequado</div>')
        tabela_html(vista.nsmallest(5, "pct"), cols_top, 260)
    with x2:
        st.html('<div class="titulo-graf">5 mais acima do adequado</div>')
        tabela_html(vista.nlargest(5, "pct"), cols_top, 260)
    st.html('<div class="titulo-graf" style="margin-top:.6rem">Detalhamento pessoa a pessoa</div>')
    busca = st.text_input("Buscar por colaborador, cargo, diretoria ou área", placeholder="Digite para filtrar…", key="busca")
    det = vista.sort_values("pct")
    if busca.strip():
        t_ = busca.strip().lower()
        det = det[det[["nome_funcionario", "descricao_cargo", "diretoria", "area"]].apply(lambda s: s.str.lower().str.contains(t_, na=False)).any(axis=1)]
    tabela_html(det.head(LIMITE_TABELA), [("nome_funcionario", "Colaborador", None, "txt"), ("descricao_cargo", "Cargo", None, "txt"),
                                          ("diretoria", "Diretoria", None, "txt"), ("salario", "Salário", 100, "reais"),
                                          ("salario_adequado", "Adequado", 100, "reais"), ("pct", "Compa-ratio", 190, "barra"),
                                          ("base_usada", "Base usada", 190, "txt")], 480)
    if len(det) > LIMITE_TABELA:
        st.html(f'<div class="nota">Mostrando {_int(LIMITE_TABELA)} de {_int(len(det))} colaboradores (menor compa-ratio primeiro). '
                'Use a busca para achar alguém ou exporte a lista completa.</div>')
    excel(det.assign(pct=(det["pct"] / 100).round(2), penetracao=(det["penetracao"] / 100).round(2))[
        ["nome_funcionario", "descricao_cargo", "diretoria", "area", "cc_texto", "salario", "salario_adequado", "pct", "penetracao", "base_usada"]].rename(
        columns={"nome_funcionario": "Colaborador", "descricao_cargo": "Cargo", "diretoria": "Diretoria", "area": "Área", "cc_texto": "Centro de custo",
                 "salario": "Salário", "salario_adequado": "Adequado", "pct": "Compa-ratio", "penetracao": "Penetração na faixa",
                 "base_usada": "Base usada"}),
          "Exportar detalhamento (Excel)", "detalhamento_aderencia.xlsx", "x_det", {**filtros_txt, "Classificação": classes})


def pagina_cargos() -> None:
    pp.secao("1. Job Matching — cargos comparados na Carreira Muller")
    com, sem = m.job_matching(base_p, mercado, ordem_bases)
    n_cargos = len(com) + len(sem)
    n_pess = com["qtd"].sum() + sem["qtd"].sum()
    j1, j2 = st.columns(2)
    with j1:
        pp.grafico(f"Cargos com referência ({_int(len(com))} de {_int(n_cargos)})", cobertura(len(com) / n_cargos if n_cargos else 0), 34, SEM_DADOS)
    with j2:
        pp.grafico(f"Colaboradores com referência ({_int(com['qtd'].sum())} de {_int(n_pess)})", cobertura(com["qtd"].sum() / n_pess if n_pess else 0), 34, SEM_DADOS)
    com = com.assign(faixa=_faixa(com))
    if len(ordem_bases) > 1:
        orig = com.groupby("base_usada").agg(cargos=("descricao_cargo", "size"), pessoas=("qtd", "sum")).reindex(ordem_bases).fillna(0).reset_index()
        orig["retirada"] = [mercado.loc[mercado["base_pesquisa"] == b, "data_retirada"].max() for b in orig["base_usada"]]
        orig["retirada"] = [f"{pd.Timestamp(d):%d/%m/%Y}" if pd.notna(d) else "—" for d in orig["retirada"]]
        orig.insert(0, "ordem", [f"{i + 1}ª" for i in range(len(orig))])
        st.html('<div class="titulo-graf" style="margin-top:.6rem">De onde veio a referência (Personalizado)</div>')
        tabela_html(orig, [("ordem", "Ordem", 70, "txt"), ("base_usada", "Base", None, "txt"), ("cargos", "Cargos", 90, "int"),
                           ("pessoas", "Pessoas", 90, "int"), ("retirada", "Relatório retirado em", 170, "txt")], 220)
    with st.container(horizontal=True, vertical_alignment="center"):
        st.html(f'<div class="titulo-graf" style="margin-bottom:0">Cargos com Job Matching ({_int(len(com))}) · ordem: mais longe do mercado primeiro</div>')
        classes_jm = st.pills("Classificação do cargo", ["Abaixo", "Dentro", "Acima"], selection_mode="multi", label_visibility="collapsed", key="classes_jm")
    com_v = com if not classes_jm else com[com["classificacao"].isin(classes_jm)]
    com_v = com_v.assign(dist=(com_v["aderencia"] - 100).abs()).sort_values("dist", ascending=False)
    tabela_html(com_v, [("descricao_cargo", "Cargo interno", None, "txt"), ("cargo_pesquisa", "Cargo na pesquisa", None, "txt"), ("qtd", "Qtd.", 55, "int"),
                        ("sal_mediana", "Salário interno", 110, "reais"), ("faixa", "Faixa interna (paga)", 170, "txt"), ("minimo", "Mínimo mercado", 110, "reais"),
                        ("salario_adequado", "Adequado", 100, "reais"), ("maximo", "Máximo mercado", 110, "reais"), ("aderencia", "Compa-ratio da mediana", 190, "barra"),
                        ("base_usada", "Base usada", 180, "txt")], 440)
    excel(com_v.drop(columns=["dist"]).assign(aderencia=(com_v["aderencia"] / 100).round(2)).rename(columns={"aderencia": "compa_ratio_mediana"}),
          "Exportar cargos com Job Matching (Excel)", "cargos_com_job_matching.xlsx", "x_jm_com", filtros_txt)

    sem = sem.assign(faixa=_faixa(sem)).sort_values("qtd", ascending=False)
    st.html(f'<div class="titulo-graf" style="margin-top:.8rem">Cargos sem Job Matching ({_int(len(sem))}) · mais pessoas primeiro</div>')
    tabela_html(sem, [("descricao_cargo", "Cargo", None, "txt"), ("qtd", "Qtd.", 60, "int"), ("sal_mediana", "Salário (mediana)", 140, "reais"),
                      ("faixa", "Faixa paga", 180, "txt")], 380)
    excel(sem, "Exportar cargos sem Job Matching (Excel)", "cargos_sem_job_matching.xlsx", "x_jm_sem", filtros_txt)
    st.html('<div class="nota">Cruzamento pelo nome do cargo interno contra o cargo equivalente mapeado na pesquisa. '
            '"Faixa interna" é o menor e o maior salário pago hoje no cargo (não é uma tabela salarial oficial).</div>')

    pp.secao("2. Compressão salarial — recém-contratados x veteranos")
    cp = m.compressao(cruz)
    if cp.empty:
        st.info("Nenhum cargo com pelo menos 2 recém-contratados e 2 veteranos no filtro.", icon=":material/info:")
        st.stop()
    comprimidos = cp[cp["razao"] >= 1]
    k = st.columns(3)
    with k[0]:
        pp.kpi("Cargos analisados", _int(len(cp)), "com 2+ recentes e 2+ veteranos")
    with k[1]:
        pp.kpi("Cargos com compressão", _int(len(comprimidos)), "recém-contratados ganham igual ou mais", VERMELHO if len(comprimidos) else VERDE)
    with k[2]:
        pp.kpi("Pessoas nesses cargos", _int((comprimidos["size_recentes"] + comprimidos["size_veteranos"]).sum()), "recentes + veteranos")
    tab = cp.assign(**{"Diferença": [f"{'+' if v >= 1 else '−'}{abs(v - 1) * 100:.0f}%" for v in cp["razao"]]})
    tabela_html(tab.head(25), [("descricao_cargo", "Cargo", None, "txt"), ("size_recentes", "Recentes (≤ 12 meses)", 175, "int"),
                               ("median_recentes", "Mediana recentes", 140, "reais"), ("size_veteranos", "Veteranos", 100, "int"),
                               ("median_veteranos", "Mediana veteranos", 140, "reais"), ("Diferença", "Recentes vs veteranos (%)", 190, "txt")], 380)
    st.html('<div class="nota">Mesmo cargo: salário mediano de quem entrou nos últimos 12 meses contra quem tem mais tempo. '
            'Diferença positiva = quem acabou de chegar já ganha mais — risco de saída e de insatisfação dos veteranos.</div>')


pp.cabecalho(navegacao.title, atualizado_em=carga or ref, filtros=filtros_txt,
             legenda=f"Quadro ativo em {ref:%d/%m/%Y} · {_int(len(cruz))} colaboradores comparados com a pesquisa · "
                     f"{_int(sem_ref)} sem cargo equivalente (ver Cargo e Mercado) · diretores, presidente e conselho fora")
if cruz.empty and navegacao.title != "Cargo e Mercado":
    st.info(SEM_DADOS, icon=":material/info:")
    st.stop()
navegacao.run()
