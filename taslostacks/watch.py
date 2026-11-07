# -*- coding: utf-8 -*-
"""Cierre automático de launchers: cuando termina un juego (lanzado desde donde sea) se cierran todos los launchers abiertos.
Si queda otro juego andando no se toca nada, para no cortarlo."""
import os, time, subprocess, winreg
import psutil
from . import paths

INTERVALO = 5   # segundos entre cada mirada mientras hay un juego andando
REPOSO = 15     # sin juegos se mira menos seguido: recorrer los procesos gasta
MINIMO = 30     # lo que dura menos que esto no era un juego (parches, instaladores, un error al abrir)
GENERICOS = {"launcher.exe": "rockstar", "agent.exe": "battle.net", "butler.exe": "itch"}  # nombres que usan otros programas: se mira también la ruta
AYUDANTES = ("crash", "reporter", "unins")  # procesos que pueden quedar en la carpeta del juego después de cerrarlo

def _procs():
    for pr in psutil.process_iter(["name", "exe"]):
        try:
            yield pr, (pr.info["name"] or "").lower(), (pr.info["exe"] or "").lower()
        except Exception:
            pass

def _es_de(nombre, ruta, d):
    return nombre in d["procs"] and GENERICOS.get(nombre, "") in ruta

def abiertos(launchers):
    vivos = set()
    for _, n, e in _procs():
        for l, d in launchers.items():
            if _es_de(n, e, d):
                vivos.add(l)
    return vivos

def algun_juego(carpetas):
    """Steam avisa en el registro qué juego corre; los demás se reconocen por un proceso dentro de su carpeta."""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as k:
            if str(winreg.QueryValueEx(k, "RunningAppID")[0]) not in ("0", ""):
                return True
    except OSError:
        pass
    prefijos = tuple(c.lower().replace("/", "\\").rstrip("\\") + "\\" for c in carpetas if c)
    return bool(prefijos) and any(e.startswith(prefijos) and not any(a in n for a in AYUDANTES) for _, n, e in _procs())

def cerrar(l, launchers):
    d = launchers[l]
    if l == "Steam" and d.get("exe") and os.path.exists(d["exe"]):
        subprocess.Popen([d["exe"], "-shutdown"], creationflags=0x08000000)
        time.sleep(8)
    victimas = [pr for pr, n, e in _procs() if _es_de(n, e, d)]
    for pr in victimas:
        try: pr.terminate()
        except Exception: pass
    try: psutil.wait_procs(victimas, timeout=8)
    except psutil.Error: pass  # servicios de Windows (EABackgroundService): no dejan ni esperarlos
    for pr in victimas:
        try:
            if pr.is_running(): pr.kill()
        except Exception: pass
    paths.log("launcher cerrado:", l)

def vigilar(carpetas, launchers, activo, sumar):
    """Hilo de toda la sesión. carpetas, launchers y activo son funciones: la biblioteca y la configuración cambian mientras corre.
    sumar(segundos) recibe el tiempo con algún juego abierto, para el contador de horas."""
    desde = ultimo = None
    while True:
        time.sleep(INTERVALO if desde else REPOSO)
        try:
            if algun_juego(carpetas()):
                ahora = time.time()
                desde = desde or ahora
                if ultimo: sumar(min(ahora - ultimo, 60))  # el tope evita contar horas si la PC se suspendió
                ultimo = ahora
            elif desde:
                time.sleep(INTERVALO)  # algunos juegos se reabren solos al arrancar
                if algun_juego(carpetas()):
                    continue
                duro, desde, ultimo = time.time() - desde, None, None
                if duro >= MINIMO and activo():
                    ls = launchers()
                    for l in abiertos(ls):
                        try: cerrar(l, ls)
                        except Exception as e: paths.log("cerrar", l, e)
        except Exception as e:
            paths.log("vigilar juegos", e)
