# -*- coding: utf-8 -*-
"""Detección de launchers instalados (registro de Windows + rutas típicas). La config puede corregir cualquier ruta."""
import os, json, glob, winreg

HKLM, HKCU = winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER
PF, PF86 = os.environ.get("ProgramFiles", r"C:\Program Files"), os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")

def reg(hive, ruta, valor):
    try:
        k = winreg.OpenKey(hive, ruta)
        v = winreg.QueryValueEx(k, valor)[0]
        return str(v) if v is not None else ""
    except OSError:
        return ""

def reg_hijas(hive, ruta):
    """{subclave: {valor: dato}} (vacío si la clave no existe)."""
    out = {}
    try:
        k = winreg.OpenKey(hive, ruta)
    except OSError:
        return out
    for i in range(winreg.QueryInfoKey(k)[0]):
        try:
            n = winreg.EnumKey(k, i)
            sk = winreg.OpenKey(k, n); vals = {}
            for j in range(winreg.QueryInfoKey(sk)[1]):
                v = winreg.EnumValue(sk, j); vals[v[0]] = v[1]
            out[n] = vals
        except OSError:
            pass
    return out

def uninstall_entries():
    """Todas las entradas de 'Programas instalados' (HKLM 64/32 + HKCU)."""
    out = []
    for hive, ruta in ((HKLM, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
                       (HKLM, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
                       (HKCU, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall")):
        for n, v in reg_hijas(hive, ruta).items():
            v["_key"] = n; out.append(v)
    return out

# Cada launcher: cómo encontrar el exe, con qué se abre, dónde se baja y qué procesos son suyos
# (los procesos se usan para cerrarlo cuando termina el juego).
LAUNCHERS = {
    "Steam": {
        "color": "#1a7fd4",
        "exe": lambda: os.path.join(reg(HKCU, r"Software\Valve\Steam", "SteamPath").replace("/", "\\") or os.path.join(PF86, "Steam"), "steam.exe"),
        "abrir": lambda exe: "steam://open/games",
        "bajar": "https://store.steampowered.com/about/",
        "procs": ["steam.exe", "steamwebhelper.exe", "steamservice.exe"],
    },
    "Epic": {
        "color": "#2a2a2a",
        "exe": lambda: _primero(os.path.join(PF, r"Epic Games\Launcher\Portal\Binaries\Win64\EpicGamesLauncher.exe"),
                                os.path.join(PF86, r"Epic Games\Launcher\Portal\Binaries\Win64\EpicGamesLauncher.exe"),
                                os.path.join(PF86, r"Epic Games\Launcher\Portal\Binaries\Win32\EpicGamesLauncher.exe")),
        "abrir": lambda exe: "com.epicgames.launcher://apps",
        "bajar": "https://store.epicgames.com/download",
        "procs": ["epicgameslauncher.exe", "epicwebhelper.exe"],
    },
    "EA": {
        "color": "#e03a3a",
        "exe": lambda: _primero(os.path.join(PF, r"Electronic Arts\EA Desktop\EA Desktop\EADesktop.exe"),
                                os.path.join(PF86, r"Electronic Arts\EA Desktop\EA Desktop\EADesktop.exe"),
                                *[os.path.join(str(e.get("InstallLocation", "")).strip('"'), "EA Desktop", "EADesktop.exe") for e in uninstall_entries()
                                  if str(e.get("DisplayName", "")).lower() in ("ea app", "ea desktop") and e.get("InstallLocation")]),
        "abrir": lambda exe: "origin2://",
        "bajar": "https://www.ea.com/ea-app",
        "procs": ["eadesktop.exe", "eabackgroundservice.exe", "ealocalhostsvc.exe", "eaconnect_microsoft.exe"],
    },
    "Xbox": {
        "color": "#107c10",
        "exe": lambda: "",  # app de la Store, no tiene exe clásico: se marca presente si existe GamingServices
        "abrir": lambda exe: "ms-xbl-3d8b930f://",
        "bajar": "https://www.xbox.com/apps/xbox-app-for-pc",
        "procs": [],
    },
    "Riot": {
        "color": "#d13639",
        "exe": lambda: _riot_exe(),
        "abrir": lambda exe: exe,
        "bajar": "https://www.riotgames.com/",
        "procs": ["riot client.exe", "riotclientservices.exe", "riotclientcrashhandler.exe"],
    },
    "Battle.net": {
        "color": "#148eff",
        "exe": lambda: next((os.path.join(e["InstallLocation"], "Battle.net Launcher.exe") for e in uninstall_entries()
                             if str(e.get("DisplayName", "")).lower() == "battle.net" and e.get("InstallLocation")),
                            os.path.join(PF86, r"Battle.net\Battle.net Launcher.exe")),
        "abrir": lambda exe: "battlenet://",
        "bajar": "https://www.blizzard.com/apps/battle.net/desktop",
        "procs": ["battle.net.exe", "agent.exe", "battle.net helper.exe"],
    },
    "Rockstar": {
        "color": "#f2a900",
        "exe": lambda: os.path.join(reg(HKLM, r"SOFTWARE\WOW6432Node\Rockstar Games\Launcher", "InstallFolder") or os.path.join(PF, r"Rockstar Games\Launcher"), "Launcher.exe"),
        "abrir": lambda exe: exe,
        "bajar": "https://socialclub.rockstargames.com/rockstar-games-launcher",
        "procs": ["launcher.exe", "launcherpatcher.exe", "rockstarservice.exe", "socialclubhelper.exe", "rockstarerrorhandler.exe"],
    },
    "Ubisoft": {
        "color": "#0070ff",
        "exe": lambda: os.path.join(reg(HKLM, r"SOFTWARE\WOW6432Node\Ubisoft\Launcher", "InstallDir").replace("/", "\\") or os.path.join(PF86, r"Ubisoft\Ubisoft Game Launcher"), "upc.exe"),
        "abrir": lambda exe: "uplay://",
        "bajar": "https://ubisoftconnect.com/",
        "procs": ["upc.exe", "ubisoftconnect.exe", "uplaywebcore.exe", "ubisoftgamelauncher.exe"],
    },
}

DESINSTALAR = {  # cómo figura cada launcher en Programas instalados de Windows
    "Steam": ("steam",), "Epic": ("epic games launcher",), "EA": ("ea app", "ea desktop"), "Riot": ("riot client",),
    "Battle.net": ("battle.net",), "Rockstar": ("rockstar games launcher",), "Ubisoft": ("ubisoft connect",),
}

def comando_desinstalar(nombre):
    """UninstallString del launcher (o '' si no está / es app de la Store)."""
    for e in uninstall_entries():
        if str(e.get("DisplayName", "")).strip().lower() in DESINSTALAR.get(nombre, ()):
            return str(e.get("QuietUninstallString") or e.get("UninstallString") or "")
    return ""

def _primero(*rutas):
    """La primera ruta que exista (o la primera de la lista si ninguna existe)."""
    return next((r for r in rutas if r and os.path.exists(r)), rutas[0] if rutas else "")

def _riot_exe():
    try:
        with open(r"C:\ProgramData\Riot Games\RiotClientInstalls.json", encoding="utf-8") as f:
            return json.load(f).get("rc_default", "").replace("/", "\\")
    except Exception:
        return r"C:\Riot Games\Riot Client\RiotClientServices.exe"

def xbox_presente():
    try:
        return bool(reg_hijas(HKLM, r"SOFTWARE\Microsoft\GamingServices\PackageRepository\Root")) or \
               bool(glob.glob(os.path.join(PF, "WindowsApps", "Microsoft.GamingApp_*")))
    except Exception:
        return False

def detectar(cfg):
    """{nombre: {"exe", "ok", "color", "abrir", "bajar", "procs", "manual"}} respetando rutas puestas a mano en la config."""
    out = {}
    manual = cfg.get("launchers", {}) if cfg else {}
    for n, d in LAUNCHERS.items():
        exe = (manual.get(n) or {}).get("exe") or ""
        es_manual = bool(exe)
        if not exe:
            try:
                exe = d["exe"]() or ""
            except Exception:
                exe = ""
        ok = os.path.exists(exe) if exe else (xbox_presente() if n == "Xbox" else False)
        out[n] = {"exe": exe, "ok": ok, "color": d["color"], "abrir": d["abrir"](exe) if ok else d["bajar"],
                  "bajar": d["bajar"], "procs": d["procs"], "manual": es_manual}
    return out
