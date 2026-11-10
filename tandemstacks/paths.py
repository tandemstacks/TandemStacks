# -*- coding: utf-8 -*-
"""Carpetas y configuración. Nada se guarda junto al programa: todo va a %LOCALAPPDATA%\\TandemStacks."""
import os, sys, json

APP = "TandemStacks"
DATA = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), APP)
CACHE = os.path.join(DATA, "cache")
CONFIG = os.path.join(os.environ.get("APPDATA", DATA), APP, "config.json")
NIVEL = os.path.join(os.path.dirname(CONFIG), "nivel.json")  # horas jugadas: junto a la config, sobrevive a desinstalar
HTML = os.path.join(DATA, "biblioteca.html")
LOG = os.path.join(DATA, "tandemstacks.log")

# assets: dentro del .exe (PyInstaller) o en el repo
if getattr(sys, "frozen", False):
    ASSETS = os.path.join(sys._MEIPASS, "assets")
else:
    ASSETS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets")

# nombres anteriores: SantiStacks (hasta la 1.1.2) y TasloStacks (hasta la 1.3.6).
# La primera vez se mudan sus carpetas (config, nivel, caché, visor) a la nueva, así nadie pierde nada.
# Si ya hay una carpeta nueva sin la marca ".mudanza" (restos de alguna prueba), gana la vieja: tiene lo que se usó de verdad.
import shutil
for _base in {os.environ.get("LOCALAPPDATA", ""), os.environ.get("APPDATA", "")} - {""}:
    _nuevo = os.path.join(_base, APP)
    _marca = os.path.join(_nuevo, ".mudanza")
    for _nombre in ("TasloStacks", "SantiStacks"):
        _viejo = os.path.join(_base, _nombre)
        if not os.path.isdir(_viejo) or os.path.exists(_marca): continue
        try:
            if os.path.exists(_nuevo): shutil.rmtree(_nuevo)
            os.rename(_viejo, _nuevo)
        except OSError: pass
        break
    try:
        os.makedirs(_nuevo, exist_ok=True)
        if not os.path.exists(_marca): open(_marca, "w").close()
    except OSError: pass

for d in (DATA, CACHE, os.path.dirname(CONFIG)):
    os.makedirs(d, exist_ok=True)

DEFAULT = {
    "steam_api_key": "",      # https://steamcommunity.com/dev/apikey (opcional: sin clave solo se ven los juegos instalados de Steam)
    "steam_id": "",           # se detecta solo del último usuario que entró a Steam
    "launchers": {},          # {"Steam": {"exe": "..."}} para corregir una ruta a mano
    "cerrar_launchers": True, # al cerrar un juego, cerrar todos los launchers abiertos
    "cerrar_otros": True,     # al abrir un juego, cerrar los launchers que ese juego no usa
    "inicio_windows": True,   # abrir TandemStacks con Windows, minimizada
    "pulso": True,            # medir cada partida (FPS, tirones, placa, procesador, RAM, ping) y guardarla por juego
    "limpiar": True,          # al cerrar un juego, borrar la basura segura (volcados de errores, logs, caché web grande)
    "idioma": "spanish",      # "spanish" o "english": idioma de la interfaz y de las fichas de Steam
    "tema": "claro",          # "claro" u "oscuro"
    "repo": "tandemstacks/TandemStacks",  # usuario/repo de GitHub para avisar de versiones nuevas
    "desvinculadas": [],      # tiendas que el usuario sacó de TandemStacks (se pueden volver a vincular desde su tarjeta)
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
