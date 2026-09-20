# -*- coding: utf-8 -*-
"""
support_stats.py
Resumen rápido de consola: tus stats por campeón, por posición y tu perfil
de support agregado. Complementa a report_v3.py con un vistazo en texto
plano, sin abrir el navegador.

Usa tu identidad desde .env (ver config.py / README).
"""

import sqlite3
import config

DB_PATH = "data/lol.db"

config.require_identity()
RIOT_ID = config.RIOT_ID

conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()

cursor.execute("SELECT puuid FROM participants WHERE riot_id = ? LIMIT 1", (RIOT_ID,))
row = cursor.fetchone()
if not row:
    print(f"ERROR: No se encontró {RIOT_ID} en la base de datos.")
    print("¿Corriste download_matches.py y database.py primero?")
    conn.close()
    raise SystemExit(1)

puuid = row[0]

print("=" * 70)
print("             KZYVNG ANALYZER — SUPPORT PROFILE")
print("=" * 70)
print(f"Cuenta: {RIOT_ID}")

# --------------------------------------------------
# CAMPEONES (minimo 3 partidas)
# --------------------------------------------------
cursor.execute("""
    SELECT champion, COUNT(*), SUM(win),
           SUM(kills), SUM(deaths), SUM(assists),
           AVG(vision_score), AVG(wards_placed),
           AVG(wards_killed), AVG(control_wards),
           AVG(gold), AVG(damage_to_champions)
    FROM participants
    WHERE puuid = ?
    GROUP BY champion
    HAVING COUNT(*) >= 3
    ORDER BY COUNT(*) DESC
""", (puuid,))

print("\nCAMPEONES (mínimo 3 partidas)")
print("-" * 70)
print(f"{'Campeón':14}{'G':>5}{'WR':>8}{'KDA':>8}{'Visión':>9}{'CWards':>8}{'Daño':>9}")

for (champ, games, wins, k, d, a, vision, wards, wk, cw, gold, dmg) in cursor.fetchall():
    kda = (k + a) / d if d else (k + a)
    print(f"{champ:14}{games:5}{wins/games*100:7.1f}%{kda:8.2f}"
          f"{vision:9.1f}{cw:8.2f}{dmg:9.0f}")

# --------------------------------------------------
# POSICIONES (team_position / individual_position — no "role")
# --------------------------------------------------
cursor.execute("""
    SELECT COALESCE(NULLIF(team_position, ''), individual_position, 'UNKNOWN') AS pos,
           COUNT(*), SUM(win)
    FROM participants
    WHERE puuid = ?
    GROUP BY pos
    ORDER BY COUNT(*) DESC
""", (puuid,))

print("\n" + "=" * 70)
print("POSICIONES")
print("-" * 70)
for pos, games, wins in cursor.fetchall():
    print(f"{pos:15}{games:4} partidas | {wins:3}W | {games-wins:3}L | {wins/games*100:5.1f}% WR")

# --------------------------------------------------
# PERFIL SUPPORT (team_position = 'UTILITY')
# --------------------------------------------------
cursor.execute("""
    SELECT COUNT(*), SUM(win), AVG(deaths), AVG(assists),
           AVG(vision_score), AVG(wards_placed), AVG(wards_killed),
           AVG(control_wards), AVG(gold), AVG(damage_to_champions),
           AVG(damage_taken)
    FROM participants
    WHERE puuid = ? AND team_position = 'UTILITY'
""", (puuid,))

(games, wins, d, a, vision, wards, wk, cw, gold, dmg, taken) = cursor.fetchone()

print("\n" + "=" * 70)
print("PERFIL SUPPORT (UTILITY)")
print("-" * 70)
if games:
    print(f"Partidas:             {games}")
    print(f"Winrate:              {wins/games*100:.1f}%")
    print(f"Muertes por partida:  {d:.2f}")
    print(f"Asistencias:          {a:.2f}")
    print(f"Vision Score:         {vision:.2f}")
    print(f"Wards colocados:      {wards:.2f}")
    print(f"Wards destruidos:     {wk:.2f}")
    print(f"Control Wards:        {cw:.2f}")
    print(f"Oro:                  {gold:.0f}")
    print(f"Daño a campeones:     {dmg:.0f}")
    print(f"Daño recibido:        {taken:.0f}")
else:
    print("No hay partidas con team_position = 'UTILITY'.")
    print("Si juegas otro rol, revisa la tabla de POSICIONES de arriba.")

conn.close()
print("\nAnálisis terminado.")
