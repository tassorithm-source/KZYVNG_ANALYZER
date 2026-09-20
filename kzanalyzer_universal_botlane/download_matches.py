import os
import json
import time
import requests
import config

API_KEY = config.RIOT_API_KEY

PUUID = None

MATCH_DIR = "data/matches"
REGION = config.RIOT_REGION

# Cuántos IDs históricos queremos revisar
BATCH_SIZE = 100
MAX_BATCHES = 10

# Solo nos interesan estas colas
TARGET_QUEUES = {
    420: "SOLO_DUO",
    440: "FLEX_5V5",
}

os.makedirs(MATCH_DIR, exist_ok=True)

headers = {
    "X-Riot-Token": API_KEY
}


def get_puuid():
    """
    Obtiene el PUUID mediante Riot ID.
    """

    game_name = config.RIOT_GAME_NAME
    tag_line = config.RIOT_TAG_LINE

    url = (
        f"https://{REGION}.api.riotgames.com/"
        f"riot/account/v1/accounts/by-riot-id/"
        f"{game_name}/{tag_line}"
    )

    response = requests.get(
        url,
        headers=headers,
        timeout=20
    )

    response.raise_for_status()

    return response.json()["puuid"]


def get_match_ids(puuid, start):
    """
    Obtiene hasta 100 IDs de partidas empezando desde 'start'.
    """

    url = (
        f"https://{REGION}.api.riotgames.com/"
        f"lol/match/v5/matches/by-puuid/"
        f"{puuid}/ids"
    )

    params = {
        "start": start,
        "count": BATCH_SIZE
    }

    response = requests.get(
        url,
        headers=headers,
        params=params,
        timeout=20
    )

    if response.status_code == 429:
        print("Rate limit de Riot. Esperando 10 segundos...")
        time.sleep(10)
        return get_match_ids(puuid, start)

    response.raise_for_status()

    return response.json()


def get_match(match_id):
    """
    Descarga el JSON completo de una partida.
    """

    url = (
        f"https://{REGION}.api.riotgames.com/"
        f"lol/match/v5/matches/{match_id}"
    )

    response = requests.get(
        url,
        headers=headers,
        timeout=20
    )

    if response.status_code == 429:
        print("Rate limit de Riot. Esperando 10 segundos...")
        time.sleep(10)
        return get_match(match_id)

    response.raise_for_status()

    return response.json()


# =========================================================
# INICIO
# =========================================================

print("=" * 70)
print("       KZYVNG ANALYZER — HISTORICAL MATCH DOWNLOADER")
print("=" * 70)

config.require_identity()

print("\nObteniendo PUUID...")

try:
    PUUID = get_puuid()
except Exception as e:
    print(f"ERROR obteniendo PUUID: {e}")
    raise SystemExit()

print("PUUID obtenido correctamente.")

existing_files = set(
    f.replace(".json", "")
    for f in os.listdir(MATCH_DIR)
    if f.endswith(".json")
)

print(f"Partidas ya descargadas: {len(existing_files)}")

all_target_matches = {}

# =========================================================
# BUSCAR HISTORIAL
# =========================================================

for batch in range(MAX_BATCHES):

    start = batch * BATCH_SIZE

    print()
    print(
        f"Buscando historial: "
        f"start={start} count={BATCH_SIZE}"
    )

    try:
        match_ids = get_match_ids(PUUID, start)
    except Exception as e:
        print(f"ERROR obteniendo IDs: {e}")
        break

    if not match_ids:
        print("Riot no devolvió más partidas.")
        break

    print(f"IDs encontrados: {len(match_ids)}")

    new_ids = [
        match_id
        for match_id in match_ids
        if match_id not in existing_files
    ]

    print(f"IDs todavía no descargados: {len(new_ids)}")

    # -----------------------------------------------------
    # Descargar partidas nuevas
    # -----------------------------------------------------

    for i, match_id in enumerate(new_ids, 1):

        print(
            f"[{i}/{len(new_ids)}] "
            f"Descargando {match_id}...",
            end=" "
        )

        try:

            data = get_match(match_id)

            info = data.get("info", {})
            queue_id = info.get("queueId")

            # Solo guardamos las colas que nos interesan
            if queue_id in TARGET_QUEUES:

                path = os.path.join(
                    MATCH_DIR,
                    f"{match_id}.json"
                )

                with open(
                    path,
                    "w",
                    encoding="utf-8"
                ) as f:
                    json.dump(
                        data,
                        f,
                        ensure_ascii=False
                    )

                existing_files.add(match_id)

                all_target_matches[match_id] = queue_id

                print(
                    f"OK → {TARGET_QUEUES[queue_id]}"
                )

            else:
                print(
                    f"omitida → queue {queue_id}"
                )

        except Exception as e:

            print(f"ERROR → {e}")

        # Pequeña pausa para no golpear innecesariamente la API
        time.sleep(0.15)

    # -----------------------------------------------------
    # Comprobar cuántas partidas objetivo tenemos
    # -----------------------------------------------------

    solo = 0
    flex = 0

    for filename in os.listdir(MATCH_DIR):

        if not filename.endswith(".json"):
            continue

        try:

            with open(
                os.path.join(MATCH_DIR, filename),
                "r",
                encoding="utf-8"
            ) as f:
                data = json.load(f)

            queue_id = data.get("info", {}).get("queueId")

            if queue_id == 420:
                solo += 1

            elif queue_id == 440:
                flex += 1

        except Exception:
            pass

    print()
    print("PROGRESO")
    print("-" * 70)
    print(f"Solo/Dúo : {solo}")
    print(f"Flex 5v5 : {flex}")
    print(f"Total    : {solo + flex}")

    # Ya tenemos suficientes partidas competitivas
    if solo >= 100:
        print("\nObjetivo de 100 Solo/Dúo alcanzado.")
        break

    # Si llegamos al final del historial
    if len(match_ids) < BATCH_SIZE:
        print("\nNo hay más partidas disponibles.")
        break

print()
print("=" * 70)
print("DESCARGA TERMINADA")
print("=" * 70)

print("Los JSON existentes NO fueron borrados.")
print("Solo se añadieron partidas Solo/Dúo y Flex 5v5 nuevas.")