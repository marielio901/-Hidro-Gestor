# Hidro Gestor

Sistema de gestão de irrigação em **Streamlit + SQLite** com:
- Dashboard executivo com KPIs, gráficos diários/mensais, alertas e manutenção
- Cadastro de fazendas, blocos, talhões e sensores
- Registro diário de irrigação e manutenção
- Planejamento dia/semana/mês com sugestão baseada em clima Open-Meteo + histórico
- Simulador de dados sintéticos dos últimos 6 meses (sul de Curitiba/PR)

## Menu (fixo)

1. Dashboard
2. Cadastrar Locais
3. Registrar atividades
4. Planejamento

## Estrutura

```text
hidrogestor/
  app.py
  pages/
    1_Dashboard.py
    2_Cadastrar_Locais.py
    3_Registrar_atividades.py
    4_Planejamento.py
  db/
    schema.sql
    db.py
  services/
    open_meteo.py
    simulator.py
    kpis.py
    alerts.py
  utils/
    formatters.py
    geo.py
    ui.py
  scripts/
    init_db.py
    generate_data.py
  requirements.txt
```

## Como rodar

1. Criar e ativar ambiente virtual:

```bash
python -m venv venv
source venv/bin/activate
```

2. Instalar dependências:

```bash
pip install -r requirements.txt
```

3. Inicializar banco:

```bash
python scripts/init_db.py
```

4. Gerar dados sintéticos (6 meses, seed fixa):

```bash
python scripts/generate_data.py
```

Opcional (CLI direta do simulador):

```bash
python -m services.simulator --months 6 --seed 20250225
```

5. Executar app:

```bash
streamlit run app.py
```

## Open-Meteo e cache

- A aba **Clima Acompanhar** no Dashboard possui o botão **Atualizar clima**.
- Os dados são gravados em `clima_diario` (com `eto_mm_dia`, `etc_mm_dia` e `fonte`).
- Em falha de API, o sistema usa o cache SQLite disponível.

## Fórmulas principais

- `1 mm em 1 ha = 10 m³`
- `aporte_mm = volume_aplicado_m3 / (area_ha * 10)`
- `perdas_m3 = max(volume_captado_m3 - volume_aplicado_m3, 0)`
- `perdas_% = perdas_m3 / max(volume_captado_m3, epsilon)`
- `kwh_m3 = energia_kwh / max(volume_aplicado_m3, epsilon)`
- `kwh_ha = energia_kwh / max(area_ha, epsilon)`
- `custo_agua = volume_captado_m3 * custo_agua_rs_m3`
- `custo_energia = energia_kwh * custo_energia_rs_kwh`
- `custo_total_irrig_ha = (custo_agua + custo_energia + custo_manutencao_rs) / max(area_ha, epsilon)`
- `ETc = ETo * Kc` (Kc default `1.05`)
- `chuva_efetiva = precipitacao_mm * 0.8`
- `demanda_mm = max(ETc - chuva_efetiva, 0)`
- `atendimento = lamina_mm / max(demanda_mm, epsilon)`
- `Ea = clamp(1 - perdas_%, 0, 1)`
- `Eirr = clamp(Ea * min(atendimento, 1), 0, 1)`

## Regras

- Não permitir bloco sem fazenda, nem talhão sem bloco.
- Código de sistema (`PIV-XXX`/`GOT-XXX`) gerado de forma enumerada e única global.
- `horas_irrigadas + horas_paradas <= 24`.
- Se `teve_problema=1`, exigir `tipo_problema` e `tempo_manutencao_h`.
- Se `volume_captado_m3 > outorga_limite_m3_dia`, gerar alerta de outorga excedida.
