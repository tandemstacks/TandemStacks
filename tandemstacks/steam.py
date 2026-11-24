# -*- coding: utf-8 -*-
"""Steam: usuario, juegos instalados (todas las bibliotecas), biblioteca completa (Web API) y fichas (appdetails + SteamSpy)."""
import os, re, json, time, glob, difflib, threading, winreg, urllib.request, urllib.parse
from . import paths
from .detect import reg, HKCU

UA = {"User-Agent": "TandemStacks/1.0 (+https://github.com)"}
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
    # Steam a veces anota la misma biblioteca dos veces (pasó al sumar F:\SteamLibrary): sin esto, cada juego y cada
    # descarga de esa biblioteca salía repetida
    vistas, unicas = set(), []
    for p in libs:
        k = os.path.normcase(os.path.normpath(p))
        if k not in vistas: vistas.add(k); unicas.append(p)
    return unicas

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

_manifs = {}  # appmanifest: (fecha, datos), para releerlo solo cuando Steam lo cambia
def _manif(f):
    try: m = os.path.getmtime(f)
    except OSError: return {}
    c = _manifs.get(f)
    if c and c[0] == m: return c[1]
    try: t = open(f, encoding="utf-8", errors="ignore").read()
    except Exception: return {}
    val = lambda k: (re.search(r'"%s"\s*"([^"]*)"' % k, t) or [None, ""])[1]
    d = {"name": val("name"), "flags": int(val("StateFlags") or 0), "total": int(val("BytesToDownload") or 0), "hecho": int(val("BytesDownloaded") or 0),
         "etapa": int(val("BytesToStage") or 0), "etapa_hecho": int(val("BytesStaged") or 0)}
    _manifs[f] = (m, d)
    return d

def _bajado_desde(desde):
    """Bytes que bajó Steam desde un momento, sumando las velocidades por minuto de logs/content_log.txt (lee solo el final)."""
    try:
        f = os.path.join(steam_path(), "logs", "content_log.txt")
        with open(f, "rb") as h:
            h.seek(max(0, os.path.getsize(f) - 200000)); t = h.read().decode("utf-8", "ignore")
        total = 0
        for fecha, mbps in re.findall(r"\[(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)\] Current download rate: ([\d.]+) Mbps", t):
            if time.mktime(time.strptime(fecha, "%Y-%m-%d %H:%M:%S")) > desde:
                total += float(mbps) * 1e6 / 8 * 60
        return int(total)
    except Exception:
        return 0

_avance = {}  # appid -> (fecha del manifiesto, bytes escritos por Steam al verlo, lo armado según el manifiesto)

_ULTIMO = None  # {appid: % visto por última vez}, guardado en la PC para mostrarlo con Steam cerrado (o después de reiniciar)

def _ultimos():
    global _ULTIMO
    if _ULTIMO is None:
        try: _ULTIMO = json.load(open(os.path.join(paths.CACHE, "steam_descargas.json"), encoding="utf-8"))
        except Exception: _ULTIMO = {}
    return _ULTIMO

def _anotar_ultimos(out):
    u = _ultimos()
    nuevo = {d["id"]: max(d["pct"], u.get(d["id"], 0)) for d in out}  # solo los que siguen pendientes: lo terminado o cancelado se olvida
    if nuevo != u:
        # al disco solo si cambió el % entero o la lista (antes se reescribía cada 4 s mientras bajaba)
        en_disco = {k: int(v) for k, v in u.items()} != {k: int(v) for k, v in nuevo.items()}
        _ULTIMO.clear(); _ULTIMO.update(nuevo)
        if en_disco:
            try:
                with open(os.path.join(paths.CACHE, "steam_descargas.json"), "w", encoding="utf-8") as f: json.dump(nuevo, f)
            except OSError: pass

def descargas():
    """Lo que Steam está bajando: [{"name", "pct", "id", "pausa"}].
    Steam anota el avance en el appmanifest solo al empezar y al pausar, así que mientras baja se suma lo que steam.exe
    escribió en el disco desde entonces (lo que va armando del juego) sobre el total a armar (BytesToStage).
    Con Steam cerrado (pedido del dueño, 13/11/2026): el appmanifest sigue diciendo que falta bajar, así que el juego sigue
    en Instalados, en pausa y con el último % que se vio; cuando Steam abre, él decide si sigue o si se canceló."""
    try:
        import psutil
        sp = next((q for q in psutil.process_iter(["name"]) if (q.info["name"] or "").lower() == "steam.exe"), None)
        try: escrito = sp.io_counters().write_bytes if sp else None  # el "pid" de ActiveProcess a veces queda en 0: se mira el proceso
        except Exception: escrito = None
    except Exception:
        sp, escrito = None, None
    out, pend = [], []
    for lib in _bibliotecas():
        for f in glob.glob(os.path.join(lib, "steamapps", "appmanifest_*.acf")):
            d = _manif(f)
            if not (d and d["total"] and d["hecho"] < d["total"] and d["flags"] & 2):  # 2 = le falta bajar algo
                continue
            try: m = os.path.getmtime(f)
            except OSError: m = 0
            pend.append((m, f, d))
    # Steam baja de a uno: el activo es el último manifiesto que tocó; los demás quedan en cola aunque digan "empezada"
    # (si no, lo que escribe para uno se le sumaba también a los otros)
    actual = max((p for p in pend if p[2]["flags"] & 1024 and not p[2]["flags"] & 512), default=None, key=lambda p: p[0]) if sp else None
    for m, f, d in pend:
            aid = (re.search(r"appmanifest_(\d+)", f) or [None, ""])[1]
            activa = actual is not None and f == actual[1]  # 1024 = actualización empezada, 512 = en pausa
            pct = max(d["hecho"] / d["total"], _ultimos().get(aid, 0) / 100)  # nunca menos que lo último que se vio
            if activa and escrito is not None and d["etapa"]:
                try: m = os.path.getmtime(f)
                except OSError: m = 0
                b = _avance.get(aid)
                if not b or b[0] != m or escrito < b[1]:  # manifiesto nuevo o Steam reiniciado: se arranca la cuenta de nuevo
                    # lo que bajó antes de que TandemStacks empezara a mirar: velocidades que Steam anota cada minuto en su registro
                    previo = min(0.99, (d["hecho"] + _bajado_desde(m)) / d["total"])
                    if b and escrito >= b[1]:  # Steam solo reescribió el manifiesto: lo ya estimado no se pierde (antes el % volvía para atrás)
                        previo = max(previo, min(0.99, b[2] + (escrito - b[1]) / d["etapa"]))
                    b = _avance[aid] = (m, escrito, previo)
                pct = max(pct, min(0.99, b[2] + (escrito - b[1]) / d["etapa"]))
            elif aid in _avance and escrito is not None:  # en cola o en pausa: queda donde iba y lo que se escriba ahora no le cuenta
                b = _avance[aid]
                pct = max(pct, b[2])
                _avance[aid] = (m, escrito, pct)
            pct = pct * 100
            out.append({"name": d["name"], "pct": round(pct, 1) if pct < 10 else int(pct), "id": aid, "pausa": not activa})  # un decimal al principio: en juegos grandes 1 % tarda mucho
    _anotar_ultimos(out)
    return out

def huella_instalados():
    partes = []
    for lib in _bibliotecas():
        for f in sorted(glob.glob(os.path.join(lib, "steamapps", "appmanifest_*.acf"))):
            # solo si está instalado o no (StateFlags 4): el tamaño y el avance cambian durante una actualización y no hace falta reescanear
            partes.append("%s|%d" % (f, bool(_manif(f).get("flags", 0) & 4)))
    return "\n".join(partes)

def biblioteca(api_key, steamid):
    """Lista completa [(appid, nombre, minutos jugados, última vez)] vía Web API. None si no hay clave, el perfil es privado o falló."""
    if not api_key or not steamid:
        return None
    try:
        j = http_json("https://api.steampowered.com/IPlayerService/GetOwnedGames/v1/?" + urllib.parse.urlencode(
            {"key": api_key, "steamid": steamid, "include_appinfo": 1, "include_played_free_games": 1, "format": "json"}))
        juegos = j.get("response", {}).get("games")
        if juegos is None:
            return None
        return [(str(g["appid"]), g.get("name", ""), g.get("playtime_forever", 0), g.get("rtime_last_played", 0)) for g in juegos]
    except Exception as e:
        paths.log("steam biblioteca:", e)
        return None

def _apps_de_paquetes():
    """Apps de las licencias de la cuenta, de appcache/packageinfo.vdf (Steam guarda ahí solo los paquetes que tenés).
    Se saltean el paquete 0 (el de Steam) y los fines de semana gratis (extended.freeweekend). Formato binario de Steam:
    encabezado de 8 bytes; por paquete: id (uint32, 0xFFFFFFFF = fin), sha1 (20), cambio (4), token (8) y sus datos en KeyValues binario."""
    import struct
    try:
        b = open(os.path.join(steam_path(), "appcache", "packageinfo.vdf"), "rb").read()
    except OSError:
        return set()
    def kv(i):
        d = {}
        while True:
            t = b[i]; i += 1
            if t == 8: return d, i
            j = b.index(b"\0", i); k = b[i:j].decode("utf-8", "replace"); i = j + 1
            if t == 0: v, i = kv(i)
            elif t == 1: j = b.index(b"\0", i); v = b[i:j].decode("utf-8", "replace"); i = j + 1
            elif t in (2, 3): v = struct.unpack_from("<i", b, i)[0]; i += 4
            elif t == 7: v = struct.unpack_from("<Q", b, i)[0]; i += 8
            else: raise ValueError("tipo %d" % t)
            d[k] = v
    apps, i = set(), 8
    try:
        tam_extra = 32 if (struct.unpack_from("<I", b, 0)[0] & 0xFF) >= 40 else 24  # desde la v40 viene el token
        while True:
            pid = struct.unpack_from("<I", b, i)[0]; i += 4
            if pid == 0xFFFFFFFF: break
            i += tam_extra
            d, i = kv(i)
            x = d.get(str(pid), d)
            if pid == 0 or (x.get("extended") or {}).get("freeweekend"): continue
            apps.update(str(v) for v in (x.get("appids") or {}).values())
    except Exception as e:
        paths.log("steam packageinfo", e)
    return apps

def biblioteca_local():
    """Sin clave: Steam guarda en appcache/librarycache una carpeta por cada cosa de tu biblioteca (juegos, DLC, bandas sonoras).
    Se pregunta a la tienda (IStoreBrowseService/GetItems, público, de a 100) cuáles son juegos; las respuestas quedan en caché
    y solo se piden las nuevas. Se suma la lista de licencias (packageinfo.vdf) por si falta alguno."""
    try:
        ids = [d for d in os.listdir(os.path.join(steam_path(), "appcache", "librarycache")) if d.isdigit()]
    except OSError:
        ids = []
    ids = sorted(set(ids) | _apps_de_paquetes())  # respaldo: juegos recién comprados que la biblioteca todavía no mostró
    if not ids:
        return None
    archivo = os.path.join(paths.CACHE, "steam_tipos.json")
    try: tipos = json.load(open(archivo, encoding="utf-8"))
    except Exception: tipos = {}
    # también los juegos ya conocidos sin géneros (caché de antes del 17/11/2026: solo tipo y nombre)
    faltan = [a for a in ids if a not in tipos or (tipos[a][0] == 0 and len(tipos[a]) < 3)]
    for i in range(0, len(faltan), 100):
        req = {"ids": [{"appid": int(a)} for a in faltan[i:i + 100]], "context": {"language": "spanish", "country_code": "US"},
               "data_request": {"include_tag_count": 20}}  # etiquetas: de ahí salen los géneros sin bajar la ficha de cada juego
        try:
            j = http_json("https://api.steampowered.com/IStoreBrowseService/GetItems/v1?input_json=" + urllib.parse.quote(json.dumps(req)), 20)
        except Exception as e:
            paths.log("steam biblioteca local:", e)
            break
        vino = {str(it.get("appid") or it.get("id")): it for it in j.get("response", {}).get("store_items", [])}
        for a in faltan[i:i + 100]:
            it = vino.get(a) or {}
            gen = [GENERO_TAG[t] for t in (it.get("tagids") or []) if t in GENERO_TAG][:5]
            tipos[a] = [it.get("type"), it.get("name", ""), gen]  # 0 = juego; lo demás (DLC, música, sin datos) no
    try:
        with open(archivo + ".tmp", "w", encoding="utf-8") as f: json.dump(tipos, f)
        os.replace(archivo + ".tmp", archivo)
    except OSError: pass
    GENEROS.clear()
    GENEROS.update({a: tipos[a][2] for a in ids if a in tipos and len(tipos[a]) > 2 and tipos[a][2]})
    return [(a, tipos[a][1], 0, 0) for a in ids if a in tipos and tipos[a][0] == 0 and tipos[a][1]]

# Géneros de Steam por etiqueta (17/11/2026): la ficha (appdetails) se baja solo de los instalados, así que los no
# instalados no tenían género y el filtro mostraba 2 de estrategia teniendo muchos más. GetItems trae las etiquetas de
# a 100 juegos; de ellas se toman solo las que son géneros de Steam, con el mismo nombre que da la ficha.
GENERO_TAG = {19: "Acción", 21: "Aventura", 9: "Estrategia", 122: "Rol", 599: "Simuladores", 701: "Deportes", 699: "Carreras",
              597: "Casual", 492: "Indie", 128: "Multijugador masivo", 113: "Free to Play", 493: "Acceso anticipado"}
GENEROS = {}  # appid → géneros, para los juegos de la biblioteca sin ficha

# ---------- fichas ----------
def _cache(appid, idioma="spanish"):
    """Una caché por idioma: cambiar de idioma no borra la otra y volver es instantáneo (español queda en la raíz, como antes)."""
    carpeta = CACHE_STEAM if idioma == "spanish" else os.path.join(CACHE_STEAM, idioma)
    os.makedirs(carpeta, exist_ok=True)
    return os.path.join(carpeta, "%s.json" % appid)

def ficha_cacheada(appid, idioma="spanish"):
    try:
        d = json.load(open(_cache(appid, idioma), encoding="utf-8"))
        if time.time() - d.get("_ts", 0) < 30 * 86400:
            return d
    except Exception:
        pass
    return None

def ficha(appid, idioma="spanish"):
    """Datos de la tienda (descripción, géneros, año, estudio, GB requeridos) + % de reseñas de la comunidad (SteamSpy). Con caché de 30 días."""
    d = ficha_cacheada(appid, idioma)
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
                json.dump(d, open(_cache(appid, idioma), "w", encoding="utf-8"), ensure_ascii=False)
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
    if _busq.get(k):  # "-" = ya se buscó y no está; "" = búsqueda vieja (con el nombre normalizado, fallaba con apóstrofos): se repite
        return "" if _busq[k] == "-" else _busq[k]
    res = ""
    try:  # se busca con el nombre tal cual: normalizado, "Assassin's" queda "assassin s" y Steam no encuentra nada
        termino = re.sub(r"[™®©]", "", nombre).strip()
        r = http_json("https://store.steampowered.com/api/storesearch/?cc=US&l=english&term=" + urllib.parse.quote(termino), 20)
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
            _busq[k] = res or "-"
            json.dump(_busq, open(_busq_file, "w", encoding="utf-8"), ensure_ascii=False)
    except Exception:
        pass
    return res
