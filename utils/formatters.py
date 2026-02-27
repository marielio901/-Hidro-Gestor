from __future__ import annotations


def fmt_num(value: float | int | None, decimals: int = 2) -> str:
    if value is None:
        return "-"
    return f"{value:,.{decimals}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def fmt_m3(value: float | int | None) -> str:
    return f"{fmt_num(value, 1)} m³"


def fmt_mm(value: float | int | None) -> str:
    return f"{fmt_num(value, 1)} mm"


def fmt_kwh(value: float | int | None) -> str:
    return f"{fmt_num(value, 1)} kWh"


def fmt_rs(value: float | int | None) -> str:
    return f"R$ {fmt_num(value, 2)}"


def fmt_pct(value: float | int | None) -> str:
    if value is None:
        return "-"
    return f"{value * 100:.1f}%"
