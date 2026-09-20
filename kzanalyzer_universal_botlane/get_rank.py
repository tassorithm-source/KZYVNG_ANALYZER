# -*- coding: utf-8 -*-
"""
get_rank.py
-----------
Descarga tu snapshot de ranked (league-v4) y, si estas en Master/GM/Challenger,
tu posicion REAL dentro de esa liga en tu servidor.

Endpoints usados (todos con X-Riot-Token, mismo patron que download_matches.py).
REGION y PLATFORM salen de tu .env (ver config.py y el README):
  1. account-v1   (regional routing)     -> puuid  [ya lo tienes, se reusa]
  2. summoner-v4  (platform routing)     -> encryptedSummonerId
  3. league-v4 by-puuid (platform routing) -> tier, division, LP, W/L, streak
  4. challengerleagues / grandmasterleagues / masterleagues (platform routing)
     -> si estas ahi, tu puesto exacto y cuanto LP te separa del #1

Guarda el resultado en data/analysis_v2/rank_snapshot.json.
report_v3.py lo lee automaticamente si existe.

Uso:  python get_rank.py
"""

import os
import json
import time
import requests
import config

API_KEY = config.RIOT_API_KEY
PLATFORM = config.RIOT_PLATFORM
REGION = config.RIOT_REGION
GAME_NAME, TAG_LINE = config.RIOT_GAME_NAME, config.RIOT_TAG_LINE
OUT_PATH = "data/analysis_v2/rank_snapshot.json"



headers = {"X-Riot-Token": API_KEY}


def get_json(url):
    r = requests.get(url, headers=headers, timeout=20)
    r.raise_for_status()
    time.sleep(1.2)  # margen conservador de rate limit
    return r.json()


def get_puuid():
    url = (f"https://{REGION}.api.riotgames.com/riot/account/v1/"
           f"accounts/by-riot-id/{GAME_NAME}/{TAG_LINE}")
    return get_json(url)["puuid"]


def get_summoner(puuid):
    url = f"https://{PLATFORM}.api.riotgames.com/lol/summoner/v4/summoners/by-puuid/{puuid}"
    return get_json(url)


def get_league_entries(puuid):
    url = f"https://{PLATFORM}.api.riotgames.com/lol/league/v4/entries/by-puuid/{puuid}"
    return get_json(url)


def get_apex_league(tier, queue="RANKED_SOLO_5x5"):
    slug = {"CHALLENGER": "challengerleagues", "GRANDMASTER": "grandmasterleagues",
            "MASTER": "masterleagues"}[tier]
    url = f"https://{PLATFORM}.api.riotgames.com/lol/league/v4/{slug}/by-queue/{queue}"
    return get_json(url)


def buscar_posicion(entries_liga, encrypted_summoner_id):
    ordenado = sorted(entries_liga["entries"], key=lambda e: -e["leaguePoints"])
    for i, e in enumerate(ordenado, 1):
        if e["summonerId"] == encrypted_summoner_id:
            return i, len(ordenado), ordenado[0]["leaguePoints"], e["leaguePoints"]
    return None


def main():
    config.require_identity()

    print("Obteniendo PUUID...")
    puuid = get_puuid()

    print("Obteniendo summonerId...")
    summ = get_summoner(puuid)
    encrypted_id = summ.get("id")

    print("Obteniendo entradas ranked (league-v4)...")
    entries = get_league_entries(puuid)

    snapshot = {"platform": PLATFORM, "fetched_at": int(time.time()), "queues": {}}

    for e in entries:
        q = e["queueType"]
        info = {
            "tier": e.get("tier"),
            "division": e.get("rank"),
            "lp": e.get("leaguePoints"),
            "wins": e.get("wins"),
            "losses": e.get("losses"),
            "hot_streak": e.get("hotStreak", False),
            "veteran": e.get("veteran", False),
            "fresh_blood": e.get("freshBlood", False),
            "inactive": e.get("inactive", False),
            "mini_series": e.get("miniSeriesDTO"),
        }
        # Posicion real si esta en apex
        if info["tier"] in ("CHALLENGER", "GRANDMASTER", "MASTER") and encrypted_id:
            print(f"  {q}: en {info['tier']}, calculando posicion exacta...")
            try:
                liga = get_apex_league(info["tier"], q)
                pos = buscar_posicion(liga, encrypted_id)
                if pos:
                    rank_num, total, top_lp, mi_lp = pos
                    info["exact_rank"] = rank_num
                    info["league_size"] = total
                    info["lp_to_first"] = top_lp - mi_lp
            except Exception as ex:
                print(f"  no se pudo calcular posicion exacta: {ex}")
        snapshot["queues"][q] = info
        print(f"  {q}: {info['tier']} {info['division'] or ''} {info['lp']} LP "
              f"({info['wins']}W {info['losses']}L)")

    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, ensure_ascii=False, indent=2)
    print(f"\nGuardado: {OUT_PATH}")
    print("Vuelve a correr report_v3.py para que el panel lo muestre.")


if __name__ == "__main__":
    main()
