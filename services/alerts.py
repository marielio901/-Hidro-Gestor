from __future__ import annotations

from datetime import date, datetime
from typing import Any

import pandas as pd

from db.db import connection



def _to_date(value: str | date | datetime) -> date:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    return datetime.fromisoformat(str(value)).date()



def generate_alerts(
    df: pd.DataFrame,
    db_path: str | None = None,
    perdas_limite: float = 0.20,
    pressao_days: int = 3,
    preventiva_days: int = 35,
    sensor_max_days: int = 2,
) -> pd.DataFrame:
    columns = ["data", "severidade", "tipo", "fazenda", "bloco", "talhao", "mensagem", "status"]
    if df.empty:
        return pd.DataFrame(columns=columns)

    ref = _to_date(max(df["data"]))
    alerts: list[dict[str, Any]] = []

    for row in df.itertuples(index=False):
        base = {
            "data": row.data,
            "talhao_id": int(row.talhao_id),
            "fazenda": row.fazenda_nome,
            "bloco": row.bloco_nome,
            "talhao": f"{row.talhao_codigo} - {row.talhao_nome}",
            "status": "ABERTO",
        }

        if not bool(row.outorga_conforme):
            alerts.append(
                {
                    **base,
                    "severidade": "ALTO",
                    "tipo": "OUTORGA_EXCEDIDA",
                    "mensagem": "Volume captado acima do limite de outorga diário.",
                }
            )

        if float(row.perdas_pct or 0) > perdas_limite:
            alerts.append(
                {
                    **base,
                    "severidade": "ALTO",
                    "tipo": "PERDAS_ELEVADAS",
                    "mensagem": f"Perdas acima de {perdas_limite * 100:.0f}%.",
                }
            )

        if not bool(row.pressao_conforme):
            alerts.append(
                {
                    **base,
                    "severidade": "MEDIO",
                    "tipo": "PRESSAO_BAIXA",
                    "mensagem": "Pressão média abaixo do alvo.",
                }
            )

        if not bool(row.ph_conforme):
            alerts.append(
                {
                    **base,
                    "severidade": "MEDIO",
                    "tipo": "PH_FORA_FAIXA",
                    "mensagem": "pH fora da faixa de conformidade (6.0 a 8.5).",
                }
            )

        if not bool(row.turbidez_conforme):
            alerts.append(
                {
                    **base,
                    "severidade": "MEDIO",
                    "tipo": "TURBIDEZ_ALTA",
                    "mensagem": "Turbidez acima do limite de 5 NTU.",
                }
            )

        if float(row.atendimento_demanda or 0) < 0.8:
            alerts.append(
                {
                    **base,
                    "severidade": "MEDIO",
                    "tipo": "SUB_IRRIGACAO",
                    "mensagem": "Atendimento da demanda hídrica abaixo de 80%.",
                }
            )

        if float(row.atendimento_demanda or 0) > 1.2:
            alerts.append(
                {
                    **base,
                    "severidade": "MEDIO",
                    "tipo": "SUPER_IRRIGACAO",
                    "mensagem": "Atendimento da demanda hídrica acima de 120%.",
                }
            )

    # Pressão baixa recorrente: conta somente se a recorrência estiver ativa no fim da série.
    for _, grp in df.sort_values(["talhao_id", "data"]).groupby("talhao_id"):
        flags = (~grp["pressao_conforme"].fillna(True)).astype(int).tolist()
        current_streak = 0
        for flag in reversed(flags):
            if flag:
                current_streak += 1
            else:
                break

        if current_streak >= pressao_days:
            last = grp.iloc[-1]
            alerts.append(
                {
                    "data": last["data"],
                    "talhao_id": int(last["talhao_id"]),
                    "severidade": "MEDIO",
                    "tipo": "PRESSAO_RECORRENTE",
                    "fazenda": last["fazenda_nome"],
                    "bloco": last["bloco_nome"],
                    "talhao": f"{last['talhao_codigo']} - {last['talhao_nome']}",
                    "mensagem": f"Pressão abaixo do alvo por {pressao_days}+ dias.",
                    "status": "ABERTO",
                }
            )

    with connection(db_path) as conn:
        overdue_prev = conn.execute(
            """
            WITH ult_prev AS (
                SELECT
                    t.id AS talhao_id,
                    t.codigo,
                    t.nome,
                    b.nome AS bloco_nome,
                    f.nome AS fazenda_nome,
                    MAX(DATE(m.data_inicio)) AS ultima_prev
                FROM talhao t
                JOIN bloco b ON b.id = t.bloco_id
                JOIN fazenda f ON f.id = b.fazenda_id
                LEFT JOIN manutencoes m
                       ON m.talhao_id = t.id
                      AND m.tipo = 'PREVENTIVA'
                GROUP BY t.id
            )
            SELECT *
            FROM ult_prev
            WHERE ultima_prev IS NULL
               OR julianday(?) - julianday(ultima_prev) > ?
            """,
            (ref.isoformat(), preventiva_days),
        ).fetchall()

        for row in overdue_prev:
            alerts.append(
                {
                    "data": ref,
                    "talhao_id": int(row["talhao_id"]),
                    "severidade": "MEDIO",
                    "tipo": "PREVENTIVA_ATRASADA",
                    "fazenda": row["fazenda_nome"],
                    "bloco": row["bloco_nome"],
                    "talhao": f"{row['codigo']} - {row['nome']}",
                    "mensagem": "Manutenção preventiva atrasada.",
                    "status": "ABERTO",
                }
            )

        stale_sensors = conn.execute(
            """
            WITH ult AS (
                SELECT
                    s.id,
                    s.tipo,
                    t.id AS talhao_id,
                    t.codigo,
                    t.nome AS talhao_nome,
                    b.nome AS bloco_nome,
                    f.nome AS fazenda_nome,
                    MAX(ls.data_hora) AS ultima
                FROM sensores s
                JOIN talhao t ON t.id = s.talhao_id
                JOIN bloco b ON b.id = t.bloco_id
                JOIN fazenda f ON f.id = b.fazenda_id
                LEFT JOIN leituras_sensores ls ON ls.sensor_id = s.id
                WHERE s.ativo = 1
                GROUP BY s.id
            )
            SELECT *
            FROM ult
            WHERE ultima IS NULL
               OR julianday(?) - julianday(ultima) > ?
            """,
            (ref.isoformat(), sensor_max_days),
        ).fetchall()

        for row in stale_sensors:
            alerts.append(
                {
                    "data": ref,
                    "talhao_id": int(row["talhao_id"]),
                    "severidade": "BAIXO",
                    "tipo": "SENSOR_SEM_LEITURA",
                    "fazenda": row["fazenda_nome"],
                    "bloco": row["bloco_nome"],
                    "talhao": f"{row['codigo']} - {row['talhao_nome']}",
                    "mensagem": f"Sensor {row['tipo']} sem leitura no prazo.",
                    "status": "ABERTO",
                }
            )

    alerts_df = pd.DataFrame(alerts)
    if alerts_df.empty:
        return pd.DataFrame(columns=columns)

    alerts_df["data"] = pd.to_datetime(alerts_df["data"]).dt.date
    alerts_df["talhao_id"] = alerts_df["talhao_id"].fillna(-1).astype(int)

    alerts_df["chave_alerta"] = alerts_df["tipo"]
    sensor_mask = alerts_df["tipo"] == "SENSOR_SEM_LEITURA"
    alerts_df.loc[sensor_mask, "chave_alerta"] = alerts_df.loc[sensor_mask, "tipo"] + "|" + alerts_df.loc[
        sensor_mask, "mensagem"
    ]

    alerts_df = (
        alerts_df.sort_values(["talhao_id", "chave_alerta", "data"])
        .drop_duplicates(subset=["talhao_id", "chave_alerta"], keep="last")
        .reset_index(drop=True)
    )

    operational_types = {
        "OUTORGA_EXCEDIDA",
        "PERDAS_ELEVADAS",
        "PRESSAO_BAIXA",
        "PH_FORA_FAIXA",
        "TURBIDEZ_ALTA",
        "SUB_IRRIGACAO",
        "SUPER_IRRIGACAO",
    }
    op_mask = alerts_df["tipo"].isin(operational_types)
    alerts_df.loc[op_mask, "status"] = alerts_df.loc[op_mask, "data"].apply(
        lambda d: "ABERTO" if _to_date(d) == ref else "FECHADO"
    )

    alerts_df = alerts_df.sort_values(["status", "severidade", "data"], ascending=[True, True, False])
    return alerts_df[columns].reset_index(drop=True)



def open_alerts_count(df: pd.DataFrame, db_path: str | None = None) -> int:
    alerts = generate_alerts(df, db_path=db_path)
    if alerts.empty:
        return 0
    return int((alerts["status"] == "ABERTO").sum())



def alerts_by_severity(df: pd.DataFrame, db_path: str | None = None) -> pd.DataFrame:
    alerts = generate_alerts(df, db_path=db_path)
    if alerts.empty:
        return pd.DataFrame(columns=["severidade", "qtd"])
    open_alerts = alerts[alerts["status"] == "ABERTO"]
    if open_alerts.empty:
        return pd.DataFrame(columns=["severidade", "qtd"])
    return open_alerts.groupby("severidade", as_index=False).size().rename(columns={"size": "qtd"})



def maintenance_backlog(db_path: str | None = None, limit: int = 500) -> pd.DataFrame:
    with connection(db_path) as conn:
        query = """
            SELECT
                m.id,
                DATE(m.data_inicio) AS data_inicio,
                DATE(m.data_fim) AS data_fim,
                m.tipo,
                m.descricao,
                m.duracao_h,
                m.custo_manutencao_rs,
                t.codigo AS talhao_codigo,
                t.nome AS talhao_nome,
                b.nome AS bloco_nome,
                f.nome AS fazenda_nome
            FROM manutencoes m
            JOIN talhao t ON t.id = m.talhao_id
            JOIN bloco b ON b.id = t.bloco_id
            JOIN fazenda f ON f.id = b.fazenda_id
            ORDER BY m.data_inicio DESC
            LIMIT ?
        """
        out = pd.read_sql_query(query, conn, params=[int(limit)])

    if out.empty:
        return out
    out["data_inicio"] = pd.to_datetime(out["data_inicio"]).dt.date
    out["data_fim"] = pd.to_datetime(out["data_fim"]).dt.date
    return out
