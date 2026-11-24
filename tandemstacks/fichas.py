# -*- coding: utf-8 -*-
"""Datos de la ficha que salen de la tienda de cada juego y se piden SOLO al abrir la ficha (nunca en segundo plano).
Con caché en disco (por idioma). Si la tienda no da un dato, no se muestra. Única excepción: si Epic no tiene descripción, va la de Steam, aclarado en la ficha.
   Steam: logros del usuario, de los archivos de Steam (appcache/stats). Si no están, Web API con la clave (caché 6 h).
   Epic: página de la tienda por slug (store-content); solo vale si su namespace es el del catálogo local. Caché 30 días.
   Xbox: displaycatalog de Microsoft por ProductId (descripción, estudio, categorías, clasificación, puntuación). Caché 30 días."""
import os, re, html, json, time, struct, threading, unicodedata, urllib.parse, urllib.request
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
    if not g.get("family") and not g.get("xbox_pid"):
        return {}
    nombre = "%s/%s.json" % (idioma, g["id"])
    d = _leer(nombre, 30 * DIA)
    if d is None:
        d = {}
        try:
            pid = g.get("xbox_pid") or xbox_producto(g["family"])
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

# ---------- Google Play: página pública del juego ----------
GPLAY_CAT = {"ACTION": "Acción", "ADVENTURE": "Aventura", "ARCADE": "Arcade", "BOARD": "Tablero", "CARD": "Cartas", "CASINO": "Casino",
             "CASUAL": "Casual", "EDUCATIONAL": "Educativo", "MUSIC": "Música", "PUZZLE": "Puzles", "RACING": "Carreras", "ROLE_PLAYING": "Rol",
             "SIMULATION": "Simulación", "SPORTS": "Deportes", "STRATEGY": "Estrategia", "TRIVIA": "Preguntas", "WORD": "Palabras"}

def _pagina(url, idioma):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept-Language": "en-US" if idioma == "english" else "es-ES,es;q=0.9,en;q=0.5"})
    b = urllib.request.urlopen(req, timeout=15).read()
    try: return b.decode("utf-8")
    except UnicodeDecodeError: return b.decode("cp1252", "ignore")

def _meta(h, k):
    m = re.search(r'<meta[^>]+(?:property|name)="%s"[^>]+content="([^"]*)"' % k, h) or re.search(r'<meta[^>]+content="([^"]*)"[^>]+(?:property|name)="%s"' % k, h)
    return re.sub(r"\s+", " ", html.unescape(m.group(1))).strip() if m else ""

def google_play(g, idioma):
    if not g.get("pkg"): return {}
    nombre = "%s/%s.json" % (idioma, g["id"])
    d = _leer(nombre, 30 * DIA)
    if d is None:
        url = "https://play.google.com/store/apps/details?id=%s&hl=%s" % (urllib.parse.quote(g["pkg"]), "en" if idioma == "english" else "es_419")
        try:
            h = _pagina(url, idioma)
            m = re.search(r'<script type="application/ld\+json"[^>]*>(.*?)</script>', h, re.S)
            j = json.loads(m.group(1)) if m else {}
            cat = str(j.get("applicationCategory") or "").replace("GAME_", "")
            r = j.get("aggregateRating") or {}
            d = {"desc": (j.get("description") or _meta(h, "og:description"))[:500], "dev": (j.get("author") or {}).get("name", ""),
                 "genres": [(GPLAY_CAT.get(cat) if idioma != "english" else None) or cat.replace("_", " ").title()] if cat else [],
                 "clasif": j.get("contentRating") or "", "url": url.split("&hl=")[0]}
            if r.get("ratingValue"):
                d.update(nota=round(float(r["ratingValue"]), 1), notaDe="Google Play", notaN=int(r.get("ratingCount") or 0))
        except Exception as e:
            paths.log("ficha google play", g.get("name"), e); return {}
        _guardar(nombre, d)
    return _limpio(d)

# ---------- EA, Ubisoft y Rockstar: la página del juego en su tienda (el link sale del catálogo público de TandemStacks) ----------
def _norm(n):
    return re.sub(r"[^a-z0-9]", "", re.sub(r"[™®©]", "", (n or "").lower()))

# Palabras que solo cambian la edición: "Anno 1800 Deluxe Edition" es Anno 1800, pero "Far Cry" no es "Far Cry 3 Blood Dragon"
# (24/11/2026: antes bastaba con que un nombre empezara con el otro y la ficha podía traer otro juego)
EDICION = {"deluxe", "gold", "ultimate", "edition", "standard", "complete", "definitive", "goty", "game", "of", "the", "year",
           "premium", "special", "collectors", "collector", "digital", "pc", "bundle", "pack", "anniversary"}

def _palabras(n):
    return re.findall(r"[a-z0-9]+", re.sub(r"[™®©']", "", (n or "").lower()))

def _misma_edicion(a, b):
    """¿Son el mismo juego, salvo palabras de edición al final?"""
    pa, pb = _palabras(a), _palabras(b)
    if not pa or not pb: return False
    corto, largo = (pa, pb) if len(pa) <= len(pb) else (pb, pa)
    return largo[:len(corto)] == corto and all(x in EDICION for x in largo[len(corto):])

def _url_tienda(g):
    """Link de la página del juego en su tienda, buscado por nombre en el catálogo (se lee una vez por juego y se guarda)."""
    from . import steam
    cache = os.path.join(paths.CACHE, "catalogo_todos.json")
    try:
        if time.time() - os.path.getmtime(cache) > 7 * DIA: raise OSError
        cat = json.load(open(cache, encoding="utf-8"))
    except Exception:
        cat = steam.http_json("https://tandemstacks.github.io/TandemStacks/catalogo/todos.json", 30)
        json.dump(cat, open(cache, "w", encoding="utf-8"), ensure_ascii=False)
    n, tienda = _norm(g["name"]), g["store"]
    cands = [j for j in cat.get("juegos", []) if isinstance((j.get("st") or {}).get(tienda), str)]
    j = next((j for j in cands if _norm(j.get("t")) == n), None) \
        or next((j for j in cands if _misma_edicion(j.get("t"), g["name"])), None)
    url = j["st"][tienda] if j else ""
    # solo páginas de las tiendas (si el catálogo viniera adulterado, no se lee ninguna otra dirección ni archivos locales)
    return url if TIENDA_URL.match(url) else ""

TIENDA_URL = re.compile(r"https://(store\.ubisoft\.com|www\.ea\.com|store\.rockstargames\.com|www\.rockstargames\.com|"
                        r"us\.shop\.battle\.net|[a-z0-9-]+\.itch\.io|itch\.io)/")

def _url_idioma(url, idioma):
    """La página en el idioma de la app (15/11/2026: antes se leía siempre la inglesa). Español latino donde la tienda lo tiene."""
    if idioma == "english":
        return url
    url = re.sub(r"^https://store\.ubisoft\.com/[a-z]{2,5}/", "https://store.ubisoft.com/latam/", url)
    url = re.sub(r"^https://www\.ea\.com/(?:[a-z]{2}(?:-[a-z]{2})?/)?games/", "https://www.ea.com/es-mx/games/", url)
    return url  # Rockstar elige el idioma por el encabezado Accept-Language (ya va en español)

# Rockstar: su web principal tiene la ficha traducida (la de la tienda viene en inglés). Código del juego -> página
ROCK_SITIO = {"gta5": "V", "gta5_enhanced": "V", "rdr2": "reddeadredemption2", "mp3": "maxpayne3", "lanoire": "lanoire", "gta4": "IV",
              "gtasa": "sanandreas", "gtavc": "vicecity", "bully": "bully", "rdr": "reddeadredemption", "gtatrilogy": "gtatrilogy"}

def _ubisoft_buscar(g, idioma):
    """Ubisoft: si el juego no está en el catálogo de TandemStacks, se busca por nombre en el buscador público de su tienda."""
    q = urllib.parse.quote(re.sub(r"[™®©]", "", g["name"]))
    h = _pagina("https://store.ubisoft.com/latam/search?q=" + q, idioma)
    for slug, pid in re.findall(r'href="https://store\.ubisoft\.com/[a-z-]+/([a-z0-9-]+)/([0-9a-f]{24})\.html', h):
        if _misma_edicion(slug.replace("-", " "), g["name"]):
            return "https://store.ubisoft.com/us/%s/%s.html" % (slug, pid)
    return ""

def pagina_tienda(g, idioma):
    nombre = "%s/%s_t3.json" % (idioma, g["id"])  # _t2: las guardadas antes estaban en inglés
    d = _leer(nombre, 30 * DIA)
    if d is None:
        d = {}
        try:
            url = _url_tienda(g)
            if not url and g.get("store") == "Ubisoft":
                url = _ubisoft_buscar(g, idioma)
            sitio = ROCK_SITIO.get(str(g.get("id", ""))[5:]) if g.get("store") == "Rockstar" else None
            if sitio:
                url = "https://www.rockstargames.com/%sgames/%s" % ("" if idioma == "english" else "es/", sitio)
            if url:
                d = {"url": url}
                h = _pagina(_url_idioma(url, idioma), idioma)
                desc = _meta(h, "og:description") or _meta(h, "description")
                if desc and _norm(desc) != _norm(g["name"]): d["desc"] = desc[:500]
        except Exception as e:
            paths.log("ficha tienda", g.get("store"), g.get("name"), e); return {}
        _guardar(nombre, d)
    return _limpio(d)

def de(g, cfg):
    """Lo que se agrega a la ficha de g al abrirla."""
    idioma = cfg.get("idioma", "spanish")
    if g.get("store") == "Steam":
        d = {}  # sin logros: el dueño sacó horas y logros de todas las tiendas (12/11/2026)
        if g.get("appid") and not g.get("desc"):  # la ficha de la tienda se baja recién ahora, al abrirla (queda en caché 30 días)
            from . import steam
            f = steam.ficha(g["appid"], idioma) or {}
            for k in ("desc", "genres", "anio", "dev", "reqGB", "revPct", "revN"):
                if f.get(k) not in (None, "", []): d[k] = f[k]
        return d
    if g.get("store") == "Epic":
        return epic(g, idioma)
    if g.get("store") == "Xbox":
        return xbox(g, idioma)
    if g.get("store") == "Google Play":
        return google_play(g, idioma)
    if g.get("store") in ("EA", "Ubisoft", "Rockstar") and not g.get("desc"):
        return pagina_tienda(g, idioma)
    return {}
