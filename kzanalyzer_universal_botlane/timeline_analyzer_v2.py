# -*- coding: utf-8 -*-
"""
KZYVNG ANALYZER - TIMELINE ANALYZER v2
--------------------------------------
Sucesor de timeline_analyzer.py. Corrige los bugs de la v1 y anade
metricas de support de engage (Nautilus / Rakan / Rell).

Cambios clave frente a v1:
  1. gold/xp/cs @10 y @15 ahora usan minutos reales (v1 leia el segundo 10).
  2. Muertes con contexto real: enemigos implicados (victimDamageReceived),
     muerte bajo torre, muerte en trade vs muerte gratis, fase de partida.
  3. Roams: excluye tiempo muerto y tiempo en base, y mide si el roam
     convirtio en kill/assist.
  4. Vision: sin doble conteo de control wards, sin setas de Teemo.
  5. Objetivos: solo epicos, y mide PRESENCIA real (distancia al evento),
     no "mi equipo gano el objetivo" (eso era un proxy de la victoria).
  6. CC aplicado (timeEnemySpentControlled): la metrica que de verdad
     mide a un support de enganche.
  7. Normalizacion por percentiles + correlacion de cada metrica con la
     victoria, para saber cuales de tus scores predicen algo.
  8. Filtra remakes (< 5 min).
"""

import os
import json
import math
import csv
import sqlite3
import statistics as st
from datetime import datetime
from collections import defaultdict
import config

DB_PATH = "data/lol.db"
MATCHES_DIR = "data/matches"
TIMELINES_DIR = "data/timelines"
OUT_DIR = "data/analysis_v2"

config.require_identity()
SELF_RIOT_ID = config.RIOT_ID
MIN_DURATION_MIN = 5.0          # por debajo = remake
ROAM_DIST = 3500                # unidades de distancia al ADC
BASE_RADIUS = 2800              # radio de fuente/base
DEAD_WINDOW_S = 45              # margen tras morir (respawn + viaje)
OBJ_PRESENCE_DIST = 2500        # presencia en objetivo epico
TRADE_WINDOW_MS = 12000         # ventana para considerar muerte "en trade"

EPIC = {"DRAGON", "BARON_NASHOR", "RIFTHERALD", "HORDE", "ATAKHAN"}
SPAWN = {100: (500, 500), 200: (14350, 14350)}

os.makedirs(OUT_DIR, exist_ok=True)


# =========================================================
# Utilidades
# =========================================================

def clamp(x, lo=0, hi=100):
    return max(lo, min(hi, x))


def dist(a, b):
    if not a or not b:
        return None
    return math.hypot(a.get("x", 0) - b.get("x", 0), a.get("y", 0) - b.get("y", 0))


def frame_at_minute(frames, minute):
    """FIX v1: antes se multiplicaba por 1000 (segundos) en vez de 60000."""
    target = minute * 60 * 1000
    elegibles = [f for f in frames if f.get("timestamp", 0) <= target]
    if not elegibles:
        return None
    ultimo = elegibles[-1]
    # si la partida termino antes de ese minuto, no hay dato valido
    if ultimo.get("timestamp", 0) < target - 90000:
        return None
    return ultimo


def stats_at(frames, pid, minute):
    f = frame_at_minute(frames, minute)
    if not f or pid is None:
        return (None, None, None, None)
    pf = f.get("participantFrames", {}).get(str(pid))
    if not pf:
        return (None, None, None, None)
    cs = (pf.get("minionsKilled") or 0) + (pf.get("jungleMinionsKilled") or 0)
    return (pf.get("totalGold"), pf.get("xp"), cs, pf.get("level"))


def nearest_frame(frames, ts):
    return min(frames, key=lambda f: abs(f.get("timestamp", 0) - ts)) if frames else None


def pos_at(frames, pid, ts):
    f = nearest_frame(frames, ts)
    if not f:
        return None
    pf = f.get("participantFrames", {}).get(str(pid))
    return pf.get("position") if pf else None


def get_events(frames):
    ev = [e for f in frames for e in f.get("events", [])]
    ev.sort(key=lambda e: e.get("timestamp", 0))
    return ev


def pct_rank(valor, poblacion):
    """Percentil (0-100) de un valor dentro de su propia distribucion."""
    if not poblacion:
        return 50.0
    menores = sum(1 for x in poblacion if x < valor)
    iguales = sum(1 for x in poblacion if x == valor)
    return (menores + 0.5 * iguales) / len(poblacion) * 100


def corr(xs, ys):
    if len(xs) < 3:
        return float("nan")
    mx, my = st.mean(xs), st.mean(ys)
    num = sum((a - mx) * (b - my) for a, b in zip(xs, ys))
    den = (sum((a - mx) ** 2 for a in xs) * sum((b - my) ** 2 for b in ys)) ** 0.5
    return num / den if den else float("nan")


# =========================================================
# Bloques de analisis
# =========================================================

def ventanas_muerte(events, self_pid):
    """Intervalos [muerte, muerte+DEAD_WINDOW] en ms."""
    out = []
    for e in events:
        if e.get("type") == "CHAMPION_KILL" and e.get("victimId") == self_pid:
            t = e.get("timestamp", 0)
            out.append((t, t + DEAD_WINDOW_S * 1000))
    return out


def esta_muerto(ventanas, ts):
    return any(a <= ts <= b for a, b in ventanas)


def analizar_muertes(events, frames, self_pid, self_team, pid_team, duration_min, pid_champ=None):
    pid_champ = pid_champ or {}
    muertes = []
    kills_equipo = [
        e.get("timestamp", 0) for e in events
        if e.get("type") == "CHAMPION_KILL"
        and pid_team.get(e.get("killerId")) == self_team
    ]

    for e in events:
        if e.get("type") != "CHAMPION_KILL" or e.get("victimId") != self_pid:
            continue
        ts = e.get("timestamp", 0)
        recibido = e.get("victimDamageReceived", []) or []

        enemigos = {
            d.get("participantId") for d in recibido
            if d.get("participantId") and pid_team.get(d.get("participantId")) != self_team
        }
        torre = any(d.get("type") == "TOWER" for d in recibido)

        # aliados vivos cerca en el frame mas proximo
        f = nearest_frame(frames, ts)
        pf = f.get("participantFrames", {}) if f else {}
        mipos = (pf.get(str(self_pid)) or {}).get("position")
        aliados_cerca = 0
        for pid, team in pid_team.items():
            if pid == self_pid or team != self_team:
                continue
            p = (pf.get(str(pid)) or {}).get("position")
            d = dist(mipos, p)
            if d is not None and d <= 2200:
                aliados_cerca += 1

        trade = any(abs(k - ts) <= TRADE_WINDOW_MS for k in kills_equipo)

        min_ = ts / 60000
        fase = "early" if min_ < 14 else ("mid" if min_ < 25 else "late")

        muertes.append({
            "time_min": round(min_, 2),
            "phase": fase,
            "killer_id": e.get("killerId"),
            "killer_champion": pid_champ.get(e.get("killerId"), ""),
            "enemies_involved": len(enemigos),
            "died_to_turret": int(torre),
            "allies_within_2200": aliados_cerca,
            "solo_death": int(aliados_cerca == 0),
            "trade_death": int(trade),
            "free_death": int(not trade),
            "shutdown": e.get("shutdownBounty", 0),
        })
    return muertes


def analizar_vision(events, self_pid, duration_min):
    colocadas, control, limpiadas = 0, 0, 0
    por_fase = defaultdict(int)
    detalle = []
    for e in events:
        t = e.get("type")
        wt = e.get("wardType", "")
        if wt in ("TEEMO_MUSHROOM", "UNDEFINED"):
            continue
        if t == "WARD_PLACED" and e.get("creatorId") == self_pid:
            colocadas += 1
            if wt == "CONTROL_WARD":
                control += 1
            m = e["timestamp"] / 60000
            por_fase["early" if m < 14 else ("mid" if m < 25 else "late")] += 1
            detalle.append({"time_min": round(m, 2), "kind": "placed", "ward_type": wt})
        elif t == "WARD_KILL" and e.get("killerId") == self_pid:
            limpiadas += 1
            detalle.append({
                "time_min": round(e["timestamp"] / 60000, 2),
                "kind": "killed", "ward_type": wt
            })
    d = max(duration_min, 1)
    return {
        "wards_placed": colocadas,
        "control_wards": control,
        "wards_killed": limpiadas,
        "wards_per_min": round(colocadas / d, 3),
        "control_per_min": round(control / d, 3),
        "clears_per_min": round(limpiadas / d, 3),
        "wards_early": por_fase["early"],
        "wards_mid": por_fase["mid"],
        "wards_late": por_fase["late"],
    }, detalle


def analizar_objetivos(events, frames, self_pid, self_team, pid_team):
    """Solo epicos. Mide PRESENCIA real, no resultado del equipo."""
    filas = []
    for e in events:
        if e.get("type") != "ELITE_MONSTER_KILL":
            continue
        tipo = e.get("monsterType", "UNKNOWN")
        if tipo not in EPIC:
            continue
        ts = e.get("timestamp", 0)
        mipos = pos_at(frames, self_pid, ts)
        d = dist(mipos, e.get("position"))
        nuestro = int(e.get("killerTeamId") == self_team)
        filas.append({
            "time_min": round(ts / 60000, 2),
            "type": tipo,
            "subtype": e.get("monsterSubType", ""),
            "taken_by_us": nuestro,
            "my_distance": round(d) if d is not None else "",
            "present": int(d is not None and d <= OBJ_PRESENCE_DIST),
        })
    return filas


def analizar_roams(frames, events, self_pid, self_team, adc_pid):
    if not adc_pid:
        return []
    ventanas = ventanas_muerte(events, self_pid)
    spawn = SPAWN.get(self_team)
    kills_mios = [
        e.get("timestamp", 0) for e in events
        if e.get("type") == "CHAMPION_KILL"
        and (e.get("killerId") == self_pid or self_pid in (e.get("assistingParticipantIds") or []))
    ]

    candidatos = []
    for fr in frames:
        ts = fr.get("timestamp", 0)
        if ts < 5 * 60 * 1000:
            continue
        if esta_muerto(ventanas, ts):
            continue
        pf = fr.get("participantFrames", {})
        mipos = (pf.get(str(self_pid)) or {}).get("position")
        adcpos = (pf.get(str(adc_pid)) or {}).get("position")
        if not mipos or not adcpos:
            continue
        if spawn and dist(mipos, {"x": spawn[0], "y": spawn[1]}) < BASE_RADIUS:
            continue  # estaba en base, no es roam
        d = dist(mipos, adcpos)
        if d is not None and d > ROAM_DIST:
            candidatos.append((ts, d))

    episodios = []
    for ts, d in candidatos:
        if episodios and ts - episodios[-1]["_end_ms"] <= 61000:
            episodios[-1]["_end_ms"] = ts
            episodios[-1]["max_distance"] = max(episodios[-1]["max_distance"], round(d))
        else:
            episodios.append({"_start_ms": ts, "_end_ms": ts, "max_distance": round(d)})

    salida = []
    for i, ep in enumerate(episodios, 1):
        a, b = ep["_start_ms"], ep["_end_ms"] + 30000
        pago = sum(1 for k in kills_mios if a - 15000 <= k <= b)
        salida.append({
            "roam_id": i,
            "start_min": round(ep["_start_ms"] / 60000, 2),
            "end_min": round(ep["_end_ms"] / 60000, 2),
            "duration_min": round((ep["_end_ms"] - ep["_start_ms"]) / 60000 + 1, 2),
            "max_distance": ep["max_distance"],
            "kills_or_assists_in_window": pago,
            "converted": int(pago > 0),
        })
    return salida


# =========================================================
# Analisis de una partida
# =========================================================

def analizar_partida(match, timeline, self_puuid):
    info = match["info"]
    participantes = info.get("participants", [])
    yo = next((p for p in participantes if p.get("puuid") == self_puuid), None)
    if not yo:
        return None

    duration_min = info.get("gameDuration", 0) / 60
    if duration_min < MIN_DURATION_MIN:
        return None

    self_pid = yo.get("participantId")
    self_team = yo.get("teamId")
    enemy_team = 200 if self_team == 100 else 100
    pid_team = {p.get("participantId"): p.get("teamId") for p in participantes}

    def buscar(team, pos):
        return next(
            (p for p in participantes
             if p.get("teamId") == team
             and (p.get("teamPosition") == pos or p.get("individualPosition") == pos)),
            None
        )

    adc = buscar(self_team, "BOTTOM")
    e_adc = buscar(enemy_team, "BOTTOM")
    e_sup = buscar(enemy_team, "UTILITY")
    adc_pid = adc.get("participantId") if adc else None
    pid_champ = {p.get("participantId"): p.get("championName") for p in participantes}

    frames = timeline.get("info", {}).get("frames", [])
    events = get_events(frames)

    kills = deaths = assists = 0
    for e in events:
        if e.get("type") != "CHAMPION_KILL":
            continue
        if e.get("killerId") == self_pid:
            kills += 1
        if e.get("victimId") == self_pid:
            deaths += 1
        if self_pid in (e.get("assistingParticipantIds") or []):
            assists += 1

    kills_equipo = sum(
        1 for e in events
        if e.get("type") == "CHAMPION_KILL" and pid_team.get(e.get("killerId")) == self_team
    )
    kp = (kills + assists) / kills_equipo if kills_equipo else None

    # --- laning con minutos CORRECTOS ---
    lane = {}
    for m in (10, 15):
        g, x, c, lv = stats_at(frames, self_pid, m)
        ga, xa, ca, _ = stats_at(frames, adc_pid, m) if adc_pid else (None,) * 4
        ge, xe, ce, _ = stats_at(frames, e_adc.get("participantId"), m) if e_adc else (None,) * 4
        gs, xs_, _, _ = stats_at(frames, e_sup.get("participantId"), m) if e_sup else (None,) * 4
        lane[f"my_gold_{m}"] = g
        lane[f"my_xp_{m}"] = x
        lane[f"my_level_{m}"] = lv
        lane[f"adc_gold_{m}"] = ga
        lane[f"adc_cs_{m}"] = ca
        lane[f"enemy_adc_gold_{m}"] = ge
        lane[f"enemy_adc_cs_{m}"] = ce
        lane[f"botlane_gold_diff_{m}"] = (
            (g + ga) - (gs + ge) if None not in (g, ga, gs, ge) else None
        )
        lane[f"adc_gold_diff_{m}"] = ga - ge if None not in (ga, ge) else None
        lane[f"adc_cs_diff_{m}"] = ca - ce if None not in (ca, ce) else None
        lane[f"sup_gold_diff_{m}"] = g - gs if None not in (g, gs) else None

    # --- CC aplicado (clave para Nautilus/Rakan/Rell) ---
    cc_ms = 0
    if frames:
        pf = frames[-1].get("participantFrames", {}).get(str(self_pid), {})
        cc_ms = pf.get("timeEnemySpentControlled", 0) or 0
    cc_per_min = cc_ms / 1000 / max(duration_min, 1)

    muertes = analizar_muertes(events, frames, self_pid, self_team, pid_team, duration_min, pid_champ)
    vis, vis_detalle = analizar_vision(events, self_pid, duration_min)
    objs = analizar_objetivos(events, frames, self_pid, self_team, pid_team)
    roams = analizar_roams(frames, events, self_pid, self_team, adc_pid)

    epicos_nuestros = [o for o in objs if o["taken_by_us"]]
    presencia = (
        sum(o["present"] for o in epicos_nuestros) / len(epicos_nuestros)
        if epicos_nuestros else None
    )

    muertes_gratis = sum(m["free_death"] for m in muertes)
    muertes_solo = sum(m["solo_death"] for m in muertes)
    muertes_torre = sum(m["died_to_turret"] for m in muertes)
    muertes_early = sum(1 for m in muertes if m["phase"] == "early")
    roams_conv = sum(r["converted"] for r in roams)

    fila = {
        "match_id": match.get("metadata", {}).get("matchId"),
        "queue_name": "SOLO_DUO" if info.get("queueId") == 420 else "FLEX_5V5",
        "date": datetime.fromtimestamp(info.get("gameCreation", 0) / 1000).isoformat(),
        "duration_min": round(duration_min, 2),
        "champion": yo.get("championName"),
        "side": "blue" if self_team == 100 else "red",
        "win": int(bool(yo.get("win"))),
        "kills": kills, "deaths": deaths, "assists": assists,
        "team_kills": kills_equipo,
        "kill_participation": round(kp, 3) if kp is not None else None,
        "deaths_per_min": round(deaths / max(duration_min, 1), 3),
        "free_deaths": muertes_gratis,
        "free_death_pct": round(muertes_gratis / deaths, 3) if deaths else None,
        "solo_deaths": muertes_solo,
        "deaths_to_turret": muertes_torre,
        "early_deaths": muertes_early,
        "cc_seconds_applied": round(cc_ms / 1000, 1),
        "cc_per_min": round(cc_per_min, 2),
        "epic_objectives_team": len(epicos_nuestros),
        "epic_presence_pct": round(presencia, 3) if presencia is not None else None,
        "roams": len(roams),
        "roams_converted": roams_conv,
        "roam_conversion_pct": round(roams_conv / len(roams), 3) if roams else None,
        # --- riot vision score real (no confundir con wards/min) ---
        "vision_score": yo.get("visionScore"),
        "damage_to_champions": yo.get("totalDamageDealtToChampions"),
        "gold_earned": yo.get("goldEarned"),
        # --- comparativa directa contra tu support rival ---
        "enemy_sup_champion": e_sup.get("championName") if e_sup else "",
        "enemy_sup_kills": e_sup.get("kills") if e_sup else None,
        "enemy_sup_deaths": e_sup.get("deaths") if e_sup else None,
        "enemy_sup_assists": e_sup.get("assists") if e_sup else None,
        "enemy_sup_vision_score": e_sup.get("visionScore") if e_sup else None,
        "enemy_sup_cc_seconds": round((e_sup.get("timeCCingOthers") or 0), 1) if e_sup else None,
    }
    fila.update(vis)
    fila.update(lane)
    return fila, muertes, vis_detalle, objs, roams


# =========================================================
# EJECUCION
# =========================================================

conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()
cur.execute("SELECT puuid FROM participants WHERE riot_id = ? LIMIT 1", (SELF_RIOT_ID,))
row = cur.fetchone()
conn.close()
if not row:
    raise SystemExit(f"No se encontro el PUUID de {SELF_RIOT_ID} en la base.")
SELF_PUUID = row[0]

resumen, f_muertes, f_vision, f_objs, f_roams = [], [], [], [], []
descartadas = 0

for filename in sorted(f for f in os.listdir(MATCHES_DIR) if f.endswith(".json")):
    tl_path = os.path.join(TIMELINES_DIR, filename)
    if not os.path.exists(tl_path):
        continue
    try:
        with open(os.path.join(MATCHES_DIR, filename), encoding="utf-8") as f:
            match = json.load(f)
        if match.get("info", {}).get("queueId") not in (420, 440):
            continue
        with open(tl_path, encoding="utf-8") as f:
            timeline = json.load(f)

        res = analizar_partida(match, timeline, SELF_PUUID)
        if not res:
            descartadas += 1
            continue

        fila, muertes, vis, objs, roams = res
        mid = fila["match_id"]
        resumen.append(fila)
        for coleccion, destino in ((muertes, f_muertes), (vis, f_vision),
                                   (objs, f_objs), (roams, f_roams)):
            for x in coleccion:
                x["match_id"] = mid
                destino.append(x)
    except Exception as e:
        print(f"ERROR {filename}: {e}")


# ---------- Normalizacion por percentiles ----------
def columna(key):
    return [r[key] for r in resumen if r.get(key) is not None]


METRICAS = {
    # metrica            -> (peso, mayor_es_mejor)
    "kill_participation": (0.20, True),
    "cc_per_min":         (0.20, True),
    "free_death_pct":     (0.20, False),
    "wards_per_min":      (0.10, True),
    "control_per_min":    (0.10, True),
    "clears_per_min":     (0.05, True),
    "epic_presence_pct":  (0.10, True),
    "roam_conversion_pct": (0.05, True),
}

poblacion = {k: columna(k) for k in METRICAS}

for r in resumen:
    total, peso_total = 0.0, 0.0
    for k, (peso, mayor_mejor) in METRICAS.items():
        v = r.get(k)
        if v is None:
            continue
        p = pct_rank(v, poblacion[k])
        if not mayor_mejor:
            p = 100 - p
        r[f"pct_{k}"] = round(p, 1)
        total += p * peso
        peso_total += peso
    r["performance_index"] = round(total / peso_total, 1) if peso_total else None


# ---------- Escritura ----------
def write_csv(nombre, filas):
    if not filas:
        return
    claves = []
    for f in filas:
        for k in f:
            if k not in claves:
                claves.append(k)
    path = os.path.join(OUT_DIR, nombre)
    with open(path, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=claves)
        w.writeheader()
        w.writerows(filas)
    print(f"Creado: {path} ({len(filas)} filas)")


write_csv("match_analysis_v2.csv", resumen)
write_csv("death_events_v2.csv", f_muertes)
write_csv("vision_events_v2.csv", f_vision)
write_csv("objective_events_v2.csv", f_objs)
write_csv("roam_events_v2.csv", f_roams)


# ---------- Informe ----------
def bloque(titulo, filas):
    if not filas:
        return
    n = len(filas)
    wins = sum(r["win"] for r in filas)

    def prom(k):
        v = [r[k] for r in filas if r.get(k) is not None]
        return sum(v) / len(v) if v else None

    def linea(etiqueta, k, fmt="{:.2f}"):
        v = prom(k)
        print(f"  {etiqueta:34} " + (fmt.format(v) if v is not None else "sin datos"))

    print()
    print("=" * 70)
    print(titulo)
    print("=" * 70)
    print(f"  Partidas: {n}   Winrate: {wins/n*100:.1f}%")
    print("  --- Laning (minuto real) ---")
    linea("Oro bot lane vs bot rival @10", "botlane_gold_diff_10", "{:+.0f}")
    linea("Oro bot lane vs bot rival @15", "botlane_gold_diff_15", "{:+.0f}")
    linea("Diff CS de tu ADC @15", "adc_cs_diff_15", "{:+.1f}")
    print("  --- Impacto ---")
    linea("Kill participation", "kill_participation", "{:.1%}")
    linea("Segundos de CC por minuto", "cc_per_min")
    linea("Presencia en epicos de tu equipo", "epic_presence_pct", "{:.1%}")
    print("  --- Muertes ---")
    linea("Muertes por partida", "deaths", "{:.2f}")
    linea("% muertes gratis (sin trade)", "free_death_pct", "{:.1%}")
    linea("Muertes en solitario", "solo_deaths")
    linea("Muertes antes del min 14", "early_deaths")
    print("  --- Vision ---")
    linea("Wards/min", "wards_per_min")
    linea("Control wards/min", "control_per_min")
    linea("Wards enemigos limpiados/min", "clears_per_min")
    print("  --- Roams ---")
    linea("Roams por partida", "roams")
    linea("% roams convertidos en kill/assist", "roam_conversion_pct", "{:.1%}")
    print("  --- Indice ---")
    linea("Performance index (percentil propio)", "performance_index", "{:.1f}")


print()
print("=" * 70)
print("KZYVNG ANALYZER v2")
print("=" * 70)
print(f"Partidas analizadas: {len(resumen)}   Descartadas (remake/<5min): {descartadas}")

for q in ("SOLO_DUO", "FLEX_5V5"):
    bloque(q, [r for r in resumen if r["queue_name"] == q])

# Por campeon
print()
print("=" * 70)
print("POR CAMPEON (>= 10 partidas)")
print("=" * 70)
agrupado = defaultdict(list)
for r in resumen:
    agrupado[r["champion"]].append(r)
print(f"  {'Campeon':12} {'G':>4} {'WR':>7} {'KP':>7} {'CC/min':>7} "
      f"{'Muertes':>8} {'%gratis':>8} {'Index':>6}")
for ch, filas in sorted(agrupado.items(), key=lambda x: -len(x[1])):
    if len(filas) < 10:
        continue
    def pm(k):
        v = [r[k] for r in filas if r.get(k) is not None]
        return sum(v) / len(v) if v else 0
    print(f"  {ch:12} {len(filas):4} {sum(r['win'] for r in filas)/len(filas)*100:6.1f}% "
          f"{pm('kill_participation'):6.1%} {pm('cc_per_min'):7.2f} "
          f"{pm('deaths'):8.2f} {pm('free_death_pct'):7.1%} {pm('performance_index'):6.1f}")

# Validacion: ¿que metrica predice la victoria?
print()
print("=" * 70)
print("VALIDACION - correlacion de cada metrica con la victoria")
print("=" * 70)
wins = [r["win"] for r in resumen]
for k in list(METRICAS) + ["performance_index", "botlane_gold_diff_15", "deaths"]:
    pares = [(r[k], r["win"]) for r in resumen if r.get(k) is not None]
    if len(pares) < 20:
        continue
    r_ = corr([p[0] for p in pares], [p[1] for p in pares])
    fuerza = "fuerte" if abs(r_) >= .35 else ("moderada" if abs(r_) >= .2 else "debil")
    print(f"  {k:24} r = {r_:+.3f}  ({fuerza}, n={len(pares)})")

print()
print("Nota: 'performance_index' es un percentil DENTRO de tu propia muestra.")
print("No es MMR ni ELO: mide como de buena fue una partida para tus estandares.")
