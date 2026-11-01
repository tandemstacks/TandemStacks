# -*- coding: utf-8 -*-
"""Portadas verticales (2:3) en %LOCALAPPDATA%\\SantiStacks\\covers. Fuentes, en orden:
   1) incluida en el programa (Riot, Battle.net), 2) Steam CDN por appid, 3) tienda Epic por slug."""
import os, io, re, json, shutil, urllib.request
from PIL import Image
from . import paths
from .steam import http

def _a23(raw, dest):
    im = Image.open(io.BytesIO(raw)).convert("RGB"); w, h = im.size
    if w / h > 2 / 3:
        nw = int(h * 2 / 3); im = im.crop(((w - nw) // 2, 0, (w - nw) // 2 + nw, h))
    else:
        nh = int(w * 1.5); im = im.crop((0, (h - nh) // 2, w, (h - nh) // 2 + nh))
    im.thumbnail((600, 900)); im.save(dest, "JPEG", quality=86)

def _steam(appid, dest):
    if not appid:
        return False
    for u in ("https://cdn.cloudflare.steamstatic.com/steam/apps/%s/library_600x900.jpg" % appid,
              "https://shared.cloudflare.steamstatic.com/store_item_assets/steam/apps/%s/library_600x900.jpg" % appid):
        try:
            _a23(http(u, 30), dest); return True
        except Exception:
            pass
    return False

def _epic(nombre, dest):
    slug = re.sub(r"[^a-z0-9]+", "-", nombre.lower().replace("™", "").replace("®", "")).strip("-")
    try:
        j = json.loads(http("https://store-content.ak.epicgames.com/api/en-US/content/products/" + slug, 20))
    except Exception:
        return False
    urls = []
    def walk(o):
        if isinstance(o, dict):
            for k, v in o.items():
                if k == "portraitBackgroundImageUrl" and isinstance(v, str): urls.insert(0, v)
                elif isinstance(v, str) and "-1200x1600-" in v: urls.append(v)
                else: walk(v)
        elif isinstance(o, list):
            for x in o: walk(x)
    walk(j)
    for u in urls:
        try:
            _a23(http(u, 60), dest); return True
        except Exception:
            pass
    return False

def asegurar(g):
    """Deja g["cover"] = 'covers/<id>.jpg' (ruta relativa al html) o ''. Devuelve True si bajó algo nuevo."""
    dest = os.path.join(paths.COVERS, g["id"] + ".jpg")
    rel = "covers/" + g["id"] + ".jpg"
    if os.path.exists(dest) and os.path.getsize(dest) > 1000:
        g["cover"] = rel; return False
    ok = False
    if g.get("cover_builtin"):
        src = os.path.join(paths.ASSETS, "covers", g["cover_builtin"])
        if os.path.exists(src):
            shutil.copy(src, dest); ok = True
    if not ok:
        ok = _steam(g.get("appid") or g.get("steam_hint"), dest)
    if not ok and g.get("store") == "Epic":
        ok = _epic(g["name"], dest)
    g["cover"] = rel if ok else ""
    return ok
