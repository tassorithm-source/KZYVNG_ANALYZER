import os
import json
import time
import requests
import config

API_KEY = config.RIOT_API_KEY
REGION = config.RIOT_REGION
MATCHES_DIR = "data/matches"
TIMELINES_DIR = "data/timelines"

os.makedirs(TIMELINES_DIR, exist_ok=True)
config.require_identity()

headers = {"X-Riot-Token": API_KEY}

match_files = [
    f for f in os.listdir(MATCHES_DIR)
    if f.endswith(".json")
]

print("=" * 70)
print("KZYVNG ANALYZER — TIMELINE DOWNLOADER")
print("=" * 70)
print(f"Match JSON encontrados: {len(match_files)}")

downloaded = 0
skipped = 0
errors = 0

def get_timeline(match_id):
    url = (
        f"https://{REGION}.api.riotgames.com/"
        f"lol/match/v5/matches/{match_id}/timeline"
    )
    for attempt in range(5):
        try:
            r = requests.get(url, headers=headers, timeout=30)
        except requests.RequestException as e:
            if attempt == 4:
                raise
            time.sleep(2)
            continue

        if r.status_code == 429:
            retry = r.headers.get("Retry-After")
            wait = int(retry) if retry and retry.isdigit() else 10
            print(f"  Rate limit; esperando {wait}s...")
            time.sleep(wait)
            continue

        if r.status_code == 404:
            return None

        r.raise_for_status()
        return r.json()

    return None

for i, filename in enumerate(sorted(match_files), 1):
    match_id = filename[:-5]
    out = os.path.join(TIMELINES_DIR, filename)

    if os.path.exists(out):
        skipped += 1
        continue

    print(f"[{i}/{len(match_files)}] {match_id}", end=" ")

    try:
        data = get_timeline(match_id)
        if data is None:
            print("404/NO DISPONIBLE")
            errors += 1
            continue

        with open(out, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)

        downloaded += 1
        print("OK")
        time.sleep(0.12)

    except Exception as e:
        errors += 1
        print(f"ERROR: {e}")

print()
print("=" * 70)
print("DESCARGA TERMINADA")
print("=" * 70)
print(f"Nuevos timelines : {downloaded}")
print(f"Ya existentes    : {skipped}")
print(f"Errores/no disp. : {errors}")
print(f"Carpeta          : {TIMELINES_DIR}")
