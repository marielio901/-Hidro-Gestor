from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from db.db import connection
from services.kpis import FilterParams, get_filter_dimensions, load_operational_dataset, planning_vs_actual
from services.open_meteo import upcoming_forecast
from utils.formatters import fmt_mm, fmt_pct
from utils.ui import render_global_filters


def _render_plan_cards_css() -> None:
    st.markdown(
        """
        <style>
        .hg-plan-card {
            position: relative;
            border: 1px solid rgba(226, 232, 240, 0.14);
            border-radius: 16px;
            padding: 12px;
            height: 170px;
            background: linear-gradient(165deg, rgba(44, 47, 50, 0.95), rgba(35, 38, 41, 0.95));
            box-shadow: 0 12px 24px rgba(0, 0, 0, 0.28);
            overflow: hidden;
            display: flex;
            flex-direction: column;
            justify-content: space-between;
        }
        .hg-plan-card::before {
            content: "";
            position: absolute;
            top: 0;
            left: 0;
            right: 0;
            height: 3px;
            background: linear-gradient(90deg, var(--accent), rgba(44, 47, 50, 0));
        }
        .hg-plan-head {
            display: flex;
            align-items: center;
            gap: 8px;
            margin-bottom: 8px;
        }
        .hg-plan-icon {
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
        .hg-plan-icon svg {
            width: 17px;
            height: 17px;
        }
        .hg-plan-title {
            font-size: 0.86rem;
            color: #cbd5e1;
            line-height: 1.15rem;
            font-weight: 600;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }
        .hg-plan-value {
            color: #f8fafc;
            font-size: clamp(1.8rem, 1.2vw + 1.1rem, 2.2rem);
            line-height: 1.08;
            font-weight: 700;
            letter-spacing: -0.02em;
            margin: 2px 0 8px 0;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }
        .hg-plan-delta {
            display: inline-flex;
            align-items: center;
            font-size: 0.78rem;
            font-weight: 600;
            color: #e2e8f0;
            background: var(--badge-bg);
            border: 1px solid rgba(226, 232, 240, 0.2);
            border-radius: 999px;
            padding: 4px 9px;
            width: fit-content;
            max-width: 100%;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }
        .hg-plan-tone-primary { --accent: #60a5fa; --badge-bg: rgba(96, 165, 250, 0.2); }
        .hg-plan-tone-success { --accent: #4ade80; --badge-bg: rgba(74, 222, 128, 0.2); }
        .hg-plan-tone-warn { --accent: #fbbf24; --badge-bg: rgba(251, 191, 36, 0.22); }
        .hg-plan-tone-info { --accent: #38bdf8; --badge-bg: rgba(56, 189, 248, 0.22); }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _plan_icon(kind: str) -> str:
    icons = {
        "plan": (
            '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" '
            'stroke-linecap="round" stroke-linejoin="round"><rect x="4" y="3.5" width="16" height="17" rx="2"/>'
            '<path d="M9 3.5h6v3H9z"/><path d="M8 10h8"/><path d="M8 14h8"/></svg>'
        ),
        "check": (
            '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" '
            'stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"/>'
            '<path d="m8.7 12.2 2.2 2.3 4.4-4.7"/></svg>'
        ),
        "water": (
            '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" '
            'stroke-linecap="round" stroke-linejoin="round"><path d="M12 3s-6 7-6 11a6 6 0 0 0 12 0c0-4-6-11-6-11Z"/>'
            '<path d="M9.5 14.5a2.5 2.5 0 0 0 5 0"/></svg>'
        ),
        "time": (
            '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" '
            'stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"/>'
            '<path d="M12 7v6l4 2"/></svg>'
        ),
    }
    return icons.get(kind, icons["plan"])


def _render_plan_card(col, title: str, value: str, delta: str, icon_kind: str, tone: str) -> None:
    with col:
        st.markdown(
            f"""
            <div class="hg-plan-card hg-plan-tone-{tone}">
                <div class="hg-plan-head">
                    <span class="hg-plan-icon">{_plan_icon(icon_kind)}</span>
                    <span class="hg-plan-title" title="{title}">{title}</span>
                </div>
                <div class="hg-plan-value" title="{value}">{value}</div>
                <div class="hg-plan-delta" title="{delta}">{delta}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )


st.title("Planejamento")

filters = render_global_filters("planejamento", default_days=120, show_status=False)

with connection() as conn:
    talhoes_meta = pd.read_sql_query(
        """
        SELECT
            t.id,
            t.codigo,
            t.nome,
            t.area_ha,
            t.meta_vazao_projeto,
            t.sistema_irrigacao,
            t.latitude_centro,
            t.longitude_centro,
            b.nome AS bloco_nome,
            f.nome AS fazenda_nome
        FROM talhao t
        JOIN bloco b ON b.id = t.bloco_id
        JOIN fazenda f ON f.id = b.fazenda_id
        ORDER BY f.nome, b.nome, t.codigo
        """,
        conn,
    )

if talhoes_meta.empty:
    st.warning("Cadastre talhões antes de planejar.")
    st.stop()

if filters.talhao_ids:
    talhoes_meta = talhoes_meta[talhoes_meta["id"].isin(filters.talhao_ids)]

if talhoes_meta.empty:
    st.warning("Nenhum talhão encontrado para os filtros selecionados.")
    st.stop()

aba_a, aba_b, aba_c = st.tabs(
    [
        "Planejar Irrigação",
        "Planejar Manutenção Preventiva",
        "Acompanhamento (Planejado vs Realizado)",
    ]
)

with aba_a:
    st.subheader("Planejar irrigação")

    c1, c2, c3 = st.columns(3)
    periodo = c1.selectbox("Período", ["DIA", "SEMANA", "MES"])
    data_ref = c2.date_input("Data de referência", value=date.today(), format="DD/MM/YYYY")
    status = c3.selectbox("Status", ["PLANEJADO", "EM_EXECUCAO", "CONCLUIDO", "CANCELADO"])

    c4, c5, c6 = st.columns(3)
    horas_planejadas = c4.number_input("Horas planejadas", min_value=0.0, value=8.0, step=0.5)
    lamina_planejada = c5.number_input("Lâmina planejada (mm)", min_value=0.0, value=4.0, step=0.1)
    prioridade = c6.slider("Prioridade", min_value=1, max_value=5, value=3)

    selecionados = st.multiselect(
        "Talhões",
        options=talhoes_meta["id"].tolist(),
        default=talhoes_meta["id"].head(3).tolist(),
        format_func=lambda x: (
            talhoes_meta.loc[talhoes_meta["id"] == x, "fazenda_nome"].iloc[0]
            + " / "
            + talhoes_meta.loc[talhoes_meta["id"] == x, "bloco_nome"].iloc[0]
            + " / "
            + talhoes_meta.loc[talhoes_meta["id"] == x, "codigo"].iloc[0]
        ),
    )

    salvar_manual = st.button("Salvar plano manual", use_container_width=True)

    if salvar_manual:
        if not selecionados:
            st.warning("Selecione ao menos um talhão.")
        else:
            with connection() as conn:
                for tid in selecionados:
                    conn.execute(
                        """
                        INSERT INTO planejamento (
                            talhao_id, periodo, data_ref, horas_planejadas, lamina_planejada_mm,
                            manutencao_planejada, tipo_manutencao, prioridade, status, notas
                        ) VALUES (?, ?, ?, ?, ?, 0, NULL, ?, ?, ?)
                        ON CONFLICT(talhao_id, periodo, data_ref) DO UPDATE SET
                            horas_planejadas = excluded.horas_planejadas,
                            lamina_planejada_mm = excluded.lamina_planejada_mm,
                            prioridade = excluded.prioridade,
                            status = excluded.status,
                            notas = excluded.notas
                        """,
                        (
                            int(tid),
                            periodo,
                            data_ref.isoformat(),
                            float(horas_planejadas),
                            float(lamina_planejada),
                            int(prioridade),
                            status,
                            "Plano manual",
                        ),
                    )
            st.success("Plano salvo para os talhões selecionados.")

    st.divider()
    st.subheader("Sugerir plano (IA simples)")
    st.caption("Baseado em ETc (Open-Meteo + Kc=1.05), chuva prevista e histórico de atendimento do talhão.")

    if st.button("Sugerir plano (IA simples)", use_container_width=True):
        if not selecionados:
            st.warning("Selecione ao menos um talhão.")
        else:
            days = {"DIA": 1, "SEMANA": 7, "MES": 30}[periodo]
            sug_rows: list[dict[str, object]] = []

            for tid in selecionados:
                row = talhoes_meta[talhoes_meta["id"] == tid].iloc[0]
                lat = float(row["latitude_centro"])
                lon = float(row["longitude_centro"])

                try:
                    forecast = upcoming_forecast(lat, lon, days=days)
                except Exception:  # noqa: BLE001
                    forecast = pd.DataFrame()

                if forecast.empty:
                    eto_med = 3.8
                    chuva_total = 4.0 if periodo != "DIA" else 0.8
                else:
                    eto_med = float(pd.to_numeric(forecast["eto_mm_dia"], errors="coerce").fillna(3.8).mean())
                    chuva_total = float(pd.to_numeric(forecast["precipitacao_mm"], errors="coerce").fillna(0).sum())

                etc_periodo = eto_med * 1.05 * days
                chuva_efetiva = chuva_total * 0.8
                demanda = max(etc_periodo - chuva_efetiva, 0.0)

                hist_filters = FilterParams(
                    start_date=max(filters.start_date, date.today() - timedelta(days=45)),
                    end_date=min(filters.end_date, date.today()),
                    talhao_ids=(int(tid),),
                )
                hist_df = load_operational_dataset(hist_filters)
                atendimento_hist = float(hist_df["atendimento_demanda"].mean()) if not hist_df.empty else 1.0

                ajuste = 1.0
                if atendimento_hist < 0.9:
                    ajuste = 1.08
                elif atendimento_hist > 1.1:
                    ajuste = 0.92

                lamina_sugerida = demanda * ajuste
                if periodo == "DIA":
                    lamina_sugerida = float(np.clip(lamina_sugerida, 0, 12))
                elif periodo == "SEMANA":
                    lamina_sugerida = float(np.clip(lamina_sugerida, 0, 70))
                else:
                    lamina_sugerida = float(np.clip(lamina_sugerida, 0, 280))

                volume_sugerido = lamina_sugerida * float(row["area_ha"]) * 10.0
                horas_sugeridas = volume_sugerido / max(float(row["meta_vazao_projeto"]), 1e-6)

                sug_rows.append(
                    {
                        "talhao_id": int(tid),
                        "fazenda": row["fazenda_nome"],
                        "bloco": row["bloco_nome"],
                        "talhao": row["codigo"],
                        "periodo": periodo,
                        "data_ref": data_ref.isoformat(),
                        "lamina_planejada_mm": round(float(lamina_sugerida), 2),
                        "horas_planejadas": round(float(horas_sugeridas), 2),
                        "prioridade": 2 if demanda > 3 else 3,
                        "status": "PLANEJADO",
                        "notas": f"Sugestão IA simples | atendimento_hist={atendimento_hist:.2f}",
                    }
                )

            sugestoes_df = pd.DataFrame(sug_rows)
            st.session_state["sugestoes_planejamento"] = sugestoes_df

    sugestoes_df = st.session_state.get("sugestoes_planejamento", pd.DataFrame())
    if not sugestoes_df.empty:
        st.dataframe(sugestoes_df, use_container_width=True, hide_index=True)
        if st.button("Salvar sugestões", use_container_width=True):
            with connection() as conn:
                for r in sugestoes_df.to_dict(orient="records"):
                    conn.execute(
                        """
                        INSERT INTO planejamento (
                            talhao_id, periodo, data_ref, horas_planejadas, lamina_planejada_mm,
                            manutencao_planejada, tipo_manutencao, prioridade, status, notas
                        ) VALUES (?, ?, ?, ?, ?, 0, NULL, ?, ?, ?)
                        ON CONFLICT(talhao_id, periodo, data_ref) DO UPDATE SET
                            horas_planejadas = excluded.horas_planejadas,
                            lamina_planejada_mm = excluded.lamina_planejada_mm,
                            prioridade = excluded.prioridade,
                            status = excluded.status,
                            notas = excluded.notas
                        """,
                        (
                            int(r["talhao_id"]),
                            str(r["periodo"]),
                            str(r["data_ref"]),
                            float(r["horas_planejadas"]),
                            float(r["lamina_planejada_mm"]),
                            int(r["prioridade"]),
                            str(r["status"]),
                            str(r["notas"]),
                        ),
                    )
            st.success("Sugestões salvas com sucesso.")

with aba_b:
    st.subheader("Planejar manutenção preventiva")

    with connection() as conn:
        prev_df = pd.read_sql_query(
            """
            WITH ult_prev AS (
                SELECT
                    t.id AS talhao_id,
                    t.codigo AS talhao_codigo,
                    t.nome AS talhao_nome,
                    b.nome AS bloco_nome,
                    f.nome AS fazenda_nome,
                    MAX(DATE(m.data_inicio)) AS ultima_preventiva
                FROM talhao t
                JOIN bloco b ON b.id = t.bloco_id
                JOIN fazenda f ON f.id = b.fazenda_id
                LEFT JOIN manutencoes m
                       ON m.talhao_id = t.id
                      AND m.tipo = 'PREVENTIVA'
                GROUP BY t.id
            )
            SELECT *,
                   CASE
                       WHEN ultima_preventiva IS NULL THEN 9999
                       ELSE CAST(julianday('now') - julianday(ultima_preventiva) AS INTEGER)
                   END AS dias_sem_preventiva
            FROM ult_prev
            ORDER BY dias_sem_preventiva DESC, fazenda_nome, bloco_nome, talhao_codigo
            """,
            conn,
        )

    if not prev_df.empty:
        prev_df["vencida"] = prev_df["dias_sem_preventiva"] > 35
        st.dataframe(prev_df, use_container_width=True, hide_index=True)

        vencidas = prev_df[prev_df["vencida"]]
        if vencidas.empty:
            st.info("Nenhum talhão com preventiva vencida.")
        else:
            st.warning(f"Talhões com preventiva vencida: {len(vencidas)}")

            t1, t2, t3, t4 = st.columns(4)
            talhao_prev = t1.selectbox(
                "Talhão",
                options=vencidas["talhao_id"].tolist(),
                format_func=lambda x: (
                    vencidas.loc[vencidas["talhao_id"] == x, "fazenda_nome"].iloc[0]
                    + " / "
                    + vencidas.loc[vencidas["talhao_id"] == x, "bloco_nome"].iloc[0]
                    + " / "
                    + vencidas.loc[vencidas["talhao_id"] == x, "talhao_codigo"].iloc[0]
                ),
            )
            data_agenda = t2.date_input("Data agenda", value=date.today(), format="DD/MM/YYYY")
            duracao = t3.number_input("Duração (h)", min_value=0.5, value=2.0, step=0.5)
            custo = t4.number_input("Custo (R$)", min_value=0.0, value=180.0)
            desc = st.text_input("Descrição", value="Preventiva agendada")

            if st.button("Agendar preventiva", use_container_width=True):
                with connection() as conn:
                    conn.execute(
                        """
                        INSERT INTO manutencoes (
                            talhao_id, data_inicio, data_fim, tipo, descricao, duracao_h, custo_manutencao_rs
                        ) VALUES (?, ?, ?, 'PREVENTIVA', ?, ?, ?)
                        """,
                        (
                            int(talhao_prev),
                            data_agenda.isoformat(),
                            data_agenda.isoformat(),
                            desc.strip() or "Preventiva agendada",
                            float(duracao),
                            float(custo),
                        ),
                    )
                st.success("Preventiva agendada.")

with aba_c:
    st.subheader("Acompanhamento: planejado vs realizado")

    pvr = planning_vs_actual(
        start_date=filters.start_date,
        end_date=filters.end_date,
        talhao_ids=filters.talhao_ids,
    )

    if pvr.empty:
        st.info("Sem registros de planejamento para o período selecionado.")
    else:
        _render_plan_cards_css()
        total_planos = int(len(pvr))
        concluidos = int((pvr["status"] == "CONCLUIDO").sum())
        taxa_conclusao = concluidos / max(total_planos, 1e-6)
        aderencia_lamina = float(np.clip(pvr["aderencia_lamina_pct"].mean(), 0, 1.0))
        aderencia_horas = float(np.clip(pvr["aderencia_horas_pct"].mean(), 0, 1.0))

        card1, card2, card3, card4 = st.columns(4)
        _render_plan_card(card1, "Planos", str(total_planos), f"Concluídos: {concluidos}", "plan", "primary")
        _render_plan_card(card2, "Concluídos", str(concluidos), f"Taxa: {fmt_pct(taxa_conclusao)}", "check", "success")
        _render_plan_card(card3, "Aderência lâmina (média)", fmt_pct(aderencia_lamina), "Meta: 100%", "water", "warn")
        _render_plan_card(card4, "Aderência horas (média)", fmt_pct(aderencia_horas), "Meta: 100%", "time", "info")

        st.markdown("<div style='height: 12px;'></div>", unsafe_allow_html=True)

        diario = (
            pvr.groupby("data_ref", as_index=False)
            .agg(
                lamina_planejada_mm=("lamina_planejada_mm", "sum"),
                lamina_real_mm=("lamina_real_mm", "sum"),
                horas_planejadas=("horas_planejadas", "sum"),
                horas_realizadas=("horas_realizadas", "sum"),
            )
            .sort_values("data_ref")
        )
        diario["ddmm"] = pd.to_datetime(diario["data_ref"]).dt.strftime("%d/%m")

        mensal = (
            diario.assign(ano_mes=pd.to_datetime(diario["data_ref"]).dt.to_period("M").astype(str))
            .groupby("ano_mes", as_index=False)
            .agg(
                lamina_planejada_mm=("lamina_planejada_mm", "sum"),
                lamina_real_mm=("lamina_real_mm", "sum"),
                horas_planejadas=("horas_planejadas", "sum"),
                horas_realizadas=("horas_realizadas", "sum"),
            )
            .sort_values("ano_mes")
        )

        g1, g2 = st.columns(2)
        with g1:
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=diario["ddmm"], y=diario["lamina_planejada_mm"], name="lamina_planejada_mm", mode="lines+markers"))
            fig.add_trace(go.Scatter(x=diario["ddmm"], y=diario["lamina_real_mm"], name="lamina_real_mm", mode="lines+markers"))
            fig.update_layout(title="Diário (dd/mm): lâmina planejada vs realizada")
            st.plotly_chart(fig, use_container_width=True)

        with g2:
            fig = go.Figure()
            fig.add_trace(go.Bar(x=mensal["ano_mes"], y=mensal["horas_planejadas"], name="horas_planejadas"))
            fig.add_trace(go.Bar(x=mensal["ano_mes"], y=mensal["horas_realizadas"], name="horas_realizadas"))
            fig.update_layout(title="Mensal (YYYY-MM): horas planejadas vs realizadas", barmode="group")
            st.plotly_chart(fig, use_container_width=True)

        st.dataframe(pvr, use_container_width=True, hide_index=True)
