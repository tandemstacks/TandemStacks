# -*- coding: utf-8 -*-
"""Las demás tiendas. Cada función devuelve juegos como dicts:
   {id, name, store, installed, dir, sizeGB, drive, launch (str|list|None), uninstall, steam_hint (appid para ficha/portada),
    cover_builtin / cover_url, desc (+ desc_en), genres, anio, dev, reqGB}
   Epic: biblioteca completa (catálogo local) + instalados. Riot y Battle.net: catálogo gratis + instalados.
   Rockstar: los títulos cuyo manifiesto bajó el launcher (= biblioteca) + instalados. EA/Xbox/Ubisoft: solo instalados."""
import os, re, io, json, glob, time, threading, subprocess
from . import paths
from .detect import reg_hijas, uninstall_entries, HKLM

_TAM_FILE = os.path.join(paths.CACHE, "tamanos.json")
try:
    _tams = json.load(open(_TAM_FILE, encoding="utf-8"))
except Exception:
    _tams = {}
_tam_lock = threading.Lock()

def tam_gb(carpeta):
    """GB de una carpeta. Recorrerla entera es lento con juegos grandes: se recuerda 1 día."""
    c = _tams.get(carpeta)
    if c and time.time() - c[1] < 86400:
        return c[0]
    try:
        gb = round(sum(os.path.getsize(os.path.join(r, f)) for r, _, fs in os.walk(carpeta) for f in fs) / 1073741824, 1)
    except Exception:
        return 0
    with _tam_lock:
        _tams[carpeta] = [gb, time.time()]
        try:
            json.dump(_tams, open(_TAM_FILE, "w", encoding="utf-8"))
        except Exception:
            pass
    return gb

def _mismo(a, b):
    """Mismo juego por nombre normalizado: igual, o uno es el otro más un agregado que NO sea un número de secuela
    (así StarCraft no se confunde con StarCraft II, ni Diablo III con Diablo II)."""
    if a == b:
        return True
    corto, largo = (a, b) if len(a) < len(b) else (b, a)
    if not corto or not largo.startswith(corto + " "):
        return False
    return not re.match(r"(i{1,3}|iv|v|vi|[0-9]+)\b", largo[len(corto) + 1:])

def drive(p):
    return (p or "C:")[:2].upper()

nrm = lambda n: re.sub(r"[^a-z0-9]+", " ", str(n).lower()).strip()

def _ps(cmd):
    """Corre PowerShell oculto y devuelve stdout (JSON esperado)."""
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", cmd], capture_output=True, text=True,
                           timeout=90, creationflags=0x08000000, encoding="utf-8", errors="ignore")
        return r.stdout or ""
    except Exception:
        return ""

# ---------------- Epic ----------------
EPIC_DATA = r"C:\ProgramData\Epic\EpicGamesLauncher\Data"
EPIC_NO_JUEGO = re.compile(r"soundtrack|\bost\b|public test|playtest|test server|test branch|resource archiver|\beditor\b|\bcontent\b|\bdemo\b|benchmark|dedicated server|\bsdk\b|\btools?\b|artbook|wallpaper", re.I)

def _epic_uri(ns, item, app):
    """La misma URI juega si está instalado y abre la instalación si no."""
    return "com.epicgames.launcher://apps/%s%%3A%s%%3A%s?action=launch&silent=true" % (ns, item, app)

def epic():
    """Biblioteca completa desde el catálogo que guarda el launcher (catcache.bin, base64 de JSON; no hace falta login)
    + lo instalado desde los manifiestos .item. Sin DLC ni extras (bandas sonoras, editores, servidores de prueba)."""
    import base64
    juegos = {}
    try:
        cat = json.loads(base64.b64decode(open(os.path.join(EPIC_DATA, "Catalog", "catcache.bin"), "rb").read()))
    except Exception:
        cat = []
    for it in cat:
        cats = {c.get("path") for c in it.get("categories", [])}
        if "games" not in cats or "addons" in cats:
            continue
        if (it.get("mainGameItem") or {}).get("id"):
            continue  # DLC / contenido de otro juego
        titulo = str(it.get("title", "")).strip()
        if not titulo or EPIC_NO_JUEGO.search(titulo):
            continue
        rel = (it.get("releaseInfo") or [{}])[0]
        if rel.get("platform") and "Windows" not in rel["platform"]:
            continue
        app = rel.get("appId", "")
        alta = next((k.get("url") for k in it.get("keyImages", []) if k.get("type") == "DieselGameBoxTall"), "")
        desc = re.sub(r"\s+", " ", str(it.get("description", ""))).strip()
        juegos[it["id"]] = {"id": "epic_" + re.sub(r"[^A-Za-z0-9]", "", app or titulo)[:40], "name": titulo, "store": "Epic", "installed": False,
                            "dir": "", "dev": str(it.get("developer", "")), "cover_url": alta, "epic_ns": it.get("namespace", ""),
                            "desc": desc[:400] if desc.lower() != titulo.lower() else "",  # casi siempre el catálogo repite el título
                            "launch": _epic_uri(it.get("namespace"), it["id"], app) if app else None}
    for f in glob.glob(os.path.join(EPIC_DATA, "Manifests", "*.item")):
        try:
            m = json.load(io.open(f, encoding="utf-8"))
        except Exception:
            continue
        if m.get("MainGameAppName") and m.get("MainGameAppName") != m.get("AppName"):
            continue  # DLC instalado
        if not m.get("DisplayName"):
            continue
        loc = m.get("InstallLocation", "")
        g = juegos.get(m.get("CatalogItemId")) or {"id": "epic_" + re.sub(r"[^A-Za-z0-9]", "", m.get("AppName", m["DisplayName"]))[:40],
                                                   "name": m["DisplayName"], "store": "Epic", "epic_ns": m.get("CatalogNamespace", "")}
        g.update(installed=True, dir=loc, drive=drive(loc), sizeGB=round(m.get("InstallSize", 0) / 1073741824, 1),
                 launch=_epic_uri(m.get("CatalogNamespace"), m.get("CatalogItemId"), m.get("AppName")))
        juegos[m.get("CatalogItemId") or g["id"]] = g
    return list(juegos.values())

# ---------------- EA ----------------
def ea():
    out = []
    for e in uninstall_entries():
        pub, nombre = str(e.get("Publisher", "")), str(e.get("DisplayName", ""))
        if "electronic arts" not in pub.lower() or not nombre or nombre.lower() in ("ea app", "ea desktop", "origin"):
            continue
        loc = str(e.get("InstallLocation", "")).strip('"')
        exe = str(e.get("DisplayIcon", "")).split(",")[0].strip('"')
        if not loc or not os.path.isdir(loc):
            continue
        out.append({"id": "ea_" + re.sub(r"[^A-Za-z0-9]", "", nombre)[:40], "name": nombre, "store": "EA", "installed": True, "dir": loc,
                    "drive": drive(loc), "sizeGB": tam_gb(loc), "launch": exe if exe.lower().endswith(".exe") and os.path.exists(exe) else None})
    return out

# ---------------- Xbox / Microsoft Store (Game Pass) ----------------
def xbox():
    """Juegos registrados por GamingServices (los que instala la app Xbox) + Minecraft y similares (paquetes con 'Game' en su manifiesto)."""
    raiz = reg_hijas(HKLM, r"SOFTWARE\Microsoft\GamingServices\PackageRepository\Root")
    paquetes = set()
    for n, v in raiz.items():
        for v2 in reg_hijas(HKLM, r"SOFTWARE\Microsoft\GamingServices\PackageRepository\Root\%s" % n).values():
            if v2.get("Package"): paquetes.add(str(v2["Package"]))
        if v.get("Package"): paquetes.add(str(v["Package"]))
    cmd = r'''
$out=@(); foreach($p in Get-AppxPackage -PackageTypeFilter Main){ if($p.IsFramework -or $p.SignatureKind -ne 'Store'){continue}
 $m=Join-Path $p.InstallLocation 'AppxManifest.xml'; if(-not (Test-Path $m)){continue}
 try{[xml]$x=Get-Content $m -ErrorAction Stop}catch{continue}
 $app=$x.Package.Applications.Application | Select-Object -First 1; if(-not $app){continue}
 $vis=$app.VisualElements; $nombre=$x.Package.Properties.DisplayName; if($vis -and $vis.DisplayName -and $vis.DisplayName -notlike 'ms-resource*'){$nombre=$vis.DisplayName}
 if($nombre -like 'ms-resource*'){$nombre=$p.Name.Split('.')[-1]}
 $esJuego=($x.Package.Capabilities.InnerXml -match 'gaming|xboxlive') -or ($x.Package.InnerXml -match 'Microsoft\.GamingServices|xboxlive|GamingApp')
 $out+=[pscustomobject]@{Full=$p.PackageFullName;Family=$p.PackageFamilyName;AppId=$app.Id;Name=$nombre;Dir=$p.InstallLocation;Juego=$esJuego} }
$out | ConvertTo-Json -Compress'''
    try:
        lista = json.loads(_ps(cmd) or "[]")
        if isinstance(lista, dict): lista = [lista]
    except Exception:
        lista = []
    out = []
    excluir = ("xbox", "gaming", "game bar", "gamingservices", "solitaire collection", "minecraft launcher", "minecraft education")
    for p in lista:
        nombre = str(p.get("Name", ""))
        es = p.get("Full") in paquetes or (p.get("Juego") and "Microsoft." not in p.get("Full", "")[:11]) or "minecraft" in nombre.lower()
        if not es or any(x in nombre.lower() for x in excluir) or not nombre:
            continue
        loc = p.get("Dir", "")
        out.append({"id": "xbox_" + re.sub(r"[^A-Za-z0-9]", "", p.get("Family", nombre))[:40], "name": nombre, "store": "Xbox", "installed": True,
                    "dir": loc, "drive": drive(loc), "sizeGB": tam_gb(loc), "launch": "shell:AppsFolder\\%s!%s" % (p.get("Family"), p.get("AppId")),
                    "family": p.get("Family", "")})
    return out

# ---------------- Riot ----------------
RIOT = [  # (id, producto, nombre, año, GB, géneros, descripción); la portada está en assets/covers/<id>.jpg
    ("riot_lol", "league_of_legends", "League of Legends", "2009", 20, ["MOBA", "Estrategia", "Multijugador"], "El MOBA de Riot: dos equipos de cinco campeones pelean por destruir el nexo rival. Gratis, con Vanguard."),
    ("riot_valorant", "valorant", "VALORANT", "2020", 40, ["Acción", "Shooter", "Multijugador"], "Shooter táctico 5v5 por rondas con agentes con habilidades. Gratis, con Vanguard."),
    ("riot_tft", "teamfighttactics", "Teamfight Tactics", "2019", 20, ["Estrategia", "Auto battler", "Multijugador"], "Auto battler de 8 jugadores con los campeones de League of Legends. Gratis."),
    ("riot_lor", "bacon", "Legends of Runeterra", "2020", 6, ["Cartas", "Estrategia"], "Juego de cartas coleccionables ambientado en Runeterra. Gratis."),
    ("riot_2xko", "lion", "2XKO", "2025", 30, ["Lucha", "Multijugador"], "Juego de lucha 2v2 por tags con campeones de League of Legends. Gratis."),
]
def riot(exe):
    out = []
    for gid, prod, nombre, anio, gb, gen, desc in RIOT:
        g = {"id": gid, "name": nombre, "store": "Riot", "installed": False, "dir": "", "anio": anio, "reqGB": gb, "genres": gen, "desc": desc,
             "dev": "Riot Games", "cover_builtin": gid + ".jpg", "launch": None, "desc_en": DESC_EN.get(gid, "")}
        ys = r"C:\ProgramData\Riot Games\Metadata\%s.live\%s.live.product_settings.yaml" % (prod, prod)
        if os.path.exists(ys):
            m = re.search(r'product_install_full_path:\s*"([^"]+)"', io.open(ys, encoding="utf-8", errors="ignore").read())
            carpeta = m.group(1).replace("/", "\\") if m else ""
            if carpeta and os.path.isdir(carpeta) and any(os.scandir(carpeta)):
                g.update(installed=True, dir=carpeta, drive=drive(carpeta), sizeGB=tam_gb(carpeta))
        if exe and os.path.exists(exe):
            g["launch"] = [exe, "--launch-product=" + prod, "--launch-patchline=live"]  # instala si falta, juega si está
            g["uninstall"] = [exe, "--uninstall-product=" + prod, "--uninstall-patchline=live"]
        out.append(g)
    return out

DESC_EN = {  # descripciones en inglés de los catálogos fijos (Riot y Battle.net)
    "riot_lol": "Riot's MOBA: two teams of five champions fight to destroy the enemy Nexus. Free, uses Vanguard.",
    "riot_valorant": "5v5 round-based tactical shooter with ability-wielding agents. Free, uses Vanguard.",
    "riot_tft": "8-player auto battler with League of Legends champions. Free.",
    "riot_lor": "Collectible card game set in Runeterra. Free.",
    "riot_2xko": "2v2 tag fighting game with League of Legends champions. Free.",
    "bnet_ow2": "Blizzard's 5v5 hero shooter. Free.", "bnet_hs": "Card game set in the Warcraft universe. Free.",
    "bnet_sc2": "Real-time strategy: terran, zerg and protoss. Multiplayer and the Wings of Liberty campaign are free.",
    "bnet_hots": "MOBA with heroes from every Blizzard universe. Free.",
    "bnet_rumble": "Action strategy with Warcraft minis, on PC since 2024. Free.",
    "bnet_dimm": "Online action RPG set between Diablo II and III. Free.",
    "bnet_cod": "Call of Duty's free battle royale (installed from Call of Duty HQ).",
}

# ---------------- Battle.net ----------------
BNET_GRATIS = [  # (id, código battlenet://, nombre, año, GB, géneros, desc, appid Steam para portada/ficha o None)
    ("bnet_ow2", "Pro", "Overwatch 2", "2022", 50, ["Acción", "Shooter", "Multijugador"], "Shooter de héroes 5v5 de Blizzard. Gratis.", "2357570"),
    ("bnet_hs", "WTCG", "Hearthstone", "2014", 5, ["Cartas", "Estrategia"], "Juego de cartas del universo Warcraft. Gratis.", None),
    ("bnet_sc2", "S2", "StarCraft II", "2010", 30, ["Estrategia", "RTS", "Multijugador"], "Estrategia en tiempo real: terran, zerg y protoss. Multijugador y campaña Wings of Liberty gratis.", None),
    ("bnet_hots", "Hero", "Heroes of the Storm", "2015", 20, ["MOBA", "Multijugador"], "MOBA con los héroes de todos los universos de Blizzard. Gratis.", None),
    ("bnet_rumble", "GRY", "Warcraft Rumble", "2023", 6, ["Estrategia", "Acción"], "Estrategia de acción con miniaturas de Warcraft, en PC desde 2024. Gratis.", None),
    ("bnet_dimm", "ANBS", "Diablo Immortal", "2022", 25, ["Acción", "RPG", "Multijugador"], "RPG de acción online entre Diablo II y III. Gratis.", None),
    ("bnet_cod", "AUKS", "Call of Duty: Warzone", "2022", 125, ["Acción", "Shooter", "Multijugador"], "Battle royale gratis de Call of Duty (se instala desde Call of Duty HQ).", "1962663"),
]
BNET_PAGOS = {  # clave del registro -> (id, código, nombre, appid Steam)
    "diablo iv": ("bnet_d4", "Fen", "Diablo IV", "2344520"), "diablo iii": ("bnet_d3", "D3", "Diablo III", None),
    "diablo ii resurrected": ("bnet_d2r", "OSI", "Diablo II: Resurrected", None), "world of warcraft": ("bnet_wow", "WoW", "World of Warcraft", None),
    "warcraft iii": ("bnet_w3", "W3", "Warcraft III: Reforged", None), "starcraft": ("bnet_scr", "S1", "StarCraft: Remastered", None),
}
def battlenet(exe):
    inst = {n: v for n, v in reg_hijas(HKLM, r"SOFTWARE\WOW6432Node\Blizzard Entertainment").items() if n.lower() != "battle.net"}
    for e in uninstall_entries():
        if "blizzard" in str(e.get("Publisher", "")).lower() and e.get("DisplayName") and "battle.net" not in str(e["DisplayName"]).lower():
            inst.setdefault(str(e["DisplayName"]), {})["InstallPath"] = e.get("InstallLocation", "")
    def instalado(nombre):
        n = nrm(nombre)
        for k, v in inst.items():
            kk = nrm(k)
            if _mismo(kk, n):
                return str(v.get("InstallPath") or v.get("InstallLocation") or "")
        return None
    out = []
    for gid, cod, nombre, anio, gb, gen, desc, hint in BNET_GRATIS:
        g = {"id": gid, "name": nombre, "store": "Battle.net", "installed": False, "dir": "", "anio": anio, "reqGB": gb, "genres": gen, "desc": desc,
             "dev": "Blizzard" if "Call of Duty" not in nombre else "Activision", "steam_hint": hint, "cover_builtin": None if hint else gid + ".jpg",
             "launch": ("battlenet://" + cod) if exe and os.path.exists(exe) else None, "desc_en": DESC_EN.get(gid, "")}
        c = instalado(nombre)
        if c is not None:
            g.update(installed=True, dir=c, drive=drive(c), sizeGB=tam_gb(c) if c and os.path.isdir(c) else 0)
        out.append(g)
    for k, v in inst.items():  # pagos: solo si están instalados
        kk = nrm(k)
        for clave, (gid, cod, nombre, hint) in BNET_PAGOS.items():
            if _mismo(kk, clave) and not any(x["id"] == gid for x in out):
                c = str(v.get("InstallPath") or v.get("InstallLocation") or "")
                out.append({"id": gid, "name": nombre, "store": "Battle.net", "installed": True, "dir": c, "drive": drive(c),
                            "sizeGB": tam_gb(c) if c and os.path.isdir(c) else 0, "dev": "Blizzard", "steam_hint": hint,
                            "cover_builtin": None if hint else gid + ".jpg", "launch": ("battlenet://" + cod) if exe and os.path.exists(exe) else None})
    return out

# ---------------- Rockstar ----------------
ROCK = {  # código del manifiesto -> (nombre, appid Steam para portada/ficha)
    "gta5": ("Grand Theft Auto V", "271590"), "gta5_enhanced": ("Grand Theft Auto V Enhanced", "3240220"), "rdr2": ("Red Dead Redemption 2", "1174180"),
    "mp3": ("Max Payne 3", "204100"), "lanoire": ("L.A. Noire", "110800"), "gta4": ("Grand Theft Auto IV", "12210"),
    "gtasa": ("Grand Theft Auto: San Andreas", "12120"), "gtavc": ("Grand Theft Auto: Vice City", "12110"), "gta3": ("Grand Theft Auto III", "12100"),
    "bully": ("Bully: Scholarship Edition", "12200"), "rdr": ("Red Dead Redemption", "2668510"), "gtatrilogy": ("GTA: The Trilogy - Definitive Edition", "1546990"),
}
def rockstar():
    base = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Rockstar Games", "Launcher")
    codigos = {m.group(1).lower() for f in glob.glob(os.path.join(base, "manifest_*_*.xml")) for m in [re.match(r"manifest_(.+?)_\d+\.xml$", os.path.basename(f))] if m}
    codigos.discard("launcher")
    rk = reg_hijas(HKLM, r"SOFTWARE\WOW6432Node\Rockstar Games")
    out = []
    for cod in sorted(codigos):
        nombre, hint = ROCK.get(cod, (cod.upper(), None))
        g = {"id": "rock_" + cod, "name": nombre, "store": "Rockstar", "installed": False, "dir": "", "steam_hint": hint, "dev": "Rockstar Games", "launch": None}
        for k, v in rk.items():
            carpeta = str(v.get("InstallFolder") or "")
            if k in ("Launcher", "Steam", "Epic") or not carpeta or not os.path.isdir(carpeta) or re.search(r"steamapps|epic games", carpeta, re.I):
                continue
            if _mismo(nrm(k), nrm(nombre)):
                g.update(installed=True, dir=carpeta, drive=drive(carpeta), sizeGB=tam_gb(carpeta))
                exe = glob.glob(os.path.join(carpeta, "Play*.exe"))
                if exe: g["launch"] = exe[0]
                break
        out.append(g)
    return out

# ---------------- Ubisoft ----------------
def ubisoft():
    out = []
    for e in uninstall_entries():
        m = re.match(r"Uplay Install (\d+)", str(e.get("_key", "")))
        if not m or not e.get("DisplayName"):
            continue
        loc = str(e.get("InstallLocation", "")).strip('"')
        out.append({"id": "ubi_" + m.group(1), "name": str(e["DisplayName"]), "store": "Ubisoft", "installed": bool(loc and os.path.isdir(loc)), "dir": loc,
                    "drive": drive(loc), "sizeGB": tam_gb(loc) if loc and os.path.isdir(loc) else 0, "launch": "uplay://launch/%s/0" % m.group(1),
                    "uninstall": "uplay://uninstall/%s" % m.group(1)})
    return out
