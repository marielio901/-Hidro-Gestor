from __future__ import annotations

import sqlite3

import pandas as pd
import streamlit as st

from db.db import connection, list_blocos, list_fazendas, list_sensores, list_talhoes

st.title("Cadastrar Locais")
st.caption("Regra adotada: o código de sistema (PIV/GOT) é único globalmente.")


def next_code(prefix: str, conn) -> str:
    row = conn.execute(
        """
        SELECT MAX(CAST(SUBSTR(codigo_sistema, 5) AS INTEGER)) AS max_seq
        FROM talhao
        WHERE codigo_sistema LIKE ?
        """,
        (f"{prefix}-%",),
    ).fetchone()
    nxt = int(row["max_seq"] or 0) + 1
    return f"{prefix}-{nxt:03d}"


def next_talhao_code(conn) -> str:
    row = conn.execute(
        "SELECT MAX(CAST(SUBSTR(codigo, 5) AS INTEGER)) AS max_seq FROM talhao WHERE codigo LIKE 'TLH-%'"
    ).fetchone()
    nxt = int(row["max_seq"] or 0) + 1
    return f"TLH-{nxt:03d}"


aba_faz, aba_bloco, aba_talhao, aba_sensor = st.tabs(["Fazendas", "Blocos", "Talhões", "Sensores"])

with aba_faz:
    st.subheader("Cadastrar fazenda")
    with st.form("form_fazenda"):
        c1, c2, c3 = st.columns(3)
        nome = c1.text_input("Nome")
        municipio = c2.text_input("Município (PR)")
        area_total = c3.number_input("Área total (ha)", min_value=0.1, value=100.0, step=1.0)

        c4, c5, c6 = st.columns(3)
        uf = c4.text_input("UF", value="PR", max_chars=2)
        latitude = c5.number_input("Latitude", value=-25.95, format="%.6f")
        longitude = c6.number_input("Longitude", value=-49.30, format="%.6f")

        salvar = st.form_submit_button("Salvar fazenda")

    if salvar:
        if not nome.strip() or not municipio.strip():
            st.error("Nome e município são obrigatórios.")
        else:
            try:
                with connection() as conn:
                    conn.execute(
                        """
                        INSERT INTO fazenda (nome, municipio, uf, latitude, longitude, area_total_ha)
                        VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (nome.strip(), municipio.strip(), uf.strip().upper(), float(latitude), float(longitude), float(area_total)),
                    )
                st.success("Fazenda cadastrada.")
            except sqlite3.IntegrityError as exc:
                st.error(f"Falha ao salvar fazenda: {exc}")

    fazendas = list_fazendas()
    st.dataframe(fazendas, use_container_width=True, hide_index=True)

    if not fazendas.empty:
        st.subheader("Editar / excluir fazenda")
        selected_id = st.selectbox("Fazenda", fazendas["id"].tolist(), format_func=lambda x: fazendas.loc[fazendas["id"] == x, "nome"].iloc[0])
        row = fazendas[fazendas["id"] == selected_id].iloc[0]

        e1, e2, e3 = st.columns(3)
        nome_e = e1.text_input("Nome (edição)", value=str(row["nome"]))
        municipio_e = e2.text_input("Município (edição)", value=str(row["municipio"]))
        area_e = e3.number_input("Área total (ha) (edição)", min_value=0.1, value=float(row["area_total_ha"]))

        e4, e5, e6 = st.columns(3)
        uf_e = e4.text_input("UF (edição)", value=str(row["uf"]), max_chars=2)
        lat_e = e5.number_input("Latitude (edição)", value=float(row["latitude"]), format="%.6f")
        lon_e = e6.number_input("Longitude (edição)", value=float(row["longitude"]), format="%.6f")

        b1, b2 = st.columns(2)
        if b1.button("Atualizar fazenda", use_container_width=True):
            with connection() as conn:
                conn.execute(
                    """
                    UPDATE fazenda
                    SET nome = ?, municipio = ?, uf = ?, latitude = ?, longitude = ?, area_total_ha = ?
                    WHERE id = ?
                    """,
                    (nome_e.strip(), municipio_e.strip(), uf_e.strip().upper(), float(lat_e), float(lon_e), float(area_e), int(selected_id)),
                )
            st.success("Fazenda atualizada.")

        if b2.button("Excluir fazenda", use_container_width=True):
            with connection() as conn:
                conn.execute("DELETE FROM fazenda WHERE id = ?", (int(selected_id),))
            st.success("Fazenda excluída.")

with aba_bloco:
    st.subheader("Cadastrar bloco")
    fazendas = list_fazendas()
    if fazendas.empty:
        st.warning("Cadastre fazendas antes de criar blocos.")
    else:
        with st.form("form_bloco"):
            c1, c2, c3 = st.columns(3)
            fazenda_id = c1.selectbox(
                "Fazenda",
                options=fazendas["id"].tolist(),
                format_func=lambda x: fazendas.loc[fazendas["id"] == x, "nome"].iloc[0],
            )
            nome_bloco = c2.text_input("Nome do bloco")
            area_bloco = c3.number_input("Área (ha)", min_value=0.1, value=20.0)
            salvar_bloco = st.form_submit_button("Salvar bloco")

        if salvar_bloco:
            if not nome_bloco.strip():
                st.error("Nome do bloco é obrigatório.")
            else:
                try:
                    with connection() as conn:
                        conn.execute(
                            "INSERT INTO bloco (fazenda_id, nome, area_ha) VALUES (?, ?, ?)",
                            (int(fazenda_id), nome_bloco.strip(), float(area_bloco)),
                        )
                    st.success("Bloco cadastrado.")
                except sqlite3.IntegrityError as exc:
                    st.error(f"Falha ao salvar bloco: {exc}")

    blocos = list_blocos()
    st.dataframe(blocos, use_container_width=True, hide_index=True)

    if not blocos.empty:
        st.subheader("Editar / excluir bloco")
        bloco_id = st.selectbox(
            "Bloco",
            options=blocos["id"].tolist(),
            format_func=lambda x: (
                blocos.loc[blocos["id"] == x, "fazenda_nome"].iloc[0] + " / " + blocos.loc[blocos["id"] == x, "nome"].iloc[0]
            ),
        )
        row = blocos[blocos["id"] == bloco_id].iloc[0]

        b1, b2 = st.columns(2)
        nome_edit = b1.text_input("Nome bloco (edição)", value=str(row["nome"]))
        area_edit = b2.number_input("Área (ha) (edição)", min_value=0.1, value=float(row["area_ha"]))

        a1, a2 = st.columns(2)
        if a1.button("Atualizar bloco", use_container_width=True):
            with connection() as conn:
                conn.execute(
                    "UPDATE bloco SET nome = ?, area_ha = ? WHERE id = ?",
                    (nome_edit.strip(), float(area_edit), int(bloco_id)),
                )
            st.success("Bloco atualizado.")

        if a2.button("Excluir bloco", use_container_width=True):
            with connection() as conn:
                conn.execute("DELETE FROM bloco WHERE id = ?", (int(bloco_id),))
            st.success("Bloco excluído.")

with aba_talhao:
    st.subheader("Cadastrar talhão")
    blocos = list_blocos()
    if blocos.empty:
        st.warning("Cadastre blocos antes de criar talhões.")
    else:
        with connection() as conn:
            tlh_default = next_talhao_code(conn)
            piv_default = next_code("PIV", conn)
            got_default = next_code("GOT", conn)

        with st.form("form_talhao"):
            c1, c2, c3, c4 = st.columns(4)
            bloco_id = c1.selectbox(
                "Bloco",
                options=blocos["id"].tolist(),
                format_func=lambda x: (
                    blocos.loc[blocos["id"] == x, "fazenda_nome"].iloc[0] + " / " + blocos.loc[blocos["id"] == x, "nome"].iloc[0]
                ),
            )
            codigo = c2.text_input("Código (TLH)", value=tlh_default)
            nome = c3.text_input("Nome")
            area_ha = c4.number_input("Área (ha)", min_value=0.1, value=10.0)

            c5, c6, c7, c8 = st.columns(4)
            sistema = c5.selectbox("Sistema irrigação", ["PIVO", "GOTEJO"])
            codigo_sistema = c6.text_input(
                "Código do sistema",
                value=piv_default if sistema == "PIVO" else got_default,
            )
            meta_pressao = c7.number_input("Meta pressão alvo (bar)", min_value=0.1, value=2.0)
            meta_vazao = c8.number_input("Meta vazão projeto (m³/h)", min_value=0.1, value=60.0)

            c9, c10, c11 = st.columns(3)
            lat = c9.number_input("Latitude centro", value=-25.95, format="%.6f")
            lon = c10.number_input("Longitude centro", value=-49.30, format="%.6f")
            outorga = c11.number_input("Outorga limite (m³/dia)", min_value=1.0, value=300.0)

            salvar_talhao = st.form_submit_button("Salvar talhão")

        if salvar_talhao:
            if not codigo.strip() or not nome.strip() or not codigo_sistema.strip():
                st.error("Código, nome e código do sistema são obrigatórios.")
            else:
                try:
                    with connection() as conn:
                        conn.execute(
                            """
                            INSERT INTO talhao (
                                bloco_id, codigo, nome, area_ha, sistema_irrigacao, codigo_sistema,
                                latitude_centro, longitude_centro, meta_pressao_alvo,
                                meta_vazao_projeto, outorga_limite_m3_dia
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                int(bloco_id),
                                codigo.strip().upper(),
                                nome.strip(),
                                float(area_ha),
                                sistema,
                                codigo_sistema.strip().upper(),
                                float(lat),
                                float(lon),
                                float(meta_pressao),
                                float(meta_vazao),
                                float(outorga),
                            ),
                        )
                    st.success("Talhão cadastrado.")
                except sqlite3.IntegrityError as exc:
                    st.error(f"Falha ao salvar talhão: {exc}")

    talhoes = list_talhoes()
    st.dataframe(talhoes, use_container_width=True, hide_index=True)

    if not talhoes.empty:
        st.subheader("Editar / excluir talhão")
        talhao_id = st.selectbox(
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
        row = talhoes[talhoes["id"] == talhao_id].iloc[0]

        e1, e2, e3, e4 = st.columns(4)
        nome_e = e1.text_input("Nome (edição)", value=str(row["nome"]))
        area_e = e2.number_input("Área (ha) (edição)", min_value=0.1, value=float(row["area_ha"]))
        pressao_e = e3.number_input("Meta pressão (edição)", min_value=0.1, value=float(row["meta_pressao_alvo"]))
        vazao_e = e4.number_input("Meta vazão (edição)", min_value=0.1, value=float(row["meta_vazao_projeto"]))

        e5, e6, e7 = st.columns(3)
        outorga_e = e5.number_input("Outorga (edição)", min_value=1.0, value=float(row["outorga_limite_m3_dia"]))
        lat_e = e6.number_input("Latitude (edição)", value=float(row["latitude_centro"]), format="%.6f")
        lon_e = e7.number_input("Longitude (edição)", value=float(row["longitude_centro"]), format="%.6f")

        x1, x2 = st.columns(2)
        if x1.button("Atualizar talhão", use_container_width=True):
            with connection() as conn:
                conn.execute(
                    """
                    UPDATE talhao
                    SET nome = ?, area_ha = ?, meta_pressao_alvo = ?, meta_vazao_projeto = ?,
                        outorga_limite_m3_dia = ?, latitude_centro = ?, longitude_centro = ?
                    WHERE id = ?
                    """,
                    (
                        nome_e.strip(),
                        float(area_e),
                        float(pressao_e),
                        float(vazao_e),
                        float(outorga_e),
                        float(lat_e),
                        float(lon_e),
                        int(talhao_id),
                    ),
                )
            st.success("Talhão atualizado.")

        if x2.button("Excluir talhão", use_container_width=True):
            with connection() as conn:
                conn.execute("DELETE FROM talhao WHERE id = ?", (int(talhao_id),))
            st.success("Talhão excluído.")

with aba_sensor:
    st.subheader("Cadastrar sensor")
    talhoes = list_talhoes()
    if talhoes.empty:
        st.warning("Cadastre talhões antes de criar sensores.")
    else:
        unidades = {
            "PH": "pH",
            "TURBIDEZ": "NTU",
            "PRESSAO": "bar",
            "VAZAO": "m3/h",
        }

        with st.form("form_sensor"):
            c1, c2, c3, c4 = st.columns(4)
            talhao_id = c1.selectbox(
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
            tipo = c2.selectbox("Tipo", ["PH", "TURBIDEZ", "PRESSAO", "VAZAO"])
            unidade = c3.text_input("Unidade", value=unidades[tipo])
            ativo = c4.checkbox("Ativo", value=True)
            salvar_sensor = st.form_submit_button("Salvar sensor")

        if salvar_sensor:
            try:
                with connection() as conn:
                    conn.execute(
                        "INSERT INTO sensores (talhao_id, tipo, unidade, ativo) VALUES (?, ?, ?, ?)",
                        (int(talhao_id), tipo, unidade.strip(), 1 if ativo else 0),
                    )
                st.success("Sensor cadastrado.")
            except sqlite3.IntegrityError as exc:
                st.error(f"Falha ao salvar sensor: {exc}")

    sensores = list_sensores()
    st.dataframe(sensores, use_container_width=True, hide_index=True)

    if not sensores.empty:
        st.subheader("Atualizar / excluir sensor")
        sensor_id = st.selectbox(
            "Sensor",
            options=sensores["id"].tolist(),
            format_func=lambda x: (
                str(x)
                + " | "
                + sensores.loc[sensores["id"] == x, "tipo"].iloc[0]
                + " | "
                + sensores.loc[sensores["id"] == x, "talhao_codigo"].iloc[0]
            ),
        )
        row = sensores[sensores["id"] == sensor_id].iloc[0]

        s1, s2 = st.columns(2)
        unidade_e = s1.text_input("Unidade (edição)", value=str(row["unidade"]))
        ativo_e = s2.checkbox("Ativo (edição)", value=bool(row["ativo"]))

        y1, y2 = st.columns(2)
        if y1.button("Atualizar sensor", use_container_width=True):
            with connection() as conn:
                conn.execute(
                    "UPDATE sensores SET unidade = ?, ativo = ? WHERE id = ?",
                    (unidade_e.strip(), 1 if ativo_e else 0, int(sensor_id)),
                )
            st.success("Sensor atualizado.")

        if y2.button("Excluir sensor", use_container_width=True):
            with connection() as conn:
                conn.execute("DELETE FROM sensores WHERE id = ?", (int(sensor_id),))
            st.success("Sensor excluído.")
