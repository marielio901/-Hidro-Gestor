from __future__ import annotations

import pandas as pd
import pydeck as pdk


def build_talhoes_map(df: pd.DataFrame) -> pdk.Deck:
    map_df = df.copy()
    if not map_df.empty:
        map_df["latitude_centro"] = pd.to_numeric(map_df["latitude_centro"], errors="coerce")
        map_df["longitude_centro"] = pd.to_numeric(map_df["longitude_centro"], errors="coerce")
        map_df = map_df.dropna(subset=["latitude_centro", "longitude_centro"])

    if map_df.empty:
        map_df = pd.DataFrame(
            [{"latitude_centro": -25.77, "longitude_centro": -49.33, "talhao": "Sem dados", "tooltip": "Sem dados"}]
        )

    lat = float(map_df["latitude_centro"].mean())
    lon = float(map_df["longitude_centro"].mean())

    layer = pdk.Layer(
        "ScatterplotLayer",
        data=map_df,
        get_position="[longitude_centro, latitude_centro]",
        get_radius=900,
        get_fill_color="[15, 118, 255, 210]",
        get_line_color="[255, 255, 255, 180]",
        line_width_min_pixels=1,
        pickable=True,
        auto_highlight=True,
    )

    tooltip = {
        "html": "<b>{talhao}</b><br/>{tooltip}",
        "style": {"backgroundColor": "#1f2937", "color": "white"},
    }

    return pdk.Deck(
        layers=[layer],
        initial_view_state=pdk.ViewState(latitude=lat, longitude=lon, zoom=10, pitch=0),
        tooltip=tooltip,
        map_provider=None,
        map_style=None,
    )
