# KZAnalyzer Universal - AI Bot Lane Synergy Coach

## Qué hace exactamente

### 1. Ingesta de datos (Riot API)
- `download_matches.py` / `download_timelines.py` — descargan tu historial
  de partidas (match-v5) y sus timelines evento a evento vía la API
  oficial de Riot.
- `get_rank.py` — consulta league-v4 para tier, división, LP, récord y, si
  estás en Master/GM/Challenger, tu posición exacta en tu servidor.
- `database.py` — persiste todo en SQLite para consultas incrementales.

### 2. Procesamiento (`timeline_analyzer_v2.py`)
Reconstruye cada partida evento por evento sobre el timeline crudo:
- Métricas de laning al **minuto real** (oro/XP/CS @10 y @15) — el bug
  más común en scripts caseros es leer el segundo 10 en vez del minuto 10.
- Clasificación de cada muerte: en trade vs. "gratis" (sin kill del
  equipo en los 12s siguientes), bajo torre, en solitario, campeón que
  te eliminó, enemigos implicados.
- CC aplicado real (`timeEnemySpentControlled`), no proxies indirectos.
- Detección de roams (separación del ADC excluyendo tiempo en base o
  muerto) y si convirtieron en kill/assist.
- Presencia real en objetivos épicos (distancia al evento en el momento
  de la kill, no "mi equipo lo tomó" — eso mide el resultado, no tu juego).
- Comparativa directa contra el jugador rival en posición support
  (`UTILITY`): KDA, vision score, CC. *(ver limitación de rol abajo)*

### 3. Motor de reglas estadísticas (`report_v3.py`)
En vez de umbrales fijos que alguien adivinó:
- Calcula percentiles de cada métrica sobre **tus** datos reales.
- Evalúa cada regla candidata con el **intervalo de confianza de Wilson
  (95%)** — si el intervalo se solapa con tu winrate base, la regla se
  descarta. No aparece un consejo a menos que haya evidencia real.
- Mina combinaciones de dos variables para detectar sinergias.
- Detecta patrones que no se ven partida por partida: sesgo de lado de
  mapa, franja horaria de mejor/peor rendimiento, perfil snowball vs.
  comeback, matchups más difíciles.

### 4. Score de mérito (fórmula de League of Graphs)
Reproduce la fórmula pública de ranking por campeón (tier × winrate ×
KDA × volumen de partidas) y la traza como **tendencia histórica**, para
ver si te acercas o te alejas del top — no un número de ELO aislado.

### 5. Panel (`report_v3.html`)
Un solo archivo HTML autocontenido — sin backend, sin build step, sin
frameworks. Se regenera cada vez que corres el pipeline y se abre con
doble clic en cualquier navegador.

## Stack técnico

| Capa | Tecnología |
|---|---|
| Procesamiento | Python 3 — `requests`, `sqlite3`, `csv`, estadística nativa |
| Datos | Riot Games API — match-v5, league-v4, summoner-v4, account-v1 |
| Almacenamiento | SQLite + CSV intermedios |
| Frontend | HTML/CSS/JS vanilla, un solo archivo |
| Gráficos | SVG dibujado a mano, sin librerías de charting |
| Estadística | Percentiles, intervalo de Wilson, correlación de Pearson |

## Cómo usarlo con tu propia cuenta

### 1. Clona el repo e instala dependencias

```bash
git clone https://github.com/TU_USUARIO/kzyvng-analyzer.git
cd kzyvng-analyzer
python -m venv .venv

# Windows
.venv\Scripts\activate
# Mac/Linux
source .venv/bin/activate

pip install -r requirements.txt
```

### 2. Consigue tu API key de Riot

1. Entra a [developer.riotgames.com](https://developer.riotgames.com) e
   inicia sesión con tu cuenta de Riot Games.
2. En el dashboard, copia tu **Development API Key**.

⚠️ **Las claves de desarrollo expiran cada 24 horas.** Tendrás que volver
ahí y regenerarla cada vez que la uses después de un día. Si quieres
automatizar esto a largo plazo sin regenerar la clave a mano, Riot ofrece
**Production API Keys** que no expiran, pero requieren solicitar
aprobación con un caso de uso — no es inmediato.

### 3. Configura tu `.env`

```bash
cp .env.example .env
```

Ábrelo y completa:
- `RIOT_API_KEY` — la que copiaste en el paso anterior.
- `RIOT_GAME_NAME` y `RIOT_TAG_LINE` — tu Riot ID (el de la barra de
  amigos: si es `Faker#KR1`, `RIOT_GAME_NAME=Faker`, `RIOT_TAG_LINE=KR1`).
- `RIOT_REGION` y `RIOT_PLATFORM` — según tu servidor. La tabla completa
  está dentro de `.env.example`.
- `MAIN_CHAMPION` — opcional. Déjalo vacío y el panel detecta
  automáticamente tu campeón más jugado.

### 4. Corre el pipeline completo

```bash
python download_matches.py
python download_timelines.py
python database.py
python timeline_analyzer_v2.py
python get_rank.py
python report_v3.py
```

Esto genera `data/analysis_v2/report_v3.html` — ábrelo con doble clic.

### 5. Actualízalo cuando quieras

Vuelve a correr los mismos seis comandos (o solo los últimos si no
descargaste partidas nuevas) y el panel se regenera con tus datos
actuales.

## Compartir tu panel con otros

`report_v3.html` es un archivo autocontenido, pero casi todo su contenido
se llena con JavaScript al cargar — si lo mandas por WhatsApp/Telegram
como **archivo**, el visor interno de esas apps no ejecuta scripts y se
ve vacío. La solución es subirlo a un hosting estático y compartir el
**link**, no el archivo:

- **[GitHub Pages](https://pages.github.com)** — gratis, el link no
  cambia entre actualizaciones (solo reemplazas el archivo).
- **[tiiny.host](https://tiiny.host)** — arrastra y suelta, más rápido
  para pruebas puntuales.

## Estructura del proyecto

```
├── config.py                  # config central (lee tu .env)
├── download_matches.py        # descarga historial de partidas
├── download_timelines.py      # descarga timelines evento a evento
├── database.py                # persiste todo en SQLite
├── timeline_analyzer_v2.py    # procesa timelines → CSV de análisis
├── get_rank.py                # snapshot de tier/división/LP (league-v4)
├── report_v3.py                # genera el panel HTML final
├── support_stats.py           # resumen rápido en consola (opcional)
├── ranked_profile.py           # resumen por cola en consola (opcional)
├── .env.example                # plantilla de configuración
└── requirements.txt
```

## Privacidad

- Tu `.env` (con tu API key) y toda tu carpeta `data/` (partidas,
  timelines, tu tier/LP) están en `.gitignore` — nunca se suben a Git.
- Nada de este repo llama a ningún servidor propio: todo el tráfico va
  directo de tu máquina a la API oficial de Riot.
- Si publicas tu `report_v3.html` en un hosting público, recuerda que
  muestra tu tier, LP y estadísticas — es tu decisión qué tan público lo
  hagas.

## Limitaciones conocidas

- **Calibrado originalmente para support.** El pipeline compara siempre
  contra el jugador en posición `UTILITY` del equipo rival ("tu support
  rival") y mide roams como distancia respecto al ADC propio. Si juegas
  otro rol, esas dos secciones específicas van a comparar contra un
  jugador que no es tu verdadero rival de línea — el resto de métricas
  (muertes, oro, visión, objetivos, CC, laning @10/@15) son genéricas y
  funcionan igual para cualquier posición. Adaptar esas dos secciones a
  tu propio rol es una mejora pendiente — PRs bienvenidos.
- El "score de mérito" reproduce la fórmula pública de League of Graphs,
  pero no tiene acceso a su leaderboard real — es un índice de tendencia
  propio, no tu posición exacta en su ranking (salvo que estés en
  Master+, donde `get_rank.py` sí puede calcular tu posición exacta en tu
  servidor vía la API oficial de Riot).
- Las reglas estadísticas necesitan volumen para aparecer (mínimo ~15-25
  partidas por condición). Con pocas partidas, varias secciones van a
  decir honestamente que todavía no hay señal suficiente — es preferible
  a inventar un consejo con una muestra de 3 partidas.

## Créditos

Construido y mantenido por **Kzyvng**. Si te sirve, dale una estrella al
repo. Pull requests y forks son bienvenidos.

Este proyecto no está afiliado a Riot Games. League of Legends es una
marca registrada de Riot Games, Inc.
