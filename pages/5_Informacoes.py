from __future__ import annotations

import streamlit as st

st.title("Informações")
st.caption("Visão geral do funcionamento do Hidro Gestor e dos principais indicadores do sistema.")

st.markdown("## Como o sistema funciona")
st.markdown(
    """
1. **Cadastrar Locais**: define fazendas, blocos, talhões e sensores.
2. **Planejamento**: cria planos de irrigação e agenda manutenções preventivas.
3. **Registrar atividades**: lança operação diária (horas, volumes, energia, problemas, manutenção).
4. **Processamento**: o sistema consolida os dados e calcula KPIs, conformidades e alertas.
5. **Dashboard**: apresenta visão executiva, técnica e financeira para decisão rápida.
"""
)

st.markdown("## Áreas e Indicadores")
c1, c2 = st.columns(2)

with c1:
    st.markdown(
        """
### Controle geral
- Aporte hídrico (m³/ha)
- Consumo de água e energia
- Custo total
- Perdas totais e alertas abertos

### Controle hídrico
- Volume captado e aplicado
- Perdas (m³ e %)
- Conformidade de outorga, pH e turbidez
- Pressão média vs pressão alvo

### Clima
- Chuva, vento, temperatura mínima/máxima
- ETo e ETc
- Séries diária (31 dias) e mensal
"""
    )

with c2:
    st.markdown(
        """
### Custos
- Custo de água por m³
- Custo de energia por m³
- Custo total por hectare
- Custo total e composição (água, energia, manutenção)

### Demanda e aplicação
- Lâmina aplicada e demanda hídrica
- Atendimento da demanda (%)
- Saldo hídrico (aplicação - demanda)
- Horas irrigadas/paradas e ocorrências de problema

### Eficiência, gestão e manutenção
- kWh/m³, kWh/ha, Ea, Eirr
- Planos concluídos, aderência de horas e lâmina
- Alertas de manutenção, backlog, ticket médio e custos por período
"""
    )

st.markdown("## Fórmulas principais")
st.code(
    """
1 mm em 1 ha = 10 m3
aporte_mm = volume_aplicado_m3 / (area_ha * 10)
perdas_m3 = max(volume_captado_m3 - volume_aplicado_m3, 0)
perdas_% = perdas_m3 / max(volume_captado_m3, epsilon)
kwh_m3 = energia_kwh / max(volume_aplicado_m3, epsilon)
kwh_ha = energia_kwh / max(area_ha, epsilon)
atendimento = lamina_mm / max(demanda_mm, epsilon)
Ea = clamp(1 - perdas_%, 0, 1)
Eirr = clamp(Ea * min(atendimento, 1), 0, 1)
""".strip(),
    language="text",
)

st.markdown("## Leitura rápida dos resultados")
st.markdown(
    """
- **Perdas altas** + **Ea baixo**: revisar vazamentos, pressão e eficiência de aplicação.
- **Atendimento < 100%**: risco de déficit hídrico (produção pode ser impactada).
- **kWh/m³ alto**: investigar bomba, pressão, setpoints e manutenção.
- **Ticket de manutenção crescente**: priorizar preventivas e recorrências por tipo/talhão.
"""
)

