from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

import numpy as np
import pandas as pd
import streamlit as st

from db.db import connection

EPSILON = 1e-6
KC_DEFAULT = 1.05


@dataclass(frozen=True)
class FilterParams:
    start_date: date
    end_date: date
    fazenda_ids: tuple[int, ...] = ()
    bloco_ids: tuple[int, ...] = ()
    talhao_ids: tuple[int, ...] = ()
    sistemas: tuple[str, ...] = ()
    status: tuple[str, ...] = ()
    only_alerts: bool = False



def _to_date(value: str | date | datetime) -> date:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    return datetime.fromisoformat(str(value)).date()



def _build_in_clause(column: str, values: tuple[Any, ...], params: list[Any]) -> str:
    if not values:
        return ""
    placeholders = ",".join(["?"] * len(values))
    params.extend(values)
    return f" AND {column} IN ({placeholders}) "


@st.cache_data(ttl=600, show_spinner=False)
def get_filter_dimensions(db_path: str | None = None) -> dict[str, pd.DataFrame]:
    with connection(db_path) as conn:
        fazendas = pd.read_sql_query("SELECT id, nome FROM fazenda ORDER BY nome", conn)
        blocos = pd.read_sql_query(
            """
            SELECT b.id, b.nome, b.fazenda_id, f.nome AS fazenda_nome
            FROM bloco b
            JOIN fazenda f ON f.id = b.fazenda_id
            ORDER BY f.nome, b.nome
            """,
            conn,
        )
        talhoes = pd.read_sql_query(
            """
            SELECT t.id, t.codigo, t.nome, t.sistema_irrigacao,
                   t.bloco_id, b.fazenda_id,
                   b.nome AS bloco_nome, f.nome AS fazenda_nome
            FROM talhao t
            JOIN bloco b ON b.id = t.bloco_id
            JOIN fazenda f ON f.id = b.fazenda_id
            ORDER BY f.nome, b.nome, t.codigo
            """,
            conn,
        )

    return {"fazendas": fazendas, "blocos": blocos, "talhoes": talhoes}


@st.cache_data(ttl=300, show_spinner=False)
def load_operational_dataset(filters: FilterParams, db_path: str | None = None) -> pd.DataFrame:
    params: list[Any] = [filters.start_date.isoformat(), filters.end_date.isoformat()]
    where = " WHERE a.data BETWEEN ? AND ? "
    where += _build_in_clause("f.id", filters.fazenda_ids, params)
    where += _build_in_clause("b.id", filters.bloco_ids, params)
    where += _build_in_clause("t.id", filters.talhao_ids, params)
    where += _build_in_clause("t.sistema_irrigacao", filters.sistemas, params)

    query = f"""
        WITH sensor_diario AS (
            SELECT
                s.talhao_id,
                DATE(ls.data_hora) AS data,
                AVG(CASE WHEN s.tipo = 'PRESSAO' THEN ls.valor END) AS pressao_media,
                AVG(CASE WHEN s.tipo = 'VAZAO' THEN ls.valor END) AS vazao_media,
                AVG(CASE WHEN s.tipo = 'PH' THEN ls.valor END) AS ph_media,
                AVG(CASE WHEN s.tipo = 'TURBIDEZ' THEN ls.valor END) AS turbidez_media,
                MAX(ls.data_hora) AS ultima_leitura,
                COUNT(*) AS leituras_totais
            FROM sensores s
            JOIN leituras_sensores ls ON ls.sensor_id = s.id
            GROUP BY s.talhao_id, DATE(ls.data_hora)
        ),
        manutencao_diaria AS (
            SELECT
                m.talhao_id,
                DATE(m.data_inicio) AS data,
                SUM(COALESCE(m.custo_manutencao_rs, 0)) AS custo_manutencao_rs,
                SUM(COALESCE(m.duracao_h, 0)) AS manutencao_h
            FROM manutencoes m
            GROUP BY m.talhao_id, DATE(m.data_inicio)
        )
        SELECT
            a.id,
            DATE(a.data) AS data,
            a.horas_irrigadas,
            a.horas_paradas,
            a.lamina_mm,
            a.volume_captado_m3,
            a.volume_aplicado_m3,
            a.energia_kwh,
            a.teve_problema,
            a.tipo_problema,
            a.tempo_manutencao_h,
            a.observacoes,
            t.id AS talhao_id,
            t.codigo AS talhao_codigo,
            t.nome AS talhao_nome,
            t.area_ha,
            t.sistema_irrigacao,
            t.codigo_sistema,
            t.latitude_centro,
            t.longitude_centro,
            t.meta_pressao_alvo,
            t.meta_vazao_projeto,
            t.outorga_limite_m3_dia,
            b.id AS bloco_id,
            b.nome AS bloco_nome,
            f.id AS fazenda_id,
            f.nome AS fazenda_nome,
            c.precipitacao_mm,
            c.temp_min_c,
            c.temp_max_c,
            c.vento_max_ms,
            c.eto_mm_dia,
            c.etc_mm_dia,
            c.fonte AS clima_fonte,
            sd.pressao_media,
            sd.vazao_media,
            sd.ph_media,
            sd.turbidez_media,
            sd.ultima_leitura,
            sd.leituras_totais,
            COALESCE(cp_f.custo_agua_rs_m3, cp_d.custo_agua_rs_m3, 0.25) AS custo_agua_rs_m3,
            COALESCE(cp_f.custo_energia_rs_kwh, cp_d.custo_energia_rs_kwh, 0.78) AS custo_energia_rs_kwh,
            COALESCE(cp_f.outros_fixos_rs_mes, cp_d.outros_fixos_rs_mes, 0) AS outros_fixos_rs_mes,
            COALESCE(md.custo_manutencao_rs, 0) AS custo_manutencao_rs,
            COALESCE(md.manutencao_h, 0) AS manutencao_h
        FROM atividades_irrigacao a
        JOIN talhao t ON t.id = a.talhao_id
        JOIN bloco b ON b.id = t.bloco_id
        JOIN fazenda f ON f.id = b.fazenda_id
        LEFT JOIN clima_diario c ON c.fazenda_id = f.id AND c.data = a.data
        LEFT JOIN sensor_diario sd ON sd.talhao_id = t.id AND sd.data = a.data
        LEFT JOIN manutencao_diaria md ON md.talhao_id = t.id AND md.data = a.data
        LEFT JOIN custos_parametros cp_f ON cp_f.fazenda_id = f.id
        LEFT JOIN custos_parametros cp_d ON cp_d.fazenda_id IS NULL
        {where}
        ORDER BY a.data, f.nome, b.nome, t.codigo
    """

    with connection(db_path) as conn:
        df = pd.read_sql_query(query, conn, params=params)

    if df.empty:
        return df

    df["data"] = pd.to_datetime(df["data"]).dt.date

    numeric_cols = [
        "horas_irrigadas",
        "horas_paradas",
        "lamina_mm",
        "volume_captado_m3",
        "volume_aplicado_m3",
        "energia_kwh",
        "tempo_manutencao_h",
        "area_ha",
        "meta_pressao_alvo",
        "meta_vazao_projeto",
        "outorga_limite_m3_dia",
        "precipitacao_mm",
        "temp_min_c",
        "temp_max_c",
        "vento_max_ms",
        "eto_mm_dia",
        "etc_mm_dia",
        "pressao_media",
        "vazao_media",
        "ph_media",
        "turbidez_media",
        "leituras_totais",
        "custo_agua_rs_m3",
        "custo_energia_rs_kwh",
        "outros_fixos_rs_mes",
        "custo_manutencao_rs",
        "manutencao_h",
    ]
    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    df["volume_aplicado_m3"] = df["volume_aplicado_m3"].fillna(0)
    volume_aplicado_calc = df["meta_vazao_projeto"].fillna(0) * df["horas_irrigadas"].fillna(0)
    df["volume_aplicado_m3"] = np.where(df["volume_aplicado_m3"] <= 0, volume_aplicado_calc, df["volume_aplicado_m3"])

    df["lamina_mm"] = df["lamina_mm"].fillna(0)
    lamina_calc = np.divide(df["volume_aplicado_m3"], np.maximum(df["area_ha"] * 10.0, EPSILON))
    df["lamina_mm"] = np.where(df["lamina_mm"] <= 0, lamina_calc, df["lamina_mm"])

    fallback_factor = np.where(
        df["tipo_problema"] == "VAZAMENTO",
        0.25,
        np.where(df["teve_problema"].fillna(0) == 1, 0.12, 0.05),
    )
    volume_captado_calc = df["volume_aplicado_m3"] * (1.0 + fallback_factor)
    df["volume_captado_m3"] = df["volume_captado_m3"].fillna(0)
    df["volume_captado_m3"] = np.where(
        (df["volume_captado_m3"] <= 0) & (df["volume_aplicado_m3"] > 0),
        volume_captado_calc,
        df["volume_captado_m3"],
    )

    df["etc_mm_dia"] = np.where(
        df["etc_mm_dia"].notna(),
        df["etc_mm_dia"],
        df["eto_mm_dia"].fillna(0) * KC_DEFAULT,
    )
    df["chuva_efetiva_mm"] = (df["precipitacao_mm"].fillna(0) * 0.8).clip(lower=0)
    df["demanda_mm_dia"] = (df["etc_mm_dia"].fillna(0) - df["chuva_efetiva_mm"]).clip(lower=0)

    demanda = df["demanda_mm_dia"].to_numpy()
    lamina = df["lamina_mm"].to_numpy()
    atendimento = np.divide(lamina, np.maximum(demanda, EPSILON))
    atendimento = np.where(demanda <= EPSILON, np.where(lamina <= EPSILON, 1.0, 1.2), atendimento)
    df["atendimento_demanda"] = np.clip(atendimento, 0, 2.0)

    df["perdas_m3"] = (df["volume_captado_m3"] - df["volume_aplicado_m3"]).clip(lower=0)
    df["perdas_pct"] = np.divide(df["perdas_m3"], np.maximum(df["volume_captado_m3"], EPSILON))

    df["aporte_hidrico_mm"] = np.divide(df["volume_aplicado_m3"], np.maximum(df["area_ha"] * 10.0, EPSILON))
    df["consumo_especifico_kwh_m3"] = np.divide(df["energia_kwh"], np.maximum(df["volume_aplicado_m3"], EPSILON))
    df["energia_por_ha"] = np.divide(df["energia_kwh"], np.maximum(df["area_ha"], EPSILON))

    df["custo_agua_rs"] = df["volume_captado_m3"] * df["custo_agua_rs_m3"]
    df["custo_energia_rs"] = df["energia_kwh"] * df["custo_energia_rs_kwh"]
    df["custo_total_dia_rs"] = df["custo_agua_rs"] + df["custo_energia_rs"] + df["custo_manutencao_rs"]
    df["custo_total_irrig_ha_rs"] = np.divide(
        df["custo_total_dia_rs"],
        np.maximum(df["area_ha"], EPSILON),
    )

    df["ea"] = np.clip(1.0 - df["perdas_pct"], 0.0, 1.0)
    df["eirr"] = np.clip(df["ea"] * np.minimum(df["atendimento_demanda"], 1.0), 0.0, 1.0)

    df["outorga_conforme"] = df["volume_captado_m3"] <= df["outorga_limite_m3_dia"]
    df["ph_conforme"] = df["ph_media"].fillna(7.0).between(6.0, 8.5, inclusive="both")
    df["turbidez_conforme"] = df["turbidez_media"].fillna(0) <= 5.0
    df["pressao_conforme"] = df["pressao_media"].fillna(df["meta_pressao_alvo"]) >= (df["meta_pressao_alvo"] * 0.9)
    df["vazao_conforme"] = df["vazao_media"].fillna(df["meta_vazao_projeto"]) >= (df["meta_vazao_projeto"] * 0.9)

    df["alerta_outorga"] = ~df["outorga_conforme"]
    df["alerta_perdas"] = df["perdas_pct"] > 0.20
    df["alerta_pressao"] = ~df["pressao_conforme"]
    df["alerta_ph"] = ~df["ph_conforme"]
    df["alerta_turbidez"] = ~df["turbidez_conforme"]
    df["alerta_demanda"] = (df["atendimento_demanda"] < 0.8) | (df["atendimento_demanda"] > 1.2)

    df["is_alerta"] = (
        df[
            [
                "alerta_outorga",
                "alerta_perdas",
                "alerta_pressao",
                "alerta_ph",
                "alerta_turbidez",
                "alerta_demanda",
            ]
        ]
        .any(axis=1)
        .astype(bool)
    )

    df["status_operacao"] = np.where(
        (df["manutencao_h"].fillna(0) > 0) | ((df["teve_problema"].fillna(0) == 1) & (df["tempo_manutencao_h"].fillna(0) > 0)),
        "MANUTENCAO",
        np.where(df["is_alerta"], "ALERTA", "OK"),
    )

    if filters.status:
        status_mask = pd.Series(False, index=df.index)
        if "MANUTENCAO" in filters.status:
            status_mask = status_mask | (df["status_operacao"] == "MANUTENCAO")
        if "ALERTA" in filters.status:
            status_mask = status_mask | (df["is_alerta"])
        if "OK" in filters.status:
            status_mask = status_mask | ((~df["is_alerta"]) & (df["status_operacao"] != "MANUTENCAO"))
        df = df[status_mask]

    if filters.only_alerts:
        df = df[df["is_alerta"]]

    return df.reset_index(drop=True)



def period_slice(df: pd.DataFrame, ref_date: date | None = None) -> dict[str, pd.DataFrame]:
    if df.empty:
        return {"dia": df, "semana": df, "mes": df}

    ref = ref_date or max(df["data"])
    start_week = ref - timedelta(days=6)
    start_month = ref.replace(day=1)

    return {
        "dia": df[df["data"] == ref],
        "semana": df[(df["data"] >= start_week) & (df["data"] <= ref)],
        "mes": df[(df["data"] >= start_month) & (df["data"] <= ref)],
    }



def aggregate_snapshot(df: pd.DataFrame) -> dict[str, float]:
    if df.empty:
        return {
            "aporte_mm": 0.0,
            "aporte_m3": 0.0,
            "consumo_agua_m3": 0.0,
            "energia_kwh": 0.0,
            "custo_total_rs": 0.0,
            "perdas_m3": 0.0,
            "perdas_pct": 0.0,
            "alertas_qtd": 0.0,
            "atendimento_medio": 0.0,
            "conformidade_outorga_pct": 0.0,
            "ph_conformidade_pct": 0.0,
            "turbidez_conformidade_pct": 0.0,
            "ea": 0.0,
            "eirr": 0.0,
            "custo_por_ha_rs": 0.0,
        }

    total_area = max(float(df["area_ha"].sum()), EPSILON)
    aporte_mm = float((df["aporte_hidrico_mm"] * df["area_ha"]).sum() / total_area)
    custo_total = float(df["custo_total_dia_rs"].sum())

    return {
        "aporte_mm": aporte_mm,
        "aporte_m3": float(df["volume_aplicado_m3"].sum()),
        "consumo_agua_m3": float(df["volume_captado_m3"].sum()),
        "energia_kwh": float(df["energia_kwh"].sum()),
        "custo_total_rs": custo_total,
        "perdas_m3": float(df["perdas_m3"].sum()),
        "perdas_pct": float(np.clip(df["perdas_m3"].sum() / max(df["volume_captado_m3"].sum(), EPSILON), 0, 1)),
        "alertas_qtd": float(df["is_alerta"].sum()),
        "atendimento_medio": float(df["atendimento_demanda"].mean()),
        "conformidade_outorga_pct": float(df["outorga_conforme"].mean()),
        "ph_conformidade_pct": float(df["ph_conforme"].mean()),
        "turbidez_conformidade_pct": float(df["turbidez_conforme"].mean()),
        "ea": float(df["ea"].mean()),
        "eirr": float(df["eirr"].mean()),
        "custo_por_ha_rs": float(custo_total / total_area),
    }



def build_cards(df: pd.DataFrame, ref_date: date | None = None) -> dict[str, dict[str, float]]:
    slices = period_slice(df, ref_date)
    return {k: aggregate_snapshot(v) for k, v in slices.items()}



def build_daily_series(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()

    daily = (
        df.groupby("data", as_index=False)
        .agg(
            volume_aplicado_m3=("volume_aplicado_m3", "sum"),
            volume_captado_m3=("volume_captado_m3", "sum"),
            energia_kwh=("energia_kwh", "sum"),
            lamina_mm=("lamina_mm", "mean"),
            demanda_mm_dia=("demanda_mm_dia", "mean"),
            atendimento_demanda=("atendimento_demanda", "mean"),
            custo_total_rs=("custo_total_dia_rs", "sum"),
            perdas_m3=("perdas_m3", "sum"),
            perdas_pct=("perdas_pct", "mean"),
            ea=("ea", "mean"),
            eirr=("eirr", "mean"),
            outorga_conforme=("outorga_conforme", "mean"),
        )
        .sort_values("data")
    )
    daily["ddmm"] = pd.to_datetime(daily["data"]).dt.strftime("%d/%m")
    return daily



def build_monthly_series(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()

    monthly = (
        df.assign(ano_mes=pd.to_datetime(df["data"]).dt.to_period("M").astype(str))
        .groupby("ano_mes", as_index=False)
        .agg(
            volume_aplicado_m3=("volume_aplicado_m3", "sum"),
            volume_captado_m3=("volume_captado_m3", "sum"),
            energia_kwh=("energia_kwh", "sum"),
            custo_total_rs=("custo_total_dia_rs", "sum"),
            perdas_m3=("perdas_m3", "sum"),
            perdas_pct=("perdas_pct", "mean"),
            atendimento_demanda=("atendimento_demanda", "mean"),
            ea=("ea", "mean"),
            eirr=("eirr", "mean"),
        )
        .sort_values("ano_mes")
    )
    return monthly



def weighted_control_metrics(df: pd.DataFrame) -> dict[str, float]:
    if df.empty:
        return {
            "pressao_media_pond": 0.0,
            "pressao_alvo_pond": 0.0,
            "vazao_media_pond": 0.0,
            "vazao_projeto_pond": 0.0,
            "eficiencia_media_pond": 0.0,
        }

    area = np.maximum(df["area_ha"].to_numpy(), EPSILON)
    return {
        "pressao_media_pond": float(np.average(df["pressao_media"].fillna(df["meta_pressao_alvo"]), weights=area)),
        "pressao_alvo_pond": float(np.average(df["meta_pressao_alvo"], weights=area)),
        "vazao_media_pond": float(np.average(df["vazao_media"].fillna(df["meta_vazao_projeto"]), weights=area)),
        "vazao_projeto_pond": float(np.average(df["meta_vazao_projeto"], weights=area)),
        "eficiencia_media_pond": float(np.average(df["eirr"], weights=area)),
    }


@st.cache_data(ttl=300, show_spinner=False)
def management_metrics(filters: FilterParams, db_path: str | None = None) -> dict[str, float]:
    df = load_operational_dataset(filters, db_path=db_path)
    if df.empty:
        return {
            "talhoes_recomendacao_atualizada_pct": 0.0,
            "leituras_no_prazo_pct": 0.0,
            "tempo_resposta_h": 0.0,
            "preventiva_em_dia_pct": 0.0,
        }

    ref = max(df["data"])
    ref_iso = ref.isoformat()

    with connection(db_path) as conn:
        total_talhoes = int(conn.execute("SELECT COUNT(*) FROM talhao").fetchone()[0] or 1)

        rec_atualizada = int(
            conn.execute(
                """
                SELECT COUNT(DISTINCT talhao_id)
                FROM planejamento
                WHERE DATE(data_ref) >= DATE(?, '-14 day')
                """,
                (ref_iso,),
            ).fetchone()[0]
            or 0
        )

        leituras = conn.execute(
            """
            WITH ult AS (
                SELECT sensor_id, MAX(data_hora) AS ultima
                FROM leituras_sensores
                GROUP BY sensor_id
            )
            SELECT
                SUM(CASE WHEN julianday(?) - julianday(ultima) <= 2 THEN 1 ELSE 0 END) AS ok,
                COUNT(*) AS total
            FROM ult
            """,
            (ref_iso,),
        ).fetchone()

        preventiva = conn.execute(
            """
            WITH ult_prev AS (
                SELECT talhao_id, MAX(DATE(data_inicio)) AS ultima_prev
                FROM manutencoes
                WHERE tipo = 'PREVENTIVA'
                GROUP BY talhao_id
            )
            SELECT
                SUM(CASE WHEN julianday(?) - julianday(ultima_prev) <= 35 THEN 1 ELSE 0 END) AS ok,
                COUNT(*) AS total
            FROM ult_prev
            """,
            (ref_iso,),
        ).fetchone()

    tempo_resp = float(df.loc[df["teve_problema"] == 1, "tempo_manutencao_h"].fillna(0).mean() or 0.0)
    ok_leituras = float(leituras["ok"] or 0)
    total_leituras = float(leituras["total"] or 1)
    ok_prev = float(preventiva["ok"] or 0)
    total_prev = float(preventiva["total"] or 1)

    return {
        "talhoes_recomendacao_atualizada_pct": float(rec_atualizada) / max(float(total_talhoes), 1),
        "leituras_no_prazo_pct": ok_leituras / max(total_leituras, 1),
        "tempo_resposta_h": tempo_resp,
        "preventiva_em_dia_pct": ok_prev / max(total_prev, 1),
    }



def ranking_talhoes(df: pd.DataFrame, metric: str, top_n: int = 10) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["talhao", metric])

    grouped = (
        df.groupby(["talhao_id", "talhao_codigo", "talhao_nome"], as_index=False)
        .agg(valor=(metric, "sum" if metric.endswith("_m3") or metric.endswith("_rs") or metric == "energia_kwh" else "mean"))
        .sort_values("valor", ascending=False)
        .head(top_n)
    )
    grouped["talhao"] = grouped["talhao_codigo"] + " - " + grouped["talhao_nome"]
    return grouped[["talhao", "valor"]]



def map_table(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()

    out = (
        df.groupby(
            [
                "talhao_id",
                "talhao_codigo",
                "talhao_nome",
                "latitude_centro",
                "longitude_centro",
            ],
            as_index=False,
        )
        .agg(
            consumo_energia=("energia_kwh", "sum"),
            aporte_hidrico=("volume_aplicado_m3", "sum"),
            produtividade=("eirr", "mean"),
            perdas=("perdas_pct", "mean"),
            horas_atividade=("horas_irrigadas", "sum"),
            alertas=("is_alerta", "sum"),
        )
    )
    out["talhao"] = out["talhao_codigo"] + " - " + out["talhao_nome"]
    return out



def detail_table(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df

    cols = [
        "data",
        "fazenda_nome",
        "bloco_nome",
        "talhao_codigo",
        "talhao_nome",
        "sistema_irrigacao",
        "status_operacao",
        "horas_irrigadas",
        "horas_paradas",
        "lamina_mm",
        "demanda_mm_dia",
        "atendimento_demanda",
        "volume_aplicado_m3",
        "volume_captado_m3",
        "perdas_m3",
        "perdas_pct",
        "energia_kwh",
        "consumo_especifico_kwh_m3",
        "energia_por_ha",
        "ea",
        "eirr",
        "pressao_media",
        "meta_pressao_alvo",
        "vazao_media",
        "meta_vazao_projeto",
        "outorga_conforme",
        "ph_media",
        "turbidez_media",
        "custo_total_dia_rs",
        "is_alerta",
    ]
    out = df.reindex(columns=cols)
    return out.sort_values(["data", "fazenda_nome", "bloco_nome", "talhao_codigo"], ascending=[False, True, True, True])


@st.cache_data(ttl=120, show_spinner=False)
def planning_vs_actual(
    start_date: date,
    end_date: date,
    talhao_ids: tuple[int, ...] = (),
    db_path: str | None = None,
) -> pd.DataFrame:
    params: list[Any] = [start_date.isoformat(), end_date.isoformat()]
    talhao_clause = ""
    if talhao_ids:
        placeholders = ",".join(["?"] * len(talhao_ids))
        talhao_clause = f" AND p.talhao_id IN ({placeholders}) "
        params.extend(talhao_ids)

    query = f"""
        SELECT
            p.id,
            DATE(p.data_ref) AS data_ref,
            p.periodo,
            p.status,
            p.prioridade,
            p.horas_planejadas,
            p.lamina_planejada_mm,
            p.manutencao_planejada,
            p.tipo_manutencao,
            p.notas,
            t.id AS talhao_id,
            t.codigo AS talhao_codigo,
            t.nome AS talhao_nome,
            b.nome AS bloco_nome,
            f.nome AS fazenda_nome,
            COALESCE(a.horas_irrigadas, 0) AS horas_realizadas,
            COALESCE(a.lamina_mm, 0) AS lamina_real_mm,
            COALESCE(a.volume_aplicado_m3, 0) AS volume_real_m3,
            COALESCE(a.energia_kwh, 0) AS energia_real_kwh
        FROM planejamento p
        JOIN talhao t ON t.id = p.talhao_id
        JOIN bloco b ON b.id = t.bloco_id
        JOIN fazenda f ON f.id = b.fazenda_id
        LEFT JOIN atividades_irrigacao a
               ON a.talhao_id = p.talhao_id
              AND DATE(a.data) = DATE(p.data_ref)
        WHERE DATE(p.data_ref) BETWEEN ? AND ?
        {talhao_clause}
        ORDER BY p.data_ref DESC, f.nome, b.nome, t.codigo
    """

    with connection(db_path) as conn:
        out = pd.read_sql_query(query, conn, params=params)

    if out.empty:
        return out

    out["data_ref"] = pd.to_datetime(out["data_ref"]).dt.date
    out["aderencia_lamina_pct"] = np.divide(
        out["lamina_real_mm"],
        np.maximum(out["lamina_planejada_mm"], EPSILON),
    )
    out["aderencia_horas_pct"] = np.divide(
        out["horas_realizadas"],
        np.maximum(out["horas_planejadas"], EPSILON),
    )
    return out
