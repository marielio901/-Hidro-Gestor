from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

import pandas as pd
import requests

from db.db import connection

ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
DAILY_FIELDS = [
    "precipitation_sum",
    "temperature_2m_min",
    "temperature_2m_max",
    "wind_speed_10m_max",
    "et0_fao_evapotranspiration",
]
KC_DEFAULT = 1.05



def _to_date(value: str | date | datetime) -> date:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    return datetime.fromisoformat(str(value)).date()



def _request_open_meteo(url: str, lat: float, lon: float, start: date, end: date) -> pd.DataFrame:
    params = {
        "latitude": lat,
        "longitude": lon,
        "daily": ",".join(DAILY_FIELDS),
        "timezone": "America/Sao_Paulo",
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
    }

    resp = requests.get(url, params=params, timeout=20)
    resp.raise_for_status()
    payload = resp.json()
    daily = payload.get("daily")
    if not daily:
        raise ValueError("Resposta sem bloco 'daily' da Open-Meteo.")

    df = pd.DataFrame(
        {
            "data": daily.get("time", []),
            "precipitacao_mm": daily.get("precipitation_sum", []),
            "temp_min_c": daily.get("temperature_2m_min", []),
            "temp_max_c": daily.get("temperature_2m_max", []),
            "vento_max_ms": daily.get("wind_speed_10m_max", []),
            "eto_mm_dia": daily.get("et0_fao_evapotranspiration", []),
        }
    )

    if df.empty:
        return df

    df["data"] = pd.to_datetime(df["data"]).dt.date
    for col in ["precipitacao_mm", "temp_min_c", "temp_max_c", "vento_max_ms", "eto_mm_dia"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    if df["eto_mm_dia"].isna().all():
        temp_avg = (df["temp_min_c"].fillna(0) + df["temp_max_c"].fillna(0)) / 2
        wind = df["vento_max_ms"].fillna(1.0)
        df["eto_mm_dia"] = (0.08 * temp_avg + 0.2 * wind).clip(lower=0)

    df["etc_mm_dia"] = df["eto_mm_dia"].fillna(0) * KC_DEFAULT
    return df



def fetch_daily_weather(lat: float, lon: float, start_date: str | date, end_date: str | date) -> pd.DataFrame:
    start = _to_date(start_date)
    end = _to_date(end_date)
    if end < start:
        raise ValueError("Data final menor que data inicial.")

    today = date.today()
    parts: list[pd.DataFrame] = []

    if start <= today:
        archive_end = min(end, today)
        parts.append(_request_open_meteo(ARCHIVE_URL, lat, lon, start, archive_end))

    if end > today:
        forecast_start = max(start, today)
        parts.append(_request_open_meteo(FORECAST_URL, lat, lon, forecast_start, end))

    if not parts:
        return pd.DataFrame()

    out = pd.concat(parts, ignore_index=True)
    out = out.drop_duplicates(subset=["data"]).sort_values("data").reset_index(drop=True)
    return out



def cache_climate_for_farm(
    fazenda_id: int,
    lat: float,
    lon: float,
    start_date: str | date,
    end_date: str | date,
    db_path: str | None = None,
) -> tuple[int, str]:
    df = fetch_daily_weather(lat, lon, start_date, end_date)
    if df.empty:
        return 0, "Sem dados retornados pela Open-Meteo."

    rows = [
        {
            "fazenda_id": int(fazenda_id),
            "data": row.data.isoformat(),
            "precipitacao_mm": float(row.precipitacao_mm or 0),
            "temp_min_c": None if pd.isna(row.temp_min_c) else float(row.temp_min_c),
            "temp_max_c": None if pd.isna(row.temp_max_c) else float(row.temp_max_c),
            "vento_max_ms": None if pd.isna(row.vento_max_ms) else float(row.vento_max_ms),
            "eto_mm_dia": None if pd.isna(row.eto_mm_dia) else float(row.eto_mm_dia),
            "etc_mm_dia": None if pd.isna(row.etc_mm_dia) else float(row.etc_mm_dia),
            "fonte": "Open-Meteo",
        }
        for row in df.itertuples(index=False)
    ]

    with connection(db_path) as conn:
        conn.executemany(
            """
            INSERT INTO clima_diario (
                fazenda_id, data, precipitacao_mm, temp_min_c, temp_max_c,
                vento_max_ms, eto_mm_dia, etc_mm_dia, fonte
            ) VALUES (
                :fazenda_id, :data, :precipitacao_mm, :temp_min_c, :temp_max_c,
                :vento_max_ms, :eto_mm_dia, :etc_mm_dia, :fonte
            )
            ON CONFLICT(fazenda_id, data) DO UPDATE SET
                precipitacao_mm = excluded.precipitacao_mm,
                temp_min_c = excluded.temp_min_c,
                temp_max_c = excluded.temp_max_c,
                vento_max_ms = excluded.vento_max_ms,
                eto_mm_dia = excluded.eto_mm_dia,
                etc_mm_dia = excluded.etc_mm_dia,
                fonte = excluded.fonte
            """,
            rows,
        )

    return len(rows), "Cache atualizado com sucesso."



def update_climate_cache(
    start_date: str | date,
    end_date: str | date,
    db_path: str | None = None,
    fazenda_ids: list[int] | None = None,
) -> dict[str, Any]:
    summary: dict[str, Any] = {"updated_rows": 0, "errors": []}

    with connection(db_path) as conn:
        if fazenda_ids:
            placeholders = ",".join(["?"] * len(fazenda_ids))
            fazendas = conn.execute(
                f"SELECT id, latitude, longitude, nome FROM fazenda WHERE id IN ({placeholders}) ORDER BY nome",
                fazenda_ids,
            ).fetchall()
        else:
            fazendas = conn.execute("SELECT id, latitude, longitude, nome FROM fazenda ORDER BY nome").fetchall()

    if not fazendas:
        return summary

    for fazenda in fazendas:
        try:
            count, _ = cache_climate_for_farm(
                fazenda_id=int(fazenda["id"]),
                lat=float(fazenda["latitude"]),
                lon=float(fazenda["longitude"]),
                start_date=start_date,
                end_date=end_date,
                db_path=db_path,
            )
            summary["updated_rows"] += count
        except Exception as exc:  # noqa: BLE001
            summary["errors"].append(f"{fazenda['nome']}: {exc}")

    return summary



def load_cached_climate(
    start_date: str | date,
    end_date: str | date,
    db_path: str | None = None,
    fazenda_ids: list[int] | None = None,
) -> pd.DataFrame:
    start = _to_date(start_date).isoformat()
    end = _to_date(end_date).isoformat()

    with connection(db_path) as conn:
        if fazenda_ids:
            placeholders = ",".join(["?"] * len(fazenda_ids))
            query = f"""
                SELECT c.*, f.nome AS fazenda_nome
                FROM clima_diario c
                JOIN fazenda f ON f.id = c.fazenda_id
                WHERE c.data BETWEEN ? AND ?
                  AND c.fazenda_id IN ({placeholders})
                ORDER BY c.data, f.nome
            """
            params = [start, end, *fazenda_ids]
        else:
            query = """
                SELECT c.*, f.nome AS fazenda_nome
                FROM clima_diario c
                JOIN fazenda f ON f.id = c.fazenda_id
                WHERE c.data BETWEEN ? AND ?
                ORDER BY c.data, f.nome
            """
            params = [start, end]

        df = pd.read_sql_query(query, conn, params=params)

    if not df.empty:
        df["data"] = pd.to_datetime(df["data"]).dt.date

    return df



def refresh_with_fallback(
    start_date: str | date,
    end_date: str | date,
    db_path: str | None = None,
    fazenda_ids: list[int] | None = None,
) -> tuple[pd.DataFrame, str]:
    try:
        summary = update_climate_cache(start_date, end_date, db_path=db_path, fazenda_ids=fazenda_ids)
        climate_df = load_cached_climate(start_date, end_date, db_path=db_path, fazenda_ids=fazenda_ids)
        if summary["errors"]:
            return climate_df, "Falha parcial na API. Exibindo cache disponível."
        return climate_df, f"Clima atualizado ({summary['updated_rows']} linhas)."
    except Exception:  # noqa: BLE001
        climate_df = load_cached_climate(start_date, end_date, db_path=db_path, fazenda_ids=fazenda_ids)
        return climate_df, "API indisponível. Exibindo último cache salvo."



def upcoming_forecast(lat: float, lon: float, days: int = 7) -> pd.DataFrame:
    start = date.today()
    end = start + timedelta(days=max(days - 1, 0))
    return fetch_daily_weather(lat, lon, start, end)
