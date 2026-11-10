# -*- coding: utf-8 -*-
"""Vigilancia de juegos (lanzados desde donde sea):
- al abrir un juego se cierran los launchers que ese juego no usa, para que tenga más memoria;
- al terminar se cierran todos los launchers abiertos y se borra la basura segura (volcados de errores, logs viejos, caché web grande).
Si queda otro juego andando no se toca nada, para no cortarlo. Lo que se libera se anota en ahorro.json (el medidor)."""
import os, time, json, glob, shutil, threading, subprocess, winreg
import psutil
from . import paths, pulso

INTERVALO = 5   # segundos entre cada mirada mientras hay un juego andando
REPOSO = 15     # sin juegos se mira menos seguido: recorrer los procesos gasta
MINIMO = 30     # lo que dura menos que esto no era un juego (parches, instaladores, un error al abrir)
ESPERA = 60     # recién al minuto de abrir un juego se cierran los otros launchers: antes el juego puede estar validando su licencia
GENERICOS = {"launcher.exe": "rockstar", "agent.exe": "battle.net", "butler.exe": "itch"}  # nombres que usan otros programas: se mira también la ruta
AYUDANTES = ("crash", "reporter", "unins")  # procesos que pueden quedar en la carpeta del juego después de cerrarlo
AHORRO = os.path.join(os.path.dirname(paths.CONFIG), "ahorro.json")

# Juegos que necesitan otro launcher además del de su tienda (ej. Assassin's Creed comprado en Steam pide Ubisoft Connect).
# Se reconocen por archivos dentro de la carpeta del juego.
NECESITA = {
    "Ubisoft": ("uplay_r1_loader64.dll", "uplay_r1_loader.dll", "upc_r2_loader64.dll", "uplay_r2_loader64.dll", "uplay_ps.dll"),
    "EA": ("installerdata.xml", "activation64.dll", "activation.dll"),
    "Rockstar": ("playgtav.exe", "playrdr2.exe", "socialclub.dll", "launcher.rpf"),
}

# ---------- medidor ----------
def ahorro():
    try:
        with open(AHORRO, encoding="utf-8") as f: return json.load(f)
    except Exception:
        return {"launchers": 0, "ram_mb": 0, "ram_max_mb": 0, "disco_mb": 0, "limpiezas": 0}

def _anotar(**suma):
    a = ahorro()
    for k, v in suma.items():
        if k == "ram_max_mb": a[k] = max(a.get(k, 0), round(v))
        else: a[k] = round(a.get(k, 0) + v, 1)
    try:
        with open(AHORRO + ".tmp", "w", encoding="utf-8") as f: json.dump(a, f)
        os.replace(AHORRO + ".tmp", AHORRO)
    except OSError as e:
        paths.log("ahorro", e)

# ---------- procesos ----------
_rutas = {}  # (pid, cuándo arrancó): ruta del programa. Pedir la ruta obliga a abrir el proceso: se pide una sola vez por proceso

_candado = threading.Lock()

def _procs():
    """[(proceso, nombre, ruta)] de todo lo que corre. Se arma entero bajo candado: lo usan dos hilos a la vez."""
    out, vivos = [], set()
    with _candado:
        for pr in psutil.process_iter(["name", "create_time"]):
            try:
                clave = (pr.pid, pr.info.get("create_time"))
                vivos.add(clave)
                if clave not in _rutas:
                    try: _rutas[clave] = (pr.exe() or "").lower()
                    except Exception: _rutas[clave] = ""
                out.append((pr, (pr.info["name"] or "").lower(), _rutas[clave]))
            except Exception:
                pass
        for clave in [c for c in _rutas if c not in vivos]:  # procesos que ya cerraron
            _rutas.pop(clave, None)
    return out

def _es_de(nombre, ruta, d):
    return nombre in d["procs"] and GENERICOS.get(nombre, "") in ruta

def abiertos(launchers):
    vivos = set()
    for _, n, e in _procs():
        for l, d in launchers.items():
            if _es_de(n, e, d):
                vivos.add(l)
    return vivos

_escrito = {}  # launcher: (bytes escritos, cuándo), para calcular la velocidad entre dos consultas
MIN_DESCARGA = 1048576  # 1 MB/s: menos que eso es el launcher guardando lo suyo, no una descarga

def descargando(launchers):
    """Velocidad a la que cada launcher escribe en el disco ({tienda: bytes/s}), solo si parece una descarga.
    Sirve para todas las tiendas que bajan con su propio programa (Xbox no: baja Windows)."""
    ahora, total = time.time(), {}
    for pr, n, e in _procs():
        for l, d in launchers.items():
            if _es_de(n, e, d):
                try: total[l] = total.get(l, 0) + pr.io_counters().write_bytes
                except Exception: pass
    out = {}
    for l, b in total.items():
        antes = _escrito.get(l)
        if antes and ahora > antes[1]:
            v = (b - antes[0]) / (ahora - antes[1])
            if v >= MIN_DESCARGA: out[l] = round(v)
        _escrito[l] = (b, ahora)
    for l in [l for l in _escrito if l not in total]: _escrito.pop(l)  # launchers que se cerraron
    return out

def en_curso(juegos):
    """Juegos andando: {carpeta: {"tienda", "desde", "exes"}}. juegos = [{"dir", "store", "appid"}] instalados.
    Steam avisa en el registro qué juego corre; los demás se reconocen por un proceso dentro de su carpeta."""
    out = {}
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as k:
            aid = str(winreg.QueryValueEx(k, "RunningAppID")[0])
        if aid not in ("0", ""):
            g = next((g for g in juegos if g.get("store") == "Steam" and str(g.get("appid")) == aid), None)
            out[(g or {}).get("dir") or "steam:" + aid] = {"tienda": "Steam", "desde": None, "exes": set(), "g": g}
    except OSError:
        pass
    prefijos = {g["dir"].lower().replace("/", "\\").rstrip("\\") + "\\": g for g in juegos if g.get("dir")}
    if not prefijos:
        return out
    tupla = tuple(prefijos)
    for pr, n, e in _procs():
        if not e.startswith(tupla) or any(a in n for a in AYUDANTES):
            continue
        p = next(p for p in tupla if e.startswith(p))
        g = prefijos[p]
        j = out.setdefault(g["dir"], {"tienda": g.get("store", ""), "desde": None, "exes": set(), "g": g})
        j["exes"].add(n)
        t = pr.info.get("create_time") or time.time()
        j["desde"] = min(j["desde"] or t, t)
    return out

def necesita(carpeta, _cache={}):
    """Launchers extra que pide el juego (por archivos de su carpeta, hasta 3 niveles)."""
    if carpeta in _cache: return _cache[carpeta]
    extra = set()
    if os.path.isdir(carpeta):
        base = carpeta.rstrip("\\").count("\\")
        if "rockstar" in carpeta.lower(): extra.add("Rockstar")
        for raiz, dirs, archivos in os.walk(carpeta):
            if raiz.count("\\") - base >= 3: dirs[:] = []
            nombres = {a.lower() for a in archivos} | {d.lower() for d in dirs}
            for l, marcas in NECESITA.items():
                if nombres.intersection(marcas): extra.add(l)
            if "__installer" in nombres: extra.add("EA")
    _cache[carpeta] = extra
    return extra

def cerrar(l, launchers, antes_de=None):
    """Cierra un launcher y devuelve los MB de memoria que usaba. Con antes_de, solo si todos sus procesos son anteriores
    (si arrancó después del juego, es porque el juego lo pidió: no se toca)."""
    d = launchers[l]
    victimas = [pr for pr, n, e in _procs() if _es_de(n, e, d)]
    if antes_de and any((pr.info.get("create_time") or 0) > antes_de for pr in victimas):
        return 0
    mb = 0
    for pr in victimas:
        try: mb += pr.memory_info().rss / 1048576
        except Exception: pass
    if l == "Steam" and d.get("exe") and os.path.exists(d["exe"]):
        subprocess.Popen([d["exe"], "-shutdown"], creationflags=0x08000000)
        time.sleep(8)
    for pr in victimas:
        try: pr.terminate()
        except Exception: pass
    try: psutil.wait_procs(victimas, timeout=8)
    except psutil.Error: pass  # servicios de Windows (EABackgroundService): no dejan ni esperarlos
    for pr in victimas:
        try:
            if pr.is_running(): pr.kill()
        except Exception: pass
    paths.log("launcher cerrado:", l, "%d MB" % mb)
    return mb

# ---------- limpieza ----------
def _peso(ruta):
    if os.path.isfile(ruta): return os.path.getsize(ruta)
    total = 0
    for raiz, _, archivos in os.walk(ruta):
        for a in archivos:
            try: total += os.path.getsize(os.path.join(raiz, a))
            except OSError: pass
    return total

def _borrar(ruta):
    """Borra un archivo o carpeta y devuelve los bytes liberados (lo que está en uso queda)."""
    antes = _peso(ruta)
    if os.path.isdir(ruta): shutil.rmtree(ruta, ignore_errors=True)
    else:
        try: os.remove(ruta)
        except OSError: pass
    return antes - (_peso(ruta) if os.path.exists(ruta) else 0)

def basura(exes, launchers, abiertos_ahora):
    """Lo que se puede borrar sin riesgo. Nunca partidas guardadas, configuraciones ni la caché de sombreadores
    (sin ella el juego se traba al abrir). Las cachés web solo si pasan los 300 MB y su launcher está cerrado."""
    loc, tmp = os.environ.get("LOCALAPPDATA", ""), os.environ.get("TEMP", "")
    rutas = []
    # volcados de errores de Windows, solo de los programas del juego que se cerró
    for x in exes:
        rutas += glob.glob(os.path.join(loc, "CrashDumps", glob.escape(x) + ".*.dmp"))
    # Unreal y Unity guardan informes de errores en carpetas propias del juego
    rutas += glob.glob(os.path.join(loc, "*", "Saved", "Crashes", "*"))
    rutas += glob.glob(os.path.join(loc, "*", "Saved", "Logs", "*-backup-*.log"))
    rutas += glob.glob(os.path.join(tmp, "*", "*", "Crashes", "*"))
    steam = os.path.dirname((launchers.get("Steam") or {}).get("exe") or "")
    if steam:
        rutas += glob.glob(os.path.join(steam, "dumps", "*.dmp"))  # solo los volcados: lo demás es del propio Steam
    rutas += glob.glob(os.path.join(loc, "EpicGamesLauncher", "Saved", "Logs", "*-backup-*.log"))
    rutas += glob.glob(os.path.join(loc, "EpicGamesLauncher", "Saved", "Crashes", "*"))
    caches = {"Steam": [os.path.join(steam, "appcache", "httpcache")] if steam else [],
              "Epic": glob.glob(os.path.join(loc, "EpicGamesLauncher", "Saved", "webcache*")),
              "Battle.net": [os.path.join(loc, "Battle.net", "BrowserCaches")]}
    for l, cs in caches.items():
        if l in abiertos_ahora: continue
        rutas += [c for c in cs if os.path.isdir(c) and _peso(c) > 300 * 1048576]
    return [r for r in dict.fromkeys(rutas) if os.path.exists(r)]

def limpiar(exes, launchers):
    libre = sum(_borrar(r) for r in basura(exes, launchers, abiertos(launchers)))
    mb = libre / 1048576
    if mb >= 0.1:
        _anotar(disco_mb=mb, limpiezas=1)
        paths.log("limpieza: %.1f MB" % mb)
    return mb

# ---------- hilo ----------
def vigilar(juegos, launchers, cfg, sumar, al_jugar=None, al_medir=None):
    """Hilo de toda la sesión. juegos, launchers y cfg son funciones: la biblioteca y la configuración cambian mientras corre.
    sumar(segundos) recibe el tiempo con algún juego abierto, para el contador de horas.
    al_jugar() se llama una vez cuando arranca un juego (TandemStacks se minimiza y se duerme).
    al_medir(juego, resumen) recibe lo que midió Pulso al terminar cada partida."""
    desde = ultimo = None
    vistos = {}       # carpeta: datos de cada juego que anduvo en esta tanda
    revisados = set() # juegos a los que ya se les cerraron los launchers que no usan
    sesion_ram = 0    # memoria liberada al abrir juegos en esta tanda
    while True:
        time.sleep(INTERVALO if desde else REPOSO)
        try:
            ahora_j = en_curso(juegos())
            if ahora_j:
                ahora = time.time()
                if not desde and al_jugar:
                    try: al_jugar()
                    except Exception as e: paths.log("al jugar", e)
                desde = desde or ahora
                if ultimo: sumar(min(ahora - ultimo, 60))  # el tope evita contar horas si la PC se suspendió
                ultimo = ahora
                for c, j in ahora_j.items():
                    if j.get("g") and j["g"]["id"] not in pulso._activos and cfg().get("pulso", True):
                        pulso.empezar(j["g"], al_medir)  # Pulso mide la partida en su propio hilo (también si lo reabrís)
                    v = vistos.setdefault(c, {"exes": set(), "desde": j["desde"]})
                    v["exes"] |= j["exes"]
                c = cfg()
                if c.get("cerrar_otros", True) and ahora - desde >= ESPERA and set(ahora_j) - revisados:
                    usa = {j["tienda"] for j in ahora_j.values()}
                    for carpeta in ahora_j: usa |= necesita(carpeta)
                    inicio = min((j["desde"] for j in ahora_j.values() if j["desde"]), default=desde)
                    ls = launchers()
                    for l in abiertos(ls) - usa:
                        try:
                            mb = cerrar(l, ls, antes_de=inicio)
                            if mb: _anotar(launchers=1, ram_mb=mb, ram_max_mb=mb); sesion_ram += mb
                        except Exception as e: paths.log("cerrar otro", l, e)
                    revisados |= set(ahora_j)
            elif desde:
                time.sleep(INTERVALO)  # algunos juegos se reabren solos al arrancar
                if en_curso(juegos()):
                    continue
                duro, desde, ultimo = time.time() - desde, None, None
                ram_abrir, sesion_ram = sesion_ram, 0  # lo que se liberó al abrir, para el aviso
                exes = set().union(*(v["exes"] for v in vistos.values())) if vistos else set()
                vistos, revisados = {}, set()
                if duro < MINIMO:
                    continue
                c, ls = cfg(), launchers()
                liberado = {"ram_mb": ram_abrir, "disco_mb": 0}
                if c.get("cerrar_launchers", True):
                    for l in abiertos(ls):
                        try:
                            mb = cerrar(l, ls)
                            if mb: _anotar(launchers=1, ram_mb=mb, ram_max_mb=mb); liberado["ram_mb"] += mb
                        except Exception as e: paths.log("cerrar", l, e)
                if c.get("limpiar", True):
                    try: liberado["disco_mb"] = limpiar(exes, ls)
                    except Exception as e: paths.log("limpiar", e)
                if al_medir and (liberado["ram_mb"] or liberado["disco_mb"]):
                    al_medir(None, liberado)
        except Exception as e:
            paths.log("vigilar juegos", e)
