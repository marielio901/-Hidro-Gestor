from __future__ import annotations

from datetime import date, timedelta
from typing import Callable

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from services.kpis import FilterParams, get_filter_dimensions



def render_global_filters(
    prefix: str,
    db_path: str | None = None,
    default_days: int = 90,
    show_status: bool = True,
    in_sidebar: bool = False,
) -> FilterParams:
    dims = get_filter_dimensions(db_path=db_path)

    if in_sidebar:
        st.sidebar.markdown("### Filtros")
        date_range = st.sidebar.date_input(
            "📅 Intervalo de datas",
            value=(date.today() - timedelta(days=default_days), date.today()),
            key=f"{prefix}_date_range",
            format="DD/MM/YYYY",
        )
        if isinstance(date_range, tuple):
            start_date, end_date = date_range
        else:
            start_date, end_date = date_range, date_range

        fazendas_df = dims["fazendas"]
        fazenda_options = [None, *fazendas_df["id"].tolist()]
        fazenda_sel = st.sidebar.selectbox(
            "🏡 Fazenda",
            options=fazenda_options,
            index=0,
            key=f"{prefix}_fazenda_sb",
            format_func=lambda x: "Todas" if x is None else fazendas_df.loc[fazendas_df["id"] == x, "nome"].iloc[0],
        )
        fazenda_ids = [] if fazenda_sel is None else [fazenda_sel]
    else:
        c1, c2, c3, c4, c5 = st.columns([1.5, 1.2, 1.2, 1.2, 1.0])

        with c1:
            date_range = st.date_input(
                "Intervalo de datas",
                value=(date.today() - timedelta(days=default_days), date.today()),
                key=f"{prefix}_date_range",
                format="DD/MM/YYYY",
            )
            if isinstance(date_range, tuple):
                start_date, end_date = date_range
            else:
                start_date, end_date = date_range, date_range

        with c2:
            fazendas_df = dims["fazendas"]
            fazenda_ids = st.multiselect(
                "Fazenda",
                options=fazendas_df["id"].tolist(),
                default=[],
                key=f"{prefix}_fazendas",
                placeholder="Selecione...",
                format_func=lambda x: fazendas_df.loc[fazendas_df["id"] == x, "nome"].iloc[0],
            )

    blocos_df = dims["blocos"]
    if fazenda_ids:
        blocos_df = blocos_df[blocos_df["fazenda_id"].isin(fazenda_ids)]

    if in_sidebar:
        bloco_options = [None, *blocos_df["id"].tolist()]
        bloco_sel = st.sidebar.selectbox(
            "🧱 Bloco",
            options=bloco_options,
            index=0,
            key=f"{prefix}_bloco_sb",
            format_func=lambda x: "Todos" if x is None else blocos_df.loc[blocos_df["id"] == x, "nome"].iloc[0],
        )
        bloco_ids = [] if bloco_sel is None else [bloco_sel]
    else:
        with c3:
            bloco_ids = st.multiselect(
                "Bloco",
                options=blocos_df["id"].tolist(),
                default=[],
                key=f"{prefix}_blocos",
                placeholder="Selecione...",
                format_func=lambda x: blocos_df.loc[blocos_df["id"] == x, "nome"].iloc[0],
            )

    talhoes_df = dims["talhoes"]
    if fazenda_ids:
        talhoes_df = talhoes_df[talhoes_df["fazenda_id"].isin(fazenda_ids)]
    if bloco_ids:
        talhoes_df = talhoes_df[talhoes_df["bloco_id"].isin(bloco_ids)]

    if in_sidebar:
        talhao_options = [None, *talhoes_df["id"].tolist()]
        talhao_sel = st.sidebar.selectbox(
            "🌱 Talhão",
            options=talhao_options,
            index=0,
            key=f"{prefix}_talhao_sb",
            format_func=lambda x: (
                "Todos"
                if x is None
                else (
                talhoes_df.loc[talhoes_df["id"] == x, "codigo"].iloc[0]
                + " - "
                + talhoes_df.loc[talhoes_df["id"] == x, "nome"].iloc[0]
                )
            ),
        )
        talhao_ids = [] if talhao_sel is None else [talhao_sel]
    else:
        with c4:
            talhao_ids = st.multiselect(
                "Talhão",
                options=talhoes_df["id"].tolist(),
                default=[],
                key=f"{prefix}_talhoes",
                placeholder="Selecione...",
                format_func=lambda x: (
                    talhoes_df.loc[talhoes_df["id"] == x, "codigo"].iloc[0]
                    + " - "
                    + talhoes_df.loc[talhoes_df["id"] == x, "nome"].iloc[0]
                ),
            )

    if in_sidebar:
        sistema_sel = st.sidebar.radio(
            "⚙️ Sistema",
            options=["Todos", "PIVO", "GOTEJO"],
            index=0,
            key=f"{prefix}_sistema_sb",
        )
        sistemas = [] if sistema_sel == "Todos" else [sistema_sel]
    else:
        with c5:
            sistema_opts = ["PIVO", "GOTEJO"]
            sistemas = st.multiselect(
                "Sistema",
                options=sistema_opts,
                default=[],
                key=f"{prefix}_sistemas",
                placeholder="Selecione...",
            )

    status_options = []
    if show_status:
        status_map = {
            "ok": "OK",
            "alerta": "ALERTA",
            "manutenção": "MANUTENCAO",
        }
        if in_sidebar:
            status_sel = st.sidebar.radio(
                "🚦 Status",
                options=["Todos", *list(status_map.keys())],
                index=0,
                key=f"{prefix}_status_sb",
            )
            selected_status_labels = [] if status_sel == "Todos" else [status_sel]
        else:
            selected_status_labels = st.multiselect(
                "Status",
                options=list(status_map.keys()),
                default=[],
                key=f"{prefix}_status",
                placeholder="Selecione...",
            )
        status_options = [status_map[x] for x in selected_status_labels]

    return FilterParams(
        start_date=start_date,
        end_date=end_date,
        fazenda_ids=tuple(int(x) for x in fazenda_ids),
        bloco_ids=tuple(int(x) for x in bloco_ids),
        talhao_ids=tuple(int(x) for x in talhao_ids),
        sistemas=tuple(str(x) for x in sistemas),
        status=tuple(status_options),
        only_alerts=False,
    )



def metric_dsm(
    label: str,
    cards: dict[str, dict[str, float]],
    key: str,
    formatter: Callable[[float], str],
) -> None:
    c1, c2, c3 = st.columns(3)
    c1.metric(f"{label} (Dia)", formatter(cards["dia"].get(key, 0.0)))
    c2.metric(f"{label} (Semana)", formatter(cards["semana"].get(key, 0.0)))
    c3.metric(f"{label} (Mês)", formatter(cards["mes"].get(key, 0.0)))



def line_daily(df: pd.DataFrame, y_cols: list[str], title: str, y_title: str) -> go.Figure:
    fig = go.Figure()
    for col in y_cols:
        if col in df.columns:
            fig.add_trace(go.Scatter(x=df["ddmm"], y=df[col], mode="lines+markers", name=col))
    fig.update_layout(title=title, xaxis_title="Dia (dd/mm)", yaxis_title=y_title)
    return fig



def bar_monthly(df: pd.DataFrame, y_cols: list[str], title: str, y_title: str) -> go.Figure:
    fig = go.Figure()
    for col in y_cols:
        if col in df.columns:
            fig.add_trace(go.Bar(x=df["ano_mes"], y=df[col], name=col))
    fig.update_layout(title=title, xaxis_title="Mês (YYYY-MM)", yaxis_title=y_title, barmode="group")
    return fig
