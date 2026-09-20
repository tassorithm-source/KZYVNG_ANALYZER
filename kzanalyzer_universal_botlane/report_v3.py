# -*- coding: utf-8 -*-
"""
KZYVNG ANALYZER - REPORT v3  (panel de ascenso)
Genera data/analysis_v2/report_v3.html a partir de los CSV de la v2.

Novedades frente a report_html.py:
  - Simulador del ranking de League of Graphs (formula real) con calculadora
    interactiva: cuanto te falta para ser el nº1 en tu campeón principal.
  - Panel objetivo vs actual con brecha por metrica.
  - "Leyes de tu cuenta": winrate real segun umbrales, calculado sobre tus
    propias partidas.
  - Reloj de muertes, presencia por tipo de objetivo, conversion de roams.
  - Tendencia de las ultimas 30 partidas frente al historico.

Uso:  python report_v3.py
Relanzalo cada vez que descargues partidas nuevas y el panel se actualiza.
"""

import csv
import json
import os
from collections import defaultdict, Counter
import config

SRC = "data/analysis_v2"
OUT = os.path.join(SRC, "report_v3.html")

rows = list(csv.DictReader(open(f"{SRC}/match_analysis_v2.csv", encoding="utf-8-sig")))
deaths = list(csv.DictReader(open(f"{SRC}/death_events_v2.csv", encoding="utf-8-sig")))
objs = list(csv.DictReader(open(f"{SRC}/objective_events_v2.csv", encoding="utf-8-sig")))
roams = list(csv.DictReader(open(f"{SRC}/roam_events_v2.csv", encoding="utf-8-sig")))

RANK_PATH = f"{SRC}/rank_snapshot.json"
rank_snapshot = None
if os.path.exists(RANK_PATH):
    try:
        rank_snapshot = json.load(open(RANK_PATH, encoding="utf-8"))
    except Exception:
        rank_snapshot = None

TIER_ORDER = ["IRON", "BRONZE", "SILVER", "GOLD", "PLATINUM", "EMERALD",
              "DIAMOND", "MASTER", "GRANDMASTER", "CHALLENGER"]
TIER_ES = {"IRON": "Hierro", "BRONZE": "Bronce", "SILVER": "Plata", "GOLD": "Oro",
           "PLATINUM": "Platino", "EMERALD": "Esmeralda", "DIAMOND": "Diamante",
           "MASTER": "Maestro", "GRANDMASTER": "Gran Maestro", "CHALLENGER": "Retador"}
DIV_ES = {"IV": "IV", "III": "III", "II": "II", "I": "I", None: ""}


def lp_hasta_siguiente_tier(tier, division, lp):
    """Estimacion estandar: 100 LP por division, 4 divisiones por tier (no apex)."""
    if tier in ("MASTER", "GRANDMASTER", "CHALLENGER") or tier is None:
        return None
    orden_div = ["IV", "III", "II", "I"]
    if division not in orden_div:
        return None
    faltan_en_tier = (len(orden_div) - 1 - orden_div.index(division)) * 100 + (100 - lp)
    return faltan_en_tier


def construir_rank_info(snapshot):
    if not snapshot:
        return None
    colas = snapshot.get("queues", {})
    salida = {}
    for q, info in colas.items():
        tier, division, lp = info.get("tier"), info.get("division"), info.get("lp") or 0
        wins, losses = info.get("wins") or 0, info.get("losses") or 0
        total = wins + losses
        item = {
            "queue": q,
            "tier": tier, "tier_es": TIER_ES.get(tier, tier),
            "division": division or "",
            "lp": lp, "wins": wins, "losses": losses,
            "wr": round(wins / total * 100, 1) if total else None,
            "hot_streak": bool(info.get("hot_streak")),
            "fresh_blood": bool(info.get("fresh_blood")),
            "veteran": bool(info.get("veteran")),
            "inactive": bool(info.get("inactive")),
            "lp_next": lp_hasta_siguiente_tier(tier, division, lp),
            "exact_rank": info.get("exact_rank"),
            "league_size": info.get("league_size"),
            "lp_to_first": info.get("lp_to_first"),
            "tier_index": TIER_ORDER.index(tier) if tier in TIER_ORDER else None,
        }
        ms = info.get("mini_series")
        if ms:
            item["promo"] = {"target": TIER_ES.get(ms.get("targetTier"), ms.get("targetTier")),
                              "progress": ms.get("progress")}
        salida[q] = item
    return salida


RANK_INFO = construir_rank_info(rank_snapshot)

rows.sort(key=lambda r: r["date"])


def n(r, k):
    try:
        return float(r.get(k, ""))
    except (TypeError, ValueError):
        return None


def avg(filas, k):
    v = [n(r, k) for r in filas if n(r, k) is not None]
    return sum(v) / len(v) if v else None


def wr(filas):
    return sum(int(r["win"]) for r in filas) / len(filas) * 100 if filas else 0


# --- campeón principal: el que pusiste en .env, o el más jugado ---
if config.MAIN_CHAMPION:
    MAIN_CHAMPION = config.MAIN_CHAMPION
else:
    _conteo = Counter(r["champion"] for r in rows)
    MAIN_CHAMPION = _conteo.most_common(1)[0][0] if _conteo else "—"

naut = [r for r in rows if r["champion"] == MAIN_CHAMPION]
ult30 = rows[-30:]

# ---------------------------------------------------------------
# TRAYECTORIA DE MERITO (formula de League of Graphs)
# Ya no es una calculadora manual: se calcula SOLO con tus datos
# reales (tier real de rank_snapshot.json si existe, WR y KDA de tus
# partidas con MAIN_CHAMPION) y se traza como serie historica para
# ver si vas subiendo o bajando, no como un numero suelto.
# ---------------------------------------------------------------
# Referencia aproximada de winrate/KDA "promedio" contra la que compara
# la formula. No es específica de un campeón — ajústala en tu .env si
# quieres más precisión (no hay endpoint público de Riot para esto).
AVG_WR_REF, AVG_KDA_REF = 50.5, 2.60
TIER_ORDER_LOG = ["IRON", "BRONZE", "SILVER", "GOLD", "PLATINUM", "EMERALD",
                  "DIAMOND", "MASTER", "GRANDMASTER", "CHALLENGER"]


def score_merito(tier_idx, winrate, kda, juegos_temporada, juegos_30d):
    base = (4 ** tier_idx) * (2 ** ((winrate - AVG_WR_REF) / 12)) * (1.33 ** (kda / AVG_KDA_REF - 1))
    pen50 = 0.75 ** max(0, 50 - juegos_temporada)
    pen5 = 0.5 ** max(0, 5 - juegos_30d)
    return base * pen50 * pen5


def tier_idx_actual(snapshot):
    if not snapshot:
        return 4  # asume Platino si no hay snapshot, punto de partida neutral
    solo = snapshot.get("queues", {}).get("RANKED_SOLO_5x5")
    if solo and solo.get("tier") in TIER_ORDER_LOG:
        return TIER_ORDER_LOG.index(solo["tier"])
    return 4


TIER_IDX_HOY = tier_idx_actual(rank_snapshot)

# serie historica: score de merito recalculado cada 5 partidas de tu campeón principal,
# usando SOLO datos disponibles hasta ese punto (asume tu tier actual como
# constante hacia atras, ya que no tenemos tu historial de tier por fecha)
MERITO_SERIE = []
if len(naut) >= 20:
    for i in range(20, len(naut) + 1, 5):
        ventana = naut[:i]
        wr_v = wr(ventana)
        kda_v = (sum(n(r, "kills") or 0 for r in ventana) + sum(n(r, "assists") or 0 for r in ventana)) / max(sum(n(r, "deaths") or 0 for r in ventana), 1)
        MERITO_SERIE.append(round(score_merito(TIER_IDX_HOY, wr_v, kda_v, len(ventana), min(len(ventana), 30)), 3))

NAUT_WR_HOY = round(wr(naut), 1) if naut else 0
NAUT_KDA_HOY = round((avg(naut, "kills") + avg(naut, "assists")) / max(avg(naut, "deaths") or 1, 0.01), 2) if naut else 0
SCORE_HOY = round(score_merito(TIER_IDX_HOY, NAUT_WR_HOY, NAUT_KDA_HOY, len(naut), min(len(naut), 30)), 3)
SCORE_HACE_20 = MERITO_SERIE[max(0, len(MERITO_SERIE) - 5)] if len(MERITO_SERIE) >= 5 else (MERITO_SERIE[0] if MERITO_SERIE else SCORE_HOY)
TENDENCIA_PCT = round((SCORE_HOY / SCORE_HACE_20 - 1) * 100, 1) if SCORE_HACE_20 else 0

# palanca mas barata para duplicar el score SIN subir de tier (referencia fija
# de la formula, no cambia partida a partida — se muestra como dato de contexto)
WR_PARA_DUPLICAR = 12
KDA_PARA_DUPLICAR = round(AVG_KDA_REF * 2 - NAUT_KDA_HOY, 2) if NAUT_KDA_HOY else None

# ---------------------------------------------------------------
# OBJETIVOS: derivados de tus propias partidas ganadoras, no inventados
# ---------------------------------------------------------------
# presencia en grubs (HORDE) aparte, porque es tu mayor agujero
obj_por_tipo = defaultdict(lambda: [0, 0])
for o in objs:
    if o["taken_by_us"] == "1":
        obj_por_tipo[o["type"]][0] += 1
        obj_por_tipo[o["type"]][1] += int(o["present"])
grub_pres = (obj_por_tipo["HORDE"][1] / obj_por_tipo["HORDE"][0] * 100) if obj_por_tipo["HORDE"][0] else 0

# ---------------------------------------------------------------
# MOTOR DE REGLAS — reemplaza las "leyes" fijas.
# Nada de umbrales inventados: cada corte sale de los percentiles de
# TUS propias partidas, y cada regla se valida con el intervalo de
# confianza de Wilson (95%). Si el intervalo inferior no supera tu
# winrate base, la regla no se muestra: es ruido, no consejo.
# ---------------------------------------------------------------
BASE_WR = round(wr(rows), 1)
BASE_WINS = sum(int(r["win"]) for r in rows)


def wilson(wins, total, z=1.96):
    if total == 0:
        return 0.0, 0.0
    p = wins / total
    denom = 1 + z * z / total
    centro = p + z * z / (2 * total)
    margen = z * ((p * (1 - p) / total + z * z / (4 * total * total)) ** 0.5)
    return (centro - margen) / denom, (centro + margen) / denom


def percentil(vals, p):
    if not vals:
        return None
    s = sorted(vals)
    k = (len(s) - 1) * p
    f, c = int(k), min(int(k) + 1, len(s) - 1)
    if f == c:
        return s[f]
    return s[f] * (c - k) + s[c] * (k - f)


# metrica -> (etiqueta, direccion "high"/"low", formato, categoria de agencia)
# categoria: "controlable" (depende solo de ti), "lider" (senal previa al
# resultado, parcialmente exogena), "dependiente" (depende de tu equipo,
# poca agencia real, se muestra pero no se recomienda como "consejo")
METRICAS_MINABLES = {
    "deaths": ("Muertes por partida", "low", "{:.1f}", "controlable"),
    "free_death_pct": ("% de muertes gratis", "low", "{:.0%}", "controlable"),
    "solo_deaths": ("Muertes en solitario", "low", "{:.1f}", "controlable"),
    "early_deaths": ("Muertes antes del min 14", "low", "{:.1f}", "controlable"),
    "cc_per_min": ("CC aplicado por minuto", "high", "{:.1f}s", "controlable"),
    "wards_per_min": ("Wards colocadas/min", "high", "{:.2f}", "controlable"),
    "control_per_min": ("Control wards/min", "high", "{:.2f}", "controlable"),
    "clears_per_min": ("Wards enemigas limpiadas/min", "high", "{:.2f}", "controlable"),
    "roam_conversion_pct": ("Roams convertidos", "high", "{:.0%}", "controlable"),
    "epic_presence_pct": ("Presencia en épicos", "high", "{:.0%}", "controlable"),
    "botlane_gold_diff_15": ("Oro de tu bot lane @15", "high", "{:+.0f}", "lider"),
    "kill_participation": ("Kill participation", "high", "{:.0%}", "dependiente"),
}
AGENCIA_TXT = {
    "controlable": "Depende solo de ti.",
    "lider": "Se mide antes de que la partida se decida: es tu mejor termómetro.",
    "dependiente": "Depende también de tus 4 aliados, tómalo como contexto, no como orden.",
}


def evaluar(cond, min_n=15):
    sub = [r for r in rows if cond(r)]
    total = len(sub)
    if total < min_n:
        return None
    wins = sum(int(r["win"]) for r in sub)
    lo, hi = wilson(wins, total)
    return {"n": total, "wr": round(wins / total * 100, 1),
            "lo": round(lo * 100, 1), "hi": round(hi * 100, 1)}


def mejor_regla_individual(key):
    label, direccion, fmt, agencia = METRICAS_MINABLES[key]
    vals = [n(r, key) for r in rows if n(r, key) is not None]
    if len(vals) < 30:
        return None
    candidatos = []
    for p in (0.33, 0.5):
        corte = percentil(vals, p if direccion == "low" else 1 - p)
        if corte is None:
            continue
        cond = (lambda r, k=key, c=corte: (n(r, k) is not None and n(r, k) <= c)) if direccion == "low" else \
               (lambda r, k=key, c=corte: (n(r, k) is not None and n(r, k) >= c))
        ev = evaluar(cond)
        if ev:
            candidatos.append((corte, ev))
    if not candidatos:
        return None
    # nos quedamos con el corte cuyo limite inferior del intervalo es mayor
    corte, ev = max(candidatos, key=lambda x: x[1]["lo"])
    if ev["lo"] <= BASE_WR:
        return None  # el intervalo se solapa con tu base: no es señal fiable
    signo = "≤" if direccion == "low" else "≥"
    return {
        "key": key, "label": label, "agencia": agencia, "corte": corte,
        "direccion": direccion,
        "cond_txt": f"{label} {signo} {fmt.format(corte)}",
        "cond": cond, **ev,
        "lift": round(ev["wr"] - BASE_WR, 1),
        "why": AGENCIA_TXT[agencia],
    }


REGLAS_SIMPLES = [r for r in (mejor_regla_individual(k) for k in METRICAS_MINABLES) if r]
REGLAS_SIMPLES.sort(key=lambda r: -r["lo"])

# Combos: solo entre reglas controlables/lider que ya mostraron senal propia,
# para no explotar el numero de comparaciones (evita p-hacking barato).
base_combo = [r for r in REGLAS_SIMPLES if r["agencia"] in ("controlable", "lider")][:5]
REGLAS_COMBO = []
for i in range(len(base_combo)):
    for j in range(i + 1, len(base_combo)):
        a, b = base_combo[i], base_combo[j]
        cond = lambda r, ca=a["cond"], cb=b["cond"]: ca(r) and cb(r)
        ev = evaluar(cond, min_n=12)
        if ev and ev["lo"] > max(a["lo"], b["lo"]):
            REGLAS_COMBO.append({
                "label": f'{a["cond_txt"]}  Y  {b["cond_txt"]}',
                "cond_txt": a["cond_txt"] + "  Y  " + b["cond_txt"],
                **ev, "lift": round(ev["wr"] - BASE_WR, 1),
            })
REGLAS_COMBO.sort(key=lambda r: -r["lo"])
REGLAS_COMBO = REGLAS_COMBO[:3]

# Fortalezas confirmadas: reglas donde tu MEDIA actual ya cae del lado bueno.
FORTALEZAS = []
for r in REGLAS_SIMPLES:
    media = avg(rows, r["key"])
    if media is None:
        continue
    ya_cumple = media <= r["corte"] if r["direccion"] == "low" else media >= r["corte"]
    if ya_cumple:
        FORTALEZAS.append(r)

# Metricas sin señal suficiente todavia (transparencia total, sin inventar)
SIN_SENAL = [METRICAS_MINABLES[k][0] for k in METRICAS_MINABLES
             if k not in {r["key"] for r in REGLAS_SIMPLES}]

for r in REGLAS_SIMPLES + REGLAS_COMBO:
    r.pop("cond", None)
    r.pop("corte", None)
    r.pop("direccion", None)

# ---------------------------------------------------------------
# COACH INSIGHTS — cosas que un jugador no ve mirando su propio
# historial partida por partida, pero que emergen al mirar las 280
# juntas: sesgos de lado de mapa, fatiga horaria, perfil de snowball,
# quien te elimina de verdad y contra que support rival peor te va.
# ---------------------------------------------------------------
COACH_INSIGHTS = []

# 1) Lado del mapa
lados = {}
for lado, nombre in (("blue", "azul"), ("red", "rojo")):
    ev = evaluar(lambda r, lado=lado: r.get("side") == lado, min_n=30)
    if ev:
        lados[nombre] = ev
if len(lados) == 2:
    (na, ea), (nb, eb) = sorted(lados.items(), key=lambda x: -x[1]["wr"])
    if ea["lo"] > eb["hi"] - 5:  # separacion real, no solo ruido
        COACH_INSIGHTS.append({
            "tag": "Lado del mapa", "fuerza": "alta" if ea["lo"] > eb["wr"] else "media",
            "texto": f"Del lado {na} ganas el {ea['wr']}% ({ea['n']} partidas) y del lado "
                     f"{nb} el {eb['wr']}% ({eb['n']}). El soporte de enganche depende del "
                     f"river y del pathing del jungla propio, que cambian de lado — vale la "
                     f"pena que revises tu posicionamiento de pre-15 cuando te toque {nb}."
        })

# 2) Franja horaria (fatiga / rendimiento por momento del dia)
def hora_de(r):
    try:
        return int(r["date"][11:13])
    except Exception:
        return None

FRANJAS = [(0, 6, "madrugada (00-06h)"), (6, 12, "mañana (06-12h)"),
           (12, 18, "tarde (12-18h)"), (18, 24, "noche (18-24h)")]
franja_res = {}
for a, b, nombre in FRANJAS:
    ev = evaluar(lambda r, a=a, b=b: (hora_de(r) is not None and a <= hora_de(r) < b), min_n=25)
    if ev:
        franja_res[nombre] = ev
if len(franja_res) >= 2:
    peor = min(franja_res.items(), key=lambda x: x[1]["wr"])
    mejor = max(franja_res.items(), key=lambda x: x[1]["wr"])
    if mejor[1]["lo"] > peor[1]["hi"] - 3 and mejor[0] != peor[0]:
        COACH_INSIGHTS.append({
            "tag": "Franja horaria", "fuerza": "alta" if mejor[1]["lo"] > peor[1]["wr"] else "media",
            "texto": f"Tu mejor franja es la {mejor[0]} ({mejor[1]['wr']}% en {mejor[1]['n']} "
                     f"partidas); tu peor es la {peor[0]} ({peor[1]['wr']}% en {peor[1]['n']}). "
                     f"Si puedes elegir cuándo rankear, evita la {peor[0]}."
        })

# 3) Perfil de snowball vs comeback (duracion de partida)
dur_res = {}
for a, b, nombre in ((0, 20, "cortas (<20 min)"), (20, 30, "medias (20-30 min)"), (30, 999, "largas (30+ min)")):
    ev = evaluar(lambda r, a=a, b=b: (n(r, "duration_min") is not None and a <= n(r, "duration_min") < b), min_n=25)
    if ev:
        dur_res[nombre] = ev
if len(dur_res) >= 2:
    mejor_d = max(dur_res.items(), key=lambda x: x[1]["wr"])
    peor_d = min(dur_res.items(), key=lambda x: x[1]["wr"])
    if mejor_d[0] != peor_d[0] and mejor_d[1]["lo"] > peor_d[1]["hi"] - 3:
        perfil = "snowballeas: cierras mejor cuando la partida es corta" if "cortas" in mejor_d[0] or "medias" in mejor_d[0] else "escalas: te va mejor cuanto más se alarga la partida"
        COACH_INSIGHTS.append({
            "tag": "Perfil de partida", "fuerza": "media",
            "texto": f"Ganas el {mejor_d[1]['wr']}% en partidas {mejor_d[0]} contra "
                     f"{peor_d[1]['wr']}% en {peor_d[0]}. Diagnóstico: {perfil}. "
                     f"Ajusta tu build/objetivo de partida a ese perfil en vez de jugar igual siempre."
        })

# 4) Quien te elimina de verdad (frecuencia de campeon asesino)
killer_count = Counter(d["killer_champion"] for d in deaths if d.get("killer_champion"))
total_muertes_con_dato = sum(killer_count.values())
if total_muertes_con_dato >= 40:
    top_killers = killer_count.most_common(3)
    txt = ", ".join(f"{champ} ({cnt}, {cnt/total_muertes_con_dato*100:.0f}%)" for champ, cnt in top_killers)
    COACH_INSIGHTS.append({
        "tag": "Quién te elimina", "fuerza": "media",
        "texto": f"Los campeones que más veces te matan en {total_muertes_con_dato} muertes "
                 f"registradas: {txt}. Si repites contra el mismo campeón, es un patrón de "
                 f"posicionamiento o de trade, no mala suerte — revisa el rango/gap-closer de esos tres."
    })

# 5) Peor matchup de support rival (con muestra minima, sin sobre-ajustar)
sup_por_champ = defaultdict(list)
for r in rows:
    ch = r.get("enemy_sup_champion")
    if ch:
        sup_por_champ[ch].append(r)
candidatos_sup = [(ch, f) for ch, f in sup_por_champ.items() if len(f) >= 8]
if candidatos_sup:
    peor_sup = min(candidatos_sup, key=lambda x: wr(x[1]))
    mejor_sup = max(candidatos_sup, key=lambda x: wr(x[1]))
    ch_p, f_p = peor_sup
    ch_m, f_m = mejor_sup
    if wr(f_p) < BASE_WR - 8 and ch_p != ch_m:
        COACH_INSIGHTS.append({
            "tag": "Matchup más difícil", "fuerza": "media" if len(f_p) >= 15 else "baja",
            "texto": f"Contra {ch_p} de soporte rival tu winrate cae a {wr(f_p):.0f}% en "
                     f"{len(f_p)} partidas (tu base es {BASE_WR}%). Contra {ch_m} en cambio "
                     f"subes a {wr(f_m):.0f}% en {len(f_m)}. Si ves a {ch_p} en el select "
                     f"enemigo, ese es tu partido para jugar más conservador en fase de línea."
        })

# 6) Comparativa agregada de visión y CC contra el support rival
mi_vis = avg(rows, "vision_score")
riv_vis = avg(rows, "enemy_sup_vision_score")
mi_cc = avg(rows, "cc_seconds_applied")
riv_cc = avg(rows, "enemy_sup_cc_seconds")
if mi_vis is not None and riv_vis is not None:
    diff_vis = mi_vis - riv_vis
    if abs(diff_vis) >= 8:
        COACH_INSIGHTS.append({
            "tag": "Vision vs rival", "fuerza": "media",
            "texto": (f"En vision score promedio vas {diff_vis:+.0f} puntos respecto al "
                      f"support rival ({mi_vis:.0f} vs {riv_vis:.0f}). "
                      + ("Buena señal: controlas el mapa mejor de lo que crees." if diff_vis > 0
                         else "Es la métrica más barata de arreglar: una ward de control extra por vuelta te iguala."))
        })

COACH_INSIGHTS = COACH_INSIGHTS[:6]

# ---------------------------------------------------------------
# Reloj de muertes
# ---------------------------------------------------------------
reloj = Counter()
for d in deaths:
    reloj[int(float(d["time_min"]) // 5 * 5)] += 1
reloj_json = [{"min": k, "n": reloj[k]} for k in sorted(reloj) if k <= 40]

fases = defaultdict(lambda: [0, 0])
for d in deaths:
    fases[d["phase"]][0] += 1
    fases[d["phase"]][1] += int(d["free_death"])
fases_json = [{"phase": p, "n": v[0], "free": round(v[1] / v[0] * 100, 1)}
              for p, v in [("early", fases["early"]), ("mid", fases["mid"]), ("late", fases["late"])]]

obj_json = [{"type": t, "n": v[0], "pres": round(v[1] / v[0] * 100, 1)}
            for t, v in sorted(obj_por_tipo.items(), key=lambda x: -x[1][0])]

# ---------------------------------------------------------------
# Tendencia — ahora cubre TODO tu historial desde la partida 1
# (ventana expansiva hasta llegar a W, luego ventana movil de W)
# ---------------------------------------------------------------
W = 20
serie_wr, serie_idx, fechas = [], [], []
for i in range(1, len(rows) + 1):
    v = rows[max(0, i - W):i]
    serie_wr.append(round(wr(v), 1))
    idx = [n(x, "performance_index") for x in v if n(x, "performance_index") is not None]
    serie_idx.append(round(sum(idx) / len(idx), 1) if idx else 50)
    fechas.append(v[-1]["date"][:10])

comparativa = []
for k, lab, fmt in [("deaths", "Muertes", "{:.2f}"), ("free_death_pct", "% gratis", "{:.0%}"),
                    ("epic_presence_pct", "Presencia epicos", "{:.0%}"),
                    ("cc_per_min", "CC/min", "{:.2f}"),
                    ("botlane_gold_diff_15", "Oro bot @15", "{:+.0f}"),
                    ("kill_participation", "KP", "{:.0%}")]:
    h, u = avg(rows, k), avg(ult30, k)
    if h is None or u is None:
        continue
    mejor = (u < h) if k in ("deaths", "free_death_pct") else (u > h)
    comparativa.append({"label": lab, "hist": fmt.format(h), "last": fmt.format(u),
                        "better": bool(mejor)})

# ---------------------------------------------------------------
# Historial reciente estilo op.gg: por partida, tu score 1-10
# (derivado del performance_index ya calculado), KDA, vision score
# real de Riot, y comparacion directa contra tu support rival — sin
# abundar, solo los numeros que importan lado a lado.
# ---------------------------------------------------------------
recent_games = []
for r in list(reversed(rows))[:12]:
    idx = n(r, "performance_index")
    score10 = round(idx / 10, 1) if idx is not None else None
    kda_txt = f'{int(n(r,"kills") or 0)}/{int(n(r,"deaths") or 0)}/{int(n(r,"assists") or 0)}'
    riv_k, riv_d, riv_a = n(r, "enemy_sup_kills"), n(r, "enemy_sup_deaths"), n(r, "enemy_sup_assists")
    riv_kda_txt = (f'{int(riv_k)}/{int(riv_d)}/{int(riv_a)}'
                   if None not in (riv_k, riv_d, riv_a) else None)
    mi_vis, riv_vis = n(r, "vision_score"), n(r, "enemy_sup_vision_score")
    recent_games.append({
        "date": r["date"][:10],
        "champion": r["champion"],
        "win": int(r["win"]),
        "kda": kda_txt,
        "score10": score10,
        "mvp": bool(idx is not None and idx >= 90),
        "vision": int(mi_vis) if mi_vis is not None else None,
        "riv_champion": r.get("enemy_sup_champion") or None,
        "riv_kda": riv_kda_txt,
        "riv_vision": int(riv_vis) if riv_vis is not None else None,
        "vision_better": (mi_vis is not None and riv_vis is not None and mi_vis > riv_vis),
    })

PAYLOAD = {
    "games": len(rows), "wr": BASE_WR,
    "riot_id": config.RIOT_ID or "tu cuenta",
    "main_champion": MAIN_CHAMPION,
    "naut_games": len(naut), "naut_wr": round(wr(naut), 1) if naut else 0,
    "naut_kda": (round((avg(naut, "kills") + avg(naut, "assists")) / max(avg(naut, "deaths") or 0.01, 0.01), 2)
                 if naut else 0),
    "first": rows[0]["date"][:10], "last": rows[-1]["date"][:10],
    "base_wr": BASE_WR,
    "reglas_simples": REGLAS_SIMPLES, "reglas_combo": REGLAS_COMBO,
    "fortalezas": FORTALEZAS, "sin_senal": SIN_SENAL,
    "coach_insights": COACH_INSIGHTS,
    "merito": {
        "score_hoy": SCORE_HOY, "score_hace_20": SCORE_HACE_20,
        "tendencia_pct": TENDENCIA_PCT, "serie": MERITO_SERIE,
        "tier_hoy": TIER_ORDER_LOG[TIER_IDX_HOY], "wr_hoy": NAUT_WR_HOY,
        "kda_hoy": NAUT_KDA_HOY, "wr_para_duplicar": WR_PARA_DUPLICAR,
        "kda_para_duplicar": KDA_PARA_DUPLICAR, "juegos": len(naut),
    },
    "reloj": reloj_json, "fases": fases_json, "objetivos": obj_json,
    "serie_wr": serie_wr, "serie_idx": serie_idx, "fechas": fechas,
    "comparativa": comparativa,
    "recent_games": recent_games,
    "roams_total": len(roams),
    "roams_conv": round(sum(int(x["converted"]) for x in roams) / len(roams) * 100, 1),
    "rank": RANK_INFO,
    "generated_at": int(__import__("time").time()),
}

HTML = """<!DOCTYPE html>
<html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>KZYVNG — Panel de ascenso</title>
<style>
:root{--bg:#0d0f14;--panel:#161a22;--panel2:#1d222c;--line:#272e3b;--fg:#e8ecf4;
--muted:#8a93a8;--acc:#4da3ff;--good:#3ecf8e;--warn:#ffc14d;--bad:#ff6b6b}
:root:not([data-theme="light"]){color-scheme:dark}
*{box-sizing:border-box}
body{margin:0;padding:26px 18px 70px;background:var(--bg);color:var(--fg);
font:15px/1.55 ui-sans-serif,system-ui,'Segoe UI',sans-serif}
.wrap{max-width:1000px;margin:0 auto}
h1{font-size:27px;margin:0 0 3px;letter-spacing:-.3px}
h2{font-size:16px;margin:36px 0 12px;color:var(--acc);text-transform:uppercase;
letter-spacing:.8px;border-bottom:1px solid var(--line);padding-bottom:8px}
.meta{color:var(--muted);font-size:13px;margin-bottom:20px}
.grid{display:grid;gap:12px}
.g4{grid-template-columns:repeat(auto-fit,minmax(170px,1fr))}
.g2{grid-template-columns:repeat(auto-fit,minmax(300px,1fr))}
.card{background:var(--panel);border:1px solid var(--line);border-radius:11px;padding:15px}
.lbl{color:var(--muted);font-size:11.5px;text-transform:uppercase;letter-spacing:.6px}
.val{font-size:26px;font-weight:650;margin:5px 0 2px}
.sub{color:var(--muted);font-size:12px}
table{width:100%;border-collapse:collapse;font-size:14px;background:var(--panel);
border:1px solid var(--line);border-radius:11px;overflow:hidden}
th,td{padding:9px 11px;text-align:left;border-bottom:1px solid var(--line)}
th{color:var(--muted);font-size:11.5px;text-transform:uppercase;letter-spacing:.5px}
tr:last-child td{border-bottom:none}
.good{color:var(--good)}.bad{color:var(--bad)}.warn{color:var(--warn)}
.track{height:10px;background:var(--panel2);border-radius:6px;overflow:hidden;margin-top:7px}
.fill{height:100%;border-radius:6px;background:var(--acc);transition:width .4s}
.fill.ok{background:var(--good)}.fill.mid{background:var(--warn)}.fill.low{background:var(--bad)}
.why{color:var(--muted);font-size:12.3px;margin-top:8px;line-height:1.45}
.row{display:flex;justify-content:space-between;align-items:baseline;gap:10px}
.now{font-size:21px;font-weight:650}
.tgt{color:var(--muted);font-size:13px}
input,select{background:var(--panel2);border:1px solid var(--line);color:var(--fg);
border-radius:8px;padding:8px 10px;font-size:14px;width:100%;font-family:inherit}
label{display:block;color:var(--muted);font-size:11.5px;text-transform:uppercase;
letter-spacing:.5px;margin-bottom:5px}
.f{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:12px}
.big{font-size:34px;font-weight:700;letter-spacing:-.5px}
.note{background:var(--panel);border-left:3px solid var(--acc);padding:12px 15px;
border-radius:0 9px 9px 0;color:var(--muted);font-size:13.3px;margin-top:13px}
.note b{color:var(--fg)}
svg.chart{width:100%;background:var(--panel);border:1px solid var(--line);border-radius:11px}
.grd{stroke:var(--line);stroke-width:1}.axs{fill:var(--muted);font-size:10px}
.l1{fill:none;stroke:var(--acc);stroke-width:2.2}
.l2{fill:none;stroke:var(--good);stroke-width:2;stroke-dasharray:5 4}
.bars rect{fill:var(--acc)}.bars rect.hot{fill:var(--bad)}
ol.plan{padding-left:20px;margin:0}
ol.plan li{margin-bottom:11px}
ol.plan b{color:var(--acc)}
.pill{display:inline-block;padding:2px 8px;border-radius:99px;font-size:11.5px;
background:var(--panel2);color:var(--muted);margin-left:6px}
@media(max-width:560px){.val{font-size:22px}.big{font-size:27px}}
</style></head><body><div class="wrap">
<h1 id="mainTitle">Panel de ascenso</h1>
<div class="meta" id="hdr"></div>

<h2>0 · Tu rango ahora (league-v4)</h2>
<div id="rankbox"></div>

<h2 id="h1title">1 · Tu trayectoria real hacia el nº1</h2>
<div class="note">League of Graphs rankea con la fórmula de mérito: <b>+1 tier multiplica tu
score ×4</b>; +12 puntos de winrate sobre la media del campeón, ×2; duplicar tu KDA, ×1.33.
Subir de tier vale más que cualquier racha de winrate — por eso esto ya no es una calculadora
para que juegues con hipótesis: es tu propio score, recalculado con tus partidas reales de
<b id="champTxt1">tu campeón principal</b> y tu tier actual, mostrado como <b>tendencia</b> para
que veas si te acercas o te alejas.</div>

<div class="card" style="margin-top:14px">
  <div class="grid g4">
    <div><div class="lbl">Tu score de mérito hoy</div><div class="big" id="mscore">—</div>
      <div class="sub" id="mtier"></div></div>
    <div><div class="lbl">Tendencia (últimas ~25 vs hace un tramo)</div>
      <div class="big" id="mtrend">—</div>
      <div class="sub">positivo = te acercas al nº1, negativo = te alejas</div></div>
    <div><div class="lbl">Para duplicar tu score sin subir de tier</div>
      <div class="val" id="mwr">—</div>
      <div class="sub" id="mkda"></div></div>
  </div>
  <div style="margin-top:14px" id="mchart"></div>
  <div class="why" id="mverdict"></div>
</div>

<h2>2 · Dónde estás hoy</h2>
<div class="grid g4" id="kpis"></div>

<h2>3 · Lo que no ves mirando partida por partida</h2>
<div class="sub" style="margin-bottom:10px">Patrones que solo aparecen al cruzar tus 280 partidas
entre sí — lado de mapa, horario, matchups y quién te elimina de verdad.</div>
<div id="coach"></div>

<h2>4 · El reloj de tus muertes</h2>
<div id="reloj"></div>
<div class="grid g2" style="margin-top:12px" id="fases"></div>

<h2>5 · Presencia en objetivos</h2>
<table><tr><th>Objetivo</th><th>Tomados por tu equipo</th><th>Estabas presente</th><th></th></tr>
<tbody id="objs"></tbody></table>

<h2>6 · Evolución y tus últimas partidas</h2>
<div id="trend"></div>
<div class="sub" style="margin-top:8px">— Winrate móvil (20 partidas) &nbsp;&nbsp; ---- Performance index &nbsp;&nbsp; · todo tu historial</div>
<table style="margin-top:14px"><tr><th>Métrica</th><th>Histórico</th><th>Últimas 30</th><th>Dirección</th></tr>
<tbody id="comp"></tbody></table>

<div class="sub" style="margin:18px 0 10px">Últimas 12 partidas, estilo resumen rápido — tu score
(sobre 10, calculado con tu propio percentil de rendimiento), KDA y visión, lado a lado con tu
support rival de esa partida.</div>
<div style="overflow-x:auto"><table>
<tr><th>Fecha</th><th>Campeón</th><th>Res.</th><th>KDA</th><th>Visión</th><th>Score</th><th>Rival</th></tr>
<tbody id="recent"></tbody></table></div>

<h2>7 · Tu manual de juego (basado en evidencia, no en opinión)</h2>
<div class="note">¿Hacer siempre lo mismo garantiza ganar? No — el League of Legends
depende de otras 9 personas que no controlas, así que ninguna métrica tuya puede ser
determinista. Lo que sí existe es <b>probabilidad condicional</b>: dado que cumples X,
¿qué tan seguido ganas? Cada regla de abajo pasó un filtro de Wilson al 95%: si el
intervalo de confianza de su winrate no supera claramente tu base (<b id="bwr2"></b>),
no aparece aquí — es ruido, no señal. Cuantas más partidas juegues, más se ajustan
estos números solos, sin que yo vuelva a tocar el código.</div>

<h3 style="margin:20px 0 10px;font-size:14.5px;color:var(--fg)">Palancas individuales con señal real</h3>
<div id="reglas_simples"></div>

<h3 style="margin:22px 0 10px;font-size:14.5px;color:var(--fg)">Combinaciones (cuando dos palancas juntas suman más que por separado)</h3>
<div id="reglas_combo"></div>

<h3 style="margin:22px 0 10px;font-size:14.5px;color:var(--fg)">Ya lo estás haciendo bien</h3>
<div class="sub" style="margin-bottom:10px">Tu promedio actual ya cae del lado ganador en estas métricas. Mantenlas, no las toques.</div>
<div id="fortalezas"></div>

<div class="note" id="sin_senal_box" style="margin-top:16px"></div>

<div class="note" style="margin-top:22px">Aviso honesto sobre estos números: parte de la
correlación entre muertes y derrotas es inversa — pierdes y por eso mueres, no solo al revés.
La métrica menos contaminada de la lista es el oro de tu bot lane en el minuto 15, porque se
mide antes de que la partida se decida. Trátala como tu indicador principal.</div>
</div>
<script>
const D = __PAYLOAD__;
const TIERS = ["Hierro","Bronce","Plata","Oro","Platino","Esmeralda","Diamante","Maestro","Gran Maestro","Retador"];
const $ = id => document.getElementById(id);

// --- cabecera
document.title = `${D.riot_id} — Panel de ascenso`;
$("mainTitle").textContent = `Panel de ascenso — ${D.riot_id}`;
$("h1title").textContent = `1 · Tu trayectoria real hacia el nº1 de ${D.main_champion}`;
$("champTxt1").textContent = D.main_champion;
$("hdr").textContent = `${D.games} partidas competitivas · ${D.first} → ${D.last} · ${D.main_champion}: ${D.naut_games} partidas, ${D.naut_wr}% WR`;

// --- rango real (league-v4)
(function(){
  if(!D.rank){
    $("rankbox").innerHTML = `<div class="note">Todavía no hay un <code>rank_snapshot.json</code>.
      Corre <b>python get_rank.py</b> en tu carpeta del proyecto (usa tu misma RIOT_API_KEY del .env)
      y vuelve a generar este panel — esta sección se rellena sola.</div>`;
    return;
  }
  const nombres = {RANKED_SOLO_5x5:"Solo/Dúo", RANKED_FLEX_SR:"Flex 5v5"};
  let html = '<div class="grid g2">';
  Object.values(D.rank).forEach(q=>{
    const div = q.division ? " "+q.division : "";
    let barra = "";
    if(q.lp_next!==null && q.lp_next!==undefined){
      const pctTier = 100 - Math.min(100, (q.lp_next/400)*100);
      barra = `<div class="track"><div class="fill mid" style="width:${pctTier.toFixed(0)}%"></div></div>
        <div class="why">${q.lp_next} LP hasta subir de tier (asumiendo 100 LP por división).</div>`;
    } else if(q.exact_rank){
      barra = `<div class="why">Puesto <b>#${q.exact_rank}</b> de ${q.league_size} en ${q.tier_es} de tu servidor.
        Te separan <b>${q.lp_to_first} LP</b> del #1.</div>`;
    }
    const streak = q.hot_streak ? '<span class="pill good">🔥 racha activa</span>' : '';
    html += `<div class="card">
      <div class="row"><b>${nombres[q.queue]||q.queue}</b>${streak}</div>
      <div class="big">${q.tier_es}${div}</div>
      <div class="row"><div class="now">${q.lp} LP</div>
        <div class="tgt">${q.wins}W ${q.losses}L · ${q.wr}% WR</div></div>
      ${barra}</div>`;
  });
  html += '</div>';
  $("rankbox").innerHTML = html;
})();

// --- KPIs
const kpi = (l,v,s) => `<div class="card"><div class="lbl">${l}</div><div class="val">${v}</div><div class="sub">${s}</div></div>`;
$("kpis").innerHTML =
  kpi("Winrate global", D.wr+"%", D.games+" partidas") +
  kpi(`Winrate ${D.main_champion}`, D.naut_wr+"%", D.naut_games+" partidas") +
  kpi(`KDA ${D.main_champion}`, D.naut_kda, "kills+asistencias / muertes") +
  kpi("Roams convertidos", D.roams_conv+"%", D.roams_total+" roams detectados");

// --- coach insights (lo que no ves partida por partida)
if(D.coach_insights && D.coach_insights.length){
  $("coach").innerHTML = D.coach_insights.map(c=>{
    const badgeCls = c.fuerza==="alta"?"good":(c.fuerza==="media"?"warn":"");
    return `<div class="card" style="margin-bottom:10px">
      <div class="row"><b>${c.tag}</b><span class="pill ${badgeCls}">señal ${c.fuerza}</span></div>
      <div class="why" style="margin-top:6px;font-size:13.8px">${c.texto}</div>
    </div>`;
  }).join("");
} else {
  $("coach").innerHTML = `<div class="note">Todavía no hay suficiente volumen para aislar
    patrones de lado de mapa, horario o matchups con confianza. Esta sección se llena sola
    a medida que subas más partidas.</div>`;
}

// --- leyes
// --- reloj de muertes
(function(){
  const d=D.reloj, W=920,H=210,pad=44;
  const max=Math.max(...d.map(x=>x.n));
  const bw=(W-pad-20)/d.length;
  let s=`<svg viewBox="0 0 ${W} ${H}" class="chart"><g class="bars">`;
  d.forEach((x,i)=>{
    const h=(x.n/max)*(H-52);
    const hot = x.min>=10 && x.min<25;
    s+=`<rect class="${hot?'hot':''}" x="${pad+i*bw+3}" y="${H-32-h}" width="${bw-6}" height="${h}" rx="3"/>`;
    s+=`<text class="axs" x="${pad+i*bw+bw/2}" y="${H-16}" text-anchor="middle">${x.min}</text>`;
    s+=`<text class="axs" x="${pad+i*bw+bw/2}" y="${H-38-h}" text-anchor="middle">${x.n}</text>`;
  });
  s+=`</g><text class="axs" x="8" y="20">muertes por franja de 5 min</text></svg>`;
  $("reloj").innerHTML=s;
})();

$("fases").innerHTML = D.fases.map(f=>{
  const nombre = {early:"Antes del min 14",mid:"Min 14 a 25",late:"Después del min 25"}[f.phase];
  return `<div class="card"><div class="lbl">${nombre}</div>
    <div class="val">${f.n} <span class="sub">muertes</span></div>
    <div class="row"><div class="sub">de las cuales gratis</div>
    <div class="${f.free>50?'bad':'warn'}"><b>${f.free}%</b></div></div>
    <div class="track"><div class="fill ${f.free>50?'low':'mid'}" style="width:${f.free}%"></div></div></div>`;
}).join("");

// --- objetivos
$("objs").innerHTML = D.objetivos.map(o=>{
  const nombres={HORDE:"Grubs / Horda del Vacío",DRAGON:"Dragón",RIFTHERALD:"Heraldo",BARON_NASHOR:"Barón",ATAKHAN:"Atakhan"};
  const c=o.pres>=50?"good":(o.pres>=25?"warn":"bad");
  return `<tr><td><b>${nombres[o.type]||o.type}</b></td><td>${o.n}</td>
    <td class="${c}"><b>${o.pres}%</b></td>
    <td><div class="track" style="margin:0"><div class="fill ${o.pres>=50?'ok':(o.pres>=25?'mid':'low')}" style="width:${o.pres}%"></div></div></td></tr>`;
}).join("");

// --- tendencia
(function(){
  const W=920,H=250,pad=44;
  const line=(arr,cls)=>{
    const st=(W-pad-16)/Math.max(arr.length-1,1);
    return `<polyline class="${cls}" points="${arr.map((v,i)=>`${pad+i*st},${H-30-(v/100)*(H-58)}`).join(" ")}"/>`;
  };
  let s=`<svg viewBox="0 0 ${W} ${H}" class="chart">`;
  for(let g=0;g<=100;g+=25){
    const y=H-30-(g/100)*(H-58);
    s+=`<line class="grd" x1="${pad}" y1="${y}" x2="${W-16}" y2="${y}"/><text class="axs" x="10" y="${y+4}">${g}</text>`;
  }
  s+=line(D.serie_wr,"l1")+line(D.serie_idx,"l2")+`</svg>`;
  $("trend").innerHTML=s;
})();

$("comp").innerHTML = D.comparativa.map(c=>
  `<tr><td>${c.label}</td><td>${c.hist}</td><td><b>${c.last}</b></td>
   <td class="${c.better?'good':'bad'}">${c.better?"mejorando":"empeorando"}</td></tr>`).join("");

// --- trayectoria de merito del campeon principal (automatica, sin inputs manuales)
(function(){
  const m = D.merito;
  $("mscore").textContent = m.score_hoy >= 1000 ? m.score_hoy.toExponential(1) : m.score_hoy.toFixed(2);
  $("mtier").textContent = `Tier ${m.tier_hoy} · ${m.wr_hoy}% WR · KDA ${m.kda_hoy} · ${m.juegos} partidas de ${D.main_champion}`;
  const tend = m.tendencia_pct;
  $("mtrend").textContent = (tend>0?"+":"") + tend + "%";
  $("mtrend").className = "big " + (tend>0?"good":(tend<0?"bad":""));
  $("mwr").textContent = `+${m.wr_para_duplicar} pts de winrate`;
  $("mkda").innerHTML = m.kda_para_duplicar ? `o KDA de ${m.kda_para_duplicar} (referencia fija de la fórmula, no cambia con tus partidas)` : "";

  if(m.serie && m.serie.length>=2){
    const W=920,H=200,pad=44, s=m.serie, mn=Math.min(...s), mx=Math.max(...s);
    const rango = (mx-mn)||1;
    const st=(W-pad-16)/(s.length-1);
    const pts = s.map((v,i)=>`${pad+i*st},${H-30-((v-mn)/rango)*(H-58)}`).join(" ");
    $("mchart").innerHTML = `<svg viewBox="0 0 ${W} ${H}" class="chart">
      <polyline class="l1" points="${pts}"/>
      <text class="axs" x="10" y="20">score de mérito, recalculado cada 5 partidas de ${D.main_champion}</text>
      </svg>`;
  } else {
    $("mchart").innerHTML = `<div class="note">Necesitas al menos 20 partidas de ${D.main_champion} para
      trazar una tendencia fiable. Ya tienes ${m.juegos} — sigue jugando y esta gráfica aparece sola.</div>`;
  }
  $("mverdict").innerHTML = tend > 3
    ? `Tu score de mérito está subiendo: en tu ventana más reciente rindes mejor que hace un
       tramo de partidas. Sigue así — esto es lo que te acerca al puesto 1 de verdad.`
    : (tend < -3
      ? `Tu score de mérito está bajando frente a un tramo anterior. No entres en pánico por una
         racha corta, pero sí revisa la sección 7 para ver qué palanca se te está escapando.`
      : `Tu score está estable. Para moverlo de verdad necesitas más volumen con ${D.main_champion} o una
         racha de winrate sostenida, no partidas sueltas.`);
})();

// --- historial reciente estilo op.gg
$("recent").innerHTML = (D.recent_games||[]).map(g=>{
  const resCls = g.win ? "good" : "bad";
  const resTxt = g.win ? "Victoria" : "Derrota";
  const scoreCls = g.score10>=8?"good":(g.score10>=5?"warn":"bad");
  const rival = g.riv_champion
    ? `${g.riv_champion} · ${g.riv_kda||"—"} · visión ${g.riv_vision??"—"}`
    : "—";
  return `<tr>
    <td>${g.date}</td>
    <td><b>${g.champion}</b></td>
    <td class="${resCls}">${resTxt}</td>
    <td>${g.kda}</td>
    <td>${g.vision??"—"}</td>
    <td class="${scoreCls}"><b>${g.score10??"—"}</b>${g.mvp?' <span class="pill good">MVP</span>':""}</td>
    <td class="sub">${rival}</td>
  </tr>`;
}).join("");

// --- manual de juego (data-driven, se recalcula cada corrida)
$("bwr2").textContent = D.base_wr + "%";

function reglaCard(r, destacada){
  const conf = r.n>=40 ? "Alta confianza" : "Confianza media";
  const confCls = r.n>=40 ? "good" : "warn";
  return `<div class="card" style="margin-bottom:10px;${destacada?"border-color:var(--good)":""}">
    <div class="row"><b>${r.cond_txt || r.label}</b>
      <span class="pill ${confCls}">${conf} · n=${r.n}</span></div>
    <div class="row" style="margin-top:6px">
      <div class="now good">${r.wr}%</div>
      <div class="tgt">winrate (base ${D.base_wr}%) · intervalo 95%: ${r.lo}–${r.hi}%</div>
    </div>
    <div class="track"><div class="fill ok" style="width:${Math.min(r.wr,100)}%"></div></div>
    ${r.why ? `<div class="why">${r.why}</div>` : ""}
  </div>`;
}

if(D.reglas_simples && D.reglas_simples.length){
  $("reglas_simples").innerHTML = D.reglas_simples.map((r,i)=>reglaCard(r, i===0)).join("");
} else {
  $("reglas_simples").innerHTML = `<div class="note">Todavía no hay suficientes partidas para
    aislar una palanca individual con confianza. Sigue jugando y esta sección se llena sola.</div>`;
}

if(D.reglas_combo && D.reglas_combo.length){
  $("reglas_combo").innerHTML = D.reglas_combo.map(r=>reglaCard(r,false)).join("");
} else {
  $("reglas_combo").innerHTML = `<div class="note">Ninguna combinación de dos palancas supera
    todavía a cada una por separado con suficiente confianza. No es un error: significa que no
    hay sinergia clara aún, no que no exista.</div>`;
}

if(D.fortalezas && D.fortalezas.length){
  $("fortalezas").innerHTML = D.fortalezas.map(r=>
    `<div class="card" style="margin-bottom:8px">
      <div class="row"><span>${r.cond_txt}</span>
      <span class="good"><b>${r.wr}%</b> <span class="pill">ya lo cumples</span></span></div>
    </div>`).join("");
} else {
  $("fortalezas").innerHTML = `<div class="note">Ninguna de tus medias actuales cae todavía del
    lado ganador de una regla con señal. Es información real, no un fallo del panel: apunta a que
    la consistencia, no picos puntuales, es lo que te falta.</div>`;
}

if(D.sin_senal && D.sin_senal.length){
  $("sin_senal_box").innerHTML = `<b>Sin señal suficiente todavía:</b> ${D.sin_senal.join(", ")}.
    No invento un consejo con esto — o la muestra es chica o el efecto no se distingue del azar
    en tus datos actuales. Vuelve a correr el panel cuando tengas más partidas.`;
} else {
  $("sin_senal_box").innerHTML = `Todas las métricas medidas ya muestran señal estadística en
    al menos un umbral. Buena señal de que la muestra ya es sólida.`;
}
</script></body></html>"""

HTML = HTML.replace("__PAYLOAD__", json.dumps(PAYLOAD, ensure_ascii=False))

open(OUT, "w", encoding="utf-8").write(HTML)
print(f"Creado: {OUT} ({len(HTML)//1024} KB)")
