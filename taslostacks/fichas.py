# -*- coding: utf-8 -*-
"""Datos de la ficha que salen de la tienda de cada juego y se piden SOLO al abrir la ficha (nunca en segundo plano).
Con caché en disco (por idioma). Si la tienda no da un dato, no se muestra. Única excepción: si Epic no tiene descripción, va la de Steam, aclarado en la ficha.
   Steam: logros del usuario, de los archivos de Steam (appcache/stats). Si no están, Web API con la clave (caché 6 h).
   Epic: página de la tienda por slug (store-content); solo vale si su namespace es el del catálogo local. Caché 30 días.
   Xbox: displaycatalog de Microsoft por ProductId (descripción, estudio, categorías, clasificación, puntuación). Caché 30 días."""
import os, re, json, time, struct, threading, unicodedata, urllib.parse
from . import paths
from .steam import http_json, steam_path, buscar_appid, ficha as steam_ficha

CARPETA = os.path.join(paths.CACHE, "fichas")
_lock = threading.Lock()
DIA = 86400

def _leer(nombre, vida):
    try:
        d = json.load(open(os.path.join(CARPETA, nombre), encoding="utf-8"))
        if time.time() - d.get("_ts", 0) < vida:
            return d
    except Exception:
        pass
    return None

def _guardar(nombre, d):
    d["_ts"] = time.time()
    try:
        with _lock:
            os.makedirs(os.path.dirname(os.path.join(CARPETA, nombre)), exist_ok=True)
            json.dump(d, open(os.path.join(CARPETA, nombre), "w", encoding="utf-8"), ensure_ascii=False)
    except Exception:
        pass
    return d

def _limpio(d):
    return {k: v for k, v in d.items() if not k.startswith("_") and v not in (None, "", [])}

# ---------- Steam: logros ----------
def _kv(b, i=0):
    """KeyValues binario de Steam -> dict."""
    d = {}
    while i < len(b):
        t = b[i]; i += 1
        if t in (8, 11):
            return d, i
        j = b.index(0, i); k = b[i:j].decode("utf-8", "ignore"); i = j + 1
        if t == 0: v, i = _kv(b, i)
        elif t == 1: j = b.index(0, i); v = b[i:j].decode("utf-8", "ignore"); i = j + 1
        elif t in (2, 4, 6): v = struct.unpack_from("<i", b, i)[0]; i += 4
        elif t == 3: v = struct.unpack_from("<f", b, i)[0]; i += 4
        elif t == 7: v = struct.unpack_from("<Q", b, i)[0]; i += 8
        else: raise ValueError("tipo %s" % t)
        d[k] = v
    return d, i

def _logros_locales(appid, steamid):
    """Steam guarda el esquema de logros y lo logrado (bits) en appcache/stats. {} si el juego no se abrió en esta PC."""
    base = os.path.join(steam_path(), "appcache", "stats")
    try:
        esq = _kv(open(os.path.join(base, "UserGameStatsSchema_%s.bin" % appid), "rb").read())[0]
        usr = _kv(open(os.path.join(base, "UserGameStats_%s_%s.bin" % (int(steamid) - 76561197960265728, appid)), "rb").read())[0]
    except Exception:
        return {}
    stats = (next(iter(esq.values()), {}) or {}).get("stats") or {}
    usr = usr.get("cache") or {}
    hechos = total = 0
    for sid, st in stats.items():
        if isinstance(st, dict) and str(st.get("type", "")).upper() == "ACHIEVEMENTS" and isinstance(st.get("bits"), dict):
            bits = (usr.get(sid) or {}).get("data", 0) & 0xFFFFFFFF
            total += len(st["bits"])
            hechos += sum(1 for k in st["bits"] if k.isdigit() and bits >> int(k) & 1)
    return {"logros": hechos, "logrosT": total} if total else {}

def steam_logros(appid, key, steamid):
    if not steamid or not appid:
        return {}
    d = _logros_locales(appid, steamid)
    if d or not key:
        return d
    nombre = "logros/%s.json" % appid
    d = _leer(nombre, 6 * 3600)
    if d is None:
        d = {}
        try:
            j = http_json("https://api.steampowered.com/ISteamUserStats/GetPlayerAchievements/v1/?" + urllib.parse.urlencode(
                {"key": key, "steamid": steamid, "appid": appid}), 15)
            ach = (j.get("playerstats") or {}).get("achievements") or []
            if ach:
                d = {"logros": sum(1 for a in ach if a.get("achieved")), "logrosT": len(ach)}
        except Exception as e:  # 400 = el juego no tiene logros o el perfil es privado: se recuerda igual
            if "400" not in str(e) and "403" not in str(e):
                paths.log("logros", appid, e); return {}
        _guardar(nombre, d)
    return _limpio(d)

# ---------- Epic ----------
EPIC_TAG = {"ACTION": "Acción", "ADVENTURE": "Aventura", "CO_OP": "Cooperativo", "MULTIPLAYER": "Multijugador", "SINGLE_PLAYER": "Un jugador",
            "SIMULATION": "Simulación", "STRATEGY": "Estrategia", "RPG": "Rol", "SHOOTER": "Shooter", "PUZZLE": "Puzle", "RACING": "Carreras",
            "SPORTS": "Deportes", "CASUAL": "Casual", "HORROR": "Terror", "INDIE": "Indie", "PLATFORMER": "Plataformas", "FIGHTING": "Lucha",
            "SURVIVAL": "Supervivencia", "OPEN_WORLD": "Mundo abierto", "EXPLORATION": "Exploración", "STEALTH": "Sigilo",
            "CITY_BUILDER": "Construcción", "CARD_GAME": "Cartas", "MMO": "MMO", "NARRATION": "Narrativo", "COMEDY": "Comedia",
            "FANTASY": "Fantasía", "PUZZLE_ADVENTURE": "Aventura de puzles", "TOWER_DEFENSE": "Defensa de torres", "ROGUE_LITE": "Roguelite",
            "TURN_BASED": "Por turnos", "RTS": "Estrategia en tiempo real", "BATTLE_ROYALE": "Battle royale", "MOBA": "MOBA"}

def _slug(t):
    t = unicodedata.normalize("NFKD", t).encode("ascii", "ignore").decode().lower().replace("&", "and")
    return re.sub(r"[^a-z0-9]+", "-", re.sub(r"['’:.!™®]", "", t)).strip("-")

def _texto(md, largo=500):
    """Markdown de la tienda -> texto plano corto (cortado en una oración si se puede)."""
    t = re.sub(r"!\[[^\]]*\]\([^)]*\)|<[^>]+>", " ", md)            # imágenes y HTML
    t = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", t)                  # links -> su texto
    t = re.sub(r"^\s*(#+|[=-]{3,}|[*-]\s)", " ", t, flags=re.M)     # títulos, subrayados, viñetas
    t = re.sub(r"\s+", " ", t.replace("*", "").replace("_", " ")).strip()
    if len(t) <= largo:
        return t
    corte = t.rfind(". ", 0, largo)
    return t[:corte + 1] if corte > largo // 3 else t[:largo].rsplit(" ", 1)[0] + "…"

def epic(g, idioma):
    ns, titulo = g.get("epic_ns"), g.get("name", "")
    if not ns or not titulo:
        return {}
    nombre = "%s/%s.json" % (idioma, g["id"])
    d = _leer(nombre, 30 * DIA)
    if d is None:
        d, slug = {}, _slug(titulo)
        loc = "en-US" if idioma == "english" else "es-ES"
        try:
            j = http_json("https://store-content-ipv4.ak.epicgames.com/api/%s/content/products/%s" % (loc, slug), 15)
            pag = next((p for p in j.get("pages") or [] if p.get("type") in ("productHome", "info")), None) or (j.get("pages") or [{}])[0]
            data = pag.get("data") or {}
            if j.get("namespace") == ns:  # otro producto con el mismo slug: no sirve
                about, meta = data.get("about") or {}, data.get("meta") or {}
                tags = meta.get("tags") or []
                rat = (j.get("productRatings") or {}).get("ratings") or []
                pegi = next((r.get("title") for r in rat if "ES" in str(r.get("countryCodes", "")).split(",")), "")
                d = {"desc": _texto(about.get("shortDescription") or about.get("description") or ""),  # algunos juegos traen solo la larga
                     "dev": about.get("developerAttribution") or ", ".join(meta.get("developer") or []),
                     "anio": (meta.get("releaseDate") or "")[:4],
                     "genres": [(EPIC_TAG.get(t) if idioma != "english" else None) or t.replace("_", " ").capitalize() for t in tags][:5],
                     "clasif": pegi, "url": "https://store.epicgames.com/%s/p/%s" % (loc, slug)}
        except Exception as e:  # 404 = la tienda vieja no tiene esa página (juegos nuevos): queda lo del catálogo local
            if "404" not in str(e):
                paths.log("ficha epic", titulo, e); return {}
        _guardar(nombre, d)
    d = _limpio(d)
    if not d.get("desc"):  # va aparte de "desc": la página aclara de dónde salió, y otra tienda de la misma tarjeta puede tener la suya
        appid = buscar_appid(titulo)
        if appid:
            d["descSteam"] = steam_ficha(appid, idioma).get("desc", "")
    return d

# ---------- Xbox / Microsoft Store ----------
XBOX_CAT = {"Action & adventure": "Acción y aventura", "Family & kids": "Familia", "Simulation": "Simulación", "Shooter": "Disparos",
            "Strategy": "Estrategia", "Racing & flying": "Carreras y vuelo", "Sports": "Deportes", "Role playing": "Rol",
            "Puzzle & trivia": "Puzles", "Platformer": "Plataformas", "Fighting": "Lucha", "Card + board": "Cartas y tablero",
            "Classics": "Clásicos", "Music": "Música", "Educational": "Educativos", "Other": "Otros",
            "Multi-Player Online Battle Arena": "MOBA"}

def xbox_producto(familia):
    """ProductId de la Microsoft Store para un paquete instalado (lo guarda también covers._xbox)."""
    from . import covers
    pid = covers._links.get("xboxid:" + familia)
    if pid:
        return pid
    j = http_json("https://displaycatalog.mp.microsoft.com/v7.0/products/lookup?" + urllib.parse.urlencode(
        {"alternateId": "PackageFamilyName", "value": familia, "market": "US", "languages": "en-us"}), 15)
    pid = next((p.get("ProductId") for p in j.get("Products", []) if p.get("ProductId")), "")
    if pid:
        covers._links["xboxid:" + familia] = pid; covers._guardar()
    return pid

def xbox(g, idioma):
    if not g.get("family"):
        return {}
    nombre = "%s/%s.json" % (idioma, g["id"])
    d = _leer(nombre, 30 * DIA)
    if d is None:
        d = {}
        try:
            pid = xbox_producto(g["family"])
            if pid:
                j = http_json("https://displaycatalog.mp.microsoft.com/v7.0/products?" + urllib.parse.urlencode(
                    {"bigIds": pid, "market": "US", "languages": "en-us" if idioma == "english" else "es-es,en-us"}), 15)
                p = (j.get("Products") or [{}])[0]
                lp, pr = (p.get("LocalizedProperties") or [{}])[0], p.get("Properties") or {}
                mp = (p.get("MarketProperties") or [{}])[0]
                rat = {r.get("RatingSystem"): r.get("RatingId", "") for r in mp.get("ContentRatings") or []}
                clasif = rat.get("PEGI") or rat.get("ESRB") or ""
                uso = next((u for u in mp.get("UsageData") or [] if u.get("AggregateTimeSpan") == "AllTime"), {})
                d = {"desc": re.sub(r"\s+", " ", lp.get("ShortDescription") or "").strip()[:500],
                     "dev": lp.get("DeveloperName") or lp.get("PublisherName") or "",
                     "anio": (mp.get("OriginalReleaseDate") or "")[:4],
                     "genres": [(XBOX_CAT.get(c) if idioma != "english" else None) or c for c in (pr.get("Categories") or [])][:5],
                     "clasif": clasif.replace(":", " ") if clasif else "",
                     "msRating": uso.get("AverageRating"), "msN": uso.get("RatingCount"),
                     "url": "https://apps.microsoft.com/detail/%s" % pid}
        except Exception as e:
            paths.log("ficha xbox", g.get("name"), e); return {}
        _guardar(nombre, d)
    return _limpio(d)

def de(g, cfg):
    """Lo que se agrega a la ficha de g al abrirla."""
    idioma = cfg.get("idioma", "spanish")
    if g.get("store") == "Steam":
        return steam_logros(g.get("appid"), cfg.get("steam_api_key"), cfg.get("steam_id"))
    if g.get("store") == "Epic":
        return epic(g, idioma)
    if g.get("store") == "Xbox":
        return xbox(g, idioma)
    return {}
