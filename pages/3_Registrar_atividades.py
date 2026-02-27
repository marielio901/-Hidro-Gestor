from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

from db.db import connection, list_blocos, list_fazendas, list_talhoes

st.title("Registrar atividades")

aba_irrig, aba_manut, aba_import = st.tabs(["Lançar Irrigação", "Lançar Manutenção", "Importar CSV"])

with aba_irrig:
    st.subheader("Lançar irrigação diária")

    fazendas = list_fazendas()
    blocos = list_blocos()
    talhoes = list_talhoes()

    if talhoes.empty:
        st.warning("Cadastre talhões antes de registrar atividades.")
    else:
        c0, c1, c2 = st.columns(3)
        fazenda_id = c0.selectbox(
            "Fazenda",
            options=fazendas["id"].tolist(),
            format_func=lambda x: fazendas.loc[fazendas["id"] == x, "nome"].iloc[0],
        )

        blocos_filtrados = blocos[blocos["fazenda_id"] == fazenda_id]
        if blocos_filtrados.empty:
            st.warning("Fazenda sem blocos cadastrados.")
            st.stop()

        bloco_id = c1.selectbox(
            "Bloco",
            options=blocos_filtrados["id"].tolist(),
            format_func=lambda x: blocos_filtrados.loc[blocos_filtrados["id"] == x, "nome"].iloc[0],
        )

        talhoes_filtrados = talhoes[talhoes["bloco_id"] == bloco_id]
        if talhoes_filtrados.empty:
            st.warning("Bloco sem talhões cadastrados.")
            st.stop()

        talhao_id = c2.selectbox(
            "Talhão",
            options=talhoes_filtrados["id"].tolist(),
            format_func=lambda x: (
                talhoes_filtrados.loc[talhoes_filtrados["id"] == x, "codigo"].iloc[0]
                + " - "
                + talhoes_filtrados.loc[talhoes_filtrados["id"] == x, "nome"].iloc[0]
            ),
        )

        info = talhoes_filtrados[talhoes_filtrados["id"] == talhao_id].iloc[0]
        outorga_limite = float(info["outorga_limite_m3_dia"])
        meta_vazao = float(info["meta_vazao_projeto"])
        area_ha = float(info["area_ha"])

        st.caption(f"Outorga do talhão: {outorga_limite:.2f} m³/dia")

        with st.form("form_irrigacao"):
            d1, d2, d3, d4 = st.columns(4)
            data_ref = d1.date_input("Data", value=date.today(), format="DD/MM/YYYY")
            horas_irrigadas = d2.number_input("Horas irrigadas", min_value=0.0, max_value=24.0, value=6.0, step=0.5)
            horas_paradas = d3.number_input("Horas paradas", min_value=0.0, max_value=24.0, value=8.0, step=0.5)
            lamina_mm = d4.number_input("Lâmina d'água (mm)", min_value=0.0, value=3.0, step=0.1)

            e1, e2, e3 = st.columns(3)
            informar_volume_captado = e1.checkbox("Informar volume captado", value=False)
            volume_captado = e2.number_input("Volume captado (m³)", min_value=0.0, value=0.0, step=1.0, disabled=not informar_volume_captado)
            energia_kwh = e3.number_input("Energia (kWh)", min_value=0.0, value=120.0, step=1.0)

            f1, f2, f3 = st.columns(3)
            informar_volume_aplicado = f1.checkbox("Informar volume aplicado", value=False)
            volume_aplicado = f2.number_input("Volume aplicado (m³)", min_value=0.0, value=0.0, step=1.0, disabled=not informar_volume_aplicado)
            teve_problema = f3.checkbox("Teve problema?", value=False)

            g1, g2, g3 = st.columns(3)
            tipo_problema = g1.selectbox(
                "Tipo problema",
                ["", "VAZAMENTO", "PRESSAO_BAIXA", "BOMBA", "ELETRICO", "OUTRO"],
                disabled=not teve_problema,
            )
            tempo_manutencao_h = g2.number_input(
                "Tempo manutenção (h)",
                min_value=0.0,
                value=0.0,
                step=0.5,
                disabled=not teve_problema,
            )
            observacoes = g3.text_input("Observações")

            salvar = st.form_submit_button("Salvar atividade")

        if salvar:
            if horas_irrigadas + horas_paradas > 24:
                st.error("Validação: horas_irrigadas + horas_paradas deve ser <= 24.")
            elif teve_problema and (not tipo_problema or tempo_manutencao_h <= 0):
                st.error("Quando teve problema, tipo_problema e tempo_manutencao_h são obrigatórios.")
            else:
                vol_aplicado = float(volume_aplicado) if informar_volume_aplicado and volume_aplicado > 0 else float(meta_vazao * horas_irrigadas)
                if vol_aplicado <= 0 and lamina_mm > 0:
                    vol_aplicado = float(lamina_mm * area_ha * 10.0)

                lamina = float(lamina_mm)
                if lamina <= 0 and vol_aplicado > 0:
                    lamina = float(vol_aplicado / max(area_ha * 10.0, 1e-6))

                if informar_volume_captado and volume_captado > 0:
                    vol_captado = float(volume_captado)
                else:
                    fator = 1.22 if tipo_problema == "VAZAMENTO" else (1.10 if teve_problema else 1.06)
                    vol_captado = float(vol_aplicado * fator)

                try:
                    with connection() as conn:
                        conn.execute(
                            """
                            INSERT INTO atividades_irrigacao (
                                talhao_id, data, horas_irrigadas, horas_paradas, lamina_mm,
                                volume_captado_m3, volume_aplicado_m3, energia_kwh,
                                teve_problema, tipo_problema, tempo_manutencao_h, observacoes
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            ON CONFLICT(talhao_id, data) DO UPDATE SET
                                horas_irrigadas = excluded.horas_irrigadas,
                                horas_paradas = excluded.horas_paradas,
                                lamina_mm = excluded.lamina_mm,
                                volume_captado_m3 = excluded.volume_captado_m3,
                                volume_aplicado_m3 = excluded.volume_aplicado_m3,
                                energia_kwh = excluded.energia_kwh,
                                teve_problema = excluded.teve_problema,
                                tipo_problema = excluded.tipo_problema,
                                tempo_manutencao_h = excluded.tempo_manutencao_h,
                                observacoes = excluded.observacoes
                            """,
                            (
                                int(talhao_id),
                                data_ref.isoformat(),
                                float(horas_irrigadas),
                                float(horas_paradas),
                                float(lamina),
                                float(vol_captado),
                                float(vol_aplicado),
                                float(energia_kwh),
                                1 if teve_problema else 0,
                                tipo_problema if teve_problema and tipo_problema else None,
                                float(tempo_manutencao_h) if teve_problema else None,
                                observacoes.strip() if observacoes else None,
                            ),
                        )

                    st.success("Atividade salva.")
                    if vol_captado > outorga_limite:
                        st.error(
                            f"ALERTA: outorga excedida ({vol_captado:.1f} m³ > {outorga_limite:.1f} m³)."
                        )
                    else:
                        st.info("Conformidade de outorga OK.")
                except Exception as exc:  # noqa: BLE001
                    st.error(f"Erro ao salvar atividade: {exc}")

        with connection() as conn:
            historico = pd.read_sql_query(
                """
                SELECT
                    a.data,
                    f.nome AS fazenda,
                    b.nome AS bloco,
                    t.codigo AS talhao,
                    a.horas_irrigadas,
                    a.horas_paradas,
                    a.lamina_mm,
                    a.volume_captado_m3,
                    a.volume_aplicado_m3,
                    a.energia_kwh,
                    a.teve_problema,
                    a.tipo_problema,
                    a.tempo_manutencao_h
                FROM atividades_irrigacao a
                JOIN talhao t ON t.id = a.talhao_id
                JOIN bloco b ON b.id = t.bloco_id
                JOIN fazenda f ON f.id = b.fazenda_id
                WHERE a.talhao_id = ?
                ORDER BY a.data DESC
                LIMIT 120
                """,
                conn,
                params=[int(talhao_id)],
            )
        st.subheader("Histórico recente do talhão")
        st.dataframe(historico, use_container_width=True, hide_index=True)

with aba_manut:
    st.subheader("Lançar manutenção")
    talhoes = list_talhoes()
    if talhoes.empty:
        st.warning("Cadastre talhões antes de lançar manutenção.")
    else:
        with st.form("form_manutencao"):
            m1, m2, m3 = st.columns(3)
            talhao_id_m = m1.selectbox(
                "Talhão",
                options=talhoes["id"].tolist(),
                format_func=lambda x: (
                    talhoes.loc[talhoes["id"] == x, "fazenda_nome"].iloc[0]
                    + " / "
                    + talhoes.loc[talhoes["id"] == x, "bloco_nome"].iloc[0]
                    + " / "
                    + talhoes.loc[talhoes["id"] == x, "codigo"].iloc[0]
                ),
            )
            tipo = m2.selectbox("Tipo", ["PREVENTIVA", "CORRETIVA"])
            custo = m3.number_input("Custo manutenção (R$)", min_value=0.0, value=200.0)

            m4, m5, m6 = st.columns(3)
            data_inicio = m4.date_input("Data início", value=date.today(), format="DD/MM/YYYY")
            data_fim = m5.date_input("Data fim", value=date.today(), format="DD/MM/YYYY")
            duracao_h = m6.number_input("Duração (h)", min_value=0.1, value=2.0, step=0.5)

            descricao = st.text_area("Descrição")
            salvar_manut = st.form_submit_button("Salvar manutenção")

        if salvar_manut:
            if not descricao.strip():
                st.error("Descrição é obrigatória.")
            elif data_fim < data_inicio:
                st.error("Data fim não pode ser menor que data início.")
            else:
                with connection() as conn:
                    conn.execute(
                        """
                        INSERT INTO manutencoes (
                            talhao_id, data_inicio, data_fim, tipo, descricao, duracao_h, custo_manutencao_rs
                        ) VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            int(talhao_id_m),
                            data_inicio.isoformat(),
                            data_fim.isoformat(),
                            tipo,
                            descricao.strip(),
                            float(duracao_h),
                            float(custo),
                        ),
                    )
                st.success("Manutenção lançada.")

    with connection() as conn:
        manut_hist = pd.read_sql_query(
            """
            SELECT
                m.id,
                m.data_inicio,
                m.data_fim,
                m.tipo,
                m.descricao,
                m.duracao_h,
                m.custo_manutencao_rs,
                f.nome AS fazenda,
                b.nome AS bloco,
                t.codigo AS talhao
            FROM manutencoes m
            JOIN talhao t ON t.id = m.talhao_id
            JOIN bloco b ON b.id = t.bloco_id
            JOIN fazenda f ON f.id = b.fazenda_id
            ORDER BY m.data_inicio DESC
            LIMIT 300
            """,
            conn,
        )
    st.dataframe(manut_hist, use_container_width=True, hide_index=True)

with aba_import:
    st.subheader("Importar CSV em lote")
    st.caption(
        "Colunas esperadas: talhao_id,data,horas_irrigadas,horas_paradas,lamina_mm,volume_captado_m3,volume_aplicado_m3,energia_kwh"
    )
    file = st.file_uploader("Arquivo CSV", type=["csv"])

    if file is not None:
        df_csv = pd.read_csv(file)
        st.dataframe(df_csv.head(20), use_container_width=True)

        if st.button("Importar linhas", use_container_width=True):
            required_cols = [
                "talhao_id",
                "data",
                "horas_irrigadas",
                "horas_paradas",
                "lamina_mm",
                "energia_kwh",
            ]
            missing = [c for c in required_cols if c not in df_csv.columns]
            if missing:
                st.error(f"CSV inválido. Colunas ausentes: {missing}")
            else:
                ok = 0
                err = 0
                with connection() as conn:
                    for _, r in df_csv.iterrows():
                        try:
                            horas_i = float(r["horas_irrigadas"])
                            horas_p = float(r["horas_paradas"])
                            if horas_i + horas_p > 24:
                                err += 1
                                continue

                            talhao_row = conn.execute(
                                "SELECT area_ha, meta_vazao_projeto FROM talhao WHERE id = ?",
                                (int(r["talhao_id"]),),
                            ).fetchone()
                            if not talhao_row:
                                err += 1
                                continue

                            vol_aplic = float(r.get("volume_aplicado_m3", 0) or 0)
                            if vol_aplic <= 0:
                                vol_aplic = float(talhao_row["meta_vazao_projeto"]) * horas_i

                            vol_capt = float(r.get("volume_captado_m3", 0) or 0)
                            if vol_capt <= 0:
                                vol_capt = vol_aplic * 1.08

                            conn.execute(
                                """
                                INSERT INTO atividades_irrigacao (
                                    talhao_id, data, horas_irrigadas, horas_paradas, lamina_mm,
                                    volume_captado_m3, volume_aplicado_m3, energia_kwh,
                                    teve_problema
                                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0)
                                ON CONFLICT(talhao_id, data) DO UPDATE SET
                                    horas_irrigadas = excluded.horas_irrigadas,
                                    horas_paradas = excluded.horas_paradas,
                                    lamina_mm = excluded.lamina_mm,
                                    volume_captado_m3 = excluded.volume_captado_m3,
                                    volume_aplicado_m3 = excluded.volume_aplicado_m3,
                                    energia_kwh = excluded.energia_kwh
                                """,
                                (
                                    int(r["talhao_id"]),
                                    str(r["data"]),
                                    horas_i,
                                    horas_p,
                                    float(r["lamina_mm"]),
                                    vol_capt,
                                    vol_aplic,
                                    float(r["energia_kwh"]),
                                ),
                            )
                            ok += 1
                        except Exception:
                            err += 1
                st.success(f"Importação concluída. Linhas válidas: {ok}. Erros: {err}.")
