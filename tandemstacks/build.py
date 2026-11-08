# -*- coding: utf-8 -*-
"""Arma biblioteca.html (plantilla + datos embebidos) en %LOCALAPPDATA%\\TandemStacks. Las portadas son links (ver covers.py)."""
import os, io, json, base64, shutil
from . import paths

def discos(juegos):
    out = []
    letras = {g.get("drive") for g in juegos if g.get("installed") and g.get("drive")} | {"C:"}
    for letra in sorted(letras):
        try:
            u = shutil.disk_usage(letra + "\\")
        except Exception:
            continue
        jg = sorted([{"name": g["name"], "gb": g.get("sizeGB", 0)} for g in juegos if g.get("installed") and g.get("drive") == letra], key=lambda x: -x["gb"])
        out.append({"letra": letra, "totalGB": round(u.total / 1073741824), "usadoGB": round(u.used / 1073741824),
                    "libreGB": round(u.free / 1073741824), "juegosGB": round(sum(x["gb"] for x in jg), 1), "juegos": jg})
    return out

GEN_EN = {"Acción": "Action", "Aventura": "Adventure", "Estrategia": "Strategy", "Multijugador": "Multiplayer", "Cartas": "Card game",
          "Lucha": "Fighting", "Simuladores": "Simulation", "Deportes": "Sports", "Carreras": "Racing", "Rol": "RPG"}

def publico(g, idioma="spanish"):
    """Lo que ve la página (sin rutas ni comandos de lanzamiento), con los textos fijos en el idioma elegido."""
    keys = ("id", "name", "store", "appid", "cover", "installed", "sizeGB", "drive", "desc", "genres", "anio", "dev", "reqGB", "revPct", "revN", "horas", "ultima", "desconocido")
    d = {k: g[k] for k in keys if g.get(k) not in (None, "", [])}
    if idioma == "english":
        if g.get("desc_en"): d["desc"] = g["desc_en"]
        if d.get("genres"): d["genres"] = [GEN_EN.get(x, x) for x in d["genres"]]
    d["installed"] = bool(g.get("installed"))
    d["lanzable"] = bool(g.get("launch"))
    d["desinst"] = bool(g.get("uninstall"))
    return d

def escribir(juegos, tiendas, cfg, estado):
    tpl = io.open(os.path.join(paths.ASSETS, "template.html"), encoding="utf-8").read()
    try:
        logo = base64.b64encode(open(os.path.join(paths.ASSETS, "logo.png"), "rb").read()).decode()
    except Exception:
        logo = ""
    # solo lo que la página usa al arrancar (nada de cuentas ni rutas: el resto lo pide por la API)
    conf = {"repo": cfg.get("repo", ""), "primer_arranque": cfg.get("primer_arranque", True),
            "tema": cfg.get("tema", "claro"), "idioma": cfg.get("idioma", "spanish")}
    js = "window.JUEGOS=%s;window.DISCOS=%s;window.TIENDAS=%s;window.CONF=%s;window.ESTADO=%s;window.LOGO=%s;" % tuple(
        json.dumps(x, ensure_ascii=False) for x in ([publico(g, cfg.get("idioma", "spanish")) for g in juegos], discos(juegos), tiendas, conf, estado, logo))
    html = tpl.replace("/*DATA*/", js)
    tmp = paths.HTML + ".tmp"
    io.open(tmp, "w", encoding="utf-8").write(html)
    os.replace(tmp, paths.HTML)
    return paths.HTML
