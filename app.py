from __future__ import annotations

import html as html_lib
import io
import os
import sys
from pathlib import Path

import altair as alt
import numpy as np
import pandas as pd
import streamlit as st

import auth

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "etl"))
import mapping_diretoria  # noqa: E402

LOGO_PATH = "assets/icone-dispersao-salarial-transparente.png"

BRAND_COLOR = "#064D66"
GREEN = "#0ca30c"
RED = "#d03b3b"
ORANGE = "#eb6834"
GRAY = "#64748b"

FAIXA_MIN, FAIXA_MAX = 60, 140
PISO_IDEAL, TETO_IDEAL = 80, 120
DIST_MAX = min(PISO_IDEAL - FAIXA_MIN, FAIXA_MAX - TETO_IDEAL)  # 20pp — mesmo raio pros dois lados

MARKET_TABLE = "interno.mercado_salarial_muller"
PEOPLE_TABLE = "interno.fato_funcionario_ativo"


@st.cache_resource
def _build_logo_wordmark(icon_path: str, text: str) -> "Image.Image | None":
    """Ícone + palavra-marca lado a lado, cozidos numa imagem só — st.logo() só
    tem um slot fixo de imagem e não deixa colocar texto ao lado. Mesmo padrão
    do painel Headcount (`.../Headcount Total/app.py::_build_logo_wordmark`)."""
    try:
        from PIL import Image, ImageDraw, ImageFont

        icon = Image.open(icon_path).convert("RGBA")
        target_h = 64
        icon = icon.resize((int(icon.width * target_h / icon.height), target_h))

        font = None
        for font_path in (r"C:\Windows\Fonts\segoeuib.ttf", r"C:\Windows\Fonts\arialbd.ttf"):
            if Path(font_path).exists():
                font = ImageFont.truetype(font_path, 34)
                break
        if font is None:
            font = ImageFont.load_default()

        draw = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
        text_box = draw.textbbox((0, 0), text, font=font)
        text_w, text_h = text_box[2] - text_box[0], text_box[3] - text_box[1]

        padding = 14
        canvas = Image.new("RGBA", (icon.width + padding + text_w + 4, target_h), (0, 0, 0, 0))
        canvas.paste(icon, (0, 0), icon)
        draw = ImageDraw.Draw(canvas)
        draw.text(
            (icon.width + padding, (target_h - text_h) // 2 - text_box[1]),
            text,
            font=font,
            fill=BRAND_COLOR,
        )
        return canvas
    except Exception as exc:
        print(f"[posicionamento] Falha ao montar o logo com texto: {exc}")
        return None


st.set_page_config(
    page_title="Pacaembu | Aderência Salarial",
    page_icon=LOGO_PATH,
    layout="wide",
    initial_sidebar_state="auto",
)

# Mesmo padrão visual do painel Headcount (Desenvolvimento Organizacional/Headcount
# Total): navy institucional #064D66 nos títulos e cards, cartão de login dividido.
# Injetado ANTES do require_login() porque essa mesma tela usa o CSS.
st.markdown(
    """
    <style>
    h3 {
        font-weight: 700;
        color: #064D66;
        margin-top: 25px;
    }
    .st-key-card-kpis, .st-key-card-scatter, .st-key-card-detalhe, .st-key-card-pizza-nivel,
    .st-key-card-top5, .st-key-card-jobmatching-overview, .st-key-card-jobmatching-tabelas {
        background-color: #FFFFFF;
        border-radius: 12px;
        box-shadow: 0 2px 8px rgba(0, 50, 68, 0.08);
    }
    [class*="st-key-kpi-card-"] {
        border-radius: 14px;
        overflow: hidden;
        box-shadow: 0 2px 8px rgba(0, 50, 68, 0.10);
        border: none;
    }
    [class*="st-key-kpi-card-"] > div {
        border: none !important;
    }

    .st-key-login_page { margin-top: 10vh; }
    [data-testid="stVerticalBlockBorderWrapper"].st-key-login_card {
        border: none !important; border-radius: 16px; overflow: hidden; padding: 0 !important;
        box-shadow: 0 14px 40px rgba(6, 77, 102, .18);
    }
    .st-key-login_card [data-testid="stHorizontalBlock"] { gap: 0 !important; }
    .st-key-login_left {
        background: linear-gradient(160deg, #064D66 0%, #2a78d6 100%);
        min-height: 460px; height: 100%; padding: 48px 30px;
        display: flex; flex-direction: column; align-items: center; justify-content: center; text-align: center;
    }
    .login-logo-pill {
        background: #FFFFFF; color: #064D66; border-radius: 12px; padding: 14px 18px;
        display: inline-flex; align-items: center; justify-content: center; gap: 10px; margin-bottom: 22px;
        box-shadow: 0 6px 18px rgba(0, 0, 0, .18); max-width: 100%; box-sizing: border-box;
        font-weight: 700; font-size: 15px;
    }
    .login-logo-pill img { height: 26px; width: auto; display: block; }
    .login-brand-sub { color: rgba(255, 255, 255, .88); font-size: 12px; line-height: 1.65; max-width: 220px; margin: 0 auto; text-align: center; }
    .st-key-login_right { padding: 48px 44px; min-height: 460px; height: 100%; display: flex; flex-direction: column; justify-content: center; }
    .login-form-title { font-size: 18px; font-weight: 600; color: #111110; margin: 0 0 4px; line-height: 1.4; }
    .login-form-sub { font-size: 12.5px; color: #6b6b68; margin: 0 0 22px; line-height: 1.5; }
    .st-key-login_right div[data-testid="stButton"] button {
        background: linear-gradient(160deg, #064D66 0%, #2a78d6 100%) !important; border: none !important;
        font-weight: 600 !important; border-radius: 8px !important; padding: 10px 0 !important;
    }
    .st-key-login_right div[data-testid="stButton"] button p { color: #FFFFFF !important; }
    .st-key-login_right div[data-testid="stButton"] button:hover { filter: brightness(1.08); }

    /* Listas HTML (Detalhamento, Extremos, Job Matching) — st.dataframe não
    permite desenhar uma barrinha fina/arredondada com preenchimento parcial
    por linha, só texto ou cor sólida de fundo por célula; por isso essas
    tabelas viraram HTML puro, com a "barrinha de progresso" desenhada à mão. */
    .htbl-wrap { overflow-y: auto; overflow-x: auto; border: 1px solid #E3E6EA; border-radius: 8px; }
    .htbl-row { display: flex; align-items: center; gap: 10px; padding: 7px 12px; border-bottom: 1px solid #F0F2F5; font-size: 13px; color: #232323; }
    .htbl-row.htbl-head { position: sticky; top: 0; background: #EDF1F3; font-weight: 700; color: #475569; font-size: 12px; z-index: 1; border-bottom: 1px solid #E3E6EA; }
    .htbl-row:not(.htbl-head):hover { background: #F8FAFB; }
    .htbl-cell { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    </style>
    """,
    unsafe_allow_html=True,
)

auth.init_db()
auth.require_login()

wordmark = _build_logo_wordmark(LOGO_PATH, "Aderência Salarial")
st.logo(wordmark if wordmark is not None else LOGO_PATH, icon_image=LOGO_PATH, size="large")


def _neon_database_url() -> str | None:
    try:
        return st.secrets["neon"]["database_url"]
    except Exception:
        return os.getenv("NEON_DATABASE_URL")


_MOCK_NIVEL_POR_FUNCAO = {
    "Analista": "Staff",
    "Engenheiro": "Supervisor/Advogado/Engenheiro",
    "Encarregado": "Staff",
    "Assistente": "Operacional",
    "Auxiliar": "Operacional",
    "Coordenador": "Coordenador/Especialista",
    "Ajudante": "Operacional",
    "Gerente": "Gerente",
}


def _make_mock_data() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Demonstração determinística — só usada quando o Neon está fora do ar."""
    rng = np.random.default_rng(7)
    cargos = [
        ("Analista Financeiro Junior", "Diretoria Adm. Financeira e RI", "Financeiro", "Corporativo", "Analista", 4200),
        ("Analista Financeiro Pleno", "Diretoria Adm. Financeira e RI", "Financeiro", "Corporativo", "Analista", 6200),
        ("Engenheiro Civil Junior", "Diretoria de Obras 1", "Obras SP", "Obras", "Engenheiro", 8500),
        ("Encarregado de Obras", "Diretoria de Obras 1", "Obras SP", "Obras", "Encarregado", 4900),
        ("Assistente Técnico", "Diretoria de Obras 2", "Obras MT", "Obras", "Assistente", 5100),
        ("Analista de Sistemas Pleno", "Diretoria Adm. Financeira e RI", "Tecnologia da Informação", "Corporativo", "Analista", 7100),
        ("Auxiliar de Cobrança", "Diretoria Adm. Financeira e RI", "Cobrança", "Corporativo", "Auxiliar", 2500),
        ("Coordenador de Vendas", "Diretoria Comercial", "Vendas", "Comercial", "Coordenador", 9800),
        ("Ajudante Geral", "Diretoria de Obras 1", "Obras SP", "Obras", "Ajudante", 2450),
        ("Gerente de Projetos", "Diretoria de Planejamento", "Planejamento", "Corporativo", "Gerente", 15500),
    ]
    people_rows, ref_rows = [], []
    bases = ["GRH ECI - Acima de 1000 Colaboradores", "Indústria da Construção", "Sudeste SP - Grande São Paulo"]
    now = pd.Timestamp.now()
    for cargo, diretoria, area, categoria, funcao, adequado in cargos:
        for base in bases:
            variacao = rng.normal(0, 0.04)
            ref_rows.append(
                {
                    "cargo_empresa": cargo,
                    "cargo_pesquisa": cargo,
                    "base_pesquisa": base,
                    "salario_adequado": round(adequado * (1 + variacao), 2),
                    "salario_minimo": None,
                    "salario_maximo": None,
                    "data_retirada": None,
                    "loaded_at": now,
                }
            )
        n = int(rng.integers(1, 40))
        salarios = adequado * rng.normal(0.92, 0.16, n).clip(0.4, 1.9)
        for i, salario in enumerate(salarios):
            people_rows.append(
                {
                    "id_funcionario": f"{cargo[:3]}-{i}",
                    "nome_funcionario": f"Colaborador {cargo[:3]}{i}",
                    "descricao_cargo": cargo,
                    "funcao_cargo": funcao,
                    "nivel_cargo": "40",
                    "gerenciamento_nivel_cargo": _MOCK_NIVEL_POR_FUNCAO.get(funcao, "Staff"),
                    "centro_de_custo": None,
                    "descricao_posicao": None,
                    "nome_diretoria": diretoria,
                    "nome_area": area,
                    "categoria_atribuicao": categoria,
                    "salario": round(float(salario), 2),
                    "loaded_at": now,
                }
            )
    return pd.DataFrame(people_rows), pd.DataFrame(ref_rows)


@st.cache_data(ttl="15m", show_spinner="Carregando dados de posicionamento salarial...")
def load_data() -> tuple[pd.DataFrame, pd.DataFrame, str]:
    """Pessoas ativas + referência de mercado, ambas do Neon (schema `interno`).

    `fato_funcionario_ativo` é o mirror pessoa a pessoa do Databricks (ver painel
    Headcount, etl/mirror_fatos_to_neon.py). `mercado_salarial_muller` é a
    referência de mercado carregada por etl/upload_faixas_salariais.py a partir
    do consolidado Carreira Muller. Cai pro mock local se a conexão falhar.
    """
    database_url = _neon_database_url()
    if database_url:
        try:
            import psycopg2

            with psycopg2.connect(database_url) as connection:
                people = pd.read_sql(
                    f"""
                    SELECT id_funcionario, nome_funcionario, descricao_cargo, funcao_cargo, nivel_cargo,
                           gerenciamento_nivel_cargo, centro_de_custo, descricao_posicao,
                           nome_diretoria, nome_area, categoria_atribuicao, salario, loaded_at
                    FROM {PEOPLE_TABLE}
                    WHERE salario IS NOT NULL AND salario > 0
                    """,
                    connection,
                )
                reference = pd.read_sql(
                    f"""
                    SELECT cargo_empresa, cargo_pesquisa, base_pesquisa, salario_adequado,
                           salario_minimo, salario_maximo, data_retirada, loaded_at
                    FROM {MARKET_TABLE}
                    """,
                    connection,
                )
            return people, reference, "Neon"
        except Exception as exc:
            print(f"[posicionamento] Neon connection failed, falling back to mock: {exc}")
    people, reference = _make_mock_data()
    return people, reference, "Mock local"


def format_currency(value: float) -> str:
    if pd.isna(value):
        return "—"
    return f"R$ {value:,.0f}".replace(",", ".")


def format_number(value: float | int) -> str:
    return f"{int(round(value)):,}".replace(",", ".")


def _excel_download_button(df: pd.DataFrame, label: str, file_name: str, key: str) -> None:
    """Botão de exportar em Excel de verdade (.xlsx via openpyxl, já na
    lista de dependências), não um CSV com outro nome — pedido em todas as
    tabelas do painel. Exporta exatamente o recorte exibido (já filtrado/
    ordenado), não a base inteira."""
    buffer = io.BytesIO()
    df.to_excel(buffer, index=False, engine="openpyxl")
    st.download_button(
        label,
        data=buffer.getvalue(),
        file_name=file_name,
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        key=key,
    )


def _ordered_options(values: pd.Series) -> list[str]:
    return sorted(set(values.dropna()))


def _dist_ideal(pct) -> "pd.Series | float":
    """0 dentro da faixa ideal (80%-120%); cresce simetricamente pra qualquer
    lado a partir daí — mesma métrica usada nas bolinhas do gráfico, na barra
    de "% do adequado" do Detalhamento e no indicador de aderência do Job
    Matching, pra manter uma única régua visual de "quão longe do ideal"."""
    return np.maximum(PISO_IDEAL - pct, 0) + np.maximum(pct - TETO_IDEAL, 0)


def _classificar(pct) -> "pd.Series | str":
    return np.select([pct < PISO_IDEAL, pct > TETO_IDEAL], ["Abaixo", "Acima"], default="Dentro")


def _severity_color(pct: float) -> str:
    """Gradiente contínuo azul -> vermelho, usado só para quem está FORA da
    faixa ideal: parte do próprio BRAND_COLOR bem na borda da faixa (mesmo
    tom de quem está "dentro" — sem costura na transição) e vai ficando mais
    vermelho quanto maior a distância."""
    if pd.isna(pct):
        return "#9AA3AE"
    t = min(_dist_ideal(pct), DIST_MAX) / DIST_MAX
    lr, lg, lb = 0x06, 0x4D, 0x66  # BRAND_COLOR
    dr, dg, db = 0xD0, 0x3B, 0x3B  # RED
    r = round(lr + (dr - lr) * t)
    g = round(lg + (dg - lg) * t)
    b = round(lb + (db - lb) * t)
    return f"#{r:02x}{g:02x}{b:02x}"


def _dot_color(pct: float) -> str:
    """Cor das bolinhas do gráfico e (indiretamente) dos blocos das barrinhas
    de aderência: azul sólido, sem gradiente, pra quem está dentro da faixa
    ideal (80%-120%) — corte categórico, não sequencial, pedido explicitamente
    pelo usuário; fora da faixa, vermelho sequencial por distância."""
    if pd.isna(pct):
        return "#9AA3AE"
    if PISO_IDEAL <= pct <= TETO_IDEAL:
        return BRAND_COLOR
    return _severity_color(pct)


BAR_SCALE_MAX = 200.0  # eixo 0%-200% — mesmo teto do ProgressColumn original
BAR_TRACK_COLOR = "#E3E6EA"
BAR_MARKER_COLOR = "#94A3B8"


def _render_html_meter(pct: float, width_px: int = 130) -> str:
    """Barrinha de progresso fina e arredondada (HTML/CSS puro): trilho cinza
    claro, preenchimento colorido (azul dentro da faixa ideal, vermelho fora
    — mesma régua de `_dot_color`) até a posição de `pct` no eixo 0%-200%, e
    3 marcadores fixos (80%/100%/120%) — mesmas referências das linhas verdes
    e da linha tracejada do gráfico de dispersão. `st.dataframe` (a tabela
    nativa) só permite texto puro ou uma cor sólida de fundo por célula — não
    dá pra desenhar isso ali, por isso as tabelas com essa barra usam
    `_render_html_table` (HTML puro) em vez de `st.dataframe`."""
    if pd.isna(pct):
        return "—"
    color = _dot_color(pct)
    fill_pct = max(0.0, min(100.0, pct / BAR_SCALE_MAX * 100))
    dots = "".join(
        f'<span style="position:absolute;left:{marker / BAR_SCALE_MAX * 100:.2f}%;top:50%;'
        f'transform:translate(-50%,-50%);width:5px;height:5px;border-radius:50%;'
        f'background:{BAR_MARKER_COLOR};"></span>'
        for marker in (PISO_IDEAL, 100, TETO_IDEAL)
    )
    return (
        '<div style="display:flex;align-items:center;gap:8px;">'
        f'<div style="position:relative;width:{width_px}px;height:6px;background:{BAR_TRACK_COLOR};'
        'border-radius:999px;flex-shrink:0;">'
        f'<div style="position:absolute;left:0;top:0;height:100%;width:{fill_pct:.1f}%;'
        f'background:{color};border-radius:999px;"></div>'
        f"{dots}"
        "</div>"
        f'<span style="font-size:12.5px;font-weight:600;white-space:nowrap;">{pct:.0f}%</span>'
        "</div>"
    )


def _html_cell_value(col: dict, value) -> str:
    kind = col.get("kind", "text")
    if kind == "bar":
        return _render_html_meter(value, width_px=col.get("bar_width", 130))
    if pd.isna(value):
        text = "—"
    elif kind == "currency":
        text = format_currency(value)
    elif kind == "int":
        text = format_number(value)
    else:
        text = html_lib.escape(str(value))
    weight = "700" if col.get("bold_if_one") and value == 1 else "400"
    return f'<span style="font-weight:{weight};">{text}</span>'


def _cell_style(col: dict) -> str:
    """`flex-shrink:0` + `min-width` em toda célula — sem isso, uma tabela
    com muitas colunas espreme as flexíveis (Cargo, Diretoria...) até truncar
    ilegível em vez de rolar horizontalmente (bug visto em teste real)."""
    flex = col["flex"]
    min_w = col.get("min_width")
    if min_w is None and not flex.startswith("0 0"):
        min_w = 140  # coluna "livre" (Cargo, Diretoria...) sem largura fixa própria
    style = f"flex:{flex};text-align:{col.get('align', 'left')};flex-shrink:0;"
    if min_w:
        style += f"min-width:{min_w}px;"
    return style


def _render_html_table(df: pd.DataFrame, columns: list[dict], max_height: int = 480) -> None:
    """Tabela em HTML puro (sem `st.dataframe`) — único jeito de desenhar a
    barrinha de progresso por linha (ver `_render_html_meter`). Cada item de
    `columns`: {"key": coluna no df, "label": cabeçalho, "flex": tamanho
    flexbox, "align": "left"/"right", "kind": "text"/"currency"/"int"/"bar",
    "bold_if_one": True (negrita o valor quando == 1, pra "Qtd."),
    "min_width": largura mínima em px (opcional, tem um padrão razoável)}."""
    row_min_width = sum(
        float(c["min_width"]) if c.get("min_width") is not None
        else float(c["flex"].split()[-1].rstrip("px")) if c["flex"].startswith("0 0")
        else 140
        for c in columns
    )
    header = "".join(f'<div class="htbl-cell" style="{_cell_style(c)}">{html_lib.escape(c["label"])}</div>' for c in columns)
    rows = []
    for _, row in df.iterrows():
        cells = "".join(
            f'<div class="htbl-cell" style="{_cell_style(c)}">{_html_cell_value(c, row[c["key"]])}</div>' for c in columns
        )
        rows.append(f'<div class="htbl-row" style="min-width:{row_min_width:.0f}px;">{cells}</div>')
    doc = (
        f'<div class="htbl-wrap" style="max-height:{max_height}px;">'
        f'<div class="htbl-row htbl-head" style="min-width:{row_min_width:.0f}px;">{header}</div>'
        + "".join(rows)
        + "</div>"
    )
    st.markdown(doc, unsafe_allow_html=True)


def _kpi_card_spec(label: str, value_text: str, value_color: str, subtitle_text: str, subtitle_color: str) -> dict:
    """Mesmo spec do card de KPI do painel Headcount (ribbon navy + faixa dourada)."""

    def _layer(mark: dict, encoding: dict) -> dict:
        return {"data": {"values": [{}]}, "mark": mark, "encoding": encoding}

    return {
        "width": "container",
        "height": "container",
        "config": {
            "autosize": {"type": "fit", "contains": "padding"},
            "view": {"stroke": None, "fill": "#FFFFFF"},
            "text": {"font": "sans-serif"},
        },
        "layer": [
            _layer(
                {"type": "rect", "color": "#FAB900", "tooltip": None},
                {"x": {"value": 0}, "x2": {"value": {"expr": "width"}}, "y": {"value": {"expr": "height-7"}}, "y2": {"value": {"expr": "height"}}},
            ),
            _layer(
                {"type": "rect", "color": "#064D66", "tooltip": None},
                {"x": {"value": 0}, "x2": {"value": {"expr": "width"}}, "y": {"value": 0}, "y2": {"value": {"expr": "height*0.20"}}},
            ),
            _layer(
                {"type": "rect", "color": "#FFFFFF", "tooltip": None},
                {
                    "x": {"value": {"expr": "width*0.88 - height*0.10"}},
                    "x2": {"value": {"expr": "width*0.88 + height*0.10 + 1"}},
                    "y": {"value": 0}, "y2": {"value": {"expr": "height*0.21"}},
                },
            ),
            _layer(
                {
                    "type": "point", "shape": "square", "filled": True, "fill": "#FFFFFF",
                    "color": "#FFFFFF", "stroke": None, "strokeWidth": 0, "opacity": 1, "fillOpacity": 1,
                    "tooltip": None,
                },
                {
                    "x": {"value": {"expr": "width*0.88 + height*0.15"}},
                    "y": {"value": {"expr": "height*0.105"}},
                    "size": {"value": {"expr": "pow(height*0.20, 2)"}},
                    "angle": {"value": 45},
                },
            ),
            _layer(
                {
                    "type": "text", "font": "sans-serif", "color": "#FFFFFF", "fontSize": 10,
                    "fontWeight": "bold", "align": "left", "baseline": "middle",
                    "limit": {"expr": "width*0.72 - 14"},
                },
                {"x": {"value": 14}, "y": {"value": {"expr": "height*0.10"}}, "text": {"value": label.upper()}},
            ),
            _layer(
                {
                    "type": "text", "font": "sans-serif", "color": value_color, "fontSize": 30,
                    "fontWeight": "700", "align": "center", "baseline": "middle",
                    "limit": {"expr": "width - 12"},
                },
                {"x": {"value": {"expr": "width/2"}}, "y": {"value": {"expr": "height*0.55"}}, "text": {"value": value_text}},
            ),
            _layer(
                {
                    "type": "text", "font": "sans-serif", "color": subtitle_color, "fontSize": 11,
                    "fontWeight": "600", "align": "center", "baseline": "middle",
                    "limit": {"expr": "width - 12"},
                },
                {"x": {"value": {"expr": "width/2"}}, "y": {"value": {"expr": "height*0.83"}}, "text": {"value": subtitle_text}},
            ),
        ],
    }


def render_kpi_card(label: str, value_text: str, subtitle_text: str, subtitle_color: str = "#6B7280", value_color: str = "#1F2937", height: int = 140) -> None:
    spec = _kpi_card_spec(label, value_text, value_color, subtitle_text, subtitle_color)
    card_key = "".join(ch for ch in label if ch.isalnum()).lower()
    with st.container(key=f"kpi-card-{card_key}"):
        st.vega_lite_chart(spec, width="stretch", height=height, theme=None, key=f"kpi-vega-{card_key}-{value_text}-{subtitle_text}")


def render_dispersion_chart(data: pd.DataFrame, height: int) -> None:
    """Mapa de dispersão pessoa a pessoa: salário (x) vs. % do salário adequado
    de mercado (y), eixo fixo em 60%-140%. Linhas verdes em 80%/120% marcam a
    faixa ideal de aderência; linha tracejada cinza em 100% marca o adequado.
    Cor das bolinhas: azul sólido (sem gradiente) pra quem está dentro da
    faixa ideal — corte categórico, não sequencial, pedido explicitamente;
    fora da faixa, vermelho sequencial por distância (mais longe, mais
    vermelho). Sem legenda — a cor já é auto-explicada pelas linhas verdes e
    pelo texto acima do gráfico. Pontos fora de 60%-140% ficam "grudados" na
    borda (scale clamp) — contados à parte no rodapé, não descartados
    silenciosamente."""
    points = (
        alt.Chart(data)
        .mark_circle(size=65, opacity=0.75, stroke="#FFFFFF", strokeWidth=0.4)
        .encode(
            x=alt.X("salario:Q", title="Salário mensal (R$)", scale=alt.Scale(zero=False), axis=alt.Axis(format=",.0f")),
            y=alt.Y("pct:Q", title="% do salário adequado de mercado", scale=alt.Scale(domain=[FAIXA_MIN, FAIXA_MAX], clamp=True)),
            color=alt.Color("cor:N", scale=None, legend=None),
            tooltip=[
                alt.Tooltip("nome_funcionario:N", title="Colaborador"),
                alt.Tooltip("descricao_cargo:N", title="Cargo"),
                alt.Tooltip("nome_diretoria:N", title="Diretoria"),
                alt.Tooltip("nome_area:N", title="Área"),
                alt.Tooltip("salario:Q", title="Salário", format=",.0f"),
                alt.Tooltip("salario_adequado:Q", title="Adequado (mercado)", format=",.0f"),
                alt.Tooltip("pct:Q", title="% do adequado", format=".1f"),
            ],
        )
    )
    ref_lines = pd.DataFrame({"y": [PISO_IDEAL, 100, TETO_IDEAL], "rotulo": [f"{PISO_IDEAL}%", "Adequado (100%)", f"{TETO_IDEAL}%"]})
    lines = (
        alt.Chart(ref_lines)
        .mark_rule(strokeWidth=2)
        .encode(
            # Domínio explícito igual ao dos pontos — sem isso, o Vega-Lite infere o
            # domínio desta camada a partir só destes 3 valores com "zero: true"
            # (padrão de escala quantitativa), estende pra [0, 120] e, ao unir com a
            # escala compartilhada da camada de pontos, o eixo Y acaba virando [0, 140]
            # em vez do [60, 140] pedido.
            y=alt.Y("y:Q", scale=alt.Scale(domain=[FAIXA_MIN, FAIXA_MAX])),
            color=alt.condition(alt.datum.y == 100, alt.value(GRAY), alt.value(GREEN)),
            strokeDash=alt.condition(alt.datum.y == 100, alt.value([5, 4]), alt.value([1, 0])),
            tooltip=[alt.Tooltip("rotulo:N", title="Referência")],
        )
    )
    chart = (lines + points).properties(height=height).interactive()
    st.altair_chart(chart, width="stretch")


# Agrupamentos puramente visuais pro gráfico por nível de gerenciamento — menos
# divisões pra caber sem espremer o eixo. Não muda o dado em si, só como esse
# gráfico especificamente agrega `gerenciamento_nivel_cargo`.
NIVEL_GERENCIAMENTO_AGRUPADO = {
    "Gerente de Vendas": "Gerente",
    "Gerente Executivo de Obras": "Gerente Executivo",
    "Coordenador de Obras": "Coordenador/Especialista",
}

# Nomes curtos só pro rótulo do eixo — os originais estouram a largura
# disponível e o Vega-Lite trunca ("Coordenador/Esp…").
NIVEL_NOME_CURTO = {
    "Coordenador/Especialista": "Coord./Especialista",
    "Supervisor/Advogado/Engenheiro": "Supervisor/Adv./Eng.",
}

STATUS_ORDER = ["Abaixo", "Dentro", "Acima"]
STATUS_COLOR = {"Abaixo": RED, "Dentro": GREEN, "Acima": ORANGE}
STATUS_ORDEM_NUM = {"Abaixo": 0, "Dentro": 1, "Acima": 2}


NIVEL_GERAL = "Geral (todos os níveis)"


def render_nivel_breakdown(data: pd.DataFrame, height: int = 340) -> None:
    """Barra horizontal 100% empilhada (Abaixo/Dentro/Acima) por nível de
    gerenciamento — substitui a pizza geral + a barra de "% dentro" por 1
    gráfico só: a pizza só repetia os KPIs do topo sem cruzar com nível, e as
    2 lado a lado não se equilibravam visualmente (pizza pequena e centrada
    x barra ocupando a largura toda). Ordenado pelo % dentro da faixa ideal,
    com uma barra "Geral" fixa no topo (não entra na ordenação) resumindo o
    total do recorte — substitui a legenda textual que ficava acima do
    gráfico."""
    nivel = data["gerenciamento_nivel_cargo"].replace(NIVEL_GERENCIAMENTO_AGRUPADO).replace(NIVEL_NOME_CURTO)
    resumo = (
        data.assign(nivel=nivel)
        .groupby(["nivel", "classificacao"])
        .size()
        .reset_index(name="quantidade")
    )
    geral = (
        data.groupby("classificacao").size().reset_index(name="quantidade").assign(nivel=NIVEL_GERAL)
    )
    resumo = pd.concat([geral, resumo], ignore_index=True)
    resumo["ordem_num"] = resumo["classificacao"].map(STATUS_ORDEM_NUM)

    totais = resumo.groupby("nivel")["quantidade"].sum()
    dentro_por_nivel = (
        resumo[resumo["classificacao"] == "Dentro"].set_index("nivel")["quantidade"].reindex(totais.index).fillna(0)
    )
    pct_dentro = dentro_por_nivel / totais
    ordem_niveis = [NIVEL_GERAL] + pct_dentro.drop(NIVEL_GERAL).sort_values(ascending=True).index.tolist()

    chart = (
        alt.Chart(resumo)
        .mark_bar()
        .encode(
            y=alt.Y("nivel:N", title=None, sort=ordem_niveis, axis=alt.Axis(labelLimit=200)),
            x=alt.X(
                "quantidade:Q",
                title="% de colaboradores",
                stack="normalize",
                axis=alt.Axis(format=".0%"),
            ),
            color=alt.Color(
                "classificacao:N",
                title=None,
                scale=alt.Scale(domain=STATUS_ORDER, range=[STATUS_COLOR[s] for s in STATUS_ORDER]),
                legend=alt.Legend(orient="bottom"),
            ),
            order=alt.Order("ordem_num:Q"),
            tooltip=[
                alt.Tooltip("nivel:N", title="Nível de gerenciamento"),
                alt.Tooltip("classificacao:N", title="Classificação"),
                alt.Tooltip("quantidade:Q", title="Colaboradores"),
            ],
        )
        .properties(height=height)
    )
    st.altair_chart(chart, width="stretch")


# Painel trabalha só de Executivo pra baixo — Diretor/Presidente/Conselheiro
# ficam fora (decisão do usuário, 2026-09-15): são níveis de topo, pouco
# comparáveis pela pesquisa de mercado (ver CONTEXT.md) e fora do escopo deste
# painel. Filtra por `funcao_cargo` bruto (valores exatos confirmados no
# Neon), antes de qualquer outro filtro — não aparecem nem como opção na
# sidebar nem em nenhuma tabela/gráfico.
NIVEIS_EXCLUIDOS = ["Diretor", "Presidente", "Conselheiro"]

all_people, all_reference, source_name = load_data()
all_people = all_people[~all_people["funcao_cargo"].isin(NIVEIS_EXCLUIDOS)]
all_people["nome_diretoria"] = all_people["nome_diretoria"].fillna("Não informado")
all_people["nome_area"] = all_people["nome_area"].fillna("Não informado")
all_people["categoria_atribuicao"] = all_people["categoria_atribuicao"].fillna("Não informado")
all_people["funcao_cargo"] = all_people["funcao_cargo"].fillna("Não informado")
all_people["gerenciamento_nivel_cargo"] = all_people["gerenciamento_nivel_cargo"].fillna("Não informado")
all_people["descricao_cargo"] = all_people["descricao_cargo"].str.strip()
all_reference["cargo_empresa"] = all_reference["cargo_empresa"].str.strip()

if source_name == "Neon":
    # `nome_diretoria`/`nome_area` do mirror bruto (rh.gold) ficam desatualizados
    # depois de reorganizações — mesma correção manual por centro de custo que o
    # painel Headcount já aplica (ver etl/mapping_diretoria.py). Substitui os
    # valores brutos globalmente (filtros, gráfico, tabelas, Job Matching).
    resolved = [
        mapping_diretoria.resolve_diretoria_area(cc, pos, pid)
        for cc, pos, pid in zip(all_people["centro_de_custo"], all_people["descricao_posicao"], all_people["id_funcionario"])
    ]
    if resolved:
        all_people["nome_diretoria"], all_people["nome_area"] = zip(*resolved)

pessoas_loaded_at = all_people["loaded_at"].max() if "loaded_at" in all_people and not all_people.empty else None
mercado_loaded_at = all_reference["loaded_at"].max() if "loaded_at" in all_reference and not all_reference.empty else None

diretoria_options = _ordered_options(all_people["nome_diretoria"])
area_options = _ordered_options(all_people["nome_area"])
categoria_options = _ordered_options(all_people["categoria_atribuicao"])
funcao_options = _ordered_options(all_people["funcao_cargo"])
base_options = _ordered_options(all_reference["base_pesquisa"])

auth.render_sidebar_account()

with st.sidebar:
    st.caption(
        "Mapa de dispersão salarial: compara o salário individual com a referência de "
        "mercado (Carreira Muller) do cargo equivalente."
    )
    st.markdown("## Explorar dados")
    selected_base = st.selectbox("Base de pesquisa de mercado", options=base_options, index=0)
    _data_retirada_base = all_reference.loc[all_reference["base_pesquisa"] == selected_base, "data_retirada"].max()
    if pd.notna(_data_retirada_base):
        st.caption(f"Relatório retirado em {_data_retirada_base:%d/%m/%Y}")
    selected_diretorias = st.multiselect("Diretoria", options=diretoria_options, default=[], placeholder="Todas")
    selected_areas = st.multiselect("Área", options=area_options, default=[], placeholder="Todas")
    selected_categorias = st.multiselect("Categoria de Atribuição", options=categoria_options, default=[], placeholder="Todas")
    selected_funcoes = st.multiselect("Função de cargo", options=funcao_options, default=[], placeholder="Todas")
    st.caption(f"Fonte: {'Neon' if source_name == 'Neon' else source_name}")


def _mask(column: pd.Series, selected: list[str]) -> pd.Series:
    if not selected:
        return pd.Series(True, index=column.index)
    return column.isin(selected)


filtered_people = all_people[
    _mask(all_people["nome_diretoria"], selected_diretorias)
    & _mask(all_people["nome_area"], selected_areas)
    & _mask(all_people["categoria_atribuicao"], selected_categorias)
    & _mask(all_people["funcao_cargo"], selected_funcoes)
]

reference_for_base = all_reference[all_reference["base_pesquisa"] == selected_base]
merged = filtered_people.merge(
    reference_for_base[["cargo_empresa", "cargo_pesquisa", "salario_adequado"]],
    left_on="descricao_cargo",
    right_on="cargo_empresa",
    how="left",
)
plotted = merged.dropna(subset=["salario_adequado"]).copy()
plotted = plotted[plotted["salario_adequado"] > 0]
plotted["pct"] = plotted["salario"] / plotted["salario_adequado"] * 100
sem_referencia = len(filtered_people) - len(plotted)

plotted["classificacao"] = _classificar(plotted["pct"])
plotted["dist_ideal"] = _dist_ideal(plotted["pct"])
plotted["cor"] = plotted["pct"].apply(_dot_color)

tab_aderencia, tab_job_matching = st.tabs(["Aderência Salarial", "Job Matching"])

with tab_aderencia:
    with st.container(horizontal=True, vertical_alignment="center"):
        st.markdown("### Posicionamento na Tabela Salarial")
        st.badge("Dados sensíveis — acesso restrito", icon=":material/lock:", color="red")
        st.badge(selected_base, icon=":material/query_stats:", color="blue")

    caption_slot = st.empty()
    kpi_slot = st.container()

    with st.container(border=True, key="card-scatter"):
        st.subheader("Dispersão salarial pessoa a pessoa")
        st.caption(
            "Cada ponto é um colaborador: azul quando está dentro da faixa ideal de aderência "
            f"({PISO_IDEAL}%–{TETO_IDEAL}%, marcada pelas linhas verdes); quanto mais avermelhado, mais "
            "longe dela, pra qualquer lado. A linha tracejada cinza marca o salário adequado (100%). "
            f"Eixo fixo entre {FAIXA_MIN}% e {FAIXA_MAX}% — pontos fora desse intervalo aparecem colados "
            "na borda."
        )
        selected_classes = st.multiselect(
            "Classificação (aderência)",
            options=["Abaixo", "Dentro", "Acima"],
            default=[],
            placeholder="Todas",
            key="classificacao_filtro",
        )
        plotted_view = plotted if not selected_classes else plotted[plotted["classificacao"].isin(selected_classes)]
        if plotted_view.empty:
            st.warning("Não há colaboradores com referência de mercado disponível para este recorte de filtros.")
            st.stop()
        render_dispersion_chart(plotted_view, height=560)

    caption_slot.caption(
        f"{format_number(len(plotted_view))} colaboradores plotados neste recorte · "
        f"{format_number(sem_referencia)} sem cargo equivalente na pesquisa de mercado selecionada (não plotados)"
    )

    status_counts = plotted_view["classificacao"].value_counts()
    abaixo = status_counts.get("Abaixo", 0) / len(plotted_view) * 100
    dentro = status_counts.get("Dentro", 0) / len(plotted_view) * 100
    acima = status_counts.get("Acima", 0) / len(plotted_view) * 100
    mediana = plotted_view["pct"].median()

    with kpi_slot:
        kpi_cols = st.columns(5)
        with kpi_cols[0]:
            render_kpi_card("Colaboradores no filtro", format_number(len(plotted_view)), f"{format_number(sem_referencia)} sem referência de mercado")
        with kpi_cols[1]:
            render_kpi_card("Dentro da faixa ideal", f"{dentro:.0f}%", f"Entre {PISO_IDEAL}% e {TETO_IDEAL}% do adequado", value_color=GREEN)
        with kpi_cols[2]:
            render_kpi_card("Abaixo da faixa ideal", f"{abaixo:.0f}%", f"Menos de {PISO_IDEAL}% do adequado", value_color=RED)
        with kpi_cols[3]:
            render_kpi_card("Acima da faixa ideal", f"{acima:.0f}%", f"Mais de {TETO_IDEAL}% do adequado", value_color=ORANGE)
        with kpi_cols[4]:
            render_kpi_card("Mediana de aderência", f"{mediana:.0f}%", "% do salário adequado", value_color=BRAND_COLOR)

    with st.container(border=True, key="card-pizza-nivel"):
        st.subheader("Aderência por nível de gerenciamento")
        render_nivel_breakdown(plotted_view)

    with st.expander("Detalhamento", expanded=False, key="card-detalhe"):
        st.caption("Dados sensíveis — não compartilhe fora do time autorizado.")
        detail = plotted_view.rename(
            columns={
                "nome_funcionario": "Colaborador",
                "descricao_cargo": "Cargo",
                "nome_diretoria": "Diretoria",
                "nome_area": "Área",
                "salario": "Salário",
                "salario_adequado": "Adequado (mercado)",
                "pct": "% do adequado",
            }
        )[["Colaborador", "Cargo", "Diretoria", "Área", "Salário", "Adequado (mercado)", "% do adequado"]]

        busca_col, ordenar_col, ordem_col = st.columns([2, 1.4, 1])
        with busca_col:
            busca = st.text_input(
                "Buscar por colaborador, cargo, diretoria ou área",
                key="detalhe_busca",
                placeholder="Digite para filtrar...",
            )
        with ordenar_col:
            ordenar_por = st.selectbox(
                "Ordenar por",
                options=["% do adequado", "Salário", "Colaborador", "Cargo", "Diretoria"],
                key="detalhe_ordenar",
            )
        with ordem_col:
            ordem_desc = st.toggle("Decrescente", key="detalhe_desc")

        if busca.strip():
            termo = busca.strip().lower()
            detail = detail[
                detail["Colaborador"].str.lower().str.contains(termo, na=False)
                | detail["Cargo"].str.lower().str.contains(termo, na=False)
                | detail["Diretoria"].str.lower().str.contains(termo, na=False)
                | detail["Área"].str.lower().str.contains(termo, na=False)
            ]
        detail = detail.sort_values(ordenar_por, ascending=not ordem_desc)

        _render_html_table(
            detail,
            columns=[
                {"key": "Colaborador", "label": "Colaborador", "flex": "1.3"},
                {"key": "Cargo", "label": "Cargo", "flex": "1.3"},
                {"key": "Diretoria", "label": "Diretoria", "flex": "1.2"},
                {"key": "Área", "label": "Área", "flex": "1.1"},
                {"key": "Salário", "label": "Salário", "flex": "0 0 90px", "align": "right", "kind": "currency"},
                {"key": "Adequado (mercado)", "label": "Adequado", "flex": "0 0 90px", "align": "right", "kind": "currency"},
                {"key": "% do adequado", "label": "% do adequado", "flex": "0 0 180px", "kind": "bar"},
            ],
        )
        _excel_download_button(detail, "Exportar para Excel", "detalhamento_aderencia_salarial.xlsx", key="excel_detalhe")

    with st.container(border=True, key="card-top5"):
        st.subheader("Extremos da tabela salarial")
        col_abaixo, col_acima = st.columns(2)
        top_cols = {
            "nome_funcionario": "Colaborador",
            "descricao_cargo": "Cargo",
            "pct": "% do adequado",
        }
        top5_columns = [
            {"key": "Colaborador", "label": "Colaborador", "flex": "1.3"},
            {"key": "Cargo", "label": "Cargo", "flex": "1.3"},
            {"key": "% do adequado", "label": "% do adequado", "flex": "0 0 180px", "kind": "bar"},
        ]
        with col_abaixo:
            st.caption("5 colaboradores mais abaixo do adequado")
            top5_abaixo = plotted_view.nsmallest(5, "pct")[list(top_cols)].rename(columns=top_cols)
            _render_html_table(top5_abaixo, columns=top5_columns, max_height=260)
            _excel_download_button(top5_abaixo, "Exportar para Excel", "top5_abaixo_adequado.xlsx", key="excel_top5_abaixo")
        with col_acima:
            st.caption("5 colaboradores mais acima do adequado")
            top5_acima = plotted_view.nlargest(5, "pct")[list(top_cols)].rename(columns=top_cols)
            _render_html_table(top5_acima, columns=top5_columns, max_height=260)
            _excel_download_button(top5_acima, "Exportar para Excel", "top5_acima_adequado.xlsx", key="excel_top5_acima")

    with st.expander("Sobre este painel"):
        st.write(
            "Compara o salário individual de cada colaborador ativo com a referência de mercado da "
            "Carreira Muller para o cargo equivalente. O valor de referência (100%) é o "
            "\"salário adequado\" da pesquisa de mercado selecionada na barra lateral."
        )
        st.write(
            "O cruzamento é feito por nome do cargo interno (`descricao_cargo`) contra o cargo "
            "equivalente mapeado na pesquisa (`Cargo_Empresa`). Cargos sem equivalente na pesquisa "
            "(ex.: posições de diretoria, cargos muito recentes) ficam de fora do gráfico — contados "
            "à parte na legenda acima, e listados na aba \"Job Matching\"."
        )
        st.caption(f"Fonte atual: {source_name} · Referência de mercado: etl/upload_faixas_salariais.py")

with tab_job_matching:
    st.markdown("### Job Matching — cargos comparados na Carreira Muller")
    st.caption(
        "Cobertura da pesquisa de mercado sobre os cargos internos (recorte de filtros da barra lateral, "
        "exceto Classificação — que é específica da aba Aderência Salarial)."
    )

    cargo_stats = (
        filtered_people.groupby("descricao_cargo")
        .agg(qtd=("salario", "size"), sal_min=("salario", "min"), sal_mediana=("salario", "median"), sal_max=("salario", "max"))
        .reset_index()
    )
    cargo_ref = reference_for_base[
        ["cargo_empresa", "cargo_pesquisa", "salario_adequado", "salario_minimo", "salario_maximo", "data_retirada"]
    ].drop_duplicates("cargo_empresa")
    cargo_matched = cargo_stats.merge(cargo_ref, left_on="descricao_cargo", right_on="cargo_empresa", how="left")
    com_matching = cargo_matched[cargo_matched["salario_adequado"].notna()].copy()
    sem_matching = cargo_matched[cargo_matched["salario_adequado"].isna()].copy()

    cargos_total = len(cargo_matched)
    cargos_sem_pct = len(sem_matching) / cargos_total * 100 if cargos_total else 0
    pessoas_total = cargo_matched["qtd"].sum()
    pessoas_sem_pct = sem_matching["qtd"].sum() / pessoas_total * 100 if pessoas_total else 0

    def _render_coverage_bar(pct_sem: float, height: int = 40) -> None:
        """Barra horizontal única 100% empilhada: Com referência x Sem
        referência. Sem eixo numérico (0-100 com marcações a cada 5 unidades
        era denso demais pra uma barra de 2 segmentos só, e disputava espaço
        com a legenda logo acima) — o valor de cada segmento vai direto nele,
        como rótulo. Posição do rótulo calculada no Python (início/fim/meio
        de cada segmento) em vez de depender do texto acompanhar o `stack`
        automático do Vega-Lite, que não posiciona texto do mesmo jeito que
        barras. Sem nenhum encoding de posição vertical (`y`), o Vega-Lite
        colapsa a área do gráfico pra altura 0 (confirmado inspecionando o
        SVG gerado) — por isso a marca usa altura literal em pixels
        (`mark_bar(height=...)`), que não depende da escala de banda."""
        data = pd.DataFrame({"situacao": ["Com referência", "Sem referência"], "pct": [100 - pct_sem, pct_sem]})
        data["fim"] = data["pct"].cumsum()
        data["inicio"] = data["fim"] - data["pct"]
        data["meio"] = (data["inicio"] + data["fim"]) / 2
        data["rotulo"] = data["pct"].round().astype(int).astype(str) + "%"

        base = alt.Chart(data).encode(
            color=alt.Color(
                "situacao:N",
                title=None,
                scale=alt.Scale(domain=["Com referência", "Sem referência"], range=[BRAND_COLOR, GRAY]),
                legend=None,
            ),
            tooltip=[
                alt.Tooltip("situacao:N", title="Situação"),
                alt.Tooltip("pct:Q", title="%", format=".1f"),
            ],
        )
        bars = base.mark_bar(height=height - 12).encode(
            x=alt.X("inicio:Q", title=None, scale=alt.Scale(domain=[0, 100]), axis=None),
            x2="fim:Q",
        )
        # `color=alt.value(...)` explícito — sem isso, o encoding de cor herdado
        # do `base` (escala navy/cinza por categoria) sobrescreve a cor do mark,
        # e o texto sai da mesma cor do fundo (invisível, bug visto em teste real).
        labels = base.mark_text(fontWeight=700, fontSize=12).encode(
            x="meio:Q", text="rotulo:N", color=alt.value("#FFFFFF")
        )
        st.altair_chart((bars + labels).properties(height=height), width="stretch")

    with st.container(border=True, key="card-jobmatching-overview"):
        # Legenda única compartilhada pelos 2 gráficos (em vez da legenda nativa
        # do Altair, que disputava espaço vertical com os eixos num gráfico de
        # só 60px de altura e ficava sobreposta).
        st.markdown(
            f'<span style="color:{BRAND_COLOR}">●</span> Com referência &nbsp;&nbsp;&nbsp;'
            f'<span style="color:{GRAY}">●</span> Sem referência',
            unsafe_allow_html=True,
        )
        col_cargos, col_colab = st.columns(2)
        with col_cargos:
            st.markdown(f"**Cargos** · {cargos_sem_pct:.0f}% sem referência")
            _render_coverage_bar(cargos_sem_pct)
        with col_colab:
            st.markdown(f"**Colaboradores** · {pessoas_sem_pct:.0f}% sem referência")
            _render_coverage_bar(pessoas_sem_pct)

    with st.container(border=True, key="card-jobmatching-tabelas"):
        st.subheader(f"Cargos com Job Matching ({len(com_matching)})")
        com_matching["Aderência à Mediana Mercado"] = com_matching["sal_mediana"] / com_matching["salario_adequado"] * 100
        com_matching["classificacao"] = _classificar(com_matching["Aderência à Mediana Mercado"])
        filtro_classificacao = st.multiselect(
            "Cargos por aderência (mediana interna x mercado)",
            options=["Abaixo", "Dentro", "Acima"],
            default=[],
            placeholder="Todas",
            key="jm_filtro_classificacao",
        )
        com_view = com_matching if not filtro_classificacao else com_matching[com_matching["classificacao"].isin(filtro_classificacao)]

        com_view = com_view.assign(
            **{
                "Qtd.": com_view["qtd"],
                "Salário Interno (mediana)": com_view["sal_mediana"],
                "Faixa Interna": np.where(
                    com_view["sal_min"].round() != com_view["sal_max"].round(),
                    com_view["sal_min"].apply(format_currency) + " – " + com_view["sal_max"].apply(format_currency),
                    "—",
                ),
                # Mínimo/Máximo reais quando o recorte já foi atualizado com essa
                # informação (etl/atualizar_recorte_mercado.py); nos recortes ainda
                # não atualizados, cai no cálculo 80%/120% do Adequado combinado
                # com o time em 2026-09-15.
                "Mínimo Mercado": com_view["salario_minimo"].fillna(com_view["salario_adequado"] * (PISO_IDEAL / 100)),
                "Adequado Mercado": com_view["salario_adequado"],
                "Máximo Mercado": com_view["salario_maximo"].fillna(com_view["salario_adequado"] * (TETO_IDEAL / 100)),
            }
        ).rename(columns={"descricao_cargo": "Cargo Interno", "cargo_pesquisa": "Cargo Relacionado"})[
            [
                "Cargo Interno",
                "Cargo Relacionado",
                "Qtd.",
                "Salário Interno (mediana)",
                "Faixa Interna",
                "Mínimo Mercado",
                "Adequado Mercado",
                "Máximo Mercado",
                "Aderência à Mediana Mercado",
            ]
        ]

        com_ordenar_col, com_ordem_col = st.columns([2, 1])
        with com_ordenar_col:
            com_ordenar_por = st.selectbox(
                "Ordenar por",
                options=["Aderência à Mediana Mercado", "Qtd.", "Salário Interno (mediana)", "Cargo Interno"],
                key="jm_com_ordenar",
            )
        with com_ordem_col:
            com_ordem_desc = st.toggle("Decrescente", key="jm_com_desc")
        com_view = com_view.sort_values(com_ordenar_por, ascending=not com_ordem_desc)

        _render_html_table(
            com_view,
            columns=[
                {"key": "Cargo Interno", "label": "Cargo Interno", "flex": "1.3"},
                {"key": "Cargo Relacionado", "label": "Cargo Relacionado", "flex": "1.3"},
                {"key": "Qtd.", "label": "Qtd.", "flex": "0 0 55px", "align": "right", "kind": "int", "bold_if_one": True},
                {"key": "Salário Interno (mediana)", "label": "Salário Interno", "flex": "0 0 100px", "align": "right", "kind": "currency"},
                {"key": "Faixa Interna", "label": "Faixa Interna", "flex": "0 0 150px"},
                {"key": "Mínimo Mercado", "label": "Mínimo Mercado", "flex": "0 0 100px", "align": "right", "kind": "currency"},
                {"key": "Adequado Mercado", "label": "Adequado Mercado", "flex": "0 0 100px", "align": "right", "kind": "currency"},
                {"key": "Máximo Mercado", "label": "Máximo Mercado", "flex": "0 0 100px", "align": "right", "kind": "currency"},
                {"key": "Aderência à Mediana Mercado", "label": "Aderência à Mediana", "flex": "0 0 180px", "kind": "bar"},
            ],
        )
        _excel_download_button(com_view, "Exportar para Excel", "cargos_com_job_matching.xlsx", key="excel_jm_com")

        st.subheader(f"Cargos sem Job Matching ({len(sem_matching)})")
        sem_view = sem_matching.assign(
            **{
                "Qtd.": sem_matching["qtd"],
                "Salário (mediana)": sem_matching["sal_mediana"],
                "Faixa": np.where(
                    sem_matching["sal_min"].round() != sem_matching["sal_max"].round(),
                    sem_matching["sal_min"].apply(format_currency) + " – " + sem_matching["sal_max"].apply(format_currency),
                    "—",
                ),
            }
        ).rename(columns={"descricao_cargo": "Cargo"})[["Cargo", "Qtd.", "Salário (mediana)", "Faixa"]]

        sem_ordenar_col, sem_ordem_col = st.columns([2, 1])
        with sem_ordenar_col:
            sem_ordenar_por = st.selectbox(
                "Ordenar por", options=["Qtd.", "Salário (mediana)", "Cargo"], key="jm_sem_ordenar"
            )
        with sem_ordem_col:
            sem_ordem_desc = st.toggle("Decrescente", value=True, key="jm_sem_desc")
        sem_view = sem_view.sort_values(sem_ordenar_por, ascending=not sem_ordem_desc)

        _render_html_table(
            sem_view,
            columns=[
                {"key": "Cargo", "label": "Cargo", "flex": "1.5"},
                {"key": "Qtd.", "label": "Qtd.", "flex": "0 0 55px", "align": "right", "kind": "int", "bold_if_one": True},
                {"key": "Salário (mediana)", "label": "Salário (mediana)", "flex": "0 0 130px", "align": "right", "kind": "currency"},
                {"key": "Faixa", "label": "Faixa", "flex": "0 0 170px"},
            ],
        )
        _excel_download_button(sem_view, "Exportar para Excel", "cargos_sem_job_matching.xlsx", key="excel_jm_sem")

        caption_parts = []
        if pessoas_loaded_at is not None and pd.notna(pessoas_loaded_at):
            caption_parts.append(f"Pessoas atualizadas em {pessoas_loaded_at:%d/%m/%Y %H:%M}")
        if mercado_loaded_at is not None and pd.notna(mercado_loaded_at):
            caption_parts.append(f"Mercado atualizado em {mercado_loaded_at:%d/%m/%Y %H:%M}")
        if pd.notna(_data_retirada_base):
            caption_parts.append(f"Relatório ({selected_base}) retirado em {_data_retirada_base:%d/%m/%Y}")
        if caption_parts:
            st.caption(" · ".join(caption_parts))
