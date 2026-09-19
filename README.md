# KZYVNG Analyzer — Experimental con ayuda de IA

Sistema de análisis estadístico personal para League of Legends, enfocado en
el rol de support de enganche (Nautilus, Rakan, Rell). Descarga el historial
de partidas vía la Riot Games API, reconstruye los timelines evento por
evento, y aplica minería de reglas estadísticas para separar patrones de
juego reales de ruido estadístico.

El resultado es un panel HTML autocontenido — sin backend, sin frameworks —
que se regenera cada vez que corre el pipeline localmente.

En evolución hacia un analizador universal de League of Legends, diseñado para adaptarse a cualquier jugador y analizar su rendimiento de forma personalizada.

## Qué hace exactamente

### 1. Ingesta de datos (Riot API)
- `download_matches.py` / `download_timelines.py` — descargan historial de
  partidas (match-v5) y sus timelines evento a evento vía la API oficial.
- `get_rank.py` — consulta league-v4 para tier, división, LP, récord y,
  en ligas apex (Master/GM/Challenger), posición exacta en el servidor.
- `database.py` — persiste todo en SQLite para consultas incrementales.

### 2. Procesamiento (`timeline_analyzer_v2.py`)
Reconstruye cada partida evento por evento sobre el timeline crudo:
- Métricas de laning corregidas al **minuto real** (oro/XP/CS @10 y @15).
- Clasificación de cada muerte: en trade vs. "gratis" (sin kill del equipo
  en los 12s siguientes), bajo torre, en solitario, enemigos implicados.
- CC aplicado real (`timeEnemySpentControlled`), no proxies indirectos.
- Detección de roams (separación del ADC excluyendo tiempo en base o
  muerto) y si convirtieron en kill/assist.
- Presencia real en objetivos épicos (distancia al evento en el momento
  de la kill, no "mi equipo lo tomó").
- Comparativa directa contra el support rival: KDA, vision score, CC.

### 3. Motor de reglas estadísticas (`report_v3.py`)
En vez de umbrales fijos:
- Calcula percentiles de cada métrica sobre los datos reales del jugador.
- Evalúa cada regla candidata con el **intervalo de confianza de Wilson
  (95%)** — si el intervalo se solapa con el winrate base, se descarta.
- Mina combinaciones de dos variables para detectar sinergias.
- Detecta patrones no evidentes a simple vista: sesgo de lado de mapa,
  franja horaria de mejor/peor rendimiento, perfil snowball vs. comeback,
  campeones que más eliminan al jugador, matchups de support rival.

### 4. Score de mérito (fórmula de League of Graphs)
Reproduce la fórmula pública de ranking por campeón (tier × winrate × KDA ×
volumen de partidas) para trackear la trayectoria real hacia el top,
en vez de mirar un número de ELO aislado.

## Stack técnico

| Capa | Tecnología |
|---|---|
| Procesamiento | Python 3 — `requests`, `sqlite3`, `csv`, estadística nativa (sin pandas/numpy) |
| Datos | Riot Games API — match-v5, league-v4, summoner-v4, account-v1 |
| Almacenamiento | SQLite + CSV intermedios |
| Frontend | HTML/CSS/JS vanilla, un solo archivo, sin build step |
| Gráficos | SVG dibujado a mano, sin librerías de charting |
| Estadística | Percentiles, intervalo de Wilson, correlación de Pearson, minería de reglas |

## Cómo correrlo

```powershell
python download_matches.py
python download_timelines.py
python database.py
python timeline_analyzer_v2.py
python get_rank.py
python report_v3.py
```

El último paso genera `data/analysis_v2/report_v3.html` — el panel final.

## Privacidad

Este repo **no incluye** la API key de Riot (`.env` está en `.gitignore`).
Las claves de desarrollo de Riot expiran cada 24h y se regeneran en
[developer.riotgames.com](https://developer.riotgames.com).

## Estado

Proyecto personal en desarrollo activo.
