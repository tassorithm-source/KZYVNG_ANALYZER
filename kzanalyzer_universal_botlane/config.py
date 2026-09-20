# -*- coding: utf-8 -*-
"""
config.py — configuración central de KZYVNG Analyzer.

Todo lo que identifica TU cuenta vive en .env, no en el código.
Copia .env.example a .env y rellena tus datos antes de correr nada.

Este archivo no se importa solo — cada script hace:
    from config import *
o usa los valores individuales que necesite.
"""

import os
import sys
from dotenv import load_dotenv

load_dotenv()

# --- identidad de tu cuenta (obligatorio) ---------------------------------
RIOT_API_KEY = os.getenv("RIOT_API_KEY", "")
RIOT_GAME_NAME = os.getenv("RIOT_GAME_NAME", "")
RIOT_TAG_LINE = os.getenv("RIOT_TAG_LINE", "")

# --- routing regional (obligatorio, ver tabla en README) ------------------
# REGION es el "regional routing" para match-v5/account-v1: americas, europe, asia, sea
# PLATFORM es el "platform routing" para league-v4/summoner-v4: la1, la2, na1, euw1,
# eun1, kr, jp1, br1, oc1, tr1, ru, etc.
RIOT_REGION = os.getenv("RIOT_REGION", "americas")
RIOT_PLATFORM = os.getenv("RIOT_PLATFORM", "na1")

# --- campeón principal a analizar en el panel (opcional) -------------------
# Si lo dejas vacío, report_v3.py detecta automaticamente tu campeón mas
# jugado en las partidas descargadas y arma la sección de mérito con ese.
MAIN_CHAMPION = os.getenv("MAIN_CHAMPION", "").strip()

RIOT_ID = f"{RIOT_GAME_NAME}#{RIOT_TAG_LINE}" if RIOT_GAME_NAME and RIOT_TAG_LINE else ""


def require_identity():
    """Los scripts que hablan con la API llaman esto al arrancar."""
    faltan = [k for k, v in {
        "RIOT_API_KEY": RIOT_API_KEY,
        "RIOT_GAME_NAME": RIOT_GAME_NAME,
        "RIOT_TAG_LINE": RIOT_TAG_LINE,
    }.items() if not v]
    if faltan:
        print("ERROR: falta configurar en tu .env: " + ", ".join(faltan))
        print("Copia .env.example a .env y completa tus datos (ver README.md).")
        sys.exit(1)
