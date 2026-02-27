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
hidro_dark.layout.paper_bgcolor = "rgba(0,0,0,0)"
hidro_dark.layout.plot_bgcolor = "rgba(0,0,0,0)"
hidro_dark.layout.legend = {"bgcolor": "rgba(0,0,0,0)"}
hidro_dark.layout.xaxis = {"gridcolor": "rgba(148, 163, 184, 0.18)", "zerolinecolor": "rgba(148, 163, 184, 0.18)"}
hidro_dark.layout.yaxis = {"gridcolor": "rgba(148, 163, 184, 0.18)", "zerolinecolor": "rgba(148, 163, 184, 0.18)"}
pio.templates["hidro_dark"] = hidro_dark
pio.templates.default = "hidro_dark"

st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@600;700&display=swap');

    [data-testid="stAppViewContainer"] {
        background: #0f1016;
        color: #e2e8f0;
    }
    [data-testid="stHeader"] {
        background: #0f1016;
        border-bottom: 1px solid rgba(226, 232, 240, 0.12);
    }
    [data-testid="stSidebar"] {
        background: #2c2f32;
        border-right: 1px solid rgba(226, 232, 240, 0.12);
    }
    .sidebar-brand {
        display: flex;
        align-items: center;
        gap: 0.6rem;
        margin: 0 0 0.35rem 0;
    }
    .sidebar-brand-logo {
        width: 2.2rem;
        height: 2.2rem;
        border-radius: 999px;
        background: radial-gradient(circle at 30% 30%, rgba(56, 189, 248, 0.35), rgba(14, 165, 233, 0.18));
        border: 1px solid rgba(125, 211, 252, 0.35);
        display: grid;
        place-items: center;
        flex-shrink: 0;
    }
    .sidebar-brand-logo svg {
        width: 1.2rem;
        height: 1.2rem;
        color: #e0f2fe;
    }
    .sidebar-app-title {
        font-family: "Space Grotesk", "Arial Rounded MT Bold", "Segoe UI", sans-serif;
        font-weight: 700;
        letter-spacing: 0.02em;
        font-size: 1.65rem;
        line-height: 1.15;
        color: #e2e8f0;
        margin: 0;
    }
    [data-testid="stSidebar"] .sidebar-filter-title {
        font-family: "Space Grotesk", "Segoe UI", sans-serif;
        font-weight: 700;
        font-size: 1.02rem;
        letter-spacing: 0.01em;
        color: #e2e8f0;
        margin: 1rem 0 0.45rem 0;
    }
    [data-testid="stSidebar"] [data-testid="stWidgetLabel"] > label {
        color: #dbe3ee !important;
        font-size: 0.92rem;
        font-weight: 600;
        letter-spacing: 0.01em;
    }
    [data-testid="stSidebar"] .stDateInput [data-baseweb="input"] > div,
    [data-testid="stSidebar"] [data-baseweb="select"] > div {
        background: linear-gradient(180deg, rgba(11, 14, 20, 0.96), rgba(8, 11, 17, 0.96));
        border: 1px solid rgba(148, 163, 184, 0.26);
        border-radius: 12px;
        min-height: 46px;
        box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.03);
        transition: border-color 0.18s ease, box-shadow 0.18s ease;
    }
    [data-testid="stSidebar"] .stDateInput [data-baseweb="input"] > div:hover,
    [data-testid="stSidebar"] [data-baseweb="select"] > div:hover {
        border-color: rgba(125, 211, 252, 0.48);
    }
    [data-testid="stSidebar"] .stDateInput [data-baseweb="input"] > div:focus-within,
    [data-testid="stSidebar"] [data-baseweb="select"] > div:focus-within {
        border-color: rgba(56, 189, 248, 0.82);
        box-shadow: 0 0 0 2px rgba(56, 189, 248, 0.18);
    }
    [data-testid="stSidebar"] .stDateInput input,
    [data-testid="stSidebar"] [data-baseweb="select"] input {
        color: #f1f5f9 !important;
    }
    [data-testid="stSidebar"] [data-baseweb="select"] [class*="placeholder"] {
        color: #93a3b8 !important;
    }
    [data-testid="stSidebar"] [data-baseweb="select"] svg {
        color: #cbd5e1;
    }
    [data-testid="stSidebar"] [data-baseweb="tag"] {
        background: rgba(56, 189, 248, 0.20) !important;
        border: 1px solid rgba(125, 211, 252, 0.45) !important;
        color: #e0f2fe !important;
        border-radius: 999px !important;
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
    [data-testid="stPlotlyChart"],
    [data-testid="stPlotlyChart"] > div,
    [data-testid="stPlotlyChart"] .js-plotly-plot,
    [data-testid="stPlotlyChart"] .plot-container,
    [data-testid="stPlotlyChart"] .svg-container {
        background: transparent !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

pages_dir = Path(__file__).parent / "pages"

st.sidebar.markdown(
    """
    <div class="sidebar-brand">
        <div class="sidebar-brand-logo" aria-hidden="true">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"
                stroke-linecap="round" stroke-linejoin="round">
                <path d="M12 3s-6 7-6 11a6 6 0 0 0 12 0c0-4-6-11-6-11Z"/>
                <path d="M9.5 14.5a2.5 2.5 0 0 0 5 0"/>
            </svg>
        </div>
        <div class="sidebar-app-title">Hidro Gestor</div>
    </div>
    """,
    unsafe_allow_html=True,
)
st.sidebar.markdown("--------------")

page_items = [
    {
        "label": "Dashboard",
        "path": pages_dir / "1_Dashboard.py",
        "icon": ":material/dashboard:",
        "fallback": "▣ Dashboard",
    },
    {
        "label": "Cadastrar Locais",
        "path": pages_dir / "2_Cadastrar_Locais.py",
        "icon": ":material/place:",
        "fallback": "◎ Cadastrar Locais",
    },
    {
        "label": "Registrar Atividades",
        "path": pages_dir / "3_Registrar_atividades.py",
        "icon": ":material/edit_note:",
        "fallback": "◧ Registrar Atividades",
    },
    {
        "label": "Planejamento",
        "path": pages_dir / "4_Planejamento.py",
        "icon": ":material/event:",
        "fallback": "◩ Planejamento",
    },
    {
        "label": "Informações",
        "path": pages_dir / "5_Informacoes.py",
        "icon": ":material/info:",
        "fallback": "◉ Informações",
    },
]

def _fallback_navigation() -> None:
    labels = [item["fallback"] for item in page_items]
    page_map = {item["fallback"]: item["path"] for item in page_items}
    escolha = st.sidebar.radio("Navegação", labels, index=0)
    runpy.run_path(str(page_map[escolha]), run_name="__main__")


if hasattr(st, "Page") and hasattr(st, "navigation"):
    nav_items = page_items

    try:
        pages = [
            st.Page(
                str(item["path"]),
                title=item["label"],
                icon=item["icon"],
                default=(idx == 0),
            )
            for idx, item in enumerate(nav_items)
        ]
    except TypeError:
        # Compatibilidade com versões que não aceitam `icon/default` no construtor de Page.
        pages = [st.Page(str(item["path"]), title=item["label"]) for item in nav_items]

    links_rendered = False
    if hasattr(st.sidebar, "page_link"):
        for idx, item in enumerate(nav_items):
            try:
                st.sidebar.page_link(pages[idx], label=item["label"], icon=item["icon"])
                links_rendered = True
            except Exception:
                try:
                    st.sidebar.page_link(str(item["path"]), label=item["label"], icon=item["icon"])
                    links_rendered = True
                except TypeError:
                    st.sidebar.page_link(str(item["path"]), label=item["label"])
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
