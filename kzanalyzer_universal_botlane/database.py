import sqlite3
import json
import os

DB_PATH = "data/lol.db"
MATCHES_DIR = "data/matches"

# =========================================================
# COLAS QUE QUEREMOS ANALIZAR
# =========================================================

QUEUE_NAMES = {
    420: "SOLO_DUO",
    440: "FLEX_5V5",
}

# =========================================================
# CONEXIÓN
# =========================================================

conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()

# =========================================================
# RECREAR TABLAS
# =========================================================

cursor.execute("DROP TABLE IF EXISTS participants")
cursor.execute("DROP TABLE IF EXISTS matches")

cursor.execute("""
CREATE TABLE matches (
    match_id TEXT PRIMARY KEY,
    game_creation INTEGER,
    game_duration INTEGER,
    game_mode TEXT,
    game_version TEXT,
    queue_id INTEGER,
    queue_name TEXT
)
""")

cursor.execute("""
CREATE TABLE participants (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    match_id TEXT,
    puuid TEXT,
    riot_id TEXT,
    champion TEXT,
    team_position TEXT,
    individual_position TEXT,
    win INTEGER,
    kills INTEGER,
    deaths INTEGER,
    assists INTEGER,
    total_cs INTEGER,
    gold INTEGER,
    damage_to_champions INTEGER,
    damage_taken INTEGER,
    vision_score REAL,
    wards_placed INTEGER,
    wards_killed INTEGER,
    control_wards INTEGER,
    turret_kills INTEGER,
    inhibitor_kills INTEGER,
    first_blood INTEGER
)
""")

# =========================================================
# CONTADORES
# =========================================================

json_files = [
    f for f in os.listdir(MATCHES_DIR)
    if f.endswith(".json")
]

imported = 0
ignored = 0
errors = 0

queue_counter = {
    "SOLO_DUO": 0,
    "FLEX_5V5": 0,
}

# =========================================================
# PROCESAR PARTIDAS
# =========================================================

for filename in json_files:

    path = os.path.join(MATCHES_DIR, filename)

    try:

        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        metadata = data.get("metadata", {})
        info = data.get("info", {})

        match_id = metadata.get("matchId")
        queue_id = info.get("queueId")

        # -------------------------------------------------
        # FILTRO DE COLAS
        # -------------------------------------------------

        if queue_id not in QUEUE_NAMES:
            ignored += 1
            continue

        queue_name = QUEUE_NAMES[queue_id]

        # -------------------------------------------------
        # DATOS DE PARTIDA
        # -------------------------------------------------

        cursor.execute("""
        INSERT INTO matches (
            match_id,
            game_creation,
            game_duration,
            game_mode,
            game_version,
            queue_id,
            queue_name
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            match_id,
            info.get("gameCreation"),
            info.get("gameDuration"),
            info.get("gameMode"),
            info.get("gameVersion"),
            queue_id,
            queue_name
        ))

        # -------------------------------------------------
        # PARTICIPANTES
        # -------------------------------------------------

        for p in info.get("participants", []):

            challenges = p.get("challenges", {})

            riot_id = (
                p.get("riotIdGameName", "")
                + "#"
                + p.get("riotIdTagline", "")
            )

            cursor.execute("""
            INSERT INTO participants (
                match_id,
                puuid,
                riot_id,
                champion,
                team_position,
                individual_position,
                win,
                kills,
                deaths,
                assists,
                total_cs,
                gold,
                damage_to_champions,
                damage_taken,
                vision_score,
                wards_placed,
                wards_killed,
                control_wards,
                turret_kills,
                inhibitor_kills,
                first_blood
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (

                match_id,
                p.get("puuid"),
                riot_id,
                p.get("championName"),

                p.get("teamPosition"),
                p.get("individualPosition"),

                1 if p.get("win") else 0,

                p.get("kills", 0),
                p.get("deaths", 0),
                p.get("assists", 0),

                (
                    p.get("totalMinionsKilled", 0)
                    + p.get("neutralMinionsKilled", 0)
                ),

                p.get("goldEarned", 0),

                p.get("totalDamageDealtToChampions", 0),
                p.get("totalDamageTaken", 0),

                p.get("visionScore", 0),
                p.get("wardsPlaced", 0),
                p.get("wardsKilled", 0),
                p.get("detectorWardsPlaced", 0),

                p.get("turretKills", 0),
                p.get("inhibitorKills", 0),

                1 if p.get("firstBloodKill") else 0
            ))

        imported += 1
        queue_counter[queue_name] += 1

    except Exception as e:

        errors += 1

        print(
            f"ERROR en {filename}: {e}"
        )

conn.commit()

# =========================================================
# RESUMEN
# =========================================================

print()
print("=" * 70)
print("       KZYVNG ANALYZER — DATABASE IMPORT")
print("=" * 70)

print()
print(f"JSON encontrados : {len(json_files)}")
print(f"Partidas importadas : {imported}")
print(f"Partidas ignoradas  : {ignored}")
print(f"Errores             : {errors}")

print()
print("COLAS IMPORTADAS")
print("-" * 70)

print(
    f"SOLO/DÚO   : {queue_counter['SOLO_DUO']}"
)

print(
    f"FLEX 5v5   : {queue_counter['FLEX_5V5']}"
)

cursor.execute("SELECT COUNT(*) FROM participants")
participants_count = cursor.fetchone()[0]

print()
print(f"Participantes : {participants_count}")

print()
print(f"Base de datos: {DB_PATH}")

conn.close()