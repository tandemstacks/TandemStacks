# -*- coding: utf-8 -*-
"""Portadas por LINK: no se descarga ni se guarda ninguna imagen. La página las pide a la tienda cuando se ven
(y el visor las guarda en su propia caché). Orden:
   1) incluida en el programa (assets/covers: Riot y Battle.net, que no tienen links fijos) → file:///
   2) link que trae la propia tienda (catálogo de Epic, 1200x1600)
   3) Steam por appid o steam_hint (también para Rockstar, EA y Battle.net con equivalente en Steam)
   4) Xbox / Microsoft Store: se busca una vez por PackageFamilyName en displaycatalog y se guarda el link
Si un link falla, la página prueba la imagen horizontal de Steam y si no, muestra el nombre sobre color."""
import os, json, pathlib, threading, urllib.parse
from . import paths
from .steam import http_json

STEAM = "https://shared.cloudflare.steamstatic.com/store_item_assets/steam/apps/%s/library_600x900.jpg"
_CACHE = os.path.join(paths.CACHE, "portadas.json")  # solo links (texto), no imágenes
try:
    _links = json.load(open(_CACHE, encoding="utf-8"))
except Exception:
    _links = {}

_lock = threading.Lock()

def _guardar():
    try:
        with _lock:
            json.dump(dict(_links), open(_CACHE, "w", encoding="utf-8"), ensure_ascii=False)
    except Exception:
        pass

def rapida(g):
    """Link de portada sin usar la red. '' si todavía hace falta buscarla."""
    if g.get("cover_builtin"):
        f = os.path.join(paths.ASSETS, "covers", g["cover_builtin"])
        if os.path.exists(f):
            return pathlib.Path(f).as_uri()
    u = g.get("cover_url")
    if u:
        return u + ("?h=900&w=600&resize=1" if "epicgames.com" in u and "?" not in u else "")
    aid = g.get("appid") or g.get("steam_hint")
    if aid:
        return _links.get("steam:%s" % aid) or STEAM % aid
    return _links.get(g["id"], "")

STEAM_BASE = "https://shared.cloudflare.steamstatic.com/store_item_assets/"

def steam_exactas(appids):
    """Pide a Steam (IStoreBrowseService/GetItems, público, de a 100) el nombre exacto de la portada vertical
    de cada juego y guarda el link. Los juegos nuevos no usan library_600x900.jpg sino <hash>/library_capsule.jpg."""
    faltan = [str(a) for a in dict.fromkeys(appids) if a and "steam:%s" % a not in _links]
    for i in range(0, len(faltan), 100):
        lote = faltan[i:i + 100]
        req = {"ids": [{"appid": int(a)} for a in lote], "context": {"language": "english", "country_code": "US"},
               "data_request": {"include_assets": True}}
        try:
            j = http_json("https://api.steampowered.com/IStoreBrowseService/GetItems/v1?input_json=" + urllib.parse.quote(json.dumps(req)), 30)
        except Exception as e:
            paths.log("steam portadas", e); continue
        for it in (j.get("response") or {}).get("store_items", []):
            a = it.get("assets") or {}
            fmt, arch = a.get("asset_url_format", ""), a.get("library_capsule") or a.get("header")
            if fmt and arch:
                _links["steam:%s" % it.get("appid")] = STEAM_BASE + fmt.split("?")[0].replace("${FILENAME}", arch)
    _guardar()

def _xbox(familia):
    """Póster vertical de la Microsoft Store para un paquete instalado."""
    j = http_json("https://displaycatalog.mp.microsoft.com/v7.0/products/lookup?" + urllib.parse.urlencode(
        {"alternateId": "PackageFamilyName", "value": familia, "market": "US", "languages": "en-us"}), 20)
    for prod in j.get("Products", []):
        imgs = [i for lp in prod.get("LocalizedProperties", []) for i in lp.get("Images", [])]
        for tipo in ("Poster", "BoxArt"):
            i = next((x for x in imgs if x.get("ImagePurpose") == tipo), None)
            if i and i.get("Uri"):
                uri = i["Uri"]
                return ("https:" + uri if uri.startswith("//") else uri) + "?w=600"
    return ""

def asegurar(g):
    """Completa g["cover"] (puede usar la red para Xbox). Guarda solo el link."""
    url = rapida(g)
    if not url and g.get("store") == "Xbox" and g.get("family"):
        try:
            url = _xbox(g["family"])
        except Exception as e:
            paths.log("portada xbox", g.get("name"), e)
        if url:
            _links[g["id"]] = url; _guardar()
    g["cover"] = url
    return bool(url)

def limpiar_descargadas():
    """Las versiones anteriores bajaban cada portada a %LOCALAPPDATA%\\TasloStacks\\covers: se borran."""
    import shutil
    vieja = os.path.join(paths.DATA, "covers")
    if os.path.isdir(vieja):
        shutil.rmtree(vieja, ignore_errors=True)
