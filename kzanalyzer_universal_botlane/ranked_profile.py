import sqlite3
import config

DB_PATH = "data/lol.db"

config.require_identity()
RIOT_ID = config.RIOT_ID

conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()

# =========================================================
# BUSCAR PUUID
# =========================================================

cursor.execute("""
    SELECT puuid
    FROM participants
    WHERE riot_id = ?
    LIMIT 1
""", (RIOT_ID,))

row = cursor.fetchone()

if not row:
    print(f"ERROR: No se encontró {RIOT_ID}.")
    conn.close()
    raise SystemExit()

puuid = row[0]


# =========================================================
# FUNCIÓN DE ANÁLISIS
# =========================================================

def analizar_cola(queue_name, titulo):

    print()
    print("=" * 70)
    print(titulo)
    print("=" * 70)

    # -----------------------------------------------------
    # TOTAL
    # -----------------------------------------------------

    cursor.execute("""
        SELECT
            COUNT(*),
            SUM(p.win),
            SUM(p.kills),
            SUM(p.deaths),
            SUM(p.assists)
        FROM participants p
        JOIN matches m
            ON p.match_id = m.match_id
        WHERE p.puuid = ?
          AND m.queue_name = ?
    """, (puuid, queue_name))

    total = cursor.fetchone()

    games, wins, kills, deaths, assists = total

    if not games:
        print("\nNo hay partidas de esta cola.")
        return

    losses = games - wins

    print()
    print("TOTAL")
    print("-" * 70)

    print(f"Partidas:    {games}")
    print(f"Victorias:   {wins}")
    print(f"Derrotas:    {losses}")
    print(f"Winrate:     {wins/games*100:.1f}%")
    print(f"KDA:         {kills}/{deaths}/{assists}")

    # -----------------------------------------------------
    # POSICIONES
    # -----------------------------------------------------

    cursor.execute("""
        SELECT
            p.team_position,
            p.individual_position,
            COUNT(*),
            SUM(p.win)
        FROM participants p
        JOIN matches m
            ON p.match_id = m.match_id
        WHERE p.puuid = ?
          AND m.queue_name = ?
        GROUP BY p.team_position, p.individual_position
        ORDER BY COUNT(*) DESC
    """, (puuid, queue_name))

    print()
    print("POSICIONES")
    print("-" * 70)

    for team_position, individual_position, count, wins in cursor.fetchall():

        team_position = team_position or "UNKNOWN"
        individual_position = individual_position or "UNKNOWN"

        print(
            f"{team_position:12} | "
            f"{individual_position:12} | "
            f"{count:3} partidas | "
            f"{wins}W / {count-wins}L | "
            f"{wins/count*100:.1f}% WR"
        )

    # -----------------------------------------------------
    # CAMPEONES
    # -----------------------------------------------------

    cursor.execute("""
        SELECT
            p.champion,
            COUNT(*),
            SUM(p.win),
            SUM(p.kills),
            SUM(p.deaths),
            SUM(p.assists)
        FROM participants p
        JOIN matches m
            ON p.match_id = m.match_id
        WHERE p.puuid = ?
          AND m.queue_name = ?
        GROUP BY p.champion
        ORDER BY COUNT(*) DESC
    """, (puuid, queue_name))

    print()
    print("CAMPEONES")
    print("-" * 70)

    for champion, count, wins, kills, deaths, assists in cursor.fetchall():

        print(
            f"{champion:20} | "
            f"{count:3} games | "
            f"{wins/count*100:5.1f}% WR | "
            f"{kills}/{deaths}/{assists}"
        )

    # -----------------------------------------------------
    # SUPPORT
    # -----------------------------------------------------

    cursor.execute("""
        SELECT
            COUNT(*),
            SUM(p.win),
            AVG(p.deaths),
            AVG(p.assists),
            AVG(p.vision_score),
            AVG(p.wards_placed),
            AVG(p.wards_killed),
            AVG(p.control_wards)
        FROM participants p
        JOIN matches m
            ON p.match_id = m.match_id
        WHERE p.puuid = ?
          AND m.queue_name = ?
          AND p.team_position = 'UTILITY'
    """, (puuid, queue_name))

    data = cursor.fetchone()

    (
        support_games,
        support_wins,
        avg_deaths,
        avg_assists,
        avg_vision,
        avg_wards,
        avg_wards_killed,
        avg_control
    ) = data

    print()
    print("UTILITY / SUPPORT")
    print("-" * 70)

    if support_games:

        print(f"Partidas:              {support_games}")
        print(
            f"Winrate:               "
            f"{support_wins/support_games*100:.1f}%"
        )
        print(f"Muertes por partida:   {avg_deaths:.2f}")
        print(f"Asistencias:           {avg_assists:.2f}")
        print(f"Vision Score:          {avg_vision:.2f}")
        print(f"Wards colocados:       {avg_wards:.2f}")
        print(f"Wards destruidos:      {avg_wards_killed:.2f}")
        print(f"Control Wards:         {avg_control:.2f}")

    else:
        print("No hay partidas de Support.")


# =========================================================
# PERFIL
# =========================================================

print("=" * 70)
print("       KZYVNG ANALYZER — RANKED PROFILE")
print("=" * 70)

analizar_cola(
    "SOLO_DUO",
    "SOLO / DÚO"
)

analizar_cola(
    "FLEX_5V5",
    "FLEX 5v5"
)

conn.close()

print()
print("=" * 70)
print("Análisis terminado.")
print("=" * 70)