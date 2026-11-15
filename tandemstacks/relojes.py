"""Relojes en vivo: lo mismo que muestra el Administrador de tareas de Windows, y cuánto de eso es el juego abierto.

Se leen los contadores de rendimiento de Windows (PDH, los mismos del Administrador de tareas):
- Procesador: "% Processor Utility" (el número del Administrador; "% Processor Time" o psutil dan menos cuando el
  procesador sube de frecuencia).
- Placa de video: "GPU Engine" por motor y por programa, igual que el Administrador: cada motor (3D, copia, video…) suma
  lo de todos los programas y el uso de la placa es el motor más ocupado. Sirve con NVIDIA, AMD e Intel.
- VRAM: "GPU Adapter Memory" (total) y "GPU Process Memory" (por programa).
- Disco: "% Idle Time" de cada disco; ocupado = 100 − libre del disco más ocupado (como "Tiempo activo").
RAM, red y bytes de disco salen de psutil. La red no se puede separar por programa: Windows no la cuenta así.
Del juego: procesador, RAM y disco por psutil (todos sus procesos, los de su carpeta), placa y VRAM por PDH.
Solo se lee cuando la página lo pide (ventana a la vista): cada 4 s, o cada 10 s con un juego abierto."""
import re, time, ctypes, threading, winreg
import ctypes.wintypes as w
import psutil

_pdh = None
_candado = threading.Lock()
_q = {}  # nombre: handle del contador
_hq = ctypes.c_void_p()
MAS_DATOS = 0x800007D2
FMT_DOUBLE, SIN_TOPE = 0x200, 0x8000

class _Valor(ctypes.Structure):
    _fields_ = [("estado", w.DWORD), ("_relleno", w.DWORD), ("v", ctypes.c_double)]

class _Item(ctypes.Structure):
    _fields_ = [("nombre", ctypes.c_wchar_p), ("valor", _Valor)]

CONTADORES = {
    "cpu": r"\Processor Information(_Total)\% Processor Utility",
    "cpu_t": r"\Processor Information(_Total)\% Processor Time",
    "gpu": r"\GPU Engine(*)\Utilization Percentage",
    "vram": r"\GPU Adapter Memory(*)\Dedicated Usage",
    "vram_p": r"\GPU Process Memory(*)\Dedicated Usage",
    "disco": r"\PhysicalDisk(*)\% Idle Time",
}

def _abrir():
    """Abre la consulta una sola vez. Si un contador no existe en esta PC (Windows viejo, sin placa) se sigue sin él."""
    global _pdh
    if _pdh is not None: return _pdh
    try:
        p = ctypes.WinDLL("pdh")
        for f in ("PdhOpenQueryW", "PdhAddEnglishCounterW", "PdhCollectQueryData", "PdhGetFormattedCounterValue", "PdhGetFormattedCounterArrayW"):
            getattr(p, f).restype = ctypes.c_uint32  # PDH_STATUS: sin signo, para comparar con MAS_DATOS
        if p.PdhOpenQueryW(None, None, ctypes.byref(_hq)) != 0: raise OSError("PdhOpenQuery")
        for k, ruta in CONTADORES.items():
            h = ctypes.c_void_p()
            if p.PdhAddEnglishCounterW(_hq, ruta, None, ctypes.byref(h)) == 0: _q[k] = h
        p.PdhCollectQueryData(_hq)  # la primera lectura solo arranca la cuenta
        _pdh = p
    except Exception:
        _pdh = False
    return _pdh

def _uno(k):
    h = _q.get(k)
    if not h: return None
    v = _Valor()
    if _pdh.PdhGetFormattedCounterValue(h, FMT_DOUBLE | SIN_TOPE, None, ctypes.byref(v)) != 0 or v.estado not in (0, 1): return None
    return v.v

def _varios(k, q=None):
    """{instancia: valor} de un contador con (*)."""
    h = (_q if q is None else q).get(k)
    if not h: return {}
    tam, n = w.DWORD(0), w.DWORD(0)
    r = _pdh.PdhGetFormattedCounterArrayW(h, FMT_DOUBLE | SIN_TOPE, ctypes.byref(tam), ctypes.byref(n), None)
    if r != MAS_DATOS or not tam.value: return {}
    buf = ctypes.create_string_buffer(tam.value)
    if _pdh.PdhGetFormattedCounterArrayW(h, FMT_DOUBLE | SIN_TOPE, ctypes.byref(tam), ctypes.byref(n), buf) != 0: return {}
    items = ctypes.cast(buf, ctypes.POINTER(_Item))
    return {items[i].nombre: items[i].valor.v for i in range(n.value) if items[i].valor.estado in (0, 1)}

_PID = re.compile(r"pid_(\d+)_")
_MOTOR = re.compile(r"(luid_\w+?_phys_\d+_eng_\d+)")

def _vram_total():
    """VRAM de la placa más grande, del registro de Windows (sirve con cualquier marca). Se lee una vez."""
    if _vram_total.v is None:
        mx = 0
        base = r"SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}"
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, base) as k:
                for i in range(winreg.QueryInfoKey(k)[0]):
                    try:
                        with winreg.OpenKey(k, winreg.EnumKey(k, i)) as s:
                            for nom in ("HardwareInformation.qwMemorySize", "HardwareInformation.MemorySize"):
                                try:
                                    v = winreg.QueryValueEx(s, nom)[0]
                                    v = int.from_bytes(v, "little") if isinstance(v, bytes) else int(v)
                                    mx = max(mx, v); break
                                except OSError: pass
                    except OSError: pass
        except OSError: pass
        _vram_total.v = mx
    return _vram_total.v
_vram_total.v = None

_ant = {"t": 0.0, "red": None, "disco": None, "juego": {}}  # lecturas anteriores, para calcular velocidades

# Pulso tiene su propia consulta: cada lectura de "GPU Engine" promedia desde la anterior, y si compartiera la de los
# relojes cada uno le acortaría el intervalo al otro.
_qp, _hqp = {}, ctypes.c_void_p()
_qp_ok = [None]

def placa_juego(pids):
    """Placa de video y memoria de video usadas SOLO por estos procesos (el juego), como el Administrador de tareas:
    {"gpu": % del motor más ocupado por el juego, "vram_mb": MB}. None si Windows no tiene estos contadores."""
    with _candado:
        p = _abrir()
        if not p: return None
        if _qp_ok[0] is None:
            _qp_ok[0] = False
            if p.PdhOpenQueryW(None, None, ctypes.byref(_hqp)) == 0:
                for k in ("gpu", "vram_p"):
                    h = ctypes.c_void_p()
                    if p.PdhAddEnglishCounterW(_hqp, CONTADORES[k], None, ctypes.byref(h)) == 0: _qp[k] = h
                p.PdhCollectQueryData(_hqp)  # la primera solo arranca la cuenta
                _qp_ok[0] = "gpu" in _qp
            return None
        if not _qp_ok[0]: return None
        p.PdhCollectQueryData(_hqp)
        pids, motores = set(pids), {}
        for inst, v in _varios("gpu", _qp).items():
            mo, pi = _MOTOR.search(inst), _PID.search(inst)
            if mo and pi and int(pi.group(1)) in pids: motores[mo.group(1)] = motores.get(mo.group(1), 0) + v
        vram = sum(v for k, v in _varios("vram_p", _qp).items() if _PID.search(k) and int(_PID.search(k).group(1)) in pids)
        return {"gpu": round(max(0, min(100, max(motores.values()) if motores else 0)), 1), "vram_mb": round(vram / 1048576)}

def medir(pids=()):
    """Todo lo de los relojes. pids = procesos del juego abierto (vacío: sin juego)."""
    with _candado:
        p = _abrir()
        if p: p.PdhCollectQueryData(_hq)
        t = time.time()
        dt = t - _ant["t"] if _ant["t"] else 0
        _ant["t"] = t
        out = {}
        # procesador
        cpu = _uno("cpu") if p else None
        cpu_t = _uno("cpu_t") if p else None
        if cpu is None: cpu = cpu_t if cpu_t is not None else psutil.cpu_percent(None)
        out["cpu"] = max(0, min(100, round(cpu)))
        # RAM (en uso = total − disponible, como el Administrador)
        m = psutil.virtual_memory()
        usada = m.total - m.available
        out.update(ram=round(100 * usada / m.total), ramGB=round(usada / 1073741824, 1), ramTotal=round(m.total / 1073741824))
        # red
        n = psutil.net_io_counters()
        if _ant["red"] and dt > 0:
            out["baja"] = max(0, round((n.bytes_recv - _ant["red"][0]) / dt))
            out["sube"] = max(0, round((n.bytes_sent - _ant["red"][1]) / dt))
        else: out["baja"] = out["sube"] = 0
        _ant["red"] = (n.bytes_recv, n.bytes_sent)
        # disco: bytes por psutil, ocupado por PDH (el disco más ocupado)
        d = psutil.disk_io_counters()
        if _ant["disco"] and dt > 0:
            out["dlee"] = max(0, round((d.read_bytes - _ant["disco"][0]) / dt))
            out["descr"] = max(0, round((d.write_bytes - _ant["disco"][1]) / dt))
        else: out["dlee"] = out["descr"] = 0
        _ant["disco"] = (d.read_bytes, d.write_bytes)
        libres = [v for k, v in (_varios("disco") if p else {}).items() if k != "_Total"]
        out["dOcup"] = max(0, min(100, round(100 - min(libres)))) if libres else 0
        # placa de video: por motor, sumando programas; la placa = el motor más ocupado
        motores, por_pid = {}, {}
        for inst, v in (_varios("gpu") if p else {}).items():
            mo, pi = _MOTOR.search(inst), _PID.search(inst)
            if not mo: continue
            motores[mo.group(1)] = motores.get(mo.group(1), 0) + v
            if pi:
                clave = (int(pi.group(1)), mo.group(1))
                por_pid[clave] = por_pid.get(clave, 0) + v
        if motores:
            out["gpu"] = max(0, min(100, round(max(motores.values()))))
            vt = _vram_total()
            vu = max((_varios("vram") or {0: 0}).values())
            out["vram"] = round(vu / 1073741824, 1)
            if vt:
                out["vramTotal"] = round(vt / 1073741824)
                out["vramPct"] = round(100 * vu / vt)
        # el juego: todos sus procesos
        pids = set(pids or ())
        if pids:
            j = {"cpu": 0.0, "ram": 0, "lee": 0, "esc": 0}
            prev, nuevo = _ant["juego"], {}
            ncpu = psutil.cpu_count() or 1
            escala = (cpu / cpu_t) if cpu_t and cpu_t > 1 else 1  # tiempo de procesador → la escala del Administrador
            for pid in pids:
                try:
                    pr = psutil.Process(pid)
                    ct, io = pr.cpu_times(), pr.io_counters()
                    j["ram"] += pr.memory_info().rss
                    nuevo[pid] = (ct.user + ct.system, io.read_bytes, io.write_bytes, pr.create_time())
                    a = prev.get(pid)
                    if a and a[3] == nuevo[pid][3] and dt > 0:
                        j["cpu"] += 100 * (nuevo[pid][0] - a[0]) / dt / ncpu * escala
                        j["lee"] += (nuevo[pid][1] - a[1]) / dt
                        j["esc"] += (nuevo[pid][2] - a[2]) / dt
                except Exception:
                    pass
            _ant["juego"] = nuevo
            jg = {"cpu": max(0, min(out["cpu"], round(j["cpu"]))), "ramGB": round(j["ram"] / 1073741824, 1),
                  "ram": round(100 * j["ram"] / m.total),
                  # en Windows lo que lee y escribe un programa incluye algo más que el disco: nunca más que el total
                  "dlee": max(0, min(out["dlee"], round(j["lee"]))), "descr": max(0, min(out["descr"], round(j["esc"])))}
            if motores:
                pm = {}
                for (pid, mo), v in por_pid.items():
                    if pid in pids: pm[mo] = pm.get(mo, 0) + v
                jg["gpu"] = max(0, min(out["gpu"], round(max(pm.values())))) if pm else 0
                vp = sum(v for k, v in (_varios("vram_p") or {}).items() if (_PID.search(k) and int(_PID.search(k).group(1)) in pids))
                jg["vram"] = round(vp / 1073741824, 1)
                if out.get("vramTotal"): jg["vramPct"] = round(100 * vp / vt)
            out["juego"] = jg
        else:
            _ant["juego"] = {}
        return out
