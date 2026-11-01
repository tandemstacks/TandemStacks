# -*- coding: utf-8 -*-
"""Carpetas y configuración. Nada se guarda junto al programa: todo va a %LOCALAPPDATA%\\SantiStacks."""
import os, sys, json

APP = "SantiStacks"
DATA = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), APP)
COVERS = os.path.join(DATA, "covers")
CACHE = os.path.join(DATA, "cache")
CONFIG = os.path.join(os.environ.get("APPDATA", DATA), APP, "config.json")
HTML = os.path.join(DATA, "biblioteca.html")
LOG = os.path.join(DATA, "santistacks.log")

# assets: dentro del .exe (PyInstaller) o en el repo
if getattr(sys, "frozen", False):
    ASSETS = os.path.join(sys._MEIPASS, "assets")
else:
    ASSETS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets")

for d in (DATA, COVERS, CACHE, os.path.dirname(CONFIG)):
    os.makedirs(d, exist_ok=True)

DEFAULT = {
    "steam_api_key": "",      # https://steamcommunity.com/dev/apikey (opcional: sin clave solo se ven los juegos instalados de Steam)
    "steam_id": "",           # se detecta solo del último usuario que entró a Steam
    "launchers": {},          # {"Steam": {"exe": "..."}} para corregir una ruta a mano
    "cerrar_launchers": True, # al cerrar el juego, cerrar el launcher que se abrió para jugarlo
    "idioma": "spanish",
    "repo": "",               # usuario/repo de GitHub para avisar de versiones nuevas
    "primer_arranque": True,
}

def cargar():
    cfg = dict(DEFAULT)
    try:
        with open(CONFIG, encoding="utf-8") as f:
            cfg.update(json.load(f))
    except Exception:
        pass
    return cfg

def guardar(cfg):
    with open(CONFIG, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=1)

def log(*a):
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            import time
            f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + " ".join(str(x) for x in a) + "\n")
    except Exception:
        pass
