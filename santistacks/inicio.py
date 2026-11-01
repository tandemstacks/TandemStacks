# -*- coding: utf-8 -*-
"""Launchers que arrancan con Windows. Se deshabilitan igual que desde el Administrador de tareas
(StartupApproved = 03): la entrada queda, no se borra nada, y se puede volver a activar desde Windows."""
import re, time, winreg

HKCU, HKLM = winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE
RUN = r"Software\Microsoft\Windows\CurrentVersion\Run"
APROB = r"Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run"
LAUNCHER = re.compile(r"steam|epicgames|eadm|ea ?desktop|eabackground|origin|riotclient|riot client|battle\.net|upc\.exe|ubisoft|uplay|rockstar|socialclub", re.I)
NO_TOCAR = re.compile(r"vanguard|vgtray", re.I)  # anti-trampas de Riot: si se saca, LoL/VALORANT no arrancan

def _entradas():
    """[(hive, nombre, comando, habilitada)] de los launchers en Run de HKCU y HKLM."""
    out = []
    for hive in (HKCU, HKLM):
        for ruta in (RUN, RUN.replace("Software", "SOFTWARE\\WOW6432Node") if hive == HKLM else None):
            if not ruta:
                continue
            try:
                k = winreg.OpenKey(hive, ruta)
            except OSError:
                continue
            for i in range(winreg.QueryInfoKey(k)[1]):
                n, cmd, _ = winreg.EnumValue(k, i)
                txt = "%s %s" % (n, cmd)
                if LAUNCHER.search(txt) and not NO_TOCAR.search(txt):
                    out.append((hive, n, str(cmd), _habilitada(hive, n)))
    return out

def _habilitada(hive, nombre):
    try:
        v = winreg.QueryValueEx(winreg.OpenKey(hive, APROB), nombre)[0]
        return not (isinstance(v, bytes) and v[:1] in (b"\x03", b"\x01"))
    except OSError:
        return True  # sin marca = Windows la arranca

def estado():
    return [{"nombre": n, "comando": c, "activa": a, "equipo": h == HKLM} for h, n, c, a in _entradas()]

def quitar_todos():
    """Deshabilita cada launcher del inicio. Devuelve {"quitados": [...], "sin_permiso": [...]}."""
    ft = int((time.time() + 11644473600) * 10**7).to_bytes(8, "little")  # FILETIME de ahora, como Windows
    quitados, sin_permiso = [], []
    for hive, n, cmd, activa in _entradas():
        if not activa:
            continue
        try:
            k = winreg.CreateKeyEx(hive, APROB, 0, winreg.KEY_SET_VALUE)
            winreg.SetValueEx(k, n, 0, winreg.REG_BINARY, b"\x03\x00\x00\x00" + ft)
            quitados.append(n)
        except OSError:
            sin_permiso.append(n)  # entradas de todo el equipo (HKLM) piden administrador
    return {"quitados": quitados, "sin_permiso": sin_permiso}
