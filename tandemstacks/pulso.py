# -*- coding: utf-8 -*-
"""Pulso: mide cada partida y la guarda como registro de ESE juego, para ver si un cambio de gráficos (o un driver,
o una actualización) lo mejoró o lo empeoró.

Mientras jugás: FPS y tirones (PresentMon, incluido en assets), placa NVIDIA (nvidia-smi), procesador, RAM, disco,
ping a internet y al servidor del juego, y temperatura del procesador si LibreHardwareMonitor está abierto.
Al cerrar: promedios, máximos, programas de fondo, si se cerró con error y la comparación contra lo normal de ese juego.
Queda en %APPDATA%\\TandemStacks\\pulso\\<id del juego>.jsonl (las últimas 20 partidas).

Solo mide: no cambia nada del sistema ni de los juegos. Todo oculto y con prioridad baja.
PresentMon necesita que el usuario esté en el grupo de Windows "Performance Log Users" (o la app como administrador):
si no, no hay FPS pero se mide todo lo demás."""
import os, re, csv, json, glob, time, ctypes, datetime, statistics, subprocess, threading, urllib.request
import psutil
from . import paths

CARPETA = os.path.join(os.path.dirname(paths.CONFIG), "pulso")
TMP = os.path.join(paths.CACHE, "pulso")
PM = os.path.join(paths.ASSETS, "PresentMon.exe")
SIN_VENTANA = 0x08000000
MIN_SEG = 60          # partidas más cortas no se guardan
GUARDAR = 200         # partidas que se guardan por juego (~1 KB cada una: meses de historial)
MUESTRA = 5           # segundos entre muestras
NO_JUEGO = ("crash", "launcher", "helper", "easyanticheat", "battleye", "beservice", "unins", "setup",
            "redist", "vc_redist", "dxsetup", "steamservice", "overlay", "report", "update", "prereq")
CALOR = 0x8 | 0x20 | 0x40 | 0x80   # nvidia-smi clocks_event_reasons: frenos por calor
ENERGIA = 0x4                      # freno por energía
_activos = set()                   # juegos que se están midiendo

def _log(*a): paths.log("pulso:", *a)

def archivo(gid):
    return os.path.join(CARPETA, re.sub(r"[^\w\-]", "_", gid) + ".jsonl")

def historial(gid):
    try:
        with open(archivo(gid), encoding="utf-8") as f:
            return [json.loads(l) for l in f if l.strip()]
    except (OSError, ValueError):
        return []

def _guardar(gid, s):
    os.makedirs(CARPETA, exist_ok=True)
    todas = (historial(gid) + [s])[-GUARDAR:]
    with open(archivo(gid) + ".tmp", "w", encoding="utf-8") as f:
        f.write("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in todas))
    os.replace(archivo(gid) + ".tmp", archivo(gid))

# ---------- mediciones ----------
def _correr(args, timeout=10):
    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=timeout, creationflags=SIN_VENTANA).stdout.strip()
    except Exception:
        return ""

_nv_ultimo = [0, {}]  # última lectura de nvidia-smi: los relojes y Pulso la comparten si tiene menos de 3 s

def nvsmi():
    if time.time() - _nv_ultimo[0] < 3: return dict(_nv_ultimo[1])
    v = _nvsmi()
    _nv_ultimo[:] = [time.time(), v]
    return dict(v)

def _nvsmi():
    campos = "utilization.gpu,temperature.gpu,power.draw,memory.used,memory.total,clocks_event_reasons.active"
    o = _correr(["nvidia-smi", "--query-gpu=" + campos, "--format=csv,noheader,nounits"])
    if not o or "Field" in o:  # drivers viejos: nombre anterior del campo
        o = _correr(["nvidia-smi", "--query-gpu=" + campos.replace("clocks_event_reasons", "clocks_throttle_reasons"), "--format=csv,noheader,nounits"])
    try:
        v = [x.strip() for x in o.splitlines()[0].split(",")]
        return {"gpu_uso": float(v[0]), "gpu_temp": float(v[1]), "gpu_w": float(v[2]), "vram": float(v[3]), "vram_total": float(v[4]),
                "frenos": int(v[5], 16) if v[5].startswith("0x") else 0}
    except Exception:
        return {}

def driver():
    o = _correr(["nvidia-smi", "--query-gpu=driver_version", "--format=csv,noheader"])
    return o.splitlines()[0].strip() if o else None

def version_juego(g):
    """Versión instalada: buildid de Steam o AppVersionString de Epic (para avisar si el cambio coincide con una actualización)."""
    try:
        if g.get("store") == "Steam" and g.get("appid") and g.get("dir"):
            f = os.path.join(os.path.dirname(os.path.dirname(g["dir"])), "appmanifest_%s.acf" % g["appid"])
            b = re.search(r'"buildid"\s*"(\d+)"', open(f, encoding="utf-8", errors="ignore").read())
            return "steam-" + b.group(1) if b else None
        if g.get("store") == "Epic" and g.get("dir"):
            for f in glob.glob(os.path.join(r"C:\ProgramData\Epic\EpicGamesLauncher\Data\Manifests", "*.item")):
                with open(f, encoding="utf-8") as h: m = json.load(h)
                if m.get("InstallLocation") and os.path.normcase(m["InstallLocation"]) == os.path.normcase(g["dir"]):
                    return "epic-" + m.get("AppVersionString", "")
    except Exception:
        pass
    return None

def ping(host, n=2):
    """(ms promedio, % perdidos) con el ping de Windows."""
    o = _correr(["ping", "-n", str(n), "-w", "1000", host], n * 2 + 5)
    ms = [int(x) for x in re.findall(r"[=<](\d+)ms", o)]
    if not o: return None, None
    return (round(statistics.mean(ms)) if ms else None), 100 * (n - len(ms)) / n

def servidor_juego(pid):
    """IP remota con más conexiones del juego (sin contar la red de la casa)."""
    try:
        ips = [c.raddr.ip for c in psutil.Process(pid).net_connections(kind="inet")
               if c.raddr and not re.match(r"^(127\.|10\.|192\.168\.|172\.(1[6-9]|2\d|3[01])\.|::1|fe80|0\.)", c.raddr.ip)]
        return max(set(ips), key=ips.count) if ips else None
    except Exception:
        return None

def temp_cpu():
    """Temperatura del procesador desde LibreHardwareMonitor (servidor web en el puerto 8085), si está abierto."""
    try:
        j = json.loads(urllib.request.urlopen("http://localhost:8085/data.json", timeout=2).read().decode())
        pila = [j]
        while pila:
            n = pila.pop()
            if n.get("Type") == "Temperature" and re.search(r"CPU Package|Core Max", n.get("Text", "")):
                return float(re.sub(r"[^\d.,]", "", n["Value"]).replace(",", "."))
            pila += n.get("Children", [])
    except Exception:
        pass
    return None

def muestrear(pid, est):
    m = nvsmi()
    try:  # lectura de disco del juego (MB/s desde la muestra anterior)
        io = psutil.Process(pid).io_counters().read_bytes
        if est.get("io") is not None:
            m["disco_mbs"] = round((io - est["io"]) / 1048576 / max(1, time.time() - est["t"]), 1)
        est["io"], est["t"] = io, time.time()
    except Exception:
        pass
    if est.get("lhm", True):  # si LibreHardwareMonitor no contestó la primera vez, no se insiste
        t = temp_cpu()
        if t is None: est["lhm"] = False
        else: m["cpu_temp"] = t
    est["n"] = est.get("n", 0) + 1
    if est["n"] % 6 == 1:  # cada ~30 s: conexión
        ip = servidor_juego(pid) or est.get("ip")
        if ip:
            est["ip"] = ip
            m["ping_srv"], m["perdida_srv"] = ping(ip)
        m["ping_inet"], m["perdida_inet"] = ping("1.1.1.1")
    nucleos = psutil.cpu_percent(interval=None, percpu=True)
    if nucleos:
        m["cpu"], m["cpu_nucleo_max"] = round(sum(nucleos) / len(nucleos), 1), max(nucleos)
    vm = psutil.virtual_memory()
    m["ram"], m["ram_libre_gb"] = vm.percent, round(vm.available / 1073741824, 2)
    try: m["swap"] = psutil.swap_memory().percent  # archivo de paginación: si sube, la RAM no alcanza y Windows usa el disco
    except Exception: pass
    try:
        pr = est.get("proc") or psutil.Process(pid)
        if "proc" not in est:
            est["proc"] = pr; pr.cpu_percent(None)  # la primera lectura solo arranca la cuenta
        else:
            m["juego_cpu"] = round(pr.cpu_percent(None) / (psutil.cpu_count() or 1), 1)
        m["juego_ram_gb"] = pr.memory_info().rss / 1073741824
    except Exception: pass
    try:  # red de toda la PC (bajada y subida en MB/s desde la muestra anterior)
        n, ahora = psutil.net_io_counters(), time.time()
        if est.get("red"):
            dt = max(1, ahora - est["red"][2])
            m["red_baja"], m["red_sube"] = round((n.bytes_recv - est["red"][0]) / 1048576 / dt, 2), round((n.bytes_sent - est["red"][1]) / 1048576 / dt, 2)
        est["red"] = (n.bytes_recv, n.bytes_sent, ahora)
    except Exception: pass
    m["t"] = time.time()
    return m

def hz_monitor():
    """Hz del monitor principal (para saber si V-Sync frena o si sobran FPS)."""
    try:
        class DM(ctypes.Structure):
            _fields_ = [("a", ctypes.c_wchar * 32), ("b", ctypes.c_ushort * 4), ("c", ctypes.c_ulong), ("d", ctypes.c_byte * 16),
                        ("e", ctypes.c_short * 5), ("f", ctypes.c_wchar * 32), ("g", ctypes.c_ushort), ("bits", ctypes.c_ulong),
                        ("ancho", ctypes.c_ulong), ("alto", ctypes.c_ulong), ("flags", ctypes.c_ulong), ("hz", ctypes.c_ulong), ("resto", ctypes.c_byte * 32)]
        d = DM(); d.b[2] = ctypes.sizeof(DM)  # dmSize (b = dmSpecVersion, dmDriverVersion, dmSize, dmDriverExtra)
        if ctypes.windll.user32.EnumDisplaySettingsW(None, -1, ctypes.byref(d)): return int(d.hz) or None
    except Exception:
        pass
    return None

def tiempos_cpu():
    t = {}
    for p in psutil.process_iter(["name", "cpu_times"]):
        ct = p.info.get("cpu_times")
        if ct: t[p.pid] = (p.info["name"], ct.user + ct.system)
    return t

def fondo(antes, despues, pid_juego, seg):
    """Programas que más procesador gastaron durante la partida (sin contar el juego)."""
    uso = {}
    for pid, (nom, t1) in despues.items():
        if pid == pid_juego or pid not in antes or not nom or nom.lower() in ("system idle process", "system"):
            continue
        uso[nom] = uso.get(nom, 0) + max(0, t1 - antes[pid][1])
    nucleos = psutil.cpu_count() or 1
    top = sorted(uso.items(), key=lambda x: -x[1])[:4]
    return [{"programa": n, "cpu": round(100 * t / (seg * nucleos), 1)} for n, t in top if t / seg * 100 / nucleos >= 0.5]

def cierre_con_error(exe, inicio):
    """¿Windows anotó un cierre con error de ese programa (eventos 1000/1002 de Aplicación) durante la partida?"""
    cmd = ("Get-WinEvent -FilterHashtable @{LogName='Application';Id=1000,1002;StartTime=(Get-Date '%s')} -ea 0 | "
           "?{$_.Properties[0].Value -eq '%s'} | measure | select -expand Count") % (
        datetime.datetime.fromtimestamp(inicio).strftime("%Y-%m-%d %H:%M:%S"), os.path.basename(exe).replace("'", "''"))
    try: return int(_correr(["powershell", "-NoProfile", "-Command", cmd], 60) or 0) > 0
    except ValueError: return False

# ---------- resumen y semáforo ----------
def evaluar(s, previas):
    """Compara la partida contra lo normal de ESE juego y deja estado (verde, amarillo, rojo) y causas en lenguaje simple."""
    causas, rojo = [], False
    fps_prev = [p["fps"] for p in previas if p.get("fps")]
    if len(fps_prev) >= 2 and s.get("fps"):
        normal = statistics.median(fps_prev[-10:])
        s["fpsNormal"] = round(normal, 1)
        caida = 1 - s["fps"] / normal
        if caida >= 0.30:
            rojo = True; causas.append("FPS %d%% más bajos que lo normal de este juego" % round(caida * 100))
        elif caida >= 0.15:
            causas.append("FPS %d%% más bajos que lo normal de este juego" % round(caida * 100))
    if causas and previas:  # ¿coincide con un driver nuevo o una actualización del juego?
        a = previas[-1]
        if a.get("driver") and s.get("driver") and a["driver"] != s["driver"]:
            causas.append("Coincide con el driver nuevo de NVIDIA (%s → %s)" % (a["driver"], s["driver"]))
        if a.get("version") and s.get("version") and a["version"] != s["version"]:
            causas.append("Coincide con una actualización del juego")
    if s.get("cerroConError"):
        rojo = True; causas.append("El juego se cerró con error (quedó registrado en Windows)")
    if s.get("frenoCalorPct", 0) >= 10:
        rojo = True; causas.append("La placa se frenó por calor el %d%% del tiempo: revisar polvo y ventilación" % s["frenoCalorPct"])
    if s.get("gpuTempMax", 0) > 83:
        causas.append("La placa llegó a %d °C" % s["gpuTempMax"])
    if s.get("fps") and s.get("fps1low") and s["fps1low"] / s["fps"] < 0.5:
        causas.append("Muchos tirones: el 1 %% más lento (%s FPS) es menos de la mitad del promedio" % s["fps1low"])
    if s.get("tironesMin", 0) > 5:
        causas.append("%s tirones por minuto (cuadros de más de 50 ms)" % s["tironesMin"])
    if s.get("vramMaxPct", 0) >= 95:
        causas.append("Memoria de video llena (%s %%): bajar las texturas un punto" % s["vramMaxPct"])
    if s.get("ramMax", 0) >= 90:
        causas.append("RAM casi llena (%s %%): cerrar programas de fondo" % s["ramMax"])
    # cuello de botella: la placa por debajo del 80 % sin que el juego esté topeado (topeado = FPS muy parejos)
    if s.get("fps") and s.get("gpuUso") is not None and s["gpuUso"] < 80 and s.get("fps1low", 0) < s["fps"] * 0.9:
        if s.get("cpuNucleoMax", 0) >= 90:
            causas.append("Limita el procesador: un núcleo al %d %% y la placa solo al %d %%" % (s["cpuNucleoMax"], s["gpuUso"]))
        else:
            causas.append("La placa trabaja al %d %%: algo la limita (procesador o el propio juego)" % s["gpuUso"])
    if s.get("cpuTempMax", 0) >= 90:
        causas.append("El procesador llegó a %d °C: puede estar frenándose por calor" % s["cpuTempMax"])
    if s.get("perdidaInternet", 0) >= 5:
        causas.append("Internet perdió %s %% de paquetes: el lag es de la conexión, no de la PC" % s["perdidaInternet"])
    elif s.get("pingInternetMax", 0) >= 150:
        causas.append("Picos de ping de %d ms (lag de la conexión)" % s["pingInternetMax"])
    if s.get("perdidaServidor", 0) >= 5 and s.get("perdidaInternet", 0) < 5:
        causas.append("El servidor del juego perdió %s %% de paquetes (problema del servidor, no tuyo)" % s["perdidaServidor"])
    if s.get("tironesMin", 0) > 5 and s.get("discoMBsMax", 0) >= 100:
        causas.append("El juego leyó hasta %d MB/s del disco: los tirones pueden ser de carga" % s["discoMBsMax"])
    tc = s.get("tironesCon") or {}
    if s.get("tironesMin", 0) > 5:
        porque = {"disco": "el disco cargando (texturas o sombreadores): si el juego está en un disco rígido, pasarlo a un SSD",
                  "procesador": "el procesador al tope: bajar distancia de visión, multitudes o física",
                  "vram": "la memoria de video llena: bajar las texturas un punto",
                  "ram": "la RAM casi llena: cerrar programas de fondo",
                  "descarga": "algo bajando de internet: pausar descargas mientras jugás",
                  "freno": "la placa frenándose por calor o energía"}
        for k, txt in sorted(porque.items(), key=lambda x: -tc.get(x[0], 0)):
            if tc.get(k, 0) >= 30:
                causas.append("El %d %% de los tirones pasó con %s" % (tc[k], txt))
        if s.get("tironesInicioPct", 0) >= 60:
            causas.append("Casi todos los tirones fueron al empezar (%d %%): el juego armaba sombreadores, después se normaliza" % s["tironesInicioPct"])
    # ¿quién frena? según cuánto del cuadro estuvo trabajando la placa
    po = s.get("placaOcupada")
    if po is not None and s.get("fps"):
        if po >= 90 and (s.get("gpuUso") or 0) >= 90:
            causas.append("Frena la placa de video (ocupada el %d %% de cada cuadro): bajar calidad o resolución, o activar DLSS/FSR" % po)
    # configuración de pantalla
    hz, fps = s.get("hz"), s.get("fps")
    if s.get("vsync") and hz and fps and fps < hz * 0.9 and s.get("tironesMin", 0) > 3:
        causas.append("V-Sync activado sin llegar a los %d Hz del monitor: los cuadros se esperan y se traban. Apagarlo en el juego (con G-SYNC queda suave igual)" % hz)
    if "composed" in (s.get("modoPantalla") or "").lower():
        causas.append("El juego se dibuja como ventana compuesta por Windows: suma demora. Probar Pantalla completa en el juego")
    if hz and fps and fps > hz * 1.5 and not s.get("vsync"):
        causas.append("Hacés %d FPS con un monitor de %d Hz: limitar a %d FPS baja calor y consumo sin que se note" % (fps, hz, hz))
    if (s.get("redBaja") or 0) >= 1 and s.get("tironesMin", 0) > 3:
        causas.append("Durante la partida se bajaban %s MB/s de internet en promedio: pausar descargas mientras jugás" % s["redBaja"])
    if (s.get("swapMax") or 0) >= 80 or (s.get("ramLibreMinGB") or 99) < 1:
        causas.append("La memoria no alcanzó (quedó %s GB libre): Windows usó el disco como RAM" % s.get("ramLibreMinGB"))
    pesados = [f for f in s.get("fondo", []) if f["cpu"] >= 3]
    if pesados and causas:
        causas.append("De fondo gastaban procesador: " + ", ".join("%s (%s %%)" % (f["programa"], f["cpu"]) for f in pesados))
    s["estado"] = "rojo" if rojo else ("amarillo" if causas else "verde")
    s["causas"] = causas
    return s

def resumir(csv_fps, muestras, g, exe, inicio, fin, fondo_cpu, error, version, drv, pm_ok, pid=None):
    dur = fin - inicio
    tiempos, momentos, ocupada, modos, sync = [], [], [], {}, {}
    try:
        with open(csv_fps, newline="", encoding="utf-8", errors="ignore") as f:
            for r in csv.DictReader(f):
                try:  # PresentMon 2 con --v1_metrics escribe "msBetweenPresents" (con minúscula); sin esa opción, "FrameTime"
                    r = {k.lower(): v for k, v in r.items() if k}
                    if pid and r.get("processid") != str(pid) and (r.get("application") or "").lower() != os.path.basename(exe).lower():
                        continue  # se graba todo lo que se dibuja: se cuenta solo el juego
                    v = float(r.get("msbetweenpresents") or r.get("frametime") or "")
                    if not 0 < v < 30000: continue  # los congelamientos de varios segundos también cuentan (son los peores tirones)
                    tiempos.append(v)
                    if v > 50: momentos.append(float(r.get("timeinseconds") or 0))  # cuándo fue cada tirón
                    g_act = r.get("msgpuactive")
                    if g_act: ocupada.append(min(1.0, float(g_act) / v))  # parte del cuadro con la placa trabajando
                    m_ = r.get("presentmode") or ""; modos[m_] = modos.get(m_, 0) + 1
                    si = r.get("syncinterval") or ""; sync[si] = sync.get(si, 0) + 1
                except ValueError:
                    pass
    except OSError:
        pass
    s = {"fecha": datetime.datetime.fromtimestamp(inicio).strftime("%Y-%m-%d %H:%M"), "juego": g.get("name"), "exe": os.path.basename(exe),
         "minutos": round(dur / 60, 1), "cerroConError": error, "fondo": fondo_cpu, "driver": drv, "version": version}
    if len(tiempos) > 100:
        t = sorted(tiempos)
        s["fps"] = round(1000 / statistics.mean(t), 1)
        s["fps1low"] = round(1000 / statistics.mean(t[int(len(t) * 0.99):]), 1)
        s["tirones"] = sum(1 for x in t if x > 50)
        s["tironesMin"] = round(s["tirones"] / (dur / 60), 1)
        if ocupada: s["placaOcupada"] = round(100 * statistics.median(ocupada))  # ~100 = frena la placa; bajo = frena el procesador o el juego
        if modos: s["modoPantalla"] = max(modos, key=modos.get)
        if sync: s["vsync"] = max(sync, key=sync.get) not in ("", "0")
        if momentos:  # tirones de la primera minuto y medio (sombreadores que se arman al entrar)
            s["tironesInicioPct"] = round(100 * sum(1 for x in momentos if x < 90) / len(momentos))
            s["tironesCon"] = _tirones_con(momentos, muestras, inicio)
    elif not pm_ok:
        s["sinFps"] = True  # PresentMon no tuvo permiso (falta el grupo "Performance Log Users")
    col = lambda k: [m[k] for m in muestras if m.get(k) is not None]
    for k, nom in (("gpu_uso", "gpuUso"), ("gpu_temp", "gpuTemp"), ("gpu_w", "gpuW"), ("cpu", "cpuUso"), ("cpu_nucleo_max", "cpuNucleoMax"), ("ram", "ram")):
        v = col(k)
        if v: s[nom], s[nom + "Max"] = round(statistics.mean(v), 1), round(max(v), 1)
    vr, tot = col("vram"), col("vram_total")
    if vr and tot: s["vramMaxGB"], s["vramMaxPct"] = round(max(vr) / 1024, 1), round(100 * max(vr) / tot[0])
    fr = col("frenos")
    if fr:
        s["frenoCalorPct"] = round(100 * sum(1 for x in fr if x & CALOR) / len(fr))
        s["frenoEnergiaPct"] = round(100 * sum(1 for x in fr if x & ENERGIA) / len(fr))
    jr = col("juego_ram_gb")
    if jr: s["juegoRamGB"] = round(max(jr), 1)
    dk = col("disco_mbs")
    if dk: s["discoMBs"], s["discoMBsMax"] = round(statistics.mean(dk), 1), round(max(dk), 1)
    ct = col("cpu_temp")
    if ct: s["cpuTemp"], s["cpuTempMax"] = round(statistics.mean(ct), 1), round(max(ct), 1)
    for k, nom in (("ping_srv", "pingServidor"), ("ping_inet", "pingInternet")):
        v = col(k)
        if v: s[nom], s[nom + "Max"] = round(statistics.mean(v)), max(v)
    for k, nom in (("perdida_srv", "perdidaServidor"), ("perdida_inet", "perdidaInternet")):
        v = col(k)
        if v: s[nom] = round(statistics.mean(v), 1)
    for k, nom in (("juego_cpu", "juegoCpu"), ("red_baja", "redBaja"), ("red_sube", "redSube"), ("swap", "swap")):
        v = col(k)
        if v: s[nom], s[nom + "Max"] = round(statistics.mean(v), 1), round(max(v), 1)
    rl = col("ram_libre_gb")
    if rl: s["ramLibreMinGB"] = round(min(rl), 1)
    hz = hz_monitor()
    if hz: s["hz"] = hz
    return evaluar(s, historial(g["id"]))

def _tirones_con(momentos, muestras, inicio):
    """Para cada tirón, qué pasaba en la muestra más cercana (cada 5 s). Devuelve % de tirones con cada cosa."""
    if not muestras: return {}
    disco_normal = statistics.median([m.get("disco_mbs") or 0 for m in muestras]) or 1
    cuenta, n = {}, 0
    for t in momentos:
        m = min(muestras, key=lambda x: abs(x.get("t", 0) - (inicio + t)))
        if abs(m.get("t", 0) - (inicio + t)) > 8: continue
        n += 1
        marcas = []
        if (m.get("disco_mbs") or 0) >= max(60, disco_normal * 3): marcas.append("disco")
        if (m.get("cpu_nucleo_max") or 0) >= 95: marcas.append("procesador")
        if m.get("vram") and m.get("vram_total") and m["vram"] / m["vram_total"] >= 0.95: marcas.append("vram")
        if (m.get("ram_libre_gb") or 99) < 1: marcas.append("ram")
        if (m.get("red_baja") or 0) >= 2: marcas.append("descarga")
        if (m.get("frenos") or 0) & (CALOR | ENERGIA): marcas.append("freno")
        for x in marcas: cuenta[x] = cuenta.get(x, 0) + 1
    return {k: round(100 * v / n) for k, v in cuenta.items()} if n else {}

# ---------- una partida ----------
def _proceso_principal(carpeta):
    """El proceso del juego: dentro de su carpeta, más de 300 MB de RAM, y que no sea launcher, anticheat ni ayudante."""
    pref = os.path.normcase(carpeta.rstrip("\\") + "\\")
    mejor = None
    for p in psutil.process_iter(["name", "exe", "memory_info"]):
        exe = p.info.get("exe") or ""
        if not exe or not os.path.normcase(exe).startswith(pref) or any(x in (p.info["name"] or "").lower() for x in NO_JUEGO):
            continue
        mem = p.info["memory_info"].rss if p.info.get("memory_info") else 0
        if mem > 300 * 1048576 and (not mejor or mem > mejor[1]):
            mejor = (p.pid, mem, exe)
    return mejor

def _limpiar_sesiones():
    """Cierra sesiones de PresentMon que quedaron colgadas en Windows (si PresentMon se cerró a la fuerza, su sesión
    sigue corriendo). Con sesiones colgadas, las nuevas perdían todos los eventos y la partida quedaba sin FPS."""
    o = _correr(["logman", "query", "-ets"], timeout=10) or ""
    vivas = {"TandemStacks_%d" % i for i in _activos_pid}
    for n in re.findall(r"^(TandemStacks_\d+)\s", o, re.M):
        if n not in vivas:
            _correr(["logman", "stop", n, "-ets"], timeout=10)
            _log("sesión colgada cerrada:", n)

_activos_pid = set()  # pids de juegos que se están midiendo ahora (sus sesiones no se tocan)

def medir(g, al_terminar=None):
    """Hilo de una partida: espera el proceso principal (hasta 3 min), mide hasta que se cierra y guarda el resumen."""
    try:
        pp = None
        for _ in range(36):
            pp = _proceso_principal(g["dir"])
            if pp: break
            time.sleep(5)
        if not pp:
            return
        pid, _, exe = pp
        os.makedirs(TMP, exist_ok=True)
        csv_fps = os.path.join(TMP, "fps_%d.csv" % pid)
        _limpiar_sesiones()
        _activos_pid.add(pid)
        pm, sesion = None, "TandemStacks_%d" % pid
        pm_txt = os.path.join(TMP, "pm_%d.txt" % pid)
        if os.path.exists(PM):
            try:
                # graba todo lo que se dibuja y después se filtra por el proceso del juego: pedirle solo el juego
                # (--process_id) no grababa nada cuando Windows no le deja identificar el proceso (juegos con anti-trampas)
                with open(pm_txt, "w") as salida:
                    pm = subprocess.Popen([PM, "--output_file", csv_fps, "--session_name", sesion, "--stop_existing_session",
                                           "--no_console_stats", "--v1_metrics"],
                                          stdout=salida, stderr=salida, creationflags=SIN_VENTANA)
                # prioridad normal a propósito: con prioridad baja, con el juego usando el procesador, PresentMon
                # no alcanzaba a leer los eventos de Windows, los perdía todos y la partida quedaba sin FPS
            except OSError as e:
                _log("presentmon", e)
        inicio, muestras, cpu0, est = time.time(), [], tiempos_cpu(), {}
        version, drv = version_juego(g), driver()
        psutil.cpu_percent(interval=None, percpu=True)
        while psutil.pid_exists(pid):
            time.sleep(MUESTRA)
            try: muestras.append(muestrear(pid, est))
            except Exception as e: _log("muestra", e)
        fin = time.time()
        pm_ok = False
        if pm:
            try:  # se le pide que cierre ordenado (así escribe lo último que tenía); si no responde, se mata
                subprocess.run([PM, "--terminate_existing_session", "--session_name", sesion], timeout=15,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=SIN_VENTANA)
                pm.wait(timeout=15)
            except Exception:
                pm.kill()
            pm_ok = os.path.exists(csv_fps)
            if not pm_ok:
                try:  # PresentMon escribe en UTF-16; lo útil está al final (eventos perdidos, errores)
                    crudo = open(pm_txt, "rb").read()
                    txt = crudo.decode("utf-16", "ignore") if crudo[:2] in (b"\xff\xfe", b"\xfe\xff") else crudo.decode("utf-8", "ignore")
                    _log("presentmon sin datos:", " ".join(txt.split())[-300:])
                except OSError: pass
        if fin - inicio >= MIN_SEG:
            s = resumir(csv_fps, muestras, g, exe, inicio, fin, fondo(cpu0, tiempos_cpu(), pid, fin - inicio),
                        cierre_con_error(exe, inicio), version, drv, pm_ok, pid)
            try:  # si TandemStacks ajustó NVIDIA para este juego, queda anotado en la partida (para comparar antes/después)
                from . import nvidia
                a = nvidia.aplicado(g["id"])
                if a: s["nvidia"] = "; ".join(a["que"])
                from . import escalera
                p = escalera.en_prueba(g["id"])
                if p: s["paso"] = p  # el paso de la escalera que se estaba probando en esta partida
            except Exception: pass
            _guardar(g["id"], s)
            _log("guardado", g.get("name"), s["estado"], "; ".join(s["causas"]))
            if al_terminar:
                try: al_terminar(g, s)
                except Exception as e: _log("aviso", e)
        for f in (csv_fps, pm_txt):
            try: os.remove(f)
            except OSError: pass
        _activos_pid.discard(pid)
    except Exception as e:
        _log("medir", g.get("name"), e)
    finally:
        _activos.discard(g["id"])

def empezar(g, al_terminar=None):
    if g["id"] in _activos or not g.get("dir"):
        return
    _activos.add(g["id"])  # se marca acá, antes del hilo, para no lanzar dos mediciones del mismo juego
    threading.Thread(target=medir, args=(g, al_terminar), daemon=True).start()
