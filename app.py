from __future__ import annotations

import copy
from pathlib import Path
import runpy

import plotly.io as pio
import streamlit as st

st.set_page_config(
    page_title="Hidro Gestor",
    page_icon="💧",
    layout="wide",
)

# Tema escuro para todos os gráficos Plotly.
hidro_dark = copy.deepcopy(pio.templates["plotly_dark"])
hidro_dark.layout.colorway = ["#22c55e", "#3b82f6", "#0ea5e9", "#34d399", "#60a5fa", "#f59e0b", "#ef4444"]
hidro_dark.layout.font = {"color": "#e2e8f0"}
hidro_dark.layout.paper_bgcolor = "#020817"
hidro_dark.layout.plot_bgcolor = "#020817"
hidro_dark.layout.xaxis = {"gridcolor": "rgba(148, 163, 184, 0.18)", "zerolinecolor": "rgba(148, 163, 184, 0.18)"}
hidro_dark.layout.yaxis = {"gridcolor": "rgba(148, 163, 184, 0.18)", "zerolinecolor": "rgba(148, 163, 184, 0.18)"}
pio.templates["hidro_dark"] = hidro_dark
pio.templates.default = "hidro_dark"

st.markdown(
    """
    <style>
    [data-testid="stAppViewContainer"] {
        background: linear-gradient(180deg, #020817 0%, #030b1a 100%);
        color: #e2e8f0;
    }
    [data-testid="stHeader"] {
        background: rgba(2, 8, 23, 0.92);
        border-bottom: 1px solid rgba(56, 189, 248, 0.20);
    }
    [data-testid="stSidebar"] {
        background: linear-gradient(180deg, #050c1b 0%, #091225 100%);
        border-right: 1px solid rgba(56, 189, 248, 0.20);
    }
    .stTabs [data-baseweb="tab-list"] button {
        color: #93c5fd;
    }
    .stTabs [data-baseweb="tab-list"] button[aria-selected="true"] {
        color: #22c55e !important;
        border-bottom-color: #22c55e !important;
    }
    [data-testid="stSidebar"] a {
        color: #93c5fd !important;
    }
    [data-testid="stSidebar"] a[aria-current="page"] {
        color: #22c55e !important;
        font-weight: 700 !important;
    }
    [data-testid="stSidebar"] a:hover {
        color: #86efac !important;
    }
    .stButton > button:hover {
        border-color: #22c55e !important;
        color: #86efac !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

pages_dir = Path(__file__).parent / "pages"

st.sidebar.title("Hidro Gestor")
st.sidebar.markdown("--------------")

page_files = {
    "Dashboard": pages_dir / "1_Dashboard.py",
    "Cadastrar Locais": pages_dir / "2_Cadastrar_Locais.py",
    "Registrar atividades": pages_dir / "3_Registrar_atividades.py",
    "Planejamento": pages_dir / "4_Planejamento.py",
    "Informações": pages_dir / "5_Informacoes.py",
}

def _fallback_navigation() -> None:
    escolha = st.sidebar.radio("Navegação", list(page_files.keys()), index=0)
    runpy.run_path(str(page_files[escolha]), run_name="__main__")


if hasattr(st, "Page") and hasattr(st, "navigation"):
    nav_items = list(page_files.items())

    try:
        pages = [
            st.Page(str(path), title=label, default=(idx == 0))
            for idx, (label, path) in enumerate(nav_items)
        ]
    except TypeError:
        # Compatibilidade com versões que não aceitam `default` no construtor de Page.
        pages = [st.Page(str(path), title=label) for label, path in nav_items]

    links_rendered = False
    if hasattr(st.sidebar, "page_link"):
        for idx, (label, path) in enumerate(nav_items):
            try:
                st.sidebar.page_link(pages[idx], label=label)
                links_rendered = True
            except Exception:
                st.sidebar.page_link(str(path), label=label)
                links_rendered = True

    if links_rendered:
        try:
            pg = st.navigation(pages, position="hidden")
        except (TypeError, ValueError):
            pg = st.navigation(pages)
    else:
        try:
            pg = st.navigation(pages, position="sidebar")
        except (TypeError, ValueError):
            pg = st.navigation(pages)

    pg.run()
else:
    # Fallback para versões antigas do Streamlit no deploy.
    _fallback_navigation()
