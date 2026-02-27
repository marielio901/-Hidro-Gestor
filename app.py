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

# Tema claro para todos os gráficos Plotly.
hidro_light = copy.deepcopy(pio.templates["plotly_white"])
hidro_light.layout.colorway = ["#16a34a", "#2563eb", "#0ea5e9", "#22c55e", "#3b82f6", "#f59e0b", "#ef4444"]
hidro_light.layout.font = {"color": "#0f172a"}
hidro_light.layout.paper_bgcolor = "#ffffff"
hidro_light.layout.plot_bgcolor = "#ffffff"
hidro_light.layout.xaxis = {"gridcolor": "rgba(148, 163, 184, 0.24)", "zerolinecolor": "rgba(148, 163, 184, 0.24)"}
hidro_light.layout.yaxis = {"gridcolor": "rgba(148, 163, 184, 0.24)", "zerolinecolor": "rgba(148, 163, 184, 0.24)"}
pio.templates["hidro_light"] = hidro_light
pio.templates.default = "hidro_light"

st.markdown(
    """
    <style>
    [data-testid="stAppViewContainer"] {
        background: linear-gradient(180deg, #f7fbff 0%, #f2f7fc 100%);
        color: #0f172a;
    }
    [data-testid="stHeader"] {
        background: rgba(255, 255, 255, 0.85);
        border-bottom: 1px solid rgba(148, 163, 184, 0.24);
    }
    [data-testid="stSidebar"] {
        background: linear-gradient(180deg, #ffffff 0%, #eef4fb 100%);
        border-right: 1px solid rgba(148, 163, 184, 0.24);
    }
    .stTabs [data-baseweb="tab-list"] button {
        color: #1d4ed8;
    }
    .stTabs [data-baseweb="tab-list"] button[aria-selected="true"] {
        color: #15803d !important;
        border-bottom-color: #16a34a !important;
    }
    [data-testid="stSidebar"] a {
        color: #1d4ed8 !important;
    }
    [data-testid="stSidebar"] a[aria-current="page"] {
        color: #15803d !important;
        font-weight: 700 !important;
    }
    [data-testid="stSidebar"] a:hover {
        color: #166534 !important;
    }
    .stButton > button:hover {
        border-color: #16a34a !important;
        color: #166534 !important;
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
