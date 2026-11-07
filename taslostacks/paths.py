# -*- coding: utf-8 -*-
"""Carpetas y configuración. Nada se guarda junto al programa: todo va a %LOCALAPPDATA%\\TasloStacks."""
import os, sys, json

APP = "TasloStacks"
DATA = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), APP)
CACHE = os.path.join(DATA, "cache")
CONFIG = os.path.join(os.environ.get("APPDATA", DATA), APP, "config.json")
NIVEL = os.path.join(os.path.dirname(CONFIG), "nivel.json")  # horas jugadas: junto a la config, sobrevive a desinstalar
HTML = os.path.join(DATA, "biblioteca.html")
LOG = os.path.join(DATA, "taslostacks.log")

# assets: dentro del .exe (PyInstaller) o en el repo
if getattr(sys, "frozen", False):
    ASSETS = os.path.join(sys._MEIPASS, "assets")
else:
    ASSETS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets")

# hasta la 1.1.2 la app se llamaba SantiStacks: se mudan sus carpetas (config, caché, visor) la primera vez
for _base in {os.environ.get("LOCALAPPDATA", ""), os.environ.get("APPDATA", "")} - {""}:
    _viejo, _nuevo = os.path.join(_base, "SantiStacks"), os.path.join(_base, APP)
    if os.path.isdir(_viejo) and not os.path.exists(_nuevo):
        try: os.rename(_viejo, _nuevo)
        except OSError: pass

for d in (DATA, CACHE, os.path.dirname(CONFIG)):
    os.makedirs(d, exist_ok=True)

DEFAULT = {
    "steam_api_key": "",      # https://steamcommunity.com/dev/apikey (opcional: sin clave solo se ven los juegos instalados de Steam)
    "steam_id": "",           # se detecta solo del último usuario que entró a Steam
    "launchers": {},          # {"Steam": {"exe": "..."}} para corregir una ruta a mano
    "cerrar_launchers": True, # al cerrar un juego, cerrar todos los launchers abiertos
    "idioma": "spanish",      # "spanish" o "english": idioma de la interfaz y de las fichas de Steam
    "tema": "claro",          # "claro" u "oscuro"
    "repo": "taslostacks/TasloStacks",  # usuario/repo de GitHub para avisar de versiones nuevas
    "desvinculadas": [],      # tiendas que el usuario sacó de TasloStacks (se pueden volver a vincular desde su tarjeta)
    "primer_arranque": True,
}

def cargar():
    cfg = dict(DEFAULT)
    try:
        with open(CONFIG, encoding="utf-8") as f:
            cfg.update(json.load(f))
    except Exception:
        pass
    cfg["repo"] = DEFAULT["repo"]  # siempre el oficial: configs viejas traían repos que ya no existen (SantiStacks, StacksSanti)
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
