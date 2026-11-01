# -*- coding: utf-8 -*-
"""Cierre automático de launchers: al lanzar un juego se anota qué launchers ya estaban abiertos; cuando el juego
termina se cierran solo los que abrió ese lanzamiento (si el usuario tenía uno abierto, se respeta)."""
import os, time, threading, subprocess, winreg
import psutil
from . import paths

def _procs():
    for pr in psutil.process_iter(["name", "exe"]):
        try:
            yield pr, (pr.info["name"] or "").lower(), (pr.info["exe"] or "").lower()
        except Exception:
            pass

def abiertos(launchers):
    vivos = set()
    for _, n, _ in _procs():
        for l, d in launchers.items():
            if n in d["procs"]:
                vivos.add(l)
    return vivos

def juego_corriendo(store, carpeta):
    if store == "Steam":
        try:
            k = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam")
            return str(winreg.QueryValueEx(k, "RunningAppID")[0]) not in ("0", "")
        except OSError:
            return False
    c = (carpeta or "").lower().replace("/", "\\").rstrip("\\")
    return bool(c) and any(e.startswith(c + "\\") for _, _, e in _procs())

def cerrar(l, launchers):
    d = launchers[l]
    if l == "Steam" and d.get("exe") and os.path.exists(d["exe"]):
        subprocess.Popen([d["exe"], "-shutdown"], creationflags=0x08000000)
        time.sleep(8)
    victimas = [pr for pr, n, _ in _procs() if n in d["procs"]]
    for pr in victimas:
        try: pr.terminate()
        except Exception: pass
    psutil.wait_procs(victimas, timeout=8)
    for pr in victimas:
        try:
            if pr.is_running(): pr.kill()
        except Exception: pass
    paths.log("launcher cerrado:", l)

def _vigilar(store, carpeta, antes, launchers):
    t0 = time.time()
    while not juego_corriendo(store, carpeta):
        if time.time() - t0 > 240:
            return  # no arrancó (canceló, está instalando...): no se toca nada
        time.sleep(3)
    while juego_corriendo(store, carpeta):
        time.sleep(5)
    time.sleep(5)
    for l in abiertos(launchers) - antes:
        try: cerrar(l, launchers)
        except Exception as e: paths.log("cerrar", l, e)

def lanzar(store, carpeta, arrancar, launchers, vigilar=True):
    antes = abiertos(launchers) if vigilar else set()
    arrancar()
    if vigilar and (store == "Steam" or carpeta):
        threading.Thread(target=_vigilar, args=(store, carpeta, antes, launchers), daemon=True).start()
