from __future__ import annotations

import argparse
import math
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

import numpy as np

from db.db import connection, init_db

SEED_DEFAULT = 20250225
EPSILON = 1e-6
KC_DEFAULT = 1.05

PROBLEMAS = ["VAZAMENTO", "PRESSAO_BAIXA", "BOMBA", "ELETRICO", "OUTRO"]
MUNICIPIOS_SUL_CURITIBA = [
    ("Fazenda Rio Grande", -25.6627, -49.3094),
    ("Mandirituba", -25.7772, -49.3274),
    ("Quitandinha", -25.8748, -49.4973),
    ("Contenda", -25.6788, -49.5388),
    ("Lapa", -25.7697, -49.7158),
    ("Araucaria", -25.5859, -49.4047),
]


@dataclass
class TalhaoMeta:
    id: int
    fazenda_id: int
    area_ha: float
    sistema: str
    meta_pressao: float
    meta_vazao: float
    outorga_limite: float



def _clamp(value: float, min_value: float, max_value: float) -> float:
    return max(min(value, max_value), min_value)



def _daterange(start: date, end: date) -> list[date]:
    return [start + timedelta(days=i) for i in range((end - start).days + 1)]



def _seasonal_climate(day: date, rng: np.random.Generator) -> dict[str, float]:
    month = day.month
    if month in (12, 1, 2):
        rain_mean = 8.2
        tmin_base = 17.0
        tmax_base = 28.0
    elif month in (3, 4, 5):
        rain_mean = 5.8
        tmin_base = 14.0
        tmax_base = 24.0
    elif month in (6, 7, 8):
        rain_mean = 3.0
        tmin_base = 8.5
        tmax_base = 19.0
    else:
        rain_mean = 5.2
        tmin_base = 12.0
        tmax_base = 23.0

    annual_wave = math.sin((day.timetuple().tm_yday / 365.0) * 2 * math.pi)
    precip = max(rng.gamma(shape=2.0, scale=rain_mean / 2.6) + annual_wave * 1.3 - 1.0, 0)
    temp_min = tmin_base + annual_wave * 1.4 + rng.normal(0, 1.6)
    temp_max = max(temp_min + 3.2, tmax_base + annual_wave * 1.9 + rng.normal(0, 1.8))
    wind = _clamp(2.0 + rng.normal(0, 0.8) + abs(annual_wave) * 0.9, 0.5, 9.5)

    temp_avg = (temp_min + temp_max) / 2
    eto = _clamp(0.09 * temp_avg + 0.13 * wind - 0.018 * precip + 0.65, 0.6, 7.8)
    etc = eto * KC_DEFAULT

    return {
        "precipitacao_mm": round(precip, 2),
        "temp_min_c": round(temp_min, 2),
        "temp_max_c": round(temp_max, 2),
        "vento_max_ms": round(wind, 2),
        "eto_mm_dia": round(eto, 2),
        "etc_mm_dia": round(etc, 2),
    }



def _generate_farms(rng: np.random.Generator) -> list[dict[str, Any]]:
    num = int(rng.integers(2, 5))
    picked = rng.choice(len(MUNICIPIOS_SUL_CURITIBA), size=num, replace=False)
    farms: list[dict[str, Any]] = []

    for i, idx in enumerate(sorted(int(x) for x in picked), start=1):
        municipio, lat, lon = MUNICIPIOS_SUL_CURITIBA[idx]
        farms.append(
            {
                "nome": f"Fazenda Vale Sul {i}",
                "municipio": municipio,
                "uf": "PR",
                "latitude": round(lat + float(rng.uniform(-0.03, 0.03)), 6),
                "longitude": round(lon + float(rng.uniform(-0.03, 0.03)), 6),
                "area_total_ha": round(float(rng.uniform(220, 950)), 2),
            }
        )
    return farms



def _insert_farms(conn, farms: list[dict[str, Any]]) -> list[int]:
    ids: list[int] = []
    for farm in farms:
        cur = conn.execute(
            """
            INSERT INTO fazenda (nome, municipio, uf, latitude, longitude, area_total_ha)
            VALUES (:nome, :municipio, :uf, :latitude, :longitude, :area_total_ha)
            """,
            farm,
        )
        ids.append(int(cur.lastrowid))
    return ids



def _insert_costs(conn, farm_ids: list[int], rng: np.random.Generator) -> None:
    rows = [
        {
            "fazenda_id": fid,
            "custo_agua_rs_m3": round(float(rng.uniform(0.18, 0.36)), 3),
            "custo_energia_rs_kwh": round(float(rng.uniform(0.62, 0.98)), 3),
            "outros_fixos_rs_mes": round(float(rng.uniform(2800, 9900)), 2),
        }
        for fid in farm_ids
    ]

    rows.append(
        {
            "fazenda_id": None,
            "custo_agua_rs_m3": 0.25,
            "custo_energia_rs_kwh": 0.78,
            "outros_fixos_rs_mes": 4500.0,
        }
    )

    conn.executemany(
        """
        INSERT INTO custos_parametros (
            fazenda_id, custo_agua_rs_m3, custo_energia_rs_kwh, outros_fixos_rs_mes
        ) VALUES (
            :fazenda_id, :custo_agua_rs_m3, :custo_energia_rs_kwh, :outros_fixos_rs_mes
        )
        """,
        rows,
    )



def _insert_hierarchy(conn, farm_ids: list[int], rng: np.random.Generator) -> list[TalhaoMeta]:
    talhoes: list[TalhaoMeta] = []
    talhao_counter = 1
    pivo_counter = 1
    got_counter = 1

    for fid in farm_ids:
        num_blocos = int(rng.integers(2, 5))
        for b in range(num_blocos):
            bloco_area = round(float(rng.uniform(45, 260)), 2)
            bloco_id = int(
                conn.execute(
                    "INSERT INTO bloco (fazenda_id, nome, area_ha) VALUES (?, ?, ?)",
                    (fid, f"Bloco {b + 1}", bloco_area),
                ).lastrowid
            )

            num_talhoes = int(rng.integers(3, 9))
            for _ in range(num_talhoes):
                sistema = "PIVO" if rng.random() < 0.5 else "GOTEJO"
                if sistema == "PIVO":
                    area = round(float(rng.uniform(10, 58)), 2)
                    meta_pressao = round(float(rng.uniform(2.4, 4.3)), 2)
                    meta_vazao = round(float(rng.uniform(70, 210)), 2)
                    codigo_sistema = f"PIV-{pivo_counter:03d}"
                    pivo_counter += 1
                else:
                    area = round(float(rng.uniform(3, 30)), 2)
                    meta_pressao = round(float(rng.uniform(1.1, 2.3)), 2)
                    meta_vazao = round(float(rng.uniform(12, 90)), 2)
                    codigo_sistema = f"GOT-{got_counter:03d}"
                    got_counter += 1

                outorga_limite = round(area * float(rng.uniform(20, 42)), 2)
                lat_offset = float(rng.uniform(-0.04, 0.04))
                lon_offset = float(rng.uniform(-0.04, 0.04))

                row = conn.execute(
                    """
                    INSERT INTO talhao (
                        bloco_id, codigo, nome, area_ha, sistema_irrigacao, codigo_sistema,
                        latitude_centro, longitude_centro, meta_pressao_alvo,
                        meta_vazao_projeto, outorga_limite_m3_dia
                    ) VALUES (
                        ?, ?, ?, ?, ?, ?,
                        (SELECT latitude + ? FROM fazenda WHERE id = ?),
                        (SELECT longitude + ? FROM fazenda WHERE id = ?),
                        ?, ?, ?
                    )
                    """,
                    (
                        bloco_id,
                        f"TLH-{talhao_counter:03d}",
                        f"Talhão {talhao_counter:03d}",
                        area,
                        sistema,
                        codigo_sistema,
                        lat_offset,
                        fid,
                        lon_offset,
                        fid,
                        meta_pressao,
                        meta_vazao,
                        outorga_limite,
                    ),
                )
                talhao_id = int(row.lastrowid)
                talhao_counter += 1

                talhoes.append(
                    TalhaoMeta(
                        id=talhao_id,
                        fazenda_id=fid,
                        area_ha=area,
                        sistema=sistema,
                        meta_pressao=meta_pressao,
                        meta_vazao=meta_vazao,
                        outorga_limite=outorga_limite,
                    )
                )

                conn.executemany(
                    """
                    INSERT INTO sensores (talhao_id, tipo, unidade, ativo)
                    VALUES (?, ?, ?, 1)
                    """,
                    [
                        (talhao_id, "PH", "pH"),
                        (talhao_id, "TURBIDEZ", "NTU"),
                        (talhao_id, "PRESSAO", "bar"),
                        (talhao_id, "VAZAO", "m3/h"),
                    ],
                )

    return talhoes



def _generate_climate(
    conn,
    farm_ids: list[int],
    dates: list[date],
    rng: np.random.Generator,
) -> dict[tuple[int, date], dict[str, float]]:
    rows: list[dict[str, Any]] = []
    lookup: dict[tuple[int, date], dict[str, float]] = {}

    for fid in farm_ids:
        for d in dates:
            weather = _seasonal_climate(d, rng)
            rows.append(
                {
                    "fazenda_id": fid,
                    "data": d.isoformat(),
                    **weather,
                    "fonte": "Simulador",
                }
            )
            lookup[(fid, d)] = weather

    conn.executemany(
        """
        INSERT INTO clima_diario (
            fazenda_id, data, precipitacao_mm, temp_min_c, temp_max_c,
            vento_max_ms, eto_mm_dia, etc_mm_dia, fonte
        ) VALUES (
            :fazenda_id, :data, :precipitacao_mm, :temp_min_c, :temp_max_c,
            :vento_max_ms, :eto_mm_dia, :etc_mm_dia, :fonte
        )
        """,
        rows,
    )
    return lookup



def _sensor_lookup(conn) -> dict[int, dict[str, int]]:
    rows = conn.execute("SELECT id, talhao_id, tipo FROM sensores").fetchall()
    out: dict[int, dict[str, int]] = {}
    for row in rows:
        out.setdefault(int(row["talhao_id"]), {})[str(row["tipo"])] = int(row["id"])
    return out



def _generate_operations(
    conn,
    talhoes: list[TalhaoMeta],
    dates: list[date],
    climate_lookup: dict[tuple[int, date], dict[str, float]],
    rng: np.random.Generator,
) -> None:
    activity_rows: list[dict[str, Any]] = []
    reading_rows: list[dict[str, Any]] = []
    maintenance_rows: list[dict[str, Any]] = []
    planning_rows: list[dict[str, Any]] = []

    sensor_map = _sensor_lookup(conn)
    corrective_counter = 0

    for talhao in talhoes:
        preventive_anchor = dates[0] + timedelta(days=int(rng.integers(0, 25)))

        for d in dates:
            climate = climate_lookup[(talhao.fazenda_id, d)]
            precip = float(climate["precipitacao_mm"])
            etc = float(climate["etc_mm_dia"])
            chuva_efetiva = precip * 0.8
            demanda = max(etc - chuva_efetiva, 0.0)

            # Mantém correlação física: maior demanda aumenta irrigação e chuva reduz irrigação.
            irrig_prob = _clamp(0.32 + (demanda / 3.5) - (precip / 80.0), 0.15, 0.98)
            irrigar = rng.random() < irrig_prob

            if irrigar:
                atendimento = float(_clamp(rng.normal(1.0, 0.15), 0.45, 1.5))
                if rng.random() < 0.09:
                    atendimento = float(_clamp(rng.normal(0.72, 0.09), 0.45, 0.92))
                elif rng.random() < 0.08:
                    atendimento = float(_clamp(rng.normal(1.28, 0.12), 1.05, 1.5))

                lamina = demanda * atendimento if demanda > 0 else float(rng.uniform(0.4, 1.9))
                lamina = float(_clamp(lamina, 0.0, 16.0))
                volume_aplicado = lamina * talhao.area_ha * 10.0

                vazao_efetiva = talhao.meta_vazao * float(_clamp(rng.normal(1.0, 0.09), 0.7, 1.3))
                horas_irrigadas = volume_aplicado / max(vazao_efetiva, EPSILON)
                if horas_irrigadas > 20:
                    horas_irrigadas = float(rng.uniform(12.0, 20.0))
                    volume_aplicado = horas_irrigadas * vazao_efetiva
                    lamina = volume_aplicado / (talhao.area_ha * 10.0)

                horas_paradas = float(_clamp(24.0 - horas_irrigadas + rng.normal(-0.4, 1.1), 0.0, 24.0 - horas_irrigadas))
                energia_kwh = max(0.0, horas_irrigadas * (vazao_efetiva * 0.33 + rng.uniform(3.0, 15.0)))
            else:
                lamina = 0.0
                volume_aplicado = 0.0
                horas_irrigadas = 0.0
                horas_paradas = float(rng.uniform(20.0, 24.0))
                energia_kwh = float(rng.uniform(0.4, 5.5))

            teve_problema = 1 if rng.random() < (0.03 + (0.02 if irrigar else 0.0)) else 0
            tipo_problema = None
            tempo_manutencao_h = None
            observacoes = ""

            if teve_problema:
                tipo_problema = str(rng.choice(PROBLEMAS, p=[0.35, 0.25, 0.2, 0.12, 0.08]))
                tempo_manutencao_h = round(float(rng.uniform(0.5, 6.5)), 2)
                observacoes = f"Evento {tipo_problema.lower()} registrado pelo simulador"
                corrective_counter += 1
                maintenance_rows.append(
                    {
                        "talhao_id": talhao.id,
                        "data_inicio": d.isoformat(),
                        "data_fim": d.isoformat(),
                        "tipo": "CORRETIVA",
                        "descricao": f"Corretiva #{corrective_counter} ({tipo_problema})",
                        "duracao_h": tempo_manutencao_h,
                        "custo_manutencao_rs": round(float(rng.uniform(200, 2800)), 2),
                    }
                )

            if d >= preventive_anchor and (d - preventive_anchor).days % 30 == 0:
                preventive_hours = round(float(rng.uniform(1.0, 4.5)), 2)
                maintenance_rows.append(
                    {
                        "talhao_id": talhao.id,
                        "data_inicio": d.isoformat(),
                        "data_fim": d.isoformat(),
                        "tipo": "PREVENTIVA",
                        "descricao": "Rotina preventiva 30 dias",
                        "duracao_h": preventive_hours,
                        "custo_manutencao_rs": round(float(rng.uniform(80, 650)), 2),
                    }
                )

            if volume_aplicado <= 0:
                volume_captado = 0.0
            else:
                if tipo_problema == "VAZAMENTO":
                    fator_perda = float(rng.uniform(0.22, 0.45))
                elif teve_problema:
                    fator_perda = float(rng.uniform(0.09, 0.22))
                else:
                    fator_perda = float(rng.uniform(0.02, 0.10))
                volume_captado = volume_aplicado * (1.0 + fator_perda)

            activity_rows.append(
                {
                    "talhao_id": talhao.id,
                    "data": d.isoformat(),
                    "horas_irrigadas": round(horas_irrigadas, 2),
                    "horas_paradas": round(horas_paradas, 2),
                    "lamina_mm": round(lamina, 2),
                    "volume_captado_m3": round(float(volume_captado), 2),
                    "volume_aplicado_m3": round(float(volume_aplicado), 2),
                    "energia_kwh": round(float(energia_kwh), 2),
                    "teve_problema": teve_problema,
                    "tipo_problema": tipo_problema,
                    "tempo_manutencao_h": tempo_manutencao_h,
                    "observacoes": observacoes,
                }
            )

            sensor_ids = sensor_map[talhao.id]
            drop_day = rng.random() < 0.02
            if not drop_day:
                for h in [0, 6, 12, 18]:
                    timestamp = datetime.combine(d, datetime.min.time()) + timedelta(hours=h)

                    if irrigar:
                        pressure_base = talhao.meta_pressao
                        flow_base = talhao.meta_vazao * float(_clamp(rng.normal(1.0, 0.09), 0.65, 1.35))
                    else:
                        pressure_base = talhao.meta_pressao * float(_clamp(rng.normal(0.35, 0.12), 0.08, 0.9))
                        flow_base = talhao.meta_vazao * float(_clamp(rng.normal(0.08, 0.05), 0.0, 0.2))

                    if tipo_problema == "PRESSAO_BAIXA":
                        pressure_base *= float(rng.uniform(0.5, 0.78))
                        flow_base *= float(rng.uniform(0.68, 0.9))
                    if tipo_problema == "VAZAMENTO":
                        flow_base *= float(rng.uniform(1.05, 1.24))

                    ph = float(rng.normal(6.7, 0.22))
                    turbidez = float(max(0.2, rng.normal(3.6 + (0.15 * precip), 1.4)))
                    if rng.random() < 0.04:
                        ph += float(rng.choice([-1.2, 1.35]))
                    if rng.random() < 0.05:
                        turbidez += float(rng.uniform(4.0, 12.0))

                    reading_rows.extend(
                        [
                            {
                                "sensor_id": sensor_ids["PRESSAO"],
                                "data_hora": timestamp.isoformat(timespec="minutes"),
                                "valor": round(float(max(0.05, rng.normal(pressure_base, 0.1))), 3),
                            },
                            {
                                "sensor_id": sensor_ids["VAZAO"],
                                "data_hora": timestamp.isoformat(timespec="minutes"),
                                "valor": round(float(max(0.0, rng.normal(flow_base, talhao.meta_vazao * 0.03))), 3),
                            },
                            {
                                "sensor_id": sensor_ids["PH"],
                                "data_hora": timestamp.isoformat(timespec="minutes"),
                                "valor": round(ph, 3),
                            },
                            {
                                "sensor_id": sensor_ids["TURBIDEZ"],
                                "data_hora": timestamp.isoformat(timespec="minutes"),
                                "valor": round(turbidez, 3),
                            },
                        ]
                    )

        start_week = dates[-1] - timedelta(days=56)
        for w in range(13):
            ref = start_week + timedelta(days=w * 7)
            if ref <= date.today() - timedelta(days=7):
                status = "CONCLUIDO"
            elif ref <= date.today():
                status = "EM_EXECUCAO"
            else:
                status = "PLANEJADO"

            clima_semana = [
                climate_lookup[(talhao.fazenda_id, ref + timedelta(days=i))]
                for i in range(7)
                if (talhao.fazenda_id, ref + timedelta(days=i)) in climate_lookup
            ]
            etc_avg = np.mean([c["etc_mm_dia"] for c in clima_semana]) if clima_semana else 3.6
            chuva_avg = np.mean([c["precipitacao_mm"] for c in clima_semana]) if clima_semana else 2.0
            demanda = max(etc_avg - (chuva_avg * 0.8), 0.0)

            lamina_planejada = float(_clamp(demanda * 7.0, 0.0, 65.0))
            volume_planejado = lamina_planejada * talhao.area_ha * 10.0
            horas_planejadas = volume_planejado / max(talhao.meta_vazao, EPSILON)

            planning_rows.append(
                {
                    "talhao_id": talhao.id,
                    "periodo": "SEMANA",
                    "data_ref": ref.isoformat(),
                    "horas_planejadas": round(float(_clamp(horas_planejadas, 0.0, 120.0)), 2),
                    "lamina_planejada_mm": round(lamina_planejada, 2),
                    "manutencao_planejada": 1 if w % 4 == 0 else 0,
                    "tipo_manutencao": "PREVENTIVA" if w % 4 == 0 else None,
                    "prioridade": int(_clamp(5 - int(lamina_planejada // 15), 1, 5)),
                    "status": status,
                    "notas": "Sugerido por histórico + clima sintético",
                }
            )

    conn.executemany(
        """
        INSERT INTO atividades_irrigacao (
            talhao_id, data, horas_irrigadas, horas_paradas, lamina_mm,
            volume_captado_m3, volume_aplicado_m3, energia_kwh,
            teve_problema, tipo_problema, tempo_manutencao_h, observacoes
        ) VALUES (
            :talhao_id, :data, :horas_irrigadas, :horas_paradas, :lamina_mm,
            :volume_captado_m3, :volume_aplicado_m3, :energia_kwh,
            :teve_problema, :tipo_problema, :tempo_manutencao_h, :observacoes
        )
        """,
        activity_rows,
    )

    conn.executemany(
        "INSERT INTO leituras_sensores (sensor_id, data_hora, valor) VALUES (:sensor_id, :data_hora, :valor)",
        reading_rows,
    )

    conn.executemany(
        """
        INSERT INTO manutencoes (
            talhao_id, data_inicio, data_fim, tipo, descricao, duracao_h, custo_manutencao_rs
        ) VALUES (
            :talhao_id, :data_inicio, :data_fim, :tipo, :descricao, :duracao_h, :custo_manutencao_rs
        )
        """,
        maintenance_rows,
    )

    conn.executemany(
        """
        INSERT INTO planejamento (
            talhao_id, periodo, data_ref, horas_planejadas, lamina_planejada_mm,
            manutencao_planejada, tipo_manutencao, prioridade, status, notas
        ) VALUES (
            :talhao_id, :periodo, :data_ref, :horas_planejadas, :lamina_planejada_mm,
            :manutencao_planejada, :tipo_manutencao, :prioridade, :status, :notas
        )
        """,
        planning_rows,
    )



def generate_synthetic_data(
    db_path: str | None = None,
    months: int = 6,
    seed: int = SEED_DEFAULT,
    reset_db: bool = True,
) -> dict[str, Any]:
    rng = np.random.default_rng(seed)

    init_db(db_path=db_path, drop_existing=reset_db)

    end = date.today()
    start = end - timedelta(days=int(months * 30.5))
    dates = _daterange(start, end)

    with connection(db_path) as conn:
        farms = _generate_farms(rng)
        farm_ids = _insert_farms(conn, farms)
        _insert_costs(conn, farm_ids, rng)
        talhoes = _insert_hierarchy(conn, farm_ids, rng)
        climate_lookup = _generate_climate(conn, farm_ids, dates, rng)
        _generate_operations(conn, talhoes, dates, climate_lookup, rng)

        summary = {
            "fazendas": conn.execute("SELECT COUNT(*) FROM fazenda").fetchone()[0],
            "blocos": conn.execute("SELECT COUNT(*) FROM bloco").fetchone()[0],
            "talhoes": conn.execute("SELECT COUNT(*) FROM talhao").fetchone()[0],
            "sensores": conn.execute("SELECT COUNT(*) FROM sensores").fetchone()[0],
            "leituras": conn.execute("SELECT COUNT(*) FROM leituras_sensores").fetchone()[0],
            "atividades": conn.execute("SELECT COUNT(*) FROM atividades_irrigacao").fetchone()[0],
            "manutencoes": conn.execute("SELECT COUNT(*) FROM manutencoes").fetchone()[0],
            "clima": conn.execute("SELECT COUNT(*) FROM clima_diario").fetchone()[0],
            "planejamento": conn.execute("SELECT COUNT(*) FROM planejamento").fetchone()[0],
            "periodo": f"{start.isoformat()} a {end.isoformat()}",
            "seed": seed,
        }

    return summary



def main() -> None:
    parser = argparse.ArgumentParser(description="Simulador de dados sintéticos do HidroGestor")
    parser.add_argument("--db-path", default=None, help="Caminho do arquivo .db")
    parser.add_argument("--months", type=int, default=6, help="Quantidade de meses para trás")
    parser.add_argument("--seed", type=int, default=SEED_DEFAULT, help="Seed pseudo-aleatória")
    parser.add_argument(
        "--append",
        action="store_true",
        help="Mantém dados existentes (não recomendado para primeira carga)",
    )
    args = parser.parse_args()

    summary = generate_synthetic_data(
        db_path=args.db_path,
        months=args.months,
        seed=args.seed,
        reset_db=not args.append,
    )

    print("Dados sintéticos gerados com sucesso:")
    for k, v in summary.items():
        print(f"- {k}: {v}")


if __name__ == "__main__":
    main()
