# -*- coding: utf-8 -*-
"""Steam: usuario, juegos instalados (todas las bibliotecas), biblioteca completa (Web API) y fichas (appdetails + SteamSpy)."""
import os, re, json, time, glob, difflib, threading, urllib.request, urllib.parse
from . import paths
from .detect import reg, HKCU

UA = {"User-Agent": "SantiStacks/1.0 (+https://github.com)"}
CACHE_STEAM = os.path.join(paths.CACHE, "steam")
os.makedirs(CACHE_STEAM, exist_ok=True)

_lock = threading.Lock()  # las fichas se piden de a 4 hilos: las cachés en disco se escriben de a uno

def http(url, timeout=30):
    req = urllib.request.Request(url, headers=UA)
    return urllib.request.urlopen(req, timeout=timeout).read()

def http_json(url, timeout=30):
    return json.loads(http(url, timeout).decode("utf-8", "ignore"))

def steam_path():
    return (reg(HKCU, r"Software\Valve\Steam", "SteamPath") or r"C:\Program Files (x86)\Steam").replace("/", "\\")

def usuario():
    """(steamid64, nombre) del último usuario que entró a Steam en esta PC."""
    try:
        t = open(os.path.join(steam_path(), "config", "loginusers.vdf"), encoding="utf-8", errors="ignore").read()
    except Exception:
        return "", ""
    mejor, mejor_ts = None, -1
    for m in re.finditer(r'"(\d{17})"\s*\{(.*?)\}', t, re.S):
        sid, cuerpo = m.group(1), m.group(2)
        ts = int((re.search(r'"Timestamp"\s*"(\d+)"', cuerpo, re.I) or [0, 0])[1] or 0)
        if re.search(r'"MostRecent"\s*"1"', cuerpo, re.I): ts += 10**12
        if ts > mejor_ts:
            mejor_ts, mejor = ts, (sid, (re.search(r'"PersonaName"\s*"([^"]*)"', cuerpo) or [0, ""])[1])
    return mejor or ("", "")

def _bibliotecas():
    """Carpetas de bibliotecas de Steam (libraryfolders.vdf)."""
    sp = steam_path(); libs = [sp]
    vdf = os.path.join(sp, "steamapps", "libraryfolders.vdf")
    if os.path.exists(vdf):
        libs = [p.replace("\\\\", "\\") for p in re.findall(r'"path"\s*"([^"]+)"', open(vdf, encoding="utf-8", errors="ignore").read())] or libs
    return libs

def instalados():
    """{appid: {"name", "gb", "drive", "dir"}} leyendo los appmanifest de todas las bibliotecas."""
    out = {}
    for lib in _bibliotecas():
        for f in glob.glob(os.path.join(lib, "steamapps", "appmanifest_*.acf")):
            try:
                t = open(f, encoding="utf-8", errors="ignore").read()
            except Exception:
                continue
            val = lambda k: (re.search(r'"%s"\s*"([^"]*)"' % k, t) or [None, ""])[1]
            aid, name = val("appid"), val("name")
            if not aid or aid == "228980" or (val("StateFlags") not in ("4", "6", "1030", "1026", "")):  # 4 = instalado completo
                continue
            out[aid] = {"name": name, "gb": round(int(val("SizeOnDisk") or 0) / 1073741824, 1), "drive": lib[:2].upper(),
                        "dir": os.path.join(lib, "steamapps", "common", val("installdir"))}
    return out

def huella_instalados():
    partes = []
    for lib in _bibliotecas():
        for f in sorted(glob.glob(os.path.join(lib, "steamapps", "appmanifest_*.acf"))):
            try:
                t = open(f, encoding="utf-8", errors="ignore").read()
                partes.append(f + "|" + "|".join(re.findall(r'"(?:StateFlags|SizeOnDisk)"\s*"(\d+)"', t)))
            except Exception:
                pass
    return "\n".join(partes)

def biblioteca(api_key, steamid):
    """Lista completa [(appid, nombre)] vía Web API. None si no hay clave, el perfil es privado o falló."""
    if not api_key or not steamid:
        return None
    try:
        j = http_json("https://api.steampowered.com/IPlayerService/GetOwnedGames/v1/?" + urllib.parse.urlencode(
            {"key": api_key, "steamid": steamid, "include_appinfo": 1, "include_played_free_games": 1, "format": "json"}))
        juegos = j.get("response", {}).get("games")
        if juegos is None:
            return None
        return [(str(g["appid"]), g.get("name", "")) for g in juegos]
    except Exception as e:
        paths.log("steam biblioteca:", e)
        return None

# ---------- fichas ----------
def _cache(appid):
    return os.path.join(CACHE_STEAM, "%s.json" % appid)

def ficha_cacheada(appid):
    try:
        d = json.load(open(_cache(appid), encoding="utf-8"))
        if time.time() - d.get("_ts", 0) < 30 * 86400:
            return d
    except Exception:
        pass
    return None

def ficha(appid, idioma="spanish"):
    """Datos de la tienda (descripción, géneros, año, estudio, GB requeridos, Metacritic) + reseñas (SteamSpy). Con caché de 30 días."""
    d = ficha_cacheada(appid)
    if d:
        return d
    d = {"_ts": time.time()}
    fallo = False  # si la tienda no respondió, no se guarda: se reintenta la próxima vez
    try:
        j = http_json("https://store.steampowered.com/api/appdetails?appids=%s&l=%s&cc=US" % (appid, idioma))
        e = j.get(str(appid)) if isinstance(j, dict) else None  # juegos retirados: Steam responde [] o sin datos
        a = (e if isinstance(e, dict) else {}).get("data") or {}
        if not isinstance(a, dict):
            a = {}
        if a:
            d["desc"] = a.get("short_description", "")
            d["genres"] = [g["description"] for g in a.get("genres", [])][:5]
            d["anio"] = (re.search(r"\d{4}", a.get("release_date", {}).get("date", "")) or [None, ""])[0] or ""
            d["dev"] = ", ".join(a.get("developers", [])[:2])
            d["tipo"] = a.get("type", "")
            if a.get("metacritic"): d["meta"] = a["metacritic"].get("score")
            pcr = a.get("pc_requirements")  # algunos juegos lo mandan como lista vacía
            req = re.sub(r"<[^>]+>", " ", str(pcr.get("minimum", "") if isinstance(pcr, dict) else ""))
            m = re.search(r"(\d+(?:[.,]\d+)?)\s*(GB|MB)\s*(?:de\s+)?(?:espacio|available|disponible|free|storage)", req, re.I) or \
                re.search(r"(?:Storage|Almacenamiento|Disco|Hard Drive|Disk Space)[^0-9]{0,20}(\d+(?:[.,]\d+)?)\s*(GB|MB)", req, re.I)
            if m:
                n = float(m.group(1).replace(",", ".")); d["reqGB"] = round(n / 1024, 1) if m.group(2).upper() == "MB" else n
    except Exception as e:
        paths.log("appdetails", appid, e)
        fallo = True
        if "429" in str(e):
            time.sleep(60)
    try:
        s = http_json("https://steamspy.com/api.php?request=appdetails&appid=%s" % appid, 20)
        pos, neg = int(s.get("positive", 0)), int(s.get("negative", 0))
        if pos + neg >= 10:
            pct = round(pos * 100 / (pos + neg))
            d.update(revPct=pct, revN=pos + neg)  # el texto ("Muy positivas"...) lo pone la página en su idioma
    except Exception as e:
        paths.log("steamspy", appid, e)
    if not fallo:
        try:
            with _lock:
                json.dump(d, open(_cache(appid), "w", encoding="utf-8"), ensure_ascii=False)
        except Exception:
            pass
    return d

# ---------- buscar en Steam un juego de otra tienda (para portada y ficha) ----------
nrm = lambda n: re.sub(r"[^a-z0-9]+", " ", n.lower().replace("™", "").replace("®", "")).strip()
# versiones de prueba, servidores, bandas sonoras: no son juegos (se ocultan si no están instaladas)
NO_JUEGO = re.compile(r"public test|test server|test branch|staging branch|\bpts\b|playtest|dedicated server|\bsdk\b|soundtrack|benchmark|ctb beta", re.I)
_busq_file = os.path.join(paths.CACHE, "busquedas.json")
try:
    _busq = json.load(open(_busq_file, encoding="utf-8"))
except Exception:
    _busq = {}

def buscar_appid(nombre):
    """appid de Steam cuyo nombre coincide casi exacto (>= 0.92 y misma primera palabra), o ''. Con caché."""
    k = nrm(nombre)
    if not k:
        return ""
    if k in _busq:
        return _busq[k]
    res = ""
    try:
        r = http_json("https://store.steampowered.com/api/storesearch/?cc=US&l=english&term=" + urllib.parse.quote(k), 20)
        mejor, score = None, 0
        for it in r.get("items", []):
            s = difflib.SequenceMatcher(None, k, nrm(it["name"])).ratio()
            if s > score: mejor, score = it, s
        if mejor and score >= 0.92 and k.split()[0] == nrm(mejor["name"]).split()[0]:
            res = str(mejor["id"])
    except Exception as e:
        paths.log("storesearch", nombre, e)
        return ""  # sin cachear: se reintenta la próxima
    try:
        with _lock:
            _busq[k] = res
            json.dump(_busq, open(_busq_file, "w", encoding="utf-8"), ensure_ascii=False)
    except Exception:
        pass
    return res
