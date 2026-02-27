from __future__ import annotations

import copy
from pathlib import Path

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

page_dashboard = st.Page(str(pages_dir / "1_Dashboard.py"), title="Dashboard", default=True)
page_cadastros = st.Page(str(pages_dir / "2_Cadastrar_Locais.py"), title="Cadastrar Locais")
page_registro = st.Page(str(pages_dir / "3_Registrar_atividades.py"), title="Registrar atividades")
page_planejamento = st.Page(str(pages_dir / "4_Planejamento.py"), title="Planejamento")
page_informacoes = st.Page(str(pages_dir / "5_Informacoes.py"), title="Informações")

st.sidebar.title("Hidro Gestor")
st.sidebar.markdown("--------------")
st.sidebar.page_link(page_dashboard, label="Dashboard")
st.sidebar.page_link(page_cadastros, label="Cadastrar Locais")
st.sidebar.page_link(page_registro, label="Registrar atividades")
st.sidebar.page_link(page_planejamento, label="Planejamento")
st.sidebar.page_link(page_informacoes, label="Informações")

pg = st.navigation(
    [page_dashboard, page_cadastros, page_registro, page_planejamento, page_informacoes],
    position="hidden",
)
pg.run()
