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
import io, os, re, csv, json, glob, time, ctypes, datetime, statistics, subprocess, threading, collections, urllib.request
import psutil
from . import paths, afterburner

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

def nvsmi(guardada=False):
    """guardada=True (relojes con un juego abierto): devuelve la última muestra de Pulso sin abrir nvidia-smi otra vez."""
    if time.time() - _nv_ultimo[0] < (20 if guardada else 3): return dict(_nv_ultimo[1])
    if guardada: return None
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

def _procesos_juego(pid, est):
    """Todos los procesos del juego (los de su carpeta, más el principal). Se buscan cada ~30 s: algunos juegos
    abren procesos aparte para dibujar o para el audio."""
    if est.get("n", 0) % 6 == 0 or "pids" not in est:
        pids = {pid}
        pref = os.path.normcase((est.get("dir") or "").rstrip("\\") + "\\")
        if len(pref) > 3:
            for p in psutil.process_iter(["exe"]):
                exe = p.info.get("exe") or ""
                if exe and os.path.normcase(exe).startswith(pref): pids.add(p.pid)
        est["pids"] = pids
    return est["pids"]

def _juego_solo(pid, est, m):
    """Lo que usa SOLO el juego (pedido del dueño 15/11/2026: los datos tienen que ser del juego, no de la PC).
    Procesador total y su hilo más ocupado (un hilo al 100 % = un núcleo al tope: lo que frena en los juegos), RAM,
    lectura de disco, placa y memoria de video. Lo de toda la PC queda en *_pc para comparar."""
    pids, ahora = _procesos_juego(pid, est), time.time()
    dt = ahora - est["tj"] if est.get("tj") else 0
    cpu = ram = lee = 0.0
    hilos, prev, nuevo = 0.0, est.get("hilos", {}), {}
    for q in pids:
        try:
            pr = psutil.Process(q)
            with pr.oneshot():
                ct, io = pr.cpu_times(), pr.io_counters()
                ram += pr.memory_info().rss
                nuevo[q] = (ct.user + ct.system, io.read_bytes, pr.create_time(),
                            {t.id: t.user_time + t.system_time for t in pr.threads()})
            a = prev.get(q)
            if a and a[2] == nuevo[q][2] and dt > 0:
                cpu += (nuevo[q][0] - a[0]) / dt
                lee += (nuevo[q][1] - a[1]) / dt
                for tid, t in nuevo[q][3].items():
                    if tid in a[3]: hilos = max(hilos, (t - a[3][tid]) / dt)
        except Exception:
            pass
    est["hilos"], est["tj"] = nuevo, ahora
    if dt > 0:
        m["cpu"] = round(min(100, 100 * cpu / (psutil.cpu_count() or 1)), 1)
        m["juego_cpu"] = m["cpu"]
        m["cpu_nucleo_max"] = round(min(100, 100 * hilos), 1)
        m["disco_mbs"] = round(max(0, lee) / 1048576, 1)
    m["juego_ram_gb"] = ram / 1073741824
    m["ram"] = round(100 * ram / psutil.virtual_memory().total, 1)
    try:
        from . import relojes
        pj = relojes.placa_juego(pids)
    except Exception:
        pj = None
    if pj:
        if "gpu_uso" in m: m["gpu_uso_pc"] = m["gpu_uso"]
        if "vram" in m: m["vram_pc"] = m["vram"]
        m["gpu_uso"], m["vram"] = pj["gpu"], pj["vram_mb"]
    m["solo_juego"] = True

def muestrear(pid, est):
    m = nvsmi()
    ab = afterburner.leer()  # MSI Afterburner abierto: temperatura del procesador y, si no es NVIDIA, de la placa
    if ab:
        if "cpuTemp" in ab: m["cpu_temp"] = ab["cpuTemp"]
        for k, nom in (("cpuMHz", "cpu_mhz"), ("cpuW", "cpu_w"), ("gpuFan", "gpu_fan")):
            if k in ab: m[nom] = ab[k]
        if "frenos" not in m and ("limTemp" in ab or "limPot" in ab):  # placas que no son NVIDIA: el freno lo dice Afterburner
            m["frenos"] = (CALOR if ab.get("limTemp") else 0) | (ENERGIA if ab.get("limPot") else 0)
        if "gpu_temp" not in m and "gpuTemp" in ab: m["gpu_temp"], m["gpu_w"] = ab["gpuTemp"], ab.get("gpuW", 0)
    if "cpu_temp" not in m and est.get("lhm", True):  # si LibreHardwareMonitor no contestó la primera vez, no se insiste
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
    if nucleos:  # toda la PC, para comparar
        m["cpu_pc"], m["cpu_nucleo_max_pc"] = round(sum(nucleos) / len(nucleos), 1), max(nucleos)
    vm = psutil.virtual_memory()
    m["ram_pc"], m["ram_libre_gb"] = vm.percent, round(vm.available / 1073741824, 2)  # libre: ¿le alcanza la memoria al juego?
    try: m["swap"] = psutil.swap_memory().percent  # archivo de paginación: si sube, la RAM no alcanza y Windows usa el disco
    except Exception: pass
    _juego_solo(pid, est, m)
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
# ---------- criterio (reglas fijas, sin IA) ----------
# Objetivo de FPS: los Hz del monitor (hasta 144); sin dato, 60.
# Fluidez:      llega si los FPS promedio son ≥ 90 % del objetivo.
# Trabas:       hay problema si hay más de 5 tirones por minuto (cuadros de más de 50 ms) o si el 1 % más lento baja de 30 FPS.
# Quién frena:  solo cuando NO se llega al objetivo. Placa al tope (≥ 95 % o ocupada ≥ 90 % de cada cuadro) → la placa;
#               un núcleo del procesador ≥ 90 % o placa ocupada ≤ 60 % → el procesador; si no, el propio juego (motor o límite de FPS).
# Sobra placa:  si se llega al objetivo y la placa trabaja < 75 % (y la memoria de video no está llena) → consejo de subir gráficos.
# Semáforo:     rojo = se cerró con error, frenos por calor o FPS 30 % abajo de lo normal; amarillo = algún problema; verde = ninguno.
#               Los consejos (subir gráficos, limitar FPS…) no cambian el color.
def objetivo_fps(s):
    hz = s.get("hz")
    return min(int(hz), 144) if hz else 60

def evaluar(s, previas):
    """Compara la partida contra el objetivo y contra lo normal de ESE juego: estado, causas (problemas) y consejos."""
    causas, consejos, rojo = [], [], False
    fps, low, tir = s.get("fps"), s.get("fps1low"), s.get("tironesMin") or 0
    obj, hz = objetivo_fps(s), s.get("hz")
    s["objetivo"] = obj
    fps_prev = [p["fps"] for p in previas if p.get("fps") and p.get("fiable", True)]  # solo partidas fiables
    if len(fps_prev) >= 2 and fps and s.get("fiable", True):
        normal = statistics.median(fps_prev[-10:])
        s["fpsNormal"] = round(normal, 1)
        caida = 1 - fps / normal
        if caida >= 0.30:
            rojo = True; causas.append("FPS %d %% más bajos que lo normal de este juego" % round(caida * 100))
        elif caida >= 0.15:
            causas.append("FPS %d %% más bajos que lo normal de este juego" % round(caida * 100))
    if causas and previas:  # ¿coincide con un driver nuevo o una actualización del juego?
        a = previas[-1]
        if a.get("driver") and s.get("driver") and a["driver"] != s["driver"]:
            causas.append("Coincide con el driver nuevo de NVIDIA (%s → %s)" % (a["driver"], s["driver"]))
        if a.get("version") and s.get("version") and a["version"] != s["version"]:
            causas.append("Coincide con una actualización del juego")
    if s.get("cerroConError"):
        rojo = True; causas.append("El juego se cerró con error (quedó registrado en Windows)")
    if s.get("frenoCalorPct", 0) >= 10:
        rojo = True; causas.append("La placa se frenó por calor el %d %% del tiempo: revisar polvo y ventilación" % s["frenoCalorPct"])
    if s.get("gpuTempMax", 0) > 83:
        causas.append("La placa llegó a %d °C (más de 83 °C)" % s["gpuTempMax"])
    if s.get("cpuTempMax", 0) >= 90:
        causas.append("El procesador llegó a %d °C: puede estar frenándose por calor" % s["cpuTempMax"])
    # trabas
    if tir > 5:
        causas.append("%s tirones por minuto (cuadros de más de 50 ms; más de 5 se notan)" % tir)
    if low is not None and low < 30:
        causas.append("El 1 %% más lento baja a %s FPS: por debajo de 30 se notan trabas" % low)
    tc = s.get("tironesCon") or {}
    if tir > 5:
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
        if s.get("discoMBsMax", 0) >= 100 and "disco" not in tc:
            causas.append("El juego leyó hasta %d MB/s del disco: los tirones pueden ser de carga" % s["discoMBsMax"])
    # fluidez y quién frena
    gpu, po, cpu1 = s.get("gpuUso"), s.get("placaOcupada"), s.get("cpuNucleoMax") or 0
    if fps:
        if fps >= obj * 0.9:
            s["frena"] = "nada"
            if gpu is not None and gpu < 75 and (s.get("vramPcMaxPct", s.get("vramMaxPct")) or 0) < 90:
                s["frena"] = "sobra"
                consejos.append("Llegás a %d FPS (objetivo %d) con la placa al %d %%: le sobra. Podés subir gráficos (texturas, sombras o resolución) mientras no bajes de %d FPS" % (fps, obj, gpu, round(obj * 0.9)))
        else:
            falta = "No llega a los %d FPS del objetivo (hace %d)" % (obj, fps)
            if (gpu or 0) >= 95 or (po or 0) >= 90:
                s["frena"] = "placa"
                cual = ("al %d %%" % gpu) if (gpu or 0) >= 95 else ("trabajó el %d %% de cada cuadro" % po)  # el dato que la delató
                causas.append(falta + ": frena la placa (%s). Bajar calidad o resolución, o activar DLSS/FSR" % cual)
            elif cpu1 >= 90 or (po is not None and po <= 60):
                s["frena"] = "procesador"
                causas.append(falta + ": frena el procesador (" + ("el hilo principal del juego" if s.get("soloJuego") else "un núcleo") + " al %d %%, la placa al %d %%). Bajar distancia de visión, multitudes o física" % (cpu1, gpu or 0))
            else:
                s["frena"] = "juego"
                causas.append(falta + ": ni la placa (%d %%) ni el procesador están al tope; puede ser el propio juego o un límite de FPS" % (gpu or 0))
    vlleno = s.get("vramPcMaxPct", s.get("vramMaxPct")) or 0  # la placa entera (desde el 15/11/2026 vramMaxPct es solo del juego)
    if vlleno >= 95:
        causas.append("Memoria de video llena (%s %%): bajar las texturas un punto" % vlleno)
    if (s.get("ramMax") or 0) >= 90:
        causas.append("RAM casi llena (%s %%): cerrar programas de fondo" % s["ramMax"])
    if (s.get("swapMax") or 0) >= 80 or (s.get("ramLibreMinGB") or 99) < 1:
        causas.append("La memoria no alcanzó (quedó %s GB libre): Windows usó el disco como RAM" % s.get("ramLibreMinGB"))
    # pantalla
    if s.get("vsync") and hz and fps and fps < hz * 0.9 and tir > 3:
        causas.append("V-Sync activado sin llegar a los %d Hz del monitor: los cuadros se esperan y se traban. Apagarlo en el juego (con G-SYNC queda suave igual)" % hz)
    if "composed" in (s.get("modoPantalla") or "").lower() and (tir > 3 or (fps and fps < obj * 0.9)):
        consejos.append("El juego está en modo ventana o sin bordes: en Pantalla completa suele andar un poco más fluido")
    if hz and fps and fps > hz * 1.5 and not s.get("vsync"):
        consejos.append("Hacés %d FPS con un monitor de %d Hz: limitar a %d FPS baja calor y consumo sin que se note" % (fps, hz, hz))
    # conexión
    if s.get("perdidaInternet", 0) >= 5:
        causas.append("Internet perdió %s %% de paquetes: el lag es de la conexión, no de la PC" % s["perdidaInternet"])
    elif s.get("pingInternetMax", 0) >= 150:
        causas.append("Picos de ping de %d ms (lag de la conexión)" % s["pingInternetMax"])
    if 5 <= s.get("perdidaServidor", 0) < 95 and s.get("perdidaInternet", 0) < 5:  # ~100 % = el servidor no contesta pings (los bloquea), no es pérdida
        causas.append("El servidor del juego perdió %s %% de paquetes (problema del servidor, no tuyo)" % s["perdidaServidor"])
    if (s.get("redBaja") or 0) >= 1 and tir > 3:
        causas.append("Durante la partida se bajaban %s MB/s de internet en promedio: pausar descargas mientras jugás" % s["redBaja"])
    pesados = [f for f in s.get("fondo", []) if f["cpu"] >= 3]
    if pesados and causas:
        causas.append("De fondo gastaban procesador: " + ", ".join("%s (%s %%)" % (f["programa"], f["cpu"]) for f in pesados))
    s["estado"] = "rojo" if rojo else ("amarillo" if causas else "verde")
    s["causas"], s["consejos"] = causas, consejos
    return s

def reevaluar(ps):
    """Las partidas guardadas con el criterio de hoy (así las viejas no quedan con reglas anteriores)."""
    out = []
    for i, p in enumerate(ps):
        t = {k: v for k, v in p.items() if k not in ("causas", "consejos", "fpsNormal", "estado", "frena", "objetivo")}
        out.append(evaluar(t, ps[:i]))
    return out

def resumir(csv_fps, muestras, g, exe, inicio, fin, fondo_cpu, error, version, drv, pm_ok, pid=None):
    dur = fin - inicio
    tiempos, momentos, ocupada, modos, sync = [], [], [], {}, {}
    try:
        with open(csv_fps, newline="", encoding="utf-8-sig", errors="ignore") as f:  # -sig: PresentMon empieza con BOM y "Application" no se reconocía
            lector = csv.reader(f)
            cab = [c.strip().strip("﻿").lower() for c in next(lector, [])]
            col = lambda n: cab.index(n) if n in cab else -1
            # PresentMon 2 con --v1_metrics escribe "msBetweenPresents" (con minúscula); sin esa opción, "FrameTime"
            i_v = col("msbetweenpresents") if col("msbetweenpresents") >= 0 else col("frametime")
            i_pid, i_app, i_t, i_gpu, i_modo, i_sync = (col("processid"), col("application"), col("timeinseconds"),
                                                       col("msgpuactive"), col("presentmode"), col("syncinterval"))
            spid, sexe = str(pid or ""), os.path.basename(exe).lower()
            n_col = len(cab)
            for n, r in enumerate(lector):
                if n % 20000 == 0: time.sleep(0)  # suelta el procesador a la ventana: leer millones de filas la trababa
                if i_v < 0 or len(r) < n_col: continue
                # índices y comparaciones directas (antes un diccionario por fila: 10 veces más lento)
                if pid and (i_pid < 0 or r[i_pid] != spid) and (i_app < 0 or r[i_app].lower() != sexe):
                    continue  # si se grabó todo lo que se dibuja: se cuenta solo el juego
                try:
                    v = float(r[i_v])
                    if not 0 < v < 30000: continue
                    tiempos.append(v)
                    momentos.append(float(r[i_t]) if i_t >= 0 and r[i_t] else 0.0)  # cuándo se dibujó cada cuadro
                    if i_gpu >= 0 and r[i_gpu]: ocupada.append(min(1.0, float(r[i_gpu]) / v))  # parte del cuadro con la placa trabajando
                    if i_modo >= 0: modos[r[i_modo]] = modos.get(r[i_modo], 0) + 1
                    if i_sync >= 0: sync[r[i_sync]] = sync.get(r[i_sync], 0) + 1
                except ValueError:
                    pass
    except OSError:
        pass
    s = {"fecha": datetime.datetime.fromtimestamp(inicio).strftime("%Y-%m-%d %H:%M"), "juego": g.get("name"), "exe": os.path.basename(exe),
         "minutos": round(dur / 60, 1), "cerroConError": error, "fondo": fondo_cpu, "driver": drv, "version": version}
    # Cálculo (reglas fijas):
    # - Cuadros de 2 s o más = pausa (pantalla de carga, menú, Alt+Tab): se cuentan aparte y NO entran en los FPS.
    # - FPS = cuadros / segundos jugados (no el promedio de los FPS de cada instante, que exagera).
    # - 1 % y 0,1 % más lentos = promedio del 1 % y 0,1 % de cuadros más largos, pasado a FPS.
    # - Tirón = cuadro de más de 50 ms y de más de 2,5 veces el cuadro típico (la mediana): a 20 FPS no todo es tirón.
    # - Tirones por minuto sobre los minutos jugados, no sobre el tiempo con el juego abierto.
    # - Cuadros parejos = % de cuadros que tardan menos de 1,5 veces el típico (100 % = imagen perfectamente pareja).
    # - Fiable si hay 2 minutos jugados y 3000 cuadros o más; si no, se muestra pero no cuenta como "lo normal".
    pausas = [x for x in tiempos if x >= 2000]
    if pausas: s["pausas"], s["pausasSeg"] = len(pausas), round(sum(pausas) / 1000)
    pares = [(x, m) for x, m in zip(tiempos, momentos) if x < 2000]
    t = sorted(x for x, _ in pares)
    if len(t) > 100:
        jugado = sum(t) / 1000
        med = statistics.median(t)
        s["minutosJugados"] = round(jugado / 60, 1)
        s["cuadros"] = len(t)
        s["fps"] = round(len(t) / jugado, 1)
        s["fpsTipico"] = round(1000 / med, 1)
        s["fps1low"] = round(1000 / statistics.mean(t[int(len(t) * 0.99):]), 1)
        s["fps01low"] = round(1000 / statistics.mean(t[int(len(t) * 0.999):]), 1)
        s["msPeor"] = round(t[-1])
        corte = max(50, med * 2.5)
        momentos = [m for x, m in pares if x > corte]  # cuándo fue cada tirón
        s["tirones"] = len(momentos)
        s["tironesMin"] = round(s["tirones"] / max(jugado / 60, 0.1), 1)
        s["parejos"] = round(100 * sum(1 for x in t if x < med * 1.5) / len(t), 1)
        s["fiable"] = jugado >= 120 and len(t) >= 3000
        if ocupada: s["placaOcupada"] = round(100 * statistics.median(ocupada))  # ~100 = frena la placa; bajo = frena el procesador o el juego
        if modos: s["modoPantalla"] = max(modos, key=modos.get)
        if sync: s["vsync"] = max(sync, key=sync.get) not in ("", "0")
        if momentos:  # tirones de la primera minuto y medio (sombreadores que se arman al entrar)
            s["tironesInicioPct"] = round(100 * sum(1 for x in momentos if x < 90) / len(momentos))
            s["tironesCon"] = _tirones_con(momentos, muestras, inicio)
    else:
        momentos = []
    if "fps" not in s and not pm_ok:
        s["sinFps"] = True  # PresentMon no tuvo permiso (falta el grupo "Performance Log Users")
    col = lambda k: [m[k] for m in muestras if m.get(k) is not None]
    for k, nom in (("gpu_uso", "gpuUso"), ("gpu_temp", "gpuTemp"), ("gpu_w", "gpuW"), ("cpu", "cpuUso"), ("cpu_nucleo_max", "cpuNucleoMax"), ("ram", "ram"),
                   ("gpu_uso_pc", "gpuPc"), ("cpu_pc", "cpuPc"), ("cpu_nucleo_max_pc", "cpuNucleoMaxPc"), ("ram_pc", "ramPc")):
        v = col(k)
        if v: s[nom], s[nom + "Max"] = round(statistics.mean(v), 1), round(max(v), 1)
    vr, tot = col("vram"), col("vram_total")
    if vr and tot: s["vramMaxGB"], s["vramMaxPct"] = round(max(vr) / 1024, 1), round(100 * max(vr) / tot[0])
    vp = col("vram_pc")  # la placa entera: si se llena, al juego le falta lugar aunque no sea todo suyo
    if vp and tot: s["vramPcMaxPct"] = round(100 * max(vp) / tot[0])
    if col("solo_juego"): s["soloJuego"] = True  # desde el 15/11/2026: procesador, RAM, disco, placa y VRAM son solo del juego
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
    for k, nom in (("cpu_mhz", "cpuMHz"), ("cpu_w", "cpuW"), ("gpu_fan", "gpuFan")):  # de MSI Afterburner, si estaba abierto
        v = col(k)
        if v: s[nom], s[nom + "Max"] = round(statistics.mean(v)), round(max(v))
    mh = col("cpu_mhz")
    if mh: s["cpuMHzMin"] = round(min(mh))
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
        vr = m.get("vram_pc", m.get("vram"))
        if vr and m.get("vram_total") and vr / m["vram_total"] >= 0.95: marcas.append("vram")
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
_vivo = {}            # pid: (_Lector de PresentMon, exe del juego), para el reloj de FPS

class _Lector(threading.Thread):
    """Lee lo que PresentMon manda por su salida (--output_stdout): PresentMon no deja leer su archivo mientras graba, así
    que el CSV lo escribe este hilo (si hace falta, para el resumen de la partida) y guarda los últimos cuadros en memoria
    para el reloj de FPS. Llegan de a tandas de ~1 s."""
    def __init__(self, proc, archivo=None):
        super().__init__(daemon=True)
        self.proc, self.archivo, self.t0 = proc, archivo, time.time()
        self.cuadros = collections.deque(maxlen=6000)  # (segundo, ms entre cuadros, programa, modo, descartado)
        self.start()
    def run(self):
        out = None
        try:
            if self.archivo: out = open(self.archivo, "w", encoding="utf-8", newline="")
            cab = None
            for linea in io.TextIOWrapper(self.proc.stdout, encoding="utf-8", errors="ignore"):
                if out: out.write(linea)
                r = linea.rstrip("\r\n").split(",")
                if cab is None:
                    cols = [c.strip().lstrip("﻿").lower() for c in r]
                    if "timeinseconds" in cols and "msbetweenpresents" in cols:
                        ix = lambda c: cols.index(c) if c in cols else -1
                        cab = (ix("timeinseconds"), ix("msbetweenpresents"), ix("application"), ix("presentmode"), ix("dropped"), ix("processid"), len(cols))
                    continue
                it, ims, iap, imo, idr, ipi, n = cab
                if len(r) != n: continue
                try: self.cuadros.append((float(r[it]), float(r[ims]), r[iap].lower() if iap >= 0 else "",
                                          r[imo].lower() if imo >= 0 else "", idr >= 0 and r[idr] == "1", r[ipi] if ipi >= 0 else ""))
                except ValueError: pass
        except Exception as e:
            _log("lector presentmon", e)
        finally:
            if out: out.close()
            try: self.proc.stdout.close()
            except Exception: pass

    def fps(self, exe=None, pid=None, seg=3):
        """exe/pid: FPS del juego (cuadros ÷ tiempo entre ellos; por nombre o, si sale <unknown>, por número de proceso).
        Sin exe: la pantalla (cuadros "Hardware…" que llegaron a la pantalla en los últimos segundos, contados contra el
        reloj: si la pantalla está quieta, son pocos)."""
        c = list(self.cuadros)
        if exe:
            c = [x for x in c if x[2] == exe or x[5] == str(pid)]
            if not c: return 0
            ult = c[-1][0]
            ms = [x[1] for x in c if x[0] >= ult - seg and x[1] > 0]
            return round(1000 * len(ms) / sum(ms)) if ms else 0
        ahora = time.time() - self.t0  # TimeInSeconds cuenta desde que arrancó PresentMon
        return round(sum(1 for x in c if x[0] > ahora - seg - 1 and x[0] <= ahora - 1 and x[3].startswith("hardware") and not x[4]) / seg)

def _esperar_lector(pid):
    lec = (_vivo.get(pid) or (None,))[0]
    if lec: lec.join(30)

def fps_ahora():
    """FPS del juego que mide Pulso (últimos 3 s). None si no hay medición."""
    for pid, (lector, exe) in list(_vivo.items()):
        if lector: return lector.fps(exe, pid)
    return None

# ---- FPS de la pantalla (sin juego): solo mientras la ventana de TandemStacks está a la vista ----
# Sin administrador, dwm.exe (el que dibuja el escritorio) sale como <unknown> y no se puede filtrar por nombre: se graba
# todo y se cuentan los cuadros "Hardware…" (Windows mandando a la pantalla, o un video/juego que va directo). Los
# "Composed" son programas que le pasan su imagen a Windows: no llegan solos a la pantalla. Nada se escribe en el disco.
_esc = {"pm": None, "lector": None, "pedido": 0.0, "hilo": None}
SESION_ESC = "TandemStacks_escritorio"  # no la toca _limpiar_sesiones (busca TandemStacks_<número>)
TANDA_ESC = 300  # PresentMon corre de a 5 min y se relanza (por si Windows lo corta)

def _pm_parar(pm, sesion):
    if not pm: return
    try:
        subprocess.run([PM, "--terminate_existing_session", "--session_name", sesion], timeout=15,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=SIN_VENTANA)
        pm.wait(10)
    except Exception:
        try: pm.kill()
        except Exception: pass

def _hilo_esc():
    """Mide mientras la página lo siga pidiendo (cada 4 s); a los 15 s sin pedidos (ventana minimizada o cerrada) o con un
    juego medido por Pulso, se apaga."""
    try:
        while time.time() - _esc["pedido"] < 15 and not _vivo:
            if not _esc["pm"] or _esc["pm"].poll() is not None:
                _esc["pm"] = subprocess.Popen([PM, "--output_stdout", "--session_name", SESION_ESC, "--stop_existing_session",
                                               "--no_console_stats", "--v1_metrics", "--timed", str(TANDA_ESC), "--terminate_after_timed"],
                                              stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, creationflags=SIN_VENTANA)
                _esc["lector"] = _Lector(_esc["pm"])
            time.sleep(2)
    except Exception as e:
        _log("fps pantalla", e)
    finally:
        _pm_parar(_esc["pm"], SESION_ESC)
        _esc["pm"] = _esc["lector"] = None
        _esc["hilo"] = None

def apagar():
    """Al cerrar TandemStacks: ningún PresentMon queda andando (ni el de la pantalla ni el de un juego en curso)."""
    _esc["pedido"] = 0
    _pm_parar(_esc["pm"], SESION_ESC)
    for pid in list(_activos_pid):
        try: subprocess.run([PM, "--terminate_existing_session", "--session_name", "TandemStacks_%d" % pid], timeout=10,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=SIN_VENTANA)
        except Exception: pass

def fps_escritorio():
    """FPS de lo que muestra la pantalla sin juego. Arranca la medición la primera vez que se pide; None mientras arranca
    o si PresentMon no está."""
    if not os.path.exists(PM): return None
    _esc["pedido"] = time.time()
    if not _esc["hilo"]:
        _esc["hilo"] = threading.Thread(target=_hilo_esc, daemon=True)
        _esc["hilo"].start()
        return None
    lec = _esc["lector"]
    return lec.fps() if lec and time.time() - lec.t0 > 4 else None
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
        _vivo[pid] = (None, os.path.basename(exe).lower())
        pm, sesion = None, "TandemStacks_%d" % pid
        pm_txt = os.path.join(TMP, "pm_%d.txt" % pid)
        def lanzar_pm(solo_juego):
            # solo_juego: graba únicamente el exe del juego (--process_name). Grabar todo lo que se dibuja (Windows, Steam,
            # Discord, la propia TandemStacks) hacía archivos de millones de filas y, al cerrar el juego, leerlas trababa la
            # app (13/11/2026, Cyberpunk 35 min). --process_id no servía con anti-trampas; por nombre se prueba y, si al
            # minuto no grabó nada, se vuelve a grabar todo.
            # --output_stdout: PresentMon no deja leer su archivo mientras graba; el CSV lo escribe _Lector, que además
            # guarda los últimos cuadros para el reloj de FPS en vivo (14/11/2026)
            args = [PM, "--output_stdout", "--session_name", sesion, "--stop_existing_session", "--no_console_stats", "--v1_metrics"]
            if solo_juego: args += ["--process_name", os.path.basename(exe)]
            with open(pm_txt, "w") as salida:
                p = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=salida, creationflags=SIN_VENTANA)
            _vivo[pid] = (_Lector(p, csv_fps), os.path.basename(exe).lower())
            return p
            # prioridad normal a propósito: con prioridad baja, con el juego usando el procesador, PresentMon
            # no alcanzaba a leer los eventos de Windows, los perdía todos y la partida quedaba sin FPS
        if os.path.exists(PM):
            try: pm = lanzar_pm(True)
            except OSError as e: _log("presentmon", e)
        solo_juego = pm is not None
        inicio, muestras, cpu0, est = time.time(), [], tiempos_cpu(), {"dir": g["dir"]}
        version, drv = version_juego(g), driver()
        psutil.cpu_percent(interval=None, percpu=True)
        while psutil.pid_exists(pid):
            time.sleep(MUESTRA)
            try: muestras.append(muestrear(pid, est))
            except Exception as e: _log("muestra", e)
            if solo_juego and time.time() - inicio > 60:  # al minuto: ¿grabó algo del juego?
                solo_juego = False
                try: vacio = os.path.getsize(csv_fps) < 2048  # solo el encabezado
                except OSError: vacio = True
                if vacio:
                    _log("presentmon: por nombre no grabó nada, se graba todo", os.path.basename(exe))
                    try:
                        subprocess.run([PM, "--terminate_existing_session", "--session_name", sesion], timeout=15,
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=SIN_VENTANA)
                        pm.wait(10)
                    except Exception:
                        try: pm.kill()
                        except Exception: pass
                    _esperar_lector(pid)  # que termine de escribir antes de que el nuevo abra el mismo archivo
                    try: pm = lanzar_pm(False)
                    except OSError as e: _log("presentmon", e); pm = None
        fin = time.time()
        pm_ok = False
        if pm:
            try:  # se le pide que cierre ordenado (así escribe lo último que tenía); si no responde, se mata
                subprocess.run([PM, "--terminate_existing_session", "--session_name", sesion], timeout=15,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=SIN_VENTANA)
                pm.wait(timeout=15)
            except Exception:
                pm.kill()
            _esperar_lector(pid)  # el CSV lo escribe el lector: que termine antes de leerlo
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
        _vivo.pop(pid, None)
    except Exception as e:
        _log("medir", g.get("name"), e)
    finally:
        _activos.discard(g["id"])

def empezar(g, al_terminar=None):
    if g["id"] in _activos or not g.get("dir"):
        return
    _activos.add(g["id"])  # se marca acá, antes del hilo, para no lanzar dos mediciones del mismo juego
    threading.Thread(target=medir, args=(g, al_terminar), daemon=True).start()
