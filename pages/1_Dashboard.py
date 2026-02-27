from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from services.alerts import generate_alerts, maintenance_backlog
from services.kpis import (
    build_cards,
    build_daily_series,
    build_monthly_series,
    load_operational_dataset,
    management_metrics,
    planning_vs_actual,
    weighted_control_metrics,
)
from services.open_meteo import load_cached_climate
from utils.formatters import fmt_kwh, fmt_m3, fmt_mm, fmt_num, fmt_pct, fmt_rs
from utils.ui import render_global_filters

st.title("Dashboard")

(
    tab_geral,
    tab_hidrico,
    tab_clima,
    tab_custos,
    tab_demanda,
    tab_energia,
    tab_gestao,
    tab_alertas,
) = st.tabs(
    [
        "Controle Geral",
        "Controle Hídrico",
        "Clima Acompanhar",
        "Custos",
        "Demanda & Aplicação",
        "Eficiência & Energia",
        "Gestão",
        "Alertas & Manutenção",
    ]
)

filters = render_global_filters("dashboard", default_days=180, show_status=True, in_sidebar=True)
df = load_operational_dataset(filters)

if df.empty:
    st.warning("Sem dados para os filtros selecionados. Gere dados sintéticos (scripts/generate_data.py).")
    st.stop()

cards = build_cards(df)
daily = build_daily_series(df)
monthly = build_monthly_series(df)
weighted = weighted_control_metrics(df)
mgmt = management_metrics(filters)
alerts_df = generate_alerts(df)

st.caption(
    f"Período selecionado: {filters.start_date.strftime('%d/%m/%Y')} a {filters.end_date.strftime('%d/%m/%Y')}"
)

dia = cards["dia"]
semana = cards["semana"]
mes = cards["mes"]
area_base_ha = float(df[["talhao_id", "area_ha"]].drop_duplicates()["area_ha"].sum() or 0.0)

aporte_dia_m3_ha = dia["aporte_m3"] / max(area_base_ha, 1e-6)
aporte_semana_m3_ha = semana["aporte_m3"] / max(area_base_ha, 1e-6)
aporte_mes_m3_ha = mes["aporte_m3"] / max(area_base_ha, 1e-6)

# Chuva convertida para horas equivalentes de irrigacao por talhao.
df["chuva_equiv_h"] = (
    (df["precipitacao_mm"].fillna(0.0) * 0.8 * df["area_ha"] * 10.0)
    / np.maximum(df["meta_vazao_projeto"], 1e-6)
)

activity_daily = (
    df.groupby("data", as_index=False)
    .agg(
        horas_irrigadas=("horas_irrigadas", "sum"),
        chuva_equiv_h=("chuva_equiv_h", "sum"),
        horas_paradas=("horas_paradas", "sum"),
        atividades=("id", "count"),
        problemas=("teve_problema", "sum"),
    )
    .sort_values("data")
)
activity_daily["ddmm"] = pd.to_datetime(activity_daily["data"]).dt.strftime("%d/%m")

activity_monthly = (
    activity_daily.assign(ano_mes=pd.to_datetime(activity_daily["data"]).dt.to_period("M").astype(str))
    .groupby("ano_mes", as_index=False)
    .agg(
        horas_irrigadas=("horas_irrigadas", "sum"),
        horas_paradas=("horas_paradas", "sum"),
        atividades=("atividades", "sum"),
        problemas=("problemas", "sum"),
    )
    .sort_values("ano_mes")
)

stop_parts = df[
    [
        "data",
        "horas_paradas",
        "horas_irrigadas",
        "tempo_manutencao_h",
        "manutencao_h",
        "tipo_problema",
        "precipitacao_mm",
        "demanda_mm_dia",
    ]
].copy()
for col in [
    "horas_paradas",
    "horas_irrigadas",
    "tempo_manutencao_h",
    "manutencao_h",
    "precipitacao_mm",
    "demanda_mm_dia",
]:
    stop_parts[col] = pd.to_numeric(stop_parts[col], errors="coerce").fillna(0.0)

stop_parts["parada_problema_h"] = np.minimum(stop_parts["tempo_manutencao_h"], stop_parts["horas_paradas"])
stop_parts["parada_preventiva_h"] = (stop_parts["manutencao_h"] - stop_parts["tempo_manutencao_h"]).clip(lower=0.0)
stop_parts["parada_preventiva_h"] = np.minimum(
    stop_parts["parada_preventiva_h"],
    (stop_parts["horas_paradas"] - stop_parts["parada_problema_h"]).clip(lower=0.0),
)

stop_parts["resto_h"] = (
    stop_parts["horas_paradas"] - stop_parts["parada_problema_h"] - stop_parts["parada_preventiva_h"]
).clip(lower=0.0)

rain_ratio = np.where(
    stop_parts["precipitacao_mm"] >= 10.0,
    0.45,
    np.where(stop_parts["precipitacao_mm"] >= 5.0, 0.30, 0.10),
)
stop_parts["parada_chuva_h"] = stop_parts["resto_h"] * rain_ratio
rest_1 = stop_parts["resto_h"] - stop_parts["parada_chuva_h"]

demand_ratio = np.where(
    stop_parts["demanda_mm_dia"] <= 0.20,
    0.42,
    np.where(stop_parts["demanda_mm_dia"] <= 0.80, 0.28, 0.10),
)
stop_parts["parada_baixa_demanda_h"] = rest_1 * demand_ratio
rest_2 = rest_1 - stop_parts["parada_baixa_demanda_h"]

adjust_ratio = np.where(stop_parts["horas_irrigadas"] > 0.0, 0.55, 0.30)
stop_parts["parada_ajuste_oper_h"] = rest_2 * adjust_ratio
stop_parts["parada_outras_h"] = (rest_2 - stop_parts["parada_ajuste_oper_h"]).clip(lower=0.0)

stop_problem = (
    stop_parts.loc[stop_parts["parada_problema_h"] > 0, ["data", "tipo_problema", "parada_problema_h"]]
    .rename(columns={"tipo_problema": "motivo", "parada_problema_h": "horas"})
    .copy()
)
stop_problem["motivo"] = stop_problem["motivo"].fillna("OUTRO").astype(str)
stop_problem["motivo"] = np.where(
    stop_problem["motivo"].isin(["VAZAMENTO", "PRESSAO_BAIXA", "BOMBA", "ELETRICO", "OUTRO"]),
    stop_problem["motivo"],
    "OUTRO",
)

stop_prevent = (
    stop_parts.loc[stop_parts["parada_preventiva_h"] > 0, ["data", "parada_preventiva_h"]]
    .rename(columns={"parada_preventiva_h": "horas"})
    .copy()
)
stop_prevent["motivo"] = "MANUT_PREVENTIVA"

stop_other = stop_parts[
    ["data", "parada_chuva_h", "parada_baixa_demanda_h", "parada_ajuste_oper_h", "parada_outras_h"]
].melt(
    id_vars="data",
    var_name="motivo_src",
    value_name="horas",
)
stop_other = stop_other.loc[stop_other["horas"] > 0].copy()
stop_other["motivo"] = stop_other["motivo_src"].map(
    {
        "parada_chuva_h": "CHUVA",
        "parada_baixa_demanda_h": "BAIXA_DEMANDA",
        "parada_ajuste_oper_h": "AJUSTE_OPERACIONAL",
        "parada_outras_h": "OUTRAS_ATIVIDADES",
    }
)

stop_reasons_daily = (
    pd.concat(
        [
            stop_problem[["data", "motivo", "horas"]],
            stop_prevent[["data", "motivo", "horas"]],
            stop_other[["data", "motivo", "horas"]],
        ],
        ignore_index=True,
    )
    .groupby(["data", "motivo"], as_index=False)
    .agg(horas=("horas", "sum"))
)


def _render_summary_cards_css() -> None:
    st.markdown(
        """
        <style>
        .hg-summary-card {
            position: relative;
            border: 1px solid rgba(226, 232, 240, 0.14);
            border-radius: 16px;
            padding: 12px 12px 10px 12px;
            height: 178px;
            background: linear-gradient(165deg, rgba(44, 47, 50, 0.95), rgba(35, 38, 41, 0.95));
            box-shadow: 0 12px 24px rgba(0, 0, 0, 0.28);
            overflow: hidden;
            display: flex;
            flex-direction: column;
            justify-content: space-between;
        }
        .hg-summary-card::before {
            content: "";
            position: absolute;
            top: 0;
            left: 0;
            right: 0;
            height: 3px;
            background: linear-gradient(90deg, var(--accent), rgba(44, 47, 50, 0));
        }
        .hg-summary-head {
            display: flex;
            align-items: center;
            gap: 8px;
            margin-bottom: 8px;
        }
        .hg-summary-icon {
            width: 30px;
            height: 30px;
            border-radius: 9px;
            border: 1px solid rgba(226, 232, 240, 0.22);
            background: rgba(15, 16, 22, 0.62);
            color: var(--accent);
            display: grid;
            place-items: center;
            flex-shrink: 0;
        }
        .hg-summary-icon svg {
            width: 17px;
            height: 17px;
        }
        .hg-summary-title {
            font-size: 0.86rem;
            color: #cbd5e1;
            line-height: 1.15rem;
            font-weight: 600;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }
        .hg-summary-value {
            color: #f8fafc;
            font-size: clamp(1.85rem, 1.25vw + 1.15rem, 2.2rem);
            line-height: 1.08;
            font-weight: 700;
            letter-spacing: -0.02em;
            margin: 2px 0 8px 0;
            min-height: 2.45rem;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }
        .hg-summary-delta {
            display: inline-flex;
            align-items: center;
            font-size: 0.78rem;
            font-weight: 600;
            color: #e2e8f0;
            background: var(--badge-bg);
            border: 1px solid rgba(226, 232, 240, 0.20);
            border-radius: 999px;
            padding: 4px 9px;
            width: fit-content;
            max-width: 100%;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }
        .hg-summary-delta-empty {
            visibility: hidden;
        }
        .hg-tone-water { --accent: #38bdf8; --badge-bg: rgba(56, 189, 248, 0.22); }
        .hg-tone-usage { --accent: #60a5fa; --badge-bg: rgba(96, 165, 250, 0.20); }
        .hg-tone-energy { --accent: #4ade80; --badge-bg: rgba(74, 222, 128, 0.20); }
        .hg-tone-cost { --accent: #34d399; --badge-bg: rgba(52, 211, 153, 0.20); }
        .hg-tone-loss { --accent: #fbbf24; --badge-bg: rgba(251, 191, 36, 0.22); }
        .hg-tone-alert { --accent: #f87171; --badge-bg: rgba(248, 113, 113, 0.22); }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _summary_icon(kind: str) -> str:
    icons = {
        "water": (
            '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" '
            'stroke-linecap="round" stroke-linejoin="round"><path d="M12 3s-6 7-6 11a6 6 0 0 0 12 0c0-4-6-11-6-11Z"/>'
            '<path d="M9.5 14.5a2.5 2.5 0 0 0 5 0"/></svg>'
        ),
        "usage": (
            '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" '
            'stroke-linecap="round" stroke-linejoin="round"><path d="M3 9c1.5 0 1.5 2 3 2s1.5-2 3-2 1.5 2 3 2 1.5-2 3-2 1.5 2 3 2 1.5-2 3-2"/>'
            '<path d="M3 15c1.5 0 1.5 2 3 2s1.5-2 3-2 1.5 2 3 2 1.5-2 3-2 1.5 2 3 2 1.5-2 3-2"/></svg>'
        ),
        "energy": (
            '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" '
            'stroke-linecap="round" stroke-linejoin="round"><path d="M13 2 5 14h6l-1 8 8-12h-6z"/></svg>'
        ),
        "cost": (
            '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" '
            'stroke-linecap="round" stroke-linejoin="round"><rect x="3.5" y="6.5" width="17" height="11" rx="2"/>'
            '<path d="M8 12h8"/><path d="M12 9v6"/></svg>'
        ),
        "loss": (
            '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" '
            'stroke-linecap="round" stroke-linejoin="round"><path d="M12 3s-6 7-6 11a6 6 0 0 0 12 0c0-4-6-11-6-11Z"/>'
            '<path d="M12 11v7"/><path d="m9.5 15.5 2.5 2.5 2.5-2.5"/></svg>'
        ),
        "alert": (
            '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" '
            'stroke-linecap="round" stroke-linejoin="round"><path d="M12 4a4 4 0 0 0-4 4v3.2L6.7 14A1 1 0 0 0 7.5 15.5h9a1 1 0 0 0 .8-1.5L16 11.2V8a4 4 0 0 0-4-4Z"/>'
            '<path d="M10 18a2 2 0 0 0 4 0"/></svg>'
        ),
    }
    return icons.get(kind, icons["alert"])


def _render_summary_card(col, title: str, value: str, delta: str | None, icon_kind: str, tone: str) -> None:
    delta_html = (
        f'<div class="hg-summary-delta" title="{delta}">{delta}</div>'
        if delta
        else '<div class="hg-summary-delta hg-summary-delta-empty">&nbsp;</div>'
    )
    with col:
        st.markdown(
            f"""
            <div class="hg-summary-card hg-tone-{tone}">
                <div class="hg-summary-head">
                    <span class="hg-summary-icon">{_summary_icon(icon_kind)}</span>
                    <span class="hg-summary-title" title="{title}">{title}</span>
                </div>
                <div class="hg-summary-value" title="{value}">{value}</div>
                {delta_html}
            </div>
            """,
            unsafe_allow_html=True,
        )


with tab_geral:
    st.subheader("Resumo geral")
    _render_summary_cards_css()

    open_alerts = int((alerts_df["status"] == "ABERTO").sum())
    closed_alerts = int((alerts_df["status"] == "FECHADO").sum())
    c1, c2, c3, c4, c5, c6 = st.columns(6)

    _render_summary_card(
        c1,
        "Aporte hídrico (m³/ha)",
        f"{fmt_num(aporte_dia_m3_ha, 2)} m³/ha",
        f"S {fmt_num(aporte_semana_m3_ha, 2)} m³/ha | M {fmt_num(aporte_mes_m3_ha, 2)} m³/ha",
        "water",
        "water",
    )
    _render_summary_card(
        c2,
        "Consumo de água",
        fmt_m3(dia["consumo_agua_m3"]),
        f"S {fmt_m3(semana['consumo_agua_m3'])} | M {fmt_m3(mes['consumo_agua_m3'])}",
        "usage",
        "usage",
    )
    _render_summary_card(
        c3,
        "Consumo de energia",
        fmt_kwh(dia["energia_kwh"]),
        f"S {fmt_kwh(semana['energia_kwh'])} | M {fmt_kwh(mes['energia_kwh'])}",
        "energy",
        "energy",
    )
    _render_summary_card(
        c4,
        "Custo total",
        fmt_rs(dia["custo_total_rs"]),
        f"S {fmt_rs(semana['custo_total_rs'])} | M {fmt_rs(mes['custo_total_rs'])}",
        "cost",
        "cost",
    )
    _render_summary_card(
        c5,
        "Perdas totais",
        fmt_pct(dia["perdas_pct"]),
        f"S {fmt_pct(semana['perdas_pct'])} | M {fmt_pct(mes['perdas_pct'])}",
        "loss",
        "loss",
    )
    _render_summary_card(
        c6,
        "Alertas abertos",
        str(open_alerts),
        f"Fechados: {closed_alerts}",
        "alert",
        "alert",
    )

    st.subheader("Atividades resumidas")
    daily_view = activity_daily.tail(31).copy()
    tick_step = max(len(daily_view) // 8, 1)
    tick_vals = daily_view["ddmm"].iloc[::tick_step]

    left_col, right_col = st.columns([3, 1])
    with left_col:
        fig = go.Figure()
        fig.add_trace(
            go.Bar(
                x=daily_view["ddmm"],
                y=daily_view["horas_irrigadas"],
                name="Irrigacao sistema",
                marker_color="#3b82f6",
            )
        )
        fig.add_trace(
            go.Bar(
                x=daily_view["ddmm"],
                y=daily_view["chuva_equiv_h"],
                name="Chuva (equiv. irrigacao)",
                marker_color="#4fb387",
            )
        )
        fig.update_layout(
            title="Horas irrigadas dia (sistema + chuva equivalente)",
            barmode="stack",
            showlegend=True,
            height=250,
            margin={"t": 50, "r": 20, "b": 60, "l": 20},
            yaxis_title="Horas",
            legend={"orientation": "h", "yanchor": "top", "y": -0.22, "xanchor": "left", "x": 0},
        )
        fig.update_xaxes(tickmode="array", tickvals=tick_vals, ticktext=tick_vals, tickangle=-20)
        st.plotly_chart(fig, use_container_width=True)

        fig = go.Figure()
        stop_view = daily_view[["data", "ddmm"]].copy()
        reasons_order = [
            "CHUVA",
            "BAIXA_DEMANDA",
            "AJUSTE_OPERACIONAL",
            "MANUT_PREVENTIVA",
            "VAZAMENTO",
            "PRESSAO_BAIXA",
            "BOMBA",
            "ELETRICO",
            "OUTRO",
            "OUTRAS_ATIVIDADES",
        ]
        reason_labels = {
            "CHUVA": "Chuva",
            "BAIXA_DEMANDA": "Baixa demanda",
            "AJUSTE_OPERACIONAL": "Ajuste operacional",
            "MANUT_PREVENTIVA": "Manutencao preventiva",
            "VAZAMENTO": "Vazamento",
            "PRESSAO_BAIXA": "Pressao baixa",
            "BOMBA": "Bomba",
            "ELETRICO": "Eletrico",
            "OUTRO": "Outro",
            "OUTRAS_ATIVIDADES": "Outras atividades",
        }
        reason_colors = {
            "CHUVA": "#4E79A7",
            "BAIXA_DEMANDA": "#F28E2B",
            "AJUSTE_OPERACIONAL": "#E15759",
            "MANUT_PREVENTIVA": "#76B7B2",
            "VAZAMENTO": "#59A14F",
            "PRESSAO_BAIXA": "#EDC948",
            "BOMBA": "#B07AA1",
            "ELETRICO": "#FF9DA7",
            "OUTRO": "#9C755F",
            "OUTRAS_ATIVIDADES": "#BAB0AB",
        }

        for reason in reasons_order:
            reason_day = stop_reasons_daily[stop_reasons_daily["motivo"] == reason][["data", "horas"]]
            reason_day = stop_view.merge(reason_day, on="data", how="left").fillna({"horas": 0.0})
            fig.add_trace(
                go.Bar(
                    x=reason_day["ddmm"],
                    y=reason_day["horas"],
                    name=reason_labels[reason],
                    marker_color=reason_colors[reason],
                )
            )
        fig.update_layout(
            title="Horas paradas dia por motivo",
            barmode="stack",
            showlegend=True,
            height=280,
            margin={"t": 50, "r": 20, "b": 70, "l": 20},
            yaxis_title="Horas",
            legend={"orientation": "h", "yanchor": "top", "y": -0.24, "xanchor": "left", "x": 0},
        )
        fig.update_xaxes(tickmode="array", tickvals=tick_vals, ticktext=tick_vals, tickangle=-20)
        st.plotly_chart(fig, use_container_width=True)

    with right_col:
        total_atividades = float(activity_daily["atividades"].sum())
        total_problemas = float(activity_daily["problemas"].sum())
        sem_problema = max(total_atividades - total_problemas, 0.0)
        sem_problema_pct = (sem_problema / max(total_atividades, 1e-6)) * 100.0
        problemas_pct = (total_problemas / max(total_atividades, 1e-6)) * 100.0

        if total_atividades <= 0:
            labels = ["Sem dados"]
            values = [1]
            colors = ["#64748b"]
            center_text = "--"
            center_sub = "Sem dados"
            pie_text = [""]
        else:
            labels = ["Sem problema", "Problemas"]
            values = [sem_problema, total_problemas]
            colors = ["#4fb387", "#c97a7a"]
            center_text = f"{sem_problema_pct:.0f}%"
            center_sub = "Sem problema"
            pie_text = ["", f"{problemas_pct:.0f}%"]

        fig = go.Figure(
            go.Pie(
                labels=labels,
                values=values,
                hole=0.62,
                marker={"colors": colors},
                text=pie_text,
                textinfo="text",
                textposition="inside",
                textfont={"size": 14, "color": "#ffffff"},
                hovertemplate="%{label}: %{percent}<extra></extra>",
                sort=False,
            )
        )
        fig.update_layout(
            title="Percentual atividade/problemas",
            height=520,
            margin={"t": 70, "r": 10, "b": 10, "l": 10},
            legend={"orientation": "h", "y": -0.06, "x": 0.0},
            annotations=[
                {
                    "text": center_text,
                    "x": 0.5,
                    "y": 0.52,
                    "font": {"size": 46, "color": "#e2e8f0"},
                    "showarrow": False,
                },
                {
                    "text": center_sub,
                    "x": 0.5,
                    "y": 0.43,
                    "font": {"size": 14, "color": "#94a3b8"},
                    "showarrow": False,
                },
            ],
        )
        st.plotly_chart(fig, use_container_width=True)

    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            x=daily_view["ddmm"],
            y=daily_view["atividades"],
            name="Atividades",
            marker_color="#4fb387",
        )
    )
    fig.add_trace(
        go.Bar(
            x=daily_view["ddmm"],
            y=daily_view["problemas"],
            name="Problemas",
            marker_color="#c97a7a",
        )
    )
    fig.update_layout(
        title="Dias: Atividade e Problemas (coluna empilhada)",
        barmode="stack",
        height=300,
        margin={"t": 50, "r": 20, "b": 70, "l": 20},
        legend={"orientation": "h", "yanchor": "top", "y": -0.22, "xanchor": "left", "x": 0},
    )
    fig.update_xaxes(tickmode="array", tickvals=tick_vals, ticktext=tick_vals, tickangle=-20)
    st.plotly_chart(fig, use_container_width=True)

    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            x=activity_monthly["ano_mes"],
            y=activity_monthly["atividades"],
            name="Atividades",
            marker_color="#4fb387",
        )
    )
    fig.add_trace(
        go.Bar(
            x=activity_monthly["ano_mes"],
            y=activity_monthly["problemas"],
            name="Problemas",
            marker_color="#c97a7a",
        )
    )
    fig.update_layout(
        title="Meses: Atividade e Problemas (coluna empilhada)",
        barmode="stack",
        height=300,
        margin={"t": 50, "r": 20, "b": 60, "l": 20},
        legend={"orientation": "h", "yanchor": "top", "y": -0.22, "xanchor": "left", "x": 0},
    )
    st.plotly_chart(fig, use_container_width=True)

with tab_hidrico:
    st.subheader("Controle hídrico")
    h1, h2, h3, h4 = st.columns(4)
    _render_summary_card(
        h1,
        "Volume captado",
        fmt_m3(dia["consumo_agua_m3"]),
        f"S {fmt_m3(semana['consumo_agua_m3'])} | M {fmt_m3(mes['consumo_agua_m3'])}",
        "water",
        "water",
    )
    _render_summary_card(
        h2,
        "Volume aplicado",
        fmt_m3(dia["aporte_m3"]),
        f"S {fmt_m3(semana['aporte_m3'])} | M {fmt_m3(mes['aporte_m3'])}",
        "usage",
        "usage",
    )
    _render_summary_card(
        h3,
        "Perdas por vazamento",
        fmt_m3(dia["perdas_m3"]),
        f"S {fmt_m3(semana['perdas_m3'])} | M {fmt_m3(mes['perdas_m3'])}",
        "loss",
        "loss",
    )
    _render_summary_card(
        h4,
        "Perdas (%)",
        fmt_pct(dia["perdas_pct"]),
        f"S {fmt_pct(semana['perdas_pct'])} | M {fmt_pct(mes['perdas_pct'])}",
        "loss",
        "loss",
    )

    st.markdown("<div style='height: 12px;'></div>", unsafe_allow_html=True)

    h5, h6, h7, h8 = st.columns(4)
    _render_summary_card(
        h5,
        "Conformidade outorga",
        fmt_pct(dia["conformidade_outorga_pct"]),
        f"S {fmt_pct(semana['conformidade_outorga_pct'])} | M {fmt_pct(mes['conformidade_outorga_pct'])}",
        "cost",
        "cost",
    )
    _render_summary_card(
        h6,
        "Conformidade pH",
        fmt_pct(dia["ph_conformidade_pct"]),
        f"S {fmt_pct(semana['ph_conformidade_pct'])} | M {fmt_pct(mes['ph_conformidade_pct'])}",
        "water",
        "water",
    )
    _render_summary_card(
        h7,
        "Conformidade turbidez",
        fmt_pct(dia["turbidez_conformidade_pct"]),
        f"S {fmt_pct(semana['turbidez_conformidade_pct'])} | M {fmt_pct(mes['turbidez_conformidade_pct'])}",
        "usage",
        "usage",
    )
    pressao_ratio_pct = (weighted["pressao_media_pond"] / max(weighted["pressao_alvo_pond"], 1e-6)) * 100.0
    _render_summary_card(
        h8,
        "Pressão média vs alvo",
        f"{weighted['pressao_media_pond']:.2f} / {weighted['pressao_alvo_pond']:.2f} bar",
        f"{pressao_ratio_pct:.0f}% do alvo",
        "energy",
        "energy",
    )

    st.markdown("<div style='height: 18px;'></div>", unsafe_allow_html=True)

    st.markdown("##### Diário (últimos 31 dias)")
    daily_31 = daily.tail(31).copy()
    if daily_31.empty:
        st.info("Sem dados diários para o período selecionado.")
    else:
        daily_31["ddmm"] = pd.to_datetime(daily_31["data"]).dt.strftime("%d/%m")
        daily_tick_step = max(len(daily_31) // 8, 1)
        daily_tick_vals = daily_31["ddmm"].iloc[::daily_tick_step]

        d1, d2, d3 = st.columns(3)
        with d1:
            fig = go.Figure()
            fig.add_trace(
                go.Bar(
                    x=daily_31["ddmm"],
                    y=daily_31["volume_captado_m3"],
                    name="Volume captado",
                    marker_color="#60a5fa",
                )
            )
            fig.update_layout(
                title="Captação (m³)",
                height=260,
                margin={"t": 50, "r": 20, "b": 30, "l": 20},
                showlegend=False,
            )
            fig.update_xaxes(tickmode="array", tickvals=daily_tick_vals, ticktext=daily_tick_vals, tickangle=-20)
            fig.update_yaxes(title="m³", rangemode="tozero")
            st.plotly_chart(fig, use_container_width=True)

        with d2:
            fig = go.Figure()
            fig.add_trace(
                go.Bar(
                    x=daily_31["ddmm"],
                    y=daily_31["volume_aplicado_m3"],
                    name="Volume aplicado",
                    marker_color="#4fb387",
                )
            )
            fig.update_layout(
                title="Aplicação (m³)",
                height=260,
                margin={"t": 50, "r": 20, "b": 30, "l": 20},
                showlegend=False,
            )
            fig.update_xaxes(tickmode="array", tickvals=daily_tick_vals, ticktext=daily_tick_vals, tickangle=-20)
            fig.update_yaxes(title="m³", rangemode="tozero")
            st.plotly_chart(fig, use_container_width=True)

        with d3:
            fig = go.Figure()
            fig.add_trace(
                go.Bar(
                    x=daily_31["ddmm"],
                    y=daily_31["perdas_m3"],
                    name="Perdas",
                    marker_color="#c97a7a",
                )
            )
            fig.update_layout(
                title="Perdas (m³)",
                height=260,
                margin={"t": 50, "r": 20, "b": 30, "l": 20},
                showlegend=False,
            )
            fig.update_xaxes(tickmode="array", tickvals=daily_tick_vals, ticktext=daily_tick_vals, tickangle=-20)
            fig.update_yaxes(title="m³", rangemode="tozero")
            st.plotly_chart(fig, use_container_width=True)

    st.markdown("##### Mensal (YYYY-MM)")
    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            x=monthly["ano_mes"],
            y=monthly["volume_captado_m3"],
            name="Volume captado (m³)",
            marker_color="#60a5fa",
        )
    )
    fig.add_trace(
        go.Bar(
            x=monthly["ano_mes"],
            y=monthly["volume_aplicado_m3"],
            name="Volume aplicado (m³)",
            marker_color="#4fb387",
        )
    )
    fig.add_trace(
        go.Bar(
            x=monthly["ano_mes"],
            y=monthly["perdas_m3"],
            name="Perdas (m³)",
            marker_color="#c97a7a",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=monthly["ano_mes"],
            y=monthly["perdas_pct"] * 100,
            name="Perdas (%)",
            mode="lines+markers",
            yaxis="y2",
            line={"color": "#f59e0b", "width": 2.5},
            marker={"size": 7},
        )
    )
    fig.update_layout(
        title="Consumo e perdas por mês",
        barmode="group",
        height=330,
        margin={"t": 50, "r": 56, "b": 30, "l": 20},
        legend={"orientation": "h", "yanchor": "top", "y": -0.18, "xanchor": "left", "x": 0},
        yaxis={"title": "m³", "rangemode": "tozero"},
        yaxis2={"title": "%", "overlaying": "y", "side": "right", "rangemode": "tozero"},
    )
    st.plotly_chart(fig, use_container_width=True)

with tab_clima:
    st.subheader("Acompanhamento climático")
    st.caption("Open-Meteo + cache SQLite")

    fazendas_sel = list(filters.fazenda_ids) if filters.fazenda_ids else None
    clima_df = load_cached_climate(
        start_date=filters.start_date,
        end_date=filters.end_date,
        fazenda_ids=fazendas_sel,
    )

    if clima_df.empty:
        st.warning("Sem clima em cache para o período selecionado.")
    else:
        clima_df["data"] = pd.to_datetime(clima_df["data"]).dt.date
        agg = (
            clima_df.groupby("data", as_index=False)
            .agg(
                precipitacao_mm=("precipitacao_mm", "mean"),
                temp_min_c=("temp_min_c", "mean"),
                temp_max_c=("temp_max_c", "mean"),
                vento_max_ms=("vento_max_ms", "mean"),
                eto_mm_dia=("eto_mm_dia", "mean"),
                etc_mm_dia=("etc_mm_dia", "mean"),
            )
            .sort_values("data")
        )
        agg["ddmm"] = pd.to_datetime(agg["data"]).dt.strftime("%d/%m")

        last = agg.iloc[-1]
        avg_rain = float(agg["precipitacao_mm"].mean())
        avg_wind = float(agg["vento_max_ms"].mean())
        avg_tmin = float(agg["temp_min_c"].mean())
        avg_tmax = float(agg["temp_max_c"].mean())
        avg_eto = float(agg["eto_mm_dia"].mean())
        avg_etc = float(agg["etc_mm_dia"].mean())

        c1, c2, c3, c4, c5 = st.columns(5)
        _render_summary_card(
            c1,
            "Chuva",
            f"{last['precipitacao_mm']:.1f} mm",
            f"Média {avg_rain:.1f} mm",
            "water",
            "water",
        )
        _render_summary_card(
            c2,
            "Vento",
            f"{last['vento_max_ms']:.1f} m/s",
            f"Média {avg_wind:.1f} m/s",
            "usage",
            "usage",
        )
        _render_summary_card(
            c3,
            "Temp mín",
            f"{last['temp_min_c']:.1f} °C",
            f"Média {avg_tmin:.1f} °C",
            "energy",
            "energy",
        )
        _render_summary_card(
            c4,
            "Temp máx",
            f"{last['temp_max_c']:.1f} °C",
            f"Média {avg_tmax:.1f} °C",
            "alert",
            "alert",
        )
        _render_summary_card(
            c5,
            "ETo / ETc",
            f"{last['eto_mm_dia']:.2f} / {last['etc_mm_dia']:.2f} mm",
            f"Médias {avg_eto:.2f} / {avg_etc:.2f} mm",
            "cost",
            "cost",
        )

        st.markdown("<div style='height: 14px;'></div>", unsafe_allow_html=True)

        st.markdown("##### Diário (últimos 31 dias)")
        clima_31 = agg.tail(31).copy()
        clima_31["temp_media_c"] = (clima_31["temp_min_c"] + clima_31["temp_max_c"]) / 2.0
        clima_31["ddmm"] = pd.to_datetime(clima_31["data"]).dt.strftime("%d/%m")
        clima_tick_step = max(len(clima_31) // 8, 1)
        clima_tick_vals = clima_31["ddmm"].iloc[::clima_tick_step]

        g1, g2, g3 = st.columns(3)
        with g1:
            fig = go.Figure()
            fig.add_trace(
                go.Bar(
                    x=clima_31["ddmm"],
                    y=clima_31["precipitacao_mm"],
                    name="Chuva",
                    marker_color="#38bdf8",
                )
            )
            fig.update_layout(
                title="Chuva (mm)",
                height=280,
                margin={"t": 50, "r": 20, "b": 30, "l": 20},
                showlegend=False,
            )
            fig.update_xaxes(tickmode="array", tickvals=clima_tick_vals, ticktext=clima_tick_vals, tickangle=-20)
            fig.update_yaxes(title="mm", rangemode="tozero")
            st.plotly_chart(fig, use_container_width=True)

        with g2:
            fig = go.Figure()
            fig.add_trace(
                go.Bar(
                    x=clima_31["ddmm"],
                    y=clima_31["vento_max_ms"],
                    name="Vento",
                    marker_color="#4fb387",
                )
            )
            fig.update_layout(
                title="Vento (m/s)",
                height=280,
                margin={"t": 50, "r": 20, "b": 30, "l": 20},
                showlegend=False,
            )
            fig.update_xaxes(tickmode="array", tickvals=clima_tick_vals, ticktext=clima_tick_vals, tickangle=-20)
            fig.update_yaxes(title="m/s", rangemode="tozero")
            st.plotly_chart(fig, use_container_width=True)

        with g3:
            fig = go.Figure()
            fig.add_trace(
                go.Bar(
                    x=clima_31["ddmm"],
                    y=clima_31["temp_media_c"],
                    name="Temperatura média",
                    marker_color="#f59e0b",
                )
            )
            fig.update_layout(
                title="Temperatura média (°C)",
                height=280,
                margin={"t": 50, "r": 20, "b": 30, "l": 20},
                showlegend=False,
            )
            fig.update_xaxes(tickmode="array", tickvals=clima_tick_vals, ticktext=clima_tick_vals, tickangle=-20)
            fig.update_yaxes(title="°C", rangemode="tozero")
            st.plotly_chart(fig, use_container_width=True)

        st.markdown("<div style='height: 14px;'></div>", unsafe_allow_html=True)
        st.markdown("##### Mensal (YYYY-MM)")
        monthly_climate = (
            agg.assign(
                ano_mes=pd.to_datetime(agg["data"]).dt.to_period("M").astype(str),
                temp_media_c=(agg["temp_min_c"] + agg["temp_max_c"]) / 2.0,
            )
            .groupby("ano_mes", as_index=False)
            .agg(
                precipitacao_mm=("precipitacao_mm", "sum"),
                vento_max_ms=("vento_max_ms", "mean"),
                temp_media_c=("temp_media_c", "mean"),
            )
            .sort_values("ano_mes")
        )

        m1, m2, m3 = st.columns(3)
        with m1:
            fig = go.Figure()
            fig.add_trace(
                go.Bar(
                    x=monthly_climate["ano_mes"],
                    y=monthly_climate["precipitacao_mm"],
                    name="Chuva mensal",
                    marker_color="#38bdf8",
                )
            )
            fig.update_layout(
                title="Chuva mensal (mm)",
                height=280,
                margin={"t": 50, "r": 20, "b": 20, "l": 20},
                showlegend=False,
            )
            fig.update_yaxes(title="mm", rangemode="tozero")
            st.plotly_chart(fig, use_container_width=True)

        with m2:
            fig = go.Figure()
            fig.add_trace(
                go.Bar(
                    x=monthly_climate["ano_mes"],
                    y=monthly_climate["vento_max_ms"],
                    name="Vento médio",
                    marker_color="#4fb387",
                )
            )
            fig.update_layout(
                title="Vento médio (m/s)",
                height=280,
                margin={"t": 50, "r": 20, "b": 20, "l": 20},
                showlegend=False,
            )
            fig.update_yaxes(title="m/s", rangemode="tozero")
            st.plotly_chart(fig, use_container_width=True)

        with m3:
            fig = go.Figure()
            fig.add_trace(
                go.Bar(
                    x=monthly_climate["ano_mes"],
                    y=monthly_climate["temp_media_c"],
                    name="Temperatura média",
                    marker_color="#f59e0b",
                )
            )
            fig.update_layout(
                title="Temperatura média (°C)",
                height=280,
                margin={"t": 50, "r": 20, "b": 20, "l": 20},
                showlegend=False,
            )
            fig.update_yaxes(title="°C", rangemode="tozero")
            st.plotly_chart(fig, use_container_width=True)

with tab_custos:
    st.subheader("Custos")
    cost_table = (
        df.groupby(["fazenda_nome", "bloco_nome", "talhao_codigo", "talhao_nome"], as_index=False)
        .agg(
            volume_captado_m3=("volume_captado_m3", "sum"),
            energia_kwh=("energia_kwh", "sum"),
            custo_agua_rs=("custo_agua_rs", "sum"),
            custo_energia_rs=("custo_energia_rs", "sum"),
            custo_manutencao_rs=("custo_manutencao_rs", "sum"),
            custo_total_rs=("custo_total_dia_rs", "sum"),
            area_ha=("area_ha", "max"),
        )
        .sort_values(["fazenda_nome", "bloco_nome", "talhao_codigo"])
    )

    total_capt = float(cost_table["volume_captado_m3"].sum())
    total_aplic = float(df["volume_aplicado_m3"].sum())
    total_area = float(cost_table["area_ha"].sum())
    total_cost = float(cost_table["custo_total_rs"].sum())
    total_water_cost = float(cost_table["custo_agua_rs"].sum())
    total_energy_cost = float(cost_table["custo_energia_rs"].sum())
    custo_agua_m3 = float(total_water_cost / max(total_capt, 1e-6))
    custo_energia_m3 = float(total_energy_cost / max(total_aplic, 1e-6))
    custo_total_ha = float(total_cost / max(total_area, 1e-6))

    c1, c2, c3, c4 = st.columns(4)
    _render_summary_card(
        c1,
        "Custo água por m³",
        fmt_rs(custo_agua_m3),
        f"Base {fmt_m3(total_capt)}",
        "water",
        "water",
    )
    _render_summary_card(
        c2,
        "Custo energia por m³",
        fmt_rs(custo_energia_m3),
        f"Base {fmt_m3(total_aplic)}",
        "energy",
        "energy",
    )
    _render_summary_card(
        c3,
        "Custo total irrigação por ha",
        fmt_rs(custo_total_ha),
        f"Área total {fmt_num(total_area, 1)} ha",
        "cost",
        "cost",
    )
    _render_summary_card(
        c4,
        "Custo total",
        fmt_rs(total_cost),
        "",
        "cost",
        "cost",
    )

    st.markdown("<div style='height: 14px;'></div>", unsafe_allow_html=True)

    by_farm = (
        cost_table.groupby("fazenda_nome", as_index=False)
        .agg(
            custo_agua_rs=("custo_agua_rs", "sum"),
            custo_energia_rs=("custo_energia_rs", "sum"),
            custo_manutencao_rs=("custo_manutencao_rs", "sum"),
            custo_total_rs=("custo_total_rs", "sum"),
        )
        .sort_values("custo_total_rs", ascending=False)
    )

    st.markdown("##### Custos por fazenda")
    g1, g2, g3 = st.columns(3)
    with g1:
        fig = go.Figure()
        fig.add_trace(
            go.Bar(
                x=by_farm["fazenda_nome"],
                y=by_farm["custo_agua_rs"],
                name="Custo água",
                marker_color="#38bdf8",
            )
        )
        fig.update_layout(
            title="Água (R$)",
            height=300,
            margin={"t": 50, "r": 20, "b": 20, "l": 20},
            showlegend=False,
        )
        fig.update_yaxes(title="R$", rangemode="tozero")
        st.plotly_chart(fig, use_container_width=True)
    with g2:
        fig = go.Figure()
        fig.add_trace(
            go.Bar(
                x=by_farm["fazenda_nome"],
                y=by_farm["custo_energia_rs"],
                name="Custo energia",
                marker_color="#4fb387",
            )
        )
        fig.update_layout(
            title="Energia (R$)",
            height=300,
            margin={"t": 50, "r": 20, "b": 20, "l": 20},
            showlegend=False,
        )
        fig.update_yaxes(title="R$", rangemode="tozero")
        st.plotly_chart(fig, use_container_width=True)
    with g3:
        fig = go.Figure()
        fig.add_trace(
            go.Bar(
                x=by_farm["fazenda_nome"],
                y=by_farm["custo_manutencao_rs"],
                name="Custo manutenção",
                marker_color="#f59e0b",
            )
        )
        fig.update_layout(
            title="Manutenção (R$)",
            height=300,
            margin={"t": 50, "r": 20, "b": 20, "l": 20},
            showlegend=False,
        )
        fig.update_yaxes(title="R$", rangemode="tozero")
        st.plotly_chart(fig, use_container_width=True)

    st.markdown("<div style='height: 12px;'></div>", unsafe_allow_html=True)
    st.markdown("##### Mensal (YYYY-MM)")
    monthly_costs = (
        df.assign(ano_mes=pd.to_datetime(df["data"]).dt.to_period("M").astype(str))
        .groupby("ano_mes", as_index=False)
        .agg(
            custo_agua_rs=("custo_agua_rs", "sum"),
            custo_energia_rs=("custo_energia_rs", "sum"),
            custo_manutencao_rs=("custo_manutencao_rs", "sum"),
        )
        .sort_values("ano_mes")
    )

    m1, m2, m3 = st.columns(3)
    with m1:
        fig = go.Figure()
        fig.add_trace(
            go.Bar(
                x=monthly_costs["ano_mes"],
                y=monthly_costs["custo_agua_rs"],
                name="Custo água",
                marker_color="#38bdf8",
            )
        )
        fig.update_layout(
            title="Custo água (R$)",
            height=280,
            margin={"t": 50, "r": 20, "b": 20, "l": 20},
            showlegend=False,
        )
        fig.update_yaxes(title="R$", rangemode="tozero")
        st.plotly_chart(fig, use_container_width=True)

    with m2:
        fig = go.Figure()
        fig.add_trace(
            go.Bar(
                x=monthly_costs["ano_mes"],
                y=monthly_costs["custo_energia_rs"],
                name="Custo energia",
                marker_color="#4fb387",
            )
        )
        fig.update_layout(
            title="Custo energia (R$)",
            height=280,
            margin={"t": 50, "r": 20, "b": 20, "l": 20},
            showlegend=False,
        )
        fig.update_yaxes(title="R$", rangemode="tozero")
        st.plotly_chart(fig, use_container_width=True)

    with m3:
        fig = go.Figure()
        fig.add_trace(
            go.Bar(
                x=monthly_costs["ano_mes"],
                y=monthly_costs["custo_manutencao_rs"],
                name="Custo manutenção",
                marker_color="#f59e0b",
            )
        )
        fig.update_layout(
            title="Custo manutenção (R$)",
            height=280,
            margin={"t": 50, "r": 20, "b": 20, "l": 20},
            showlegend=False,
        )
        fig.update_yaxes(title="R$", rangemode="tozero")
        st.plotly_chart(fig, use_container_width=True)

with tab_demanda:
    st.subheader("Demanda & Aplicação")
    demanda_dia_mm = float(daily["demanda_mm_dia"].iloc[-1]) if not daily.empty else 0.0
    demanda_media_31_mm = float(daily["demanda_mm_dia"].tail(31).mean()) if not daily.empty else 0.0
    atendimento_dia = float(np.clip(dia["atendimento_medio"], 0, 2.0))
    atendimento_media_31 = float(np.clip(daily["atendimento_demanda"].tail(31).mean(), 0, 2.0)) if not daily.empty else 0.0

    atividades_dia = int(activity_daily["atividades"].iloc[-1]) if not activity_daily.empty else 0
    atividades_media_31 = float(activity_daily["atividades"].tail(31).mean()) if not activity_daily.empty else 0.0
    horas_irrigadas_dia = float(activity_daily["horas_irrigadas"].iloc[-1]) if not activity_daily.empty else 0.0
    horas_paradas_dia = float(activity_daily["horas_paradas"].iloc[-1]) if not activity_daily.empty else 0.0
    horas_irrigadas_31 = float(activity_daily["horas_irrigadas"].tail(31).sum()) if not activity_daily.empty else 0.0
    horas_paradas_31 = float(activity_daily["horas_paradas"].tail(31).sum()) if not activity_daily.empty else 0.0
    horas_total_dia = horas_irrigadas_dia + horas_paradas_dia
    taxa_parada_dia = horas_paradas_dia / max(horas_total_dia, 1e-6)
    problemas_total = int(df["teve_problema"].sum())
    problemas_31 = int(activity_daily["problemas"].tail(31).sum()) if not activity_daily.empty else 0

    c1, c2, c3, c4 = st.columns(4)
    _render_summary_card(
        c1,
        "Lâmina aplicada (mm)",
        fmt_mm(dia["aporte_mm"]),
        f"S {fmt_mm(semana.get('aporte_mm', 0.0))} | M {fmt_mm(mes.get('aporte_mm', 0.0))}",
        "water",
        "water",
    )
    _render_summary_card(
        c2,
        "Demanda hídrica (mm)",
        f"{demanda_dia_mm:.2f} mm",
        f"Média 31d {demanda_media_31_mm:.2f} mm",
        "usage",
        "usage",
    )
    _render_summary_card(
        c3,
        "Atendimento da demanda",
        fmt_pct(atendimento_dia),
        f"Média 31d {fmt_pct(atendimento_media_31)}",
        "cost",
        "cost",
    )
    _render_summary_card(
        c4,
        "Atividades de campo (dia)",
        str(atividades_dia),
        f"Média 31d {fmt_num(atividades_media_31, 1)}",
        "alert",
        "alert",
    )

    st.markdown("<div style='height: 12px;'></div>", unsafe_allow_html=True)

    c5, c6, c7, c8 = st.columns(4)
    _render_summary_card(
        c5,
        "Horas irrigadas (dia)",
        f"{horas_irrigadas_dia:.1f} h",
        f"31d {horas_irrigadas_31:.1f} h",
        "water",
        "water",
    )
    _render_summary_card(
        c6,
        "Horas paradas (dia)",
        f"{horas_paradas_dia:.1f} h",
        f"31d {horas_paradas_31:.1f} h",
        "loss",
        "loss",
    )
    _render_summary_card(
        c7,
        "Ocorrências de problema",
        str(problemas_total),
        f"Últimos 31d: {problemas_31}",
        "alert",
        "alert",
    )
    _render_summary_card(
        c8,
        "Taxa de parada (dia)",
        fmt_pct(taxa_parada_dia),
        f"{horas_paradas_dia:.1f}h de {horas_total_dia:.1f}h",
        "loss",
        "loss",
    )

    st.markdown("<div style='height: 14px;'></div>", unsafe_allow_html=True)

    st.markdown("##### Diário (últimos 31 dias)")
    daily_31_dem = daily.tail(31).copy()
    daily_31_act = activity_daily.tail(31).copy()

    if daily_31_dem.empty:
        st.info("Sem dados diários de demanda no período selecionado.")
    else:
        daily_31_dem["ddmm"] = pd.to_datetime(daily_31_dem["data"]).dt.strftime("%d/%m")
        daily_31_dem["atendimento_pct"] = np.clip(daily_31_dem["atendimento_demanda"], 0, 2.0) * 100.0
        daily_31_dem["saldo_mm"] = daily_31_dem["lamina_mm"] - daily_31_dem["demanda_mm_dia"]
        demand_tick_step = max(len(daily_31_dem) // 8, 1)
        demand_tick_vals = daily_31_dem["ddmm"].iloc[::demand_tick_step]

        d1, d2, d3 = st.columns(3)
        with d1:
            fig = go.Figure()
            fig.add_trace(
                go.Bar(
                    x=daily_31_dem["ddmm"],
                    y=daily_31_dem["lamina_mm"],
                    name="Aplicação",
                    marker_color="#38bdf8",
                )
            )
            fig.update_layout(
                title="Aplicação diária (mm)",
                height=280,
                margin={"t": 50, "r": 20, "b": 30, "l": 20},
                showlegend=False,
            )
            fig.update_xaxes(tickmode="array", tickvals=demand_tick_vals, ticktext=demand_tick_vals, tickangle=-20)
            fig.update_yaxes(title="mm", rangemode="tozero")
            st.plotly_chart(fig, use_container_width=True)

        with d2:
            fig = go.Figure()
            fig.add_trace(
                go.Bar(
                    x=daily_31_dem["ddmm"],
                    y=daily_31_dem["demanda_mm_dia"],
                    name="Demanda",
                    marker_color="#4fb387",
                )
            )
            fig.update_layout(
                title="Demanda diária (mm)",
                height=280,
                margin={"t": 50, "r": 20, "b": 30, "l": 20},
                showlegend=False,
            )
            fig.update_xaxes(tickmode="array", tickvals=demand_tick_vals, ticktext=demand_tick_vals, tickangle=-20)
            fig.update_yaxes(title="mm", rangemode="tozero")
            st.plotly_chart(fig, use_container_width=True)

        with d3:
            fig = go.Figure()
            fig.add_trace(
                go.Bar(
                    x=daily_31_dem["ddmm"],
                    y=daily_31_dem["atendimento_pct"],
                    name="Atendimento",
                    marker_color="#f59e0b",
                )
            )
            fig.update_layout(
                title="Atendimento diário (%)",
                height=280,
                margin={"t": 50, "r": 20, "b": 30, "l": 20},
                showlegend=False,
            )
            fig.update_xaxes(tickmode="array", tickvals=demand_tick_vals, ticktext=demand_tick_vals, tickangle=-20)
            fig.update_yaxes(title="%", rangemode="tozero")
            st.plotly_chart(fig, use_container_width=True)

        st.markdown("<div style='height: 12px;'></div>", unsafe_allow_html=True)
        d4, d5 = st.columns(2)
        with d4:
            saldo_colors = np.where(daily_31_dem["saldo_mm"] >= 0, "#4fb387", "#c97a7a")
            fig = go.Figure()
            fig.add_trace(
                go.Bar(
                    x=daily_31_dem["ddmm"],
                    y=daily_31_dem["saldo_mm"],
                    name="Saldo",
                    marker_color=saldo_colors,
                )
            )
            fig.update_layout(
                title="Saldo hídrico diário (aplicação - demanda)",
                height=290,
                margin={"t": 50, "r": 20, "b": 30, "l": 20},
                showlegend=False,
            )
            fig.update_xaxes(tickmode="array", tickvals=demand_tick_vals, ticktext=demand_tick_vals, tickangle=-20)
            fig.update_yaxes(title="mm")
            st.plotly_chart(fig, use_container_width=True)

        with d5:
            if daily_31_act.empty:
                st.info("Sem dados de atividade para os últimos 31 dias.")
            else:
                daily_31_act["ddmm"] = pd.to_datetime(daily_31_act["data"]).dt.strftime("%d/%m")
                act_tick_step = max(len(daily_31_act) // 8, 1)
                act_tick_vals = daily_31_act["ddmm"].iloc[::act_tick_step]
                fig = go.Figure()
                fig.add_trace(
                    go.Bar(
                        x=daily_31_act["ddmm"],
                        y=daily_31_act["horas_irrigadas"],
                        name="Horas irrigadas",
                        marker_color="#38bdf8",
                    )
                )
                fig.add_trace(
                    go.Bar(
                        x=daily_31_act["ddmm"],
                        y=daily_31_act["horas_paradas"],
                        name="Horas paradas",
                        marker_color="#c97a7a",
                    )
                )
                fig.update_layout(
                    title="Horas de campo (31 dias)",
                    barmode="group",
                    height=290,
                    margin={"t": 50, "r": 20, "b": 30, "l": 20},
                    legend={"orientation": "h", "yanchor": "top", "y": -0.18, "xanchor": "left", "x": 0},
                )
                fig.update_xaxes(tickmode="array", tickvals=act_tick_vals, ticktext=act_tick_vals, tickangle=-20)
                fig.update_yaxes(title="h", rangemode="tozero")
                st.plotly_chart(fig, use_container_width=True)

    st.markdown("<div style='height: 12px;'></div>", unsafe_allow_html=True)
    st.markdown("##### Mensal (YYYY-MM)")
    monthly_demanda = (
        daily.assign(ano_mes=pd.to_datetime(daily["data"]).dt.to_period("M").astype(str))
        .groupby("ano_mes", as_index=False)
        .agg(
            aplicacao_mm=("lamina_mm", "sum"),
            demanda_mm=("demanda_mm_dia", "sum"),
            atendimento_pct=("atendimento_demanda", "mean"),
        )
        .sort_values("ano_mes")
    )
    monthly_demanda["atendimento_pct"] = np.clip(monthly_demanda["atendimento_pct"], 0, 2.0) * 100.0
    monthly_demanda["saldo_mm"] = monthly_demanda["aplicacao_mm"] - monthly_demanda["demanda_mm"]

    m1, m2, m3 = st.columns(3)
    with m1:
        fig = go.Figure()
        fig.add_trace(
            go.Bar(
                x=monthly_demanda["ano_mes"],
                y=monthly_demanda["aplicacao_mm"],
                name="Aplicação",
                marker_color="#38bdf8",
            )
        )
        fig.add_trace(
            go.Bar(
                x=monthly_demanda["ano_mes"],
                y=monthly_demanda["demanda_mm"],
                name="Demanda",
                marker_color="#4fb387",
            )
        )
        fig.update_layout(
            title="Aplicação x Demanda (mm)",
            barmode="group",
            height=300,
            margin={"t": 50, "r": 20, "b": 20, "l": 20},
            legend={"orientation": "h", "yanchor": "top", "y": -0.18, "xanchor": "left", "x": 0},
        )
        fig.update_yaxes(title="mm", rangemode="tozero")
        st.plotly_chart(fig, use_container_width=True)

    with m2:
        saldo_mensal_colors = np.where(monthly_demanda["saldo_mm"] >= 0, "#4fb387", "#c97a7a")
        fig = go.Figure()
        fig.add_trace(
            go.Bar(
                x=monthly_demanda["ano_mes"],
                y=monthly_demanda["saldo_mm"],
                name="Saldo",
                marker_color=saldo_mensal_colors,
            )
        )
        fig.update_layout(
            title="Saldo hídrico mensal (mm)",
            height=300,
            margin={"t": 50, "r": 20, "b": 20, "l": 20},
            showlegend=False,
        )
        fig.update_yaxes(title="mm")
        st.plotly_chart(fig, use_container_width=True)

    with m3:
        fig = go.Figure()
        fig.add_trace(
            go.Bar(
                x=monthly_demanda["ano_mes"],
                y=monthly_demanda["atendimento_pct"],
                name="Atendimento médio",
                marker_color="#f59e0b",
            )
        )
        fig.update_layout(
            title="Atendimento médio mensal (%)",
            height=300,
            margin={"t": 50, "r": 20, "b": 20, "l": 20},
            showlegend=False,
        )
        fig.update_yaxes(title="%", rangemode="tozero")
        st.plotly_chart(fig, use_container_width=True)

with tab_energia:
    st.subheader("Eficiência & Energia")
    energia_dia = float(dia["energia_kwh"])
    energia_sem = float(semana["energia_kwh"])
    energia_mes = float(mes["energia_kwh"])
    energia_periodo = float(df["energia_kwh"].sum())
    energia_custo_total = float(df["custo_energia_rs"].sum())
    kwh_m3 = float(df["energia_kwh"].sum() / max(df["volume_aplicado_m3"].sum(), 1e-6))
    kwh_m3_sem = float(semana["energia_kwh"] / max(semana["aporte_m3"], 1e-6))
    kwh_m3_mes = float(mes["energia_kwh"] / max(mes["aporte_m3"], 1e-6))
    kwh_ha = float(df["energia_kwh"].sum() / max(df["area_ha"].sum(), 1e-6))
    kwh_ha_sem = float(semana["energia_kwh"] / max(area_base_ha, 1e-6))
    kwh_ha_mes = float(mes["energia_kwh"] / max(area_base_ha, 1e-6))
    custo_energia_m3 = float(df["custo_energia_rs"].sum() / max(df["volume_aplicado_m3"].sum(), 1e-6))

    c1, c2, c3 = st.columns(3)
    _render_summary_card(
        c1,
        "Energia (Dia)",
        fmt_kwh(energia_dia),
        f"S {fmt_kwh(energia_sem)} | M {fmt_kwh(energia_mes)}",
        "energy",
        "energy",
    )
    _render_summary_card(
        c2,
        "Energia (Semana)",
        fmt_kwh(energia_sem),
        f"Dia {fmt_kwh(energia_dia)} | M {fmt_kwh(energia_mes)}",
        "energy",
        "energy",
    )
    _render_summary_card(
        c3,
        "Energia (Mês)",
        fmt_kwh(energia_mes),
        f"Período {fmt_kwh(energia_periodo)}",
        "energy",
        "energy",
    )

    st.markdown("<div style='height: 12px;'></div>", unsafe_allow_html=True)

    c4, c5, c6 = st.columns(3)
    _render_summary_card(
        c4,
        "Consumo específico (kWh/m³)",
        f"{kwh_m3:.3f}",
        f"S {kwh_m3_sem:.3f} | M {kwh_m3_mes:.3f}",
        "usage",
        "usage",
    )
    _render_summary_card(
        c5,
        "Energia por ha (kWh/ha)",
        f"{kwh_ha:.2f}",
        f"S {kwh_ha_sem:.2f} | M {kwh_ha_mes:.2f}",
        "water",
        "water",
    )
    _render_summary_card(
        c6,
        "Custo energia por m³",
        fmt_rs(custo_energia_m3),
        f"Custo total {fmt_rs(energia_custo_total)}",
        "cost",
        "cost",
    )

    st.markdown("<div style='height: 12px;'></div>", unsafe_allow_html=True)

    c7, c8, c9 = st.columns(3)
    _render_summary_card(
        c7,
        "Ea",
        fmt_pct(dia["ea"]),
        f"S {fmt_pct(semana['ea'])} | M {fmt_pct(mes['ea'])}",
        "water",
        "water",
    )
    _render_summary_card(
        c8,
        "Eirr",
        fmt_pct(dia["eirr"]),
        f"S {fmt_pct(semana['eirr'])} | M {fmt_pct(mes['eirr'])}",
        "usage",
        "usage",
    )
    _render_summary_card(
        c9,
        "Perdas totais",
        fmt_pct(dia["perdas_pct"]),
        f"S {fmt_pct(semana['perdas_pct'])} | M {fmt_pct(mes['perdas_pct'])}",
        "loss",
        "loss",
    )

    st.markdown("<div style='height: 14px;'></div>", unsafe_allow_html=True)

    st.markdown("##### Diário (últimos 31 dias)")
    daily_energy = daily.tail(31).copy()
    if daily_energy.empty:
        st.info("Sem dados de energia para o período selecionado.")
    else:
        daily_energy["kwh_m3"] = np.divide(
            daily_energy["energia_kwh"],
            np.maximum(daily_energy["volume_aplicado_m3"], 1e-6),
        )
        daily_energy_cost = (
            df.groupby("data", as_index=False)
            .agg(custo_energia_rs=("custo_energia_rs", "sum"))
            .sort_values("data")
            .tail(31)
        )
        daily_energy = (
            daily_energy.merge(daily_energy_cost, on="data", how="left").fillna({"custo_energia_rs": 0.0})
        )
        daily_energy["ddmm"] = pd.to_datetime(daily_energy["data"]).dt.strftime("%d/%m")
        energy_tick_step = max(len(daily_energy) // 8, 1)
        energy_tick_vals = daily_energy["ddmm"].iloc[::energy_tick_step]

        d1, d2, d3 = st.columns(3)
        with d1:
            fig = go.Figure()
            fig.add_trace(
                go.Bar(
                    x=daily_energy["ddmm"],
                    y=daily_energy["energia_kwh"],
                    name="Energia",
                    marker_color="#60a5fa",
                )
            )
            fig.update_layout(
                title="Energia diária (kWh)",
                height=280,
                margin={"t": 50, "r": 20, "b": 30, "l": 20},
                showlegend=False,
            )
            fig.update_xaxes(tickmode="array", tickvals=energy_tick_vals, ticktext=energy_tick_vals, tickangle=-20)
            fig.update_yaxes(title="kWh", rangemode="tozero")
            st.plotly_chart(fig, use_container_width=True)

        with d2:
            fig = go.Figure()
            fig.add_trace(
                go.Bar(
                    x=daily_energy["ddmm"],
                    y=daily_energy["kwh_m3"],
                    name="Consumo específico",
                    marker_color="#4fb387",
                )
            )
            fig.update_layout(
                title="Consumo específico diário (kWh/m³)",
                height=280,
                margin={"t": 50, "r": 20, "b": 30, "l": 20},
                showlegend=False,
            )
            fig.update_xaxes(tickmode="array", tickvals=energy_tick_vals, ticktext=energy_tick_vals, tickangle=-20)
            fig.update_yaxes(title="kWh/m³", rangemode="tozero")
            st.plotly_chart(fig, use_container_width=True)

        with d3:
            fig = go.Figure()
            fig.add_trace(
                go.Bar(
                    x=daily_energy["ddmm"],
                    y=daily_energy["custo_energia_rs"],
                    name="Custo energia",
                    marker_color="#f59e0b",
                )
            )
            fig.update_layout(
                title="Custo energia diário (R$)",
                height=280,
                margin={"t": 50, "r": 20, "b": 30, "l": 20},
                showlegend=False,
            )
            fig.update_xaxes(tickmode="array", tickvals=energy_tick_vals, ticktext=energy_tick_vals, tickangle=-20)
            fig.update_yaxes(title="R$", rangemode="tozero")
            st.plotly_chart(fig, use_container_width=True)

    st.markdown("<div style='height: 12px;'></div>", unsafe_allow_html=True)
    st.markdown("##### Mensal (YYYY-MM)")
    monthly_energy = (
        df.assign(ano_mes=pd.to_datetime(df["data"]).dt.to_period("M").astype(str))
        .groupby("ano_mes", as_index=False)
        .agg(
            energia_kwh=("energia_kwh", "sum"),
            volume_aplicado_m3=("volume_aplicado_m3", "sum"),
            custo_energia_rs=("custo_energia_rs", "sum"),
        )
        .sort_values("ano_mes")
    )
    monthly_energy["kwh_m3"] = np.divide(
        monthly_energy["energia_kwh"],
        np.maximum(monthly_energy["volume_aplicado_m3"], 1e-6),
    )

    m1, m2, m3 = st.columns(3)
    with m1:
        fig = go.Figure()
        fig.add_trace(
            go.Bar(
                x=monthly_energy["ano_mes"],
                y=monthly_energy["energia_kwh"],
                name="Energia mensal",
                marker_color="#60a5fa",
            )
        )
        fig.update_layout(
            title="Energia mensal (kWh)",
            height=300,
            margin={"t": 50, "r": 20, "b": 20, "l": 20},
            showlegend=False,
        )
        fig.update_yaxes(title="kWh", rangemode="tozero")
        st.plotly_chart(fig, use_container_width=True)

    with m2:
        fig = go.Figure()
        fig.add_trace(
            go.Bar(
                x=monthly_energy["ano_mes"],
                y=monthly_energy["kwh_m3"],
                name="Consumo específico mensal",
                marker_color="#4fb387",
            )
        )
        fig.update_layout(
            title="Consumo específico mensal (kWh/m³)",
            height=300,
            margin={"t": 50, "r": 20, "b": 20, "l": 20},
            showlegend=False,
        )
        fig.update_yaxes(title="kWh/m³", rangemode="tozero")
        st.plotly_chart(fig, use_container_width=True)

    with m3:
        fig = go.Figure()
        fig.add_trace(
            go.Bar(
                x=monthly_energy["ano_mes"],
                y=monthly_energy["custo_energia_rs"],
                name="Custo energia mensal",
                marker_color="#f59e0b",
            )
        )
        fig.update_layout(
            title="Custo energia mensal (R$)",
            height=300,
            margin={"t": 50, "r": 20, "b": 20, "l": 20},
            showlegend=False,
        )
        fig.update_yaxes(title="R$", rangemode="tozero")
        st.plotly_chart(fig, use_container_width=True)

with tab_gestao:
    st.subheader("Gestão (Real x Planejamento)")
    pvr = planning_vs_actual(
        start_date=filters.start_date,
        end_date=filters.end_date,
        talhao_ids=filters.talhao_ids,
    )

    tempo_resposta_h = float(mgmt["tempo_resposta_h"])
    c1, c2, c3, c4 = st.columns(4)
    _render_summary_card(
        c1,
        "% Recomendação atualizada",
        fmt_pct(mgmt["talhoes_recomendacao_atualizada_pct"]),
        "Meta >= 95%",
        "usage",
        "usage",
    )
    _render_summary_card(
        c2,
        "% Leituras no prazo",
        fmt_pct(mgmt["leituras_no_prazo_pct"]),
        "Meta >= 95%",
        "water",
        "water",
    )
    _render_summary_card(
        c3,
        "Tempo resposta alarmes",
        f"{tempo_resposta_h:.2f} h",
        "Meta <= 4h",
        "alert",
        "alert",
    )
    _render_summary_card(
        c4,
        "% Preventivas em dia",
        fmt_pct(mgmt["preventiva_em_dia_pct"]),
        "Meta >= 90%",
        "cost",
        "cost",
    )

    st.markdown("<div style='height: 12px;'></div>", unsafe_allow_html=True)

    planos = int(len(pvr))
    concluidos = int((pvr["status"] == "CONCLUIDO").sum()) if planos > 0 else 0
    taxa_conclusao = concluidos / max(planos, 1e-6)
    aderencia_lamina = float(np.clip(pvr["aderencia_lamina_pct"].mean(), 0, 1.0)) if planos > 0 else 0.0
    aderencia_horas = float(np.clip(pvr["aderencia_horas_pct"].mean(), 0, 1.0)) if planos > 0 else 0.0

    a1, a2, a3, a4 = st.columns(4)
    _render_summary_card(
        a1,
        "Planos",
        str(planos),
        f"Concluídos: {concluidos}",
        "usage",
        "usage",
    )
    _render_summary_card(
        a2,
        "Concluídos",
        str(concluidos),
        f"Taxa {fmt_pct(taxa_conclusao)}",
        "water",
        "water",
    )
    _render_summary_card(
        a3,
        "Aderência lâmina",
        fmt_pct(aderencia_lamina),
        "Meta 100%",
        "energy",
        "energy",
    )
    _render_summary_card(
        a4,
        "Aderência horas",
        fmt_pct(aderencia_horas),
        "Meta 100%",
        "energy",
        "energy",
    )

    st.markdown("<div style='height: 14px;'></div>", unsafe_allow_html=True)

    if pvr.empty:
        st.info("Sem registros de planejamento no período selecionado.")
    else:

        pvr_day = (
            pvr.groupby("data_ref", as_index=False)
            .agg(
                horas_planejadas=("horas_planejadas", "sum"),
                horas_realizadas=("horas_realizadas", "sum"),
                lamina_planejada_mm=("lamina_planejada_mm", "sum"),
                lamina_real_mm=("lamina_real_mm", "sum"),
            )
            .sort_values("data_ref")
        )
        pvr_day = pvr_day.tail(31).copy()
        pvr_day["ddmm"] = pd.to_datetime(pvr_day["data_ref"]).dt.strftime("%d/%m")
        pvr_tick_step = max(len(pvr_day) // 8, 1)
        pvr_tick_vals = pvr_day["ddmm"].iloc[::pvr_tick_step]

        status_order = ["PLANEJADO", "EM_EXECUCAO", "CONCLUIDO", "ATRASADO", "CANCELADO"]
        status_labels = {
            "PLANEJADO": "Planejado",
            "EM_EXECUCAO": "Execução",
            "CONCLUIDO": "Concluído",
            "ATRASADO": "Atrasado",
            "CANCELADO": "Cancelado",
        }
        status_counts = (
            pvr.assign(status_norm=pvr["status"].astype(str).str.upper())
            .groupby("status_norm", as_index=False)
            .size()
            .rename(columns={"size": "qtd"})
        )
        status_counts = status_counts.set_index("status_norm").reindex(status_order, fill_value=0).reset_index()
        status_counts["label"] = status_counts["status_norm"].map(status_labels)
        status_total = float(status_counts["qtd"].sum())
        status_counts["pct"] = np.where(status_total > 0, (status_counts["qtd"] / status_total) * 100.0, 0.0)

        left_col, right_col = st.columns([2.2, 1.2], gap="medium")
        with left_col:
            fig = go.Figure()
            fig.add_trace(
                go.Bar(
                    x=pvr_day["ddmm"],
                    y=pvr_day["horas_planejadas"],
                    name="Horas planejadas",
                    marker_color="#60a5fa",
                )
            )
            fig.add_trace(
                go.Bar(
                    x=pvr_day["ddmm"],
                    y=pvr_day["horas_realizadas"],
                    name="Horas realizadas",
                    marker_color="#4fb387",
                )
            )
            fig.update_layout(
                title="Horas planejadas x realizadas (31 dias)",
                barmode="group",
                height=340,
                margin={"t": 55, "r": 20, "b": 45, "l": 20},
                legend={"orientation": "h", "yanchor": "top", "y": -0.18, "xanchor": "left", "x": 0},
            )
            fig.update_xaxes(tickmode="array", tickvals=pvr_tick_vals, ticktext=pvr_tick_vals, tickangle=-20)
            fig.update_yaxes(title="h", rangemode="tozero")
            st.plotly_chart(fig, use_container_width=True)

            st.markdown("<div style='height: 8px;'></div>", unsafe_allow_html=True)

            fig = go.Figure()
            fig.add_trace(
                go.Bar(
                    x=pvr_day["ddmm"],
                    y=pvr_day["lamina_planejada_mm"],
                    name="Lâmina planejada",
                    marker_color="#60a5fa",
                )
            )
            fig.add_trace(
                go.Bar(
                    x=pvr_day["ddmm"],
                    y=pvr_day["lamina_real_mm"],
                    name="Lâmina realizada",
                    marker_color="#4fb387",
                )
            )
            fig.update_layout(
                title="Lâmina planejada x realizada (31 dias)",
                barmode="group",
                height=340,
                margin={"t": 55, "r": 20, "b": 45, "l": 20},
                legend={"orientation": "h", "yanchor": "top", "y": -0.18, "xanchor": "left", "x": 0},
            )
            fig.update_xaxes(tickmode="array", tickvals=pvr_tick_vals, ticktext=pvr_tick_vals, tickangle=-20)
            fig.update_yaxes(title="mm", rangemode="tozero")
            st.plotly_chart(fig, use_container_width=True)

        with right_col:
            st.markdown("##### Status dos planos")
            if status_counts.empty:
                st.info("Sem status de planos no período.")
            else:
                radar_theta = status_counts["label"].tolist()
                radar_r = status_counts["pct"].tolist()
                radar_text = [f"{v:.1f}%" for v in radar_r]

                fig = go.Figure()
                fig.add_trace(
                    go.Scatterpolar(
                        r=radar_r,
                        theta=radar_theta,
                        fill="toself",
                        mode="lines+markers+text",
                        text=radar_text,
                        textposition="top center",
                        textfont={"size": 11, "color": "#e2e8f0"},
                        name="Status (%)",
                        line={"color": "#60a5fa", "width": 2.4},
                        marker={"size": 7, "color": "#4fb387"},
                    )
                )
                polar_cfg = {
                    "bgcolor": "rgba(2, 8, 23, 0.78)",
                    "radialaxis": {
                        "visible": True,
                        "range": [0, 100],
                        "ticksuffix": "%",
                        "tick0": 0,
                        "dtick": 20,
                        "tickfont": {"size": 11, "color": "#cbd5e1"},
                        "gridcolor": "rgba(148, 163, 184, 0.30)",
                    },
                    "angularaxis": {
                        "type": "category",
                        "tickfont": {"size": 11, "color": "#cbd5e1"},
                        "rotation": 90,
                        "direction": "clockwise",
                        "gridcolor": "rgba(148, 163, 184, 0.30)",
                    },
                }
                try:
                    fig.update_layout(
                        title="Radar de status (%)",
                        height=460,
                        margin={"t": 60, "r": 55, "b": 40, "l": 55},
                        showlegend=False,
                        polar={**polar_cfg, "gridshape": "linear"},
                    )
                except Exception:
                    # Alguns ambientes de deploy usam Plotly sem `gridshape` no polar.
                    fig.update_layout(
                        title="Radar de status (%)",
                        height=460,
                        margin={"t": 60, "r": 55, "b": 40, "l": 55},
                        showlegend=False,
                        polar=polar_cfg,
                    )
                st.plotly_chart(fig, use_container_width=True)
                st.caption(
                    " | ".join(
                        f"{row.label}: {int(row.qtd)} ({row.pct:.1f}%)"
                        for row in status_counts.itertuples(index=False)
                    )
                )

with tab_alertas:
    st.subheader("Alertas & Manutenção")
    manut_alerts = alerts_df[alerts_df["tipo"].isin(["PREVENTIVA_ATRASADA"])].copy()

    backlog = maintenance_backlog(limit=500)
    if not backlog.empty:
        backlog = backlog[(backlog["data_inicio"] >= filters.start_date) & (backlog["data_inicio"] <= filters.end_date)].copy()

    alertas_manut_total = int(len(manut_alerts))
    alertas_manut_abertos = int((manut_alerts["status"] == "ABERTO").sum()) if not manut_alerts.empty else 0
    alertas_manut_altos = int((manut_alerts["severidade"] == "ALTO").sum()) if not manut_alerts.empty else 0
    eventos_manut = int(len(backlog))
    tipos_manut = int(backlog["tipo"].nunique()) if not backlog.empty else 0
    custo_manut_total = float(backlog["custo_manutencao_rs"].sum()) if not backlog.empty else 0.0
    ticket_medio_manut = float(custo_manut_total / max(eventos_manut, 1))

    c1, c2, c3 = st.columns(3)
    _render_summary_card(
        c1,
        "Alertas de manutenção",
        str(alertas_manut_total),
        f"Abertos {alertas_manut_abertos} | Altos {alertas_manut_altos}",
        "alert",
        "alert",
    )
    _render_summary_card(
        c2,
        "Eventos de manutenção",
        str(eventos_manut),
        f"Tipos distintos {tipos_manut}",
        "usage",
        "usage",
    )
    _render_summary_card(
        c3,
        "Custo de manutenção",
        fmt_rs(custo_manut_total),
        f"Ticket médio {fmt_rs(ticket_medio_manut)}",
        "cost",
        "cost",
    )

    st.markdown("<div style='height: 14px;'></div>", unsafe_allow_html=True)

    sev_order = ["ALTO", "MEDIO", "BAIXO"]
    sev_df = (
        manut_alerts.assign(severidade_norm=manut_alerts["severidade"].astype(str).str.upper())
        .groupby("severidade_norm", as_index=False)
        .size()
        .rename(columns={"size": "qtd"})
    )
    sev_df = sev_df.set_index("severidade_norm").reindex(sev_order, fill_value=0).reset_index()
    sev_df = sev_df.rename(columns={"severidade_norm": "severidade"})

    alert_status_order = ["ABERTO", "FECHADO"]
    alert_status_df = (
        manut_alerts.assign(status_norm=manut_alerts["status"].astype(str).str.upper())
        .groupby("status_norm", as_index=False)
        .size()
        .rename(columns={"size": "qtd"})
    )
    alert_status_df = alert_status_df.set_index("status_norm").reindex(alert_status_order, fill_value=0).reset_index()
    alert_status_df = alert_status_df.rename(columns={"status_norm": "status"})

    g1, g2, g3 = st.columns(3)
    with g1:
        fig = go.Figure()
        fig.add_trace(
            go.Bar(
                x=sev_df["severidade"],
                y=sev_df["qtd"],
                marker_color=["#c97a7a", "#f59e0b", "#4fb387"],
                name="Alertas",
            )
        )
        fig.update_layout(
            title="Alertas por severidade",
            height=280,
            margin={"t": 50, "r": 20, "b": 20, "l": 20},
            showlegend=False,
        )
        fig.update_yaxes(title="qtd", rangemode="tozero")
        st.plotly_chart(fig, use_container_width=True)

    with g2:
        fig = go.Figure(
            go.Pie(
                labels=alert_status_df["status"],
                values=alert_status_df["qtd"],
                hole=0.58,
                marker={"colors": ["#c97a7a", "#4fb387"]},
                textinfo="percent",
            )
        )
        fig.update_layout(
            title="Status dos alertas",
            height=280,
            margin={"t": 50, "r": 20, "b": 20, "l": 20},
            legend={"orientation": "h", "yanchor": "top", "y": -0.12, "xanchor": "left", "x": 0},
        )
        st.plotly_chart(fig, use_container_width=True)

    with g3:
        if backlog.empty:
            st.info("Sem backlog de manutenção no período.")
        else:
            tipo_df = backlog.groupby("tipo", as_index=False).size().rename(columns={"size": "qtd"})
            fig = go.Figure(
                go.Pie(
                    labels=tipo_df["tipo"],
                    values=tipo_df["qtd"],
                    hole=0.45,
                    textinfo="percent",
                    marker={"colors": ["#60a5fa", "#4fb387", "#f59e0b", "#c97a7a"]},
                )
            )
            fig.update_layout(
                title="Composição do backlog",
                height=280,
                margin={"t": 50, "r": 20, "b": 20, "l": 20},
                legend={"orientation": "h", "yanchor": "top", "y": -0.12, "xanchor": "left", "x": 0},
            )
            st.plotly_chart(fig, use_container_width=True)

    if backlog.empty:
        st.info("Sem eventos de manutenção no período para detalhamento adicional.")
    else:
        tipo_stats = (
            backlog.groupby("tipo", as_index=False)
            .agg(
                eventos=("id", "count"),
                custo_rs=("custo_manutencao_rs", "sum"),
                duracao_media_h=("duracao_h", "mean"),
            )
            .sort_values("eventos", ascending=False)
        )
        tipo_stats["ticket_medio_rs"] = np.divide(tipo_stats["custo_rs"], np.maximum(tipo_stats["eventos"], 1))

        fazenda_stats = (
            backlog.groupby("fazenda_nome", as_index=False)
            .agg(eventos=("id", "count"), custo_rs=("custo_manutencao_rs", "sum"))
            .sort_values("custo_rs", ascending=False)
        )

        talhao_stats = (
            backlog.groupby(["fazenda_nome", "talhao_codigo", "talhao_nome"], as_index=False)
            .agg(eventos=("id", "count"), custo_rs=("custo_manutencao_rs", "sum"))
            .sort_values("custo_rs", ascending=False)
            .head(8)
        )
        talhao_stats["talhao_label"] = talhao_stats["talhao_codigo"].astype(str) + " - " + talhao_stats["talhao_nome"].astype(str)

        diario_manut = (
            backlog.assign(data_inicio=pd.to_datetime(backlog["data_inicio"]))
            .groupby("data_inicio", as_index=False)
            .agg(eventos=("id", "count"), custo_rs=("custo_manutencao_rs", "sum"))
            .sort_values("data_inicio")
            .tail(31)
        )
        diario_manut["ddmm"] = diario_manut["data_inicio"].dt.strftime("%d/%m")
        diario_tick_step = max(len(diario_manut) // 8, 1)
        diario_tick_vals = diario_manut["ddmm"].iloc[::diario_tick_step]

        mensal_manut = (
            backlog.assign(ano_mes=pd.to_datetime(backlog["data_inicio"]).dt.to_period("M").astype(str))
            .groupby("ano_mes", as_index=False)
            .agg(custo_manutencao_rs=("custo_manutencao_rs", "sum"), eventos=("id", "count"))
            .sort_values("ano_mes")
        )
        mensal_manut["ticket_medio_rs"] = np.divide(
            mensal_manut["custo_manutencao_rs"],
            np.maximum(mensal_manut["eventos"], 1),
        )

        st.markdown("<div style='height: 12px;'></div>", unsafe_allow_html=True)
        d1, d2, d3 = st.columns(3)
        with d1:
            fig = go.Figure()
            fig.add_trace(
                go.Bar(
                    x=tipo_stats["tipo"],
                    y=tipo_stats["eventos"],
                    name="Eventos",
                    marker_color="#60a5fa",
                )
            )
            fig.update_layout(
                title="Eventos por tipo",
                height=290,
                margin={"t": 50, "r": 20, "b": 20, "l": 20},
                showlegend=False,
            )
            fig.update_yaxes(title="qtd", rangemode="tozero")
            st.plotly_chart(fig, use_container_width=True)

        with d2:
            fig = go.Figure()
            fig.add_trace(
                go.Bar(
                    x=fazenda_stats["fazenda_nome"],
                    y=fazenda_stats["custo_rs"],
                    name="Custo",
                    marker_color="#4fb387",
                )
            )
            fig.update_layout(
                title="Custo por fazenda (R$)",
                height=290,
                margin={"t": 50, "r": 20, "b": 20, "l": 20},
                showlegend=False,
            )
            fig.update_yaxes(title="R$", rangemode="tozero")
            st.plotly_chart(fig, use_container_width=True)

        with d3:
            fig = go.Figure()
            fig.add_trace(
                go.Bar(
                    x=tipo_stats["tipo"],
                    y=tipo_stats["ticket_medio_rs"],
                    name="Ticket médio",
                    marker_color="#f59e0b",
                )
            )
            fig.update_layout(
                title="Ticket médio por tipo (R$)",
                height=290,
                margin={"t": 50, "r": 20, "b": 20, "l": 20},
                showlegend=False,
            )
            fig.update_yaxes(title="R$", rangemode="tozero")
            st.plotly_chart(fig, use_container_width=True)

        st.markdown("<div style='height: 12px;'></div>", unsafe_allow_html=True)
        d4, d5 = st.columns(2)
        with d4:
            fig = go.Figure()
            fig.add_trace(
                go.Bar(
                    y=talhao_stats["talhao_label"],
                    x=talhao_stats["custo_rs"],
                    name="Custo",
                    orientation="h",
                    marker_color="#60a5fa",
                )
            )
            fig.update_layout(
                title="Top talhões por custo (R$)",
                height=340,
                margin={"t": 50, "r": 20, "b": 20, "l": 20},
                showlegend=False,
            )
            fig.update_xaxes(title="R$", rangemode="tozero")
            st.plotly_chart(fig, use_container_width=True)

        with d5:
            fig = go.Figure()
            fig.add_trace(
                go.Bar(
                    x=diario_manut["ddmm"],
                    y=diario_manut["custo_rs"],
                    name="Custo diário",
                    marker_color="#4fb387",
                )
            )
            fig.add_trace(
                go.Scatter(
                    x=diario_manut["ddmm"],
                    y=diario_manut["eventos"],
                    name="Eventos",
                    mode="lines+markers",
                    yaxis="y2",
                    line={"color": "#f59e0b", "width": 2.2},
                    marker={"size": 6},
                )
            )
            fig.update_layout(
                title="Diário (31 dias): custo e eventos",
                height=340,
                margin={"t": 50, "r": 56, "b": 30, "l": 20},
                legend={"orientation": "h", "yanchor": "top", "y": -0.18, "xanchor": "left", "x": 0},
                yaxis={"title": "R$", "rangemode": "tozero"},
                yaxis2={"title": "qtd", "overlaying": "y", "side": "right", "rangemode": "tozero"},
            )
            fig.update_xaxes(tickmode="array", tickvals=diario_tick_vals, ticktext=diario_tick_vals, tickangle=-20)
            st.plotly_chart(fig, use_container_width=True)

        st.markdown("<div style='height: 12px;'></div>", unsafe_allow_html=True)
        m1, m2 = st.columns(2)
        with m1:
            fig = go.Figure()
            fig.add_trace(
                go.Bar(
                    x=mensal_manut["ano_mes"],
                    y=mensal_manut["custo_manutencao_rs"],
                    name="Custo",
                    marker_color="#60a5fa",
                )
            )
            fig.add_trace(
                go.Scatter(
                    x=mensal_manut["ano_mes"],
                    y=mensal_manut["eventos"],
                    name="Eventos",
                    mode="lines+markers",
                    yaxis="y2",
                    line={"color": "#4fb387", "width": 2.2},
                    marker={"size": 7},
                )
            )
            fig.update_layout(
                title="Mensal (YYYY-MM): custo e eventos",
                height=320,
                margin={"t": 50, "r": 56, "b": 20, "l": 20},
                legend={"orientation": "h", "yanchor": "top", "y": -0.18, "xanchor": "left", "x": 0},
                yaxis={"title": "R$", "rangemode": "tozero"},
                yaxis2={"title": "qtd", "overlaying": "y", "side": "right", "rangemode": "tozero"},
            )
            st.plotly_chart(fig, use_container_width=True)

        with m2:
            fig = go.Figure()
            fig.add_trace(
                go.Bar(
                    x=mensal_manut["ano_mes"],
                    y=mensal_manut["ticket_medio_rs"],
                    name="Ticket médio",
                    marker_color="#f59e0b",
                )
            )
            fig.update_layout(
                title="Mensal (YYYY-MM): ticket médio",
                height=320,
                margin={"t": 50, "r": 20, "b": 20, "l": 20},
                showlegend=False,
            )
            fig.update_yaxes(title="R$", rangemode="tozero")
            st.plotly_chart(fig, use_container_width=True)
