# -*- coding: utf-8 -*-
"""Las demás tiendas. Cada función devuelve juegos como dicts:
   {id, name, store, installed, dir, sizeGB, drive, launch (str|list|None), uninstall, steam_hint (appid para ficha/portada),
    cover_builtin / cover_url, desc (+ desc_en), genres, anio, dev, reqGB}
   Epic: biblioteca completa (catálogo local) + instalados. Riot y Battle.net: catálogo gratis + instalados.
   Rockstar: los títulos cuyo manifiesto bajó el launcher (= biblioteca) + instalados. EA/Xbox/Ubisoft/Amazon: solo instalados.
   GOG e itch.io: biblioteca completa (bases SQLite de sus apps) + instalados."""
import os, re, io, json, glob, time, pathlib, threading, subprocess
from . import paths
from .detect import reg_hijas, uninstall_entries, HKLM, LAUNCHERS

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
    return gb

def guardar_tamanos(juegos):
    """Se guarda una vez por escaneo (no por cada carpeta) y se olvidan los juegos que ya no están instalados."""
    usadas = {g.get("dir") for g in juegos if g.get("installed") and g.get("dir")}
    with _tam_lock:
        for c in [c for c in _tams if c not in usadas]: _tams.pop(c)
        try:
            with open(_TAM_FILE, "w", encoding="utf-8") as f: json.dump(_tams, f)
        except Exception:
            pass

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
    familias = {g["family"].lower() for g in out if g.get("family")}
    try:
        out += [g for g in xbox_cuenta() if g.get("family", "").lower() not in familias]
    except Exception as e:
        paths.log("xbox cuenta:", e)
    return out

def xbox_cuenta():
    """Juegos comprados en la Microsoft Store, instalados o no. La Store guarda en texto la lista de licencias de la cuenta
    (LocalCache/Msa*_PersistentEntitlementsCache.json): solo ids, sin nombres. Nombre, portada y paquete salen de
    displaycatalog (público), con caché; solo se piden los nuevos. Quedan afuera pruebas, apps y licencias vencidas.
    Game Pass no aparece ahí: solo lo comprado."""
    base = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Packages", "Microsoft.WindowsStore_8wekyb3d8bbwe", "LocalCache")
    pids = []
    for f in glob.glob(os.path.join(base, "Msa*_PersistentEntitlementsCache.json")):
        try:
            for e in json.load(open(f, encoding="utf-8-sig")).get("Entitlements", []):
                if e.get("ProductKind") == "Game" and not e.get("IsTrial") and e.get("Status") == "Active" and e.get("ProductId") not in pids:
                    pids.append(e["ProductId"])
        except Exception as ex:
            paths.log("xbox licencias:", ex)
    if not pids:
        return []
    archivo = os.path.join(paths.CACHE, "xbox_productos.json")
    try: datos = json.load(open(archivo, encoding="utf-8"))
    except Exception: datos = {}
    faltan = [p for p in pids if p not in datos]
    from .steam import http_json
    for i in range(0, len(faltan), 20):
        try:
            j = http_json("https://displaycatalog.mp.microsoft.com/v7.0/products?bigIds=%s&market=US&languages=es-es,en-us" % ",".join(faltan[i:i + 20]), 20)
        except Exception as ex:
            paths.log("xbox catálogo:", ex)
            break
        for pr in j.get("Products", []):
            lp = (pr.get("LocalizedProperties") or [{}])[0]
            imgs = {im.get("ImagePurpose"): im.get("Uri", "") for im in lp.get("Images", [])}
            portada = imgs.get("Poster") or imgs.get("BoxArt") or ""
            fam = re.search(r'"PackageFamilyName"\s*:\s*"([^"]+)"', json.dumps(pr))
            datos[pr.get("ProductId")] = {"t": lp.get("ProductTitle", ""), "c": ("https:" + portada) if portada.startswith("//") else portada,
                                          "f": fam.group(1) if fam else ""}
        for p in faltan[i:i + 20]:
            datos.setdefault(p, {"t": "", "c": "", "f": ""})
    try:
        with open(archivo + ".tmp", "w", encoding="utf-8") as f: json.dump(datos, f, ensure_ascii=False)
        os.replace(archivo + ".tmp", archivo)
    except OSError: pass
    out = []
    for p in pids:
        d = datos.get(p) or {}
        n = d.get("t", "").lower()
        if not n or any(x in n for x in ("minecraft launcher", "minecraft education", "not supported", "preview", "xbox", "game bar")): continue
        g = {"id": "xbox_" + re.sub(r"[^A-Za-z0-9]", "", d["f"] or p)[:40], "name": d["t"], "store": "Xbox", "installed": False, "dir": "",
             "launch": "ms-windows-store://pdp/?productid=" + p, "family": d["f"], "xbox_pid": p}
        if d.get("c"): g["cover_url"] = d["c"]
        out.append(g)
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
    return _wow_versiones(out, exe)

# WoW: cada versión (Retail, Classic, Aniversario...) se instala aparte, en su carpeta dentro de la de WoW.
WOW_VERSIONES = [  # (carpeta, id, nombre, código de "Battle.net.exe --exec=launch X" o None si no se conoce: abre la página de WoW)
    ("_retail_", "bnet_wow", "World of Warcraft", "WoW"),
    ("_classic_", "bnet_wow_classic", "World of Warcraft: Mists of Pandaria Classic", "WoWC"),
    ("_classic_era_", "bnet_wow_era", "World of Warcraft Classic", None),
    ("_anniversary_", "bnet_wow_aniv", "World of Warcraft: Burning Crusade Anniversary", None),
]
def _wow_versiones(out, exe):
    wow = next((g for g in out if g["id"] == "bnet_wow"), None)
    if not wow or not wow["dir"] or not os.path.isdir(wow["dir"]):
        return out
    versiones = []
    for carpeta, gid, nombre, cod in WOW_VERSIONES:
        c = os.path.join(wow["dir"], carpeta)
        if not os.path.isdir(c):
            continue
        g = dict(wow, id=gid, name=nombre, dir=c, sizeGB=tam_gb(c))
        if cod and exe and os.path.exists(exe): g["launch"] = [exe, "--exec=launch " + cod]
        versiones.append(g)
    if not versiones:  # carpeta vieja sin versiones: queda la tarjeta única
        return out
    return [g for g in out if g["id"] != "bnet_wow"] + versiones

# ---------------- Rockstar ----------------
ROCK = {  # código del manifiesto -> (nombre, appid Steam para portada/ficha)
    "gta5": ("Grand Theft Auto V", "271590"), "gta5_enhanced": ("Grand Theft Auto V Enhanced", "3240220"), "rdr2": ("Red Dead Redemption 2", "1174180"),
    "mp3": ("Max Payne 3", "204100"), "lanoire": ("L.A. Noire", "110800"), "gta4": ("Grand Theft Auto IV", "12210"),
    "gtasa": ("Grand Theft Auto: San Andreas", "12120"), "gtavc": ("Grand Theft Auto: Vice City", "12110"), "gta3": ("Grand Theft Auto III", "12100"),
    "bully": ("Bully: Scholarship Edition", "12200"), "rdr": ("Red Dead Redemption", "2668510"), "gtatrilogy": ("GTA: The Trilogy - Definitive Edition", "1546990"),
}
# La lista de juegos de la cuenta está cifrada, pero el launcher baja sin cifrar las imágenes de cada juego que tenés
# (uipackages\assets\packages\public\<id>.jpg.cache, y borra las que ya no). Cada portada vertical tiene un id fijo:
ROCK_PORTADAS = {"6fcf0d27-f501-4272-82a6-3a3f86d6422c": "gta5", "9a56bbaa-b519-44c5-97b7-aa74ce64fd3a": "mp3",
                 "df7e2c4c-bec4-4634-966a-2c85731316d1": "rdr2"}
def rockstar():
    base = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Rockstar Games", "Launcher")
    codigos = {m.group(1).lower() for f in glob.glob(os.path.join(base, "manifest_*_*.xml")) for m in [re.match(r"manifest_(.+?)_\d+\.xml$", os.path.basename(f))] if m}
    codigos.discard("launcher")
    raras = []  # portadas verticales (≈401x539) que la tabla todavía no conoce
    for f in glob.glob(os.path.join(base, "uipackages", "assets", "packages", "public", "*")):
        h = os.path.basename(f).split(".")[0].lower()
        cod = ROCK_PORTADAS.get(h)
        if cod: codigos.add(cod)
        elif f.lower().endswith(".jpg.cache"):
            t = _jpg_tam(f)
            if t and 380 <= t[0] <= 420 and 520 <= t[1] <= 560: raras.append((h, f))
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
    lanzar = LAUNCHERS["Rockstar"]["abrir"](LAUNCHERS["Rockstar"]["exe"]()) if "abrir" in LAUNCHERS["Rockstar"] else None
    out += [_sin_identificar("Rockstar", h, f, lanzar) for h, f in sorted(raras)]
    return out

# ---------------- Ubisoft ----------------
UBI_ICONOS = {  # ícono que baja Ubisoft Connect -> juego (se suman a medida que aparezcan)
    "2e12c86976b047eb31f24364b382a0a2": "Assassin's Creed III", "436885f573ff3b6c934cdd33bca9be22": "Assassin's Creed Valhalla",
    "912c28f69e6d44a0c9b106038aa98259": "Far Cry 4", "00842e79ba6c2bf42759a65da1e0cc59": "Far Cry 3 Blood Dragon",
    "1dfa256ba4370c1212f01a1251268216": "Watch Dogs 2", "15a8918b82e47c0da7e24b34d42d71c1": "Tom Clancy's The Division 2",
    "736e15bcd62e86efee7946230be731f6": "Tom Clancy's Ghost Recon Breakpoint", "8231e71808581ef4d3499fe96ecdf921": "Trackmania",
    "4214440db42e3ce9a5d557418c6a7327": "Rayman Origins", "b9e5651a4de5a78d2e5ba4f73ee4478b": "Prince of Persia: The Sands of Time",
    "b210fc1356a7938eb80daf2278b160b7": "Beyond Good and Evil", "3a22e1056f6c9dc902879d02ff4f1893": "Tom Clancy's Splinter Cell",
}
def ubisoft():
    out, iconos_inst = [], set()
    for e in uninstall_entries():
        m = re.match(r"Uplay Install (\d+)", str(e.get("_key", "")))
        if not m or not e.get("DisplayName"):
            continue
        loc = str(e.get("InstallLocation", "")).strip('"')
        ico = re.search(r"([0-9a-f]{32})\.ico", str(e.get("DisplayIcon", "")).lower())  # los instalados suelen usar el mismo ícono
        if ico: iconos_inst.add(ico.group(1))
        out.append({"id": "ubi_" + m.group(1), "name": str(e["DisplayName"]), "store": "Ubisoft", "installed": bool(loc and os.path.isdir(loc)), "dir": loc,
                    "drive": drive(loc), "sizeGB": tam_gb(loc) if loc and os.path.isdir(loc) else 0, "launch": "uplay://launch/%s/0" % m.group(1),
                    "uninstall": "uplay://uninstall/%s" % m.group(1)})
    # Juegos de la cuenta no instalados: la lista está cifrada, pero el launcher baja el ícono de cada juego que tenés
    # (data\<id>.ico junto a upc.exe) y el id de cada ícono es fijo. Sin el número de Ubisoft, se abre Ubisoft Connect.
    # Los íconos que todavía no están en la tabla salen como "sin identificar", para que cualquiera pueda avisar cuál es.
    carpeta = os.path.dirname(LAUNCHERS["Ubisoft"]["exe"]())
    vistos = {nrm(g["name"]) for g in out}
    for f in sorted(glob.glob(os.path.join(carpeta, "data", "*.ico"))):
        h = os.path.basename(f)[:-4].lower()
        nombre = UBI_ICONOS.get(h)
        if nombre and nrm(nombre) not in vistos:
            vistos.add(nrm(nombre))
            out.append({"id": "ubi_" + nrm(nombre).replace(" ", "_"), "name": nombre, "store": "Ubisoft", "installed": False, "dir": "", "launch": "uplay://"})
        elif not nombre and h not in iconos_inst:
            out.append(_sin_identificar("Ubisoft", h, f, "uplay://"))
    return out

def _sin_identificar(tienda, h, archivo, launch):
    """Juego de la cuenta que la app todavía no reconoce: se muestra con su imagen y la ficha ofrece avisar cuál es."""
    return {"id": "x_%s_%s" % (tienda.lower(), h[:12]), "name": "%s · sin identificar (%s)" % (tienda, h[:6]), "store": tienda, "installed": False,
            "dir": "", "launch": launch, "cover_url": pathlib.Path(archivo).as_uri(), "desconocido": h}

def _jpg_tam(ruta):
    """(ancho, alto) de un JPG leyendo solo su encabezado, o None."""
    try:
        with open(ruta, "rb") as f:
            if f.read(2) != b"\xff\xd8": return None
            while True:
                b = f.read(1)
                while b and b != b"\xff": b = f.read(1)
                m = f.read(1)
                while m == b"\xff": m = f.read(1)
                if not m: return None
                largo = int.from_bytes(f.read(2), "big")
                if m[0] in (0xC0, 0xC1, 0xC2):
                    f.read(1); alto = int.from_bytes(f.read(2), "big"); ancho = int.from_bytes(f.read(2), "big")
                    return ancho, alto
                f.seek(largo - 2, 1)
    except (OSError, ValueError):
        return None

# ---------------- bases SQLite de los launchers ----------------
import sqlite3

class _Copia(sqlite3.Connection):
    """Conexión a una copia temporal: al cerrarla se borra la copia (si no, quedaba un archivo por cada escaneo)."""
    def close(self):
        super().close()
        for ext in ("", "-wal", "-shm", "-journal"):
            try: os.remove(self.tmp + ext)
            except OSError: pass

for _f in glob.glob(os.path.join(paths.CACHE, "db_*")):  # copias que dejaron versiones anteriores
    try: os.remove(_f)
    except OSError: pass

def _sqlite(ruta):
    """Abre una copia de la base del launcher (la original puede estar en uso y con cambios en el -wal). Cerrarla la borra."""
    import shutil
    if not os.path.exists(ruta):
        return None
    tmp = os.path.join(paths.CACHE, "db_%s_%s" % (threading.get_ident(), os.path.basename(ruta)))  # un archivo por hilo: escaneo y vigilancia corren juntos
    shutil.copy(ruta, tmp)
    for ext in ("-wal", "-shm"):
        if os.path.exists(ruta + ext): shutil.copy(ruta + ext, tmp + ext)
        elif os.path.exists(tmp + ext): os.remove(tmp + ext)
    c = sqlite3.connect(tmp, factory=_Copia)
    c.tmp = tmp
    return c

def _carga(v):
    try:
        return json.loads(v)
    except Exception:
        return {}

# ---------------- GOG ----------------
GOG_DB = r"C:\ProgramData\GOG.com\Galaxy\storage\galaxy-2.0.db"
GOG_NO_JUEGO = re.compile(EPIC_NO_JUEGO.pattern + r"|goodies|bonus content|upgrade|season pass", re.I)

def gog(exe):
    """Biblioteca completa desde la base de GOG Galaxy (LibraryReleases + GamePieces; no hace falta login)
    + instalados desde el registro (sirve también para juegos instalados sin Galaxy)."""
    juegos = {}
    c = _sqlite(GOG_DB)
    if c:
        try:
            tipos = {n: i for i, n in c.execute("select id, type from GamePieceTypes")}
            def pieza(rk, tipo):
                r = c.execute("select value from GamePieces where releaseKey=? and gamePieceTypeId=? order by userId is null", (rk, tipos.get(tipo))).fetchone()
                return _carga(r[0]) if r else {}
            for (rk,) in c.execute("select distinct releaseKey from LibraryReleases where releaseKey like 'gog_%'").fetchall():
                titulo = (pieza(rk, "title") or pieza(rk, "originalTitle")).get("title", "")
                if not titulo or GOG_NO_JUEGO.search(titulo):
                    continue
                meta = pieza(rk, "meta") or pieza(rk, "originalMeta")
                img = pieza(rk, "originalImages")
                desc = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", pieza(rk, "summary").get("summary") or "")).strip()
                anio = time.gmtime(meta["releaseDate"]).tm_year if meta.get("releaseDate") else None
                pid = rk[4:]
                juegos[pid] = {"id": "gog_" + pid, "name": titulo, "store": "GOG", "installed": False, "dir": "",
                               "cover_url": (img.get("verticalCover") or "").replace(".webp", ".jpg") if img.get("verticalCover") else "",
                               "desc": desc[:400], "genres": meta.get("genres") or [], "anio": anio, "dev": ", ".join(meta.get("developers") or []),
                               "launch": "goggalaxy://openGameView/" + rk}
        finally:
            c.close()
    desins = None
    for pid, v in reg_hijas(HKLM, r"SOFTWARE\WOW6432Node\GOG.com\Games").items():
        carpeta = str(v.get("path") or "")
        if not carpeta or not os.path.isdir(carpeta) or str(v.get("dependsOn") or "").strip():
            continue  # DLC: depende de otro juego
        g = juegos.get(pid) or {"id": "gog_" + pid, "name": str(v.get("gameName") or pid), "store": "GOG"}
        juego_exe = str(v.get("exe") or "")
        g.update(installed=True, dir=carpeta, drive=drive(carpeta), sizeGB=tam_gb(carpeta),
                 launch=[exe, "/command=runGame", "/gameId=" + pid, "/path=" + carpeta] if exe and os.path.exists(exe)
                 else (juego_exe if os.path.exists(juego_exe) else None))
        if desins is None: desins = {str(e.get("_key", "")): str(e.get("UninstallString", "")) for e in uninstall_entries()}  # se lee una sola vez
        uni = desins.get(pid + "_is1", "")
        if uni: g["uninstall"] = uni
        juegos[pid] = g
    return list(juegos.values())

# ---------------- Amazon Games ----------------
AMAZON_SQL = os.path.join(os.environ.get("LOCALAPPDATA", ""), r"Amazon Games\Data\Games\Sql")

def amazon():
    """Solo instalados: la lista de juegos de la cuenta (Entitlements.sqlite) está cifrada por Windows para el launcher."""
    out = []
    c = _sqlite(os.path.join(AMAZON_SQL, "GameInstallInfo.sqlite"))
    if not c:
        return out
    try:
        for gid, carpeta, titulo in c.execute("select Id, InstallDirectory, ProductTitle from DbSet where Installed=1"):
            if not titulo or not carpeta or not os.path.isdir(carpeta):
                continue
            out.append({"id": "amz_" + re.sub(r"[^A-Za-z0-9]", "", gid)[:40], "name": titulo, "store": "Amazon", "installed": True,
                        "dir": carpeta, "drive": drive(carpeta), "sizeGB": tam_gb(carpeta), "launch": "amazon-games://play/" + gid})
    finally:
        c.close()
    return out

# ---------------- itch.io ----------------
ITCH_DB = os.path.join(os.environ.get("APPDATA", ""), r"itch\db\butler.db")

def itch():
    """Biblioteca (juegos comprados o reclamados: download_keys) + instalados (caves) desde la base de la app de itch."""
    juegos = {}
    c = _sqlite(ITCH_DB)
    if not c:
        return []
    try:
        def fila(gid):
            r = c.execute("select id, title, short_text, cover_url, classification, published_at from games where id=?", (gid,)).fetchone()
            return r
        def nuevo(r):
            gid, titulo, corto, portada, clase, pub = r
            return {"id": "itch_%s" % gid, "name": titulo, "store": "itch.io", "installed": False, "dir": "", "desc": (corto or "")[:400],
                    "cover_url": portada or "", "anio": int(str(pub)[:4]) if pub and str(pub)[:4].isdigit() else None,
                    "tipo": "game" if (clase or "game") == "game" else "otro", "launch": "itch://games/%s" % gid}
        for (gid,) in c.execute("select distinct game_id from download_keys").fetchall():
            r = fila(gid)
            if r and r[1]: juegos[gid] = nuevo(r)
        cols = [x[1] for x in c.execute("pragma table_info(caves)")]
        carp = "install_folder_name" if "install_folder_name" in cols else None
        sel = "select c.id, c.game_id, l.path%s from caves c left join install_locations l on l.id=c.install_location_id" % (", c." + carp if carp else "")
        for fila_c in c.execute(sel).fetchall():
            cid, gid, base = fila_c[:3]
            carpeta = os.path.join(base, fila_c[3]) if carp and base and fila_c[3] else ""
            g = juegos.get(gid)
            if not g:
                r = fila(gid)
                if not r or not r[1]: continue
                g = juegos[gid] = nuevo(r)
            g.update(installed=True, dir=carpeta, drive=drive(carpeta) if carpeta else "", sizeGB=tam_gb(carpeta) if carpeta and os.path.isdir(carpeta) else 0,
                     launch="itch://caves/%s/launch" % cid)
    finally:
        c.close()
    return list(juegos.values())

def huella_bases():
    """Qué juegos hay en las bases de GOG, Amazon e itch (no su fecha: los launchers las tocan seguido aunque nada cambie)."""
    partes = []
    for ruta, sql in ((GOG_DB, "select releaseKey from LibraryReleases"),
                      (os.path.join(AMAZON_SQL, "GameInstallInfo.sqlite"), "select Id from DbSet where Installed=1"),
                      (ITCH_DB, "select 'k' || game_id from download_keys union all select 'c' || id from caves")):
        firma = tuple((os.path.getsize(r), os.path.getmtime(r)) if os.path.exists(r) else None for r in (ruta, ruta + "-wal"))
        if ruta in _huellas and _huellas[ruta][0] == firma:  # la base no se tocó: no hace falta copiarla de nuevo
            partes.append(_huellas[ruta][1]); continue
        texto = ""
        try:
            c = _sqlite(ruta)
            if c:
                texto = "|".join(sorted(str(r[0]) for r in c.execute(sql)))
                c.close()
        except Exception:
            pass
        _huellas[ruta] = (firma, texto)
        partes.append(texto)
    return "\n".join(partes)
_huellas = {}  # base: (tamaño y fecha, lo que tenía), para no copiarla entera cada 12 s
