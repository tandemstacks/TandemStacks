# -*- coding: utf-8 -*-
"""Ventana de SantiStacks (pywebview) + escaneo de bibliotecas en segundo plano + API que usa la página."""
import os, re, sys, json, time, glob, ctypes, pathlib, threading, subprocess, urllib.parse
from concurrent.futures import ThreadPoolExecutor
import webview
from . import paths, steam, stores, covers, detect, build, watch, VERSION

ORDEN_TIENDAS = ["Steam", "Epic", "EA", "Xbox", "Riot", "Battle.net", "Rockstar", "Ubisoft"]

class Nucleo:
    def __init__(self):
        self.cfg = paths.cargar()
        self.launchers = {}
        self.juegos = []
        self.tiendas = []
        self.estado = {"fase": "inicio", "hecho": 0, "total": 0, "version": 0, "msg": ""}
        self.lock = threading.Lock()
        self.ventana = None
        self._pool = None
        self._stop_fichas = threading.Event()

    # ---------- escaneo ----------
    def escanear(self, con_fichas=True):
        """Fase 1 (segundos): launchers + juegos + lo instalado. Fase 2 (minutos, en hilos): fichas y portadas."""
        with self.lock:
            self._stop_fichas.set()
            self.estado.update(fase="escaneando", msg="Buscando launchers y juegos…", hecho=0, total=0)
            self.launchers = detect.detectar(self.cfg)
            sid, persona = steam.usuario()
            if not self.cfg.get("steam_id") and sid:
                self.cfg["steam_id"] = sid
            self.cfg["_steam_user"] = persona
            juegos = []
            # Steam
            inst = steam.instalados()
            bib = steam.biblioteca(self.cfg.get("steam_api_key"), self.cfg.get("steam_id")) if self.launchers["Steam"]["ok"] or inst else None
            vistos = set()
            for aid, nombre in (bib or []):
                g = {"id": aid, "appid": aid, "name": nombre, "store": "Steam", "installed": False, "launch": "steam://run/" + aid}
                if aid in inst:
                    g.update(installed=True, sizeGB=inst[aid]["gb"], drive=inst[aid]["drive"], dir=inst[aid]["dir"])
                juegos.append(g); vistos.add(aid)
            for aid, i in inst.items():
                if aid not in vistos:
                    juegos.append({"id": aid, "appid": aid, "name": i["name"], "store": "Steam", "installed": True, "sizeGB": i["gb"], "drive": i["drive"], "dir": i["dir"], "launch": "steam://run/" + aid})
            steam_info = ("%d juegos" % len(bib)) if bib is not None else ("%d instalados · sin clave API no se ve la biblioteca completa" % len(inst) if not self.cfg.get("steam_api_key") else "%d instalados · la clave o el perfil no dejaron leer la biblioteca" % len(inst))
            # otras tiendas
            try: juegos += stores.epic()
            except Exception as e: paths.log("epic", e)
            try: juegos += stores.ea()
            except Exception as e: paths.log("ea", e)
            try: juegos += stores.xbox()
            except Exception as e: paths.log("xbox", e)
            try: juegos += stores.riot(self.launchers["Riot"]["exe"])
            except Exception as e: paths.log("riot", e)
            try: juegos += stores.battlenet(self.launchers["Battle.net"]["exe"])
            except Exception as e: paths.log("bnet", e)
            try: juegos += stores.rockstar()
            except Exception as e: paths.log("rockstar", e)
            try: juegos += stores.ubisoft()
            except Exception as e: paths.log("ubisoft", e)
            # fichas ya cacheadas + portadas ya bajadas (instantáneo)
            for g in juegos:
                f = steam.ficha_cacheada(g.get("appid") or g.get("steam_hint") or "")
                if f: self._aplicar_ficha(g, f)
                dest = os.path.join(paths.COVERS, g["id"] + ".jpg")
                g["cover"] = "covers/%s.jpg" % g["id"] if os.path.exists(dest) else ""
            juegos = [g for g in juegos if g.get("tipo", "game") in ("game", "")]  # fuera DLC, demos, bandas sonoras, herramientas
            fuera = set(self.cfg.get("desvinculadas") or [])
            juegos = [g for g in juegos if g["store"] not in fuera]
            self.juegos = juegos
            # resumen de tiendas
            cuenta = lambda s: sum(1 for g in juegos if g["store"] == s)
            solo_inst = {"EA", "Xbox", "Ubisoft"}
            self.tiendas = []
            for n in ORDEN_TIENDAS:
                l = self.launchers[n]
                if n == "Steam": info, st = steam_info, ("ok" if bib is not None else "parcial") if l["ok"] else "no"
                elif n in solo_inst: info, st = ("%d instalados (%s)" % (cuenta(n), "Ubisoft guarda tu biblioteca cifrada: solo se ven los instalados" if n == "Ubisoft" else "la tienda no deja leer la biblioteca completa")), ("parcial" if l["ok"] else "no")
                else: info, st = ("%d juegos" % cuenta(n)), ("ok" if l["ok"] else "no")
                if not l["ok"]: info = "launcher no instalado" + (" · %d juegos" % cuenta(n) if cuenta(n) else "")
                if n in fuera: st, info = "no", "desvinculada (clic para volver a vincular)"
                self.tiendas.append({"n": n, "c": l["color"], "st": st, "info": info, "ok": l["ok"], "bajar": l["bajar"], "fuera": n in fuera})
            self.cfg["_launchers_vista"] = [{"n": n, "exe": self.launchers[n]["exe"], "ok": self.launchers[n]["ok"], "manual": self.launchers[n]["manual"]} for n in ORDEN_TIENDAS]
            self.estado.update(fase="listo", msg="")
            self._publicar()
        if con_fichas:
            threading.Thread(target=self._fichas, daemon=True).start()

    def _aplicar_ficha(self, g, f):
        for k in ("desc", "genres", "anio", "dev", "reqGB", "meta", "revPct", "revN", "revTxt", "tipo"):
            if f.get(k) not in (None, "", []) and g.get(k) in (None, "", []):
                g[k] = f[k]

    def _fichas(self):
        """Fase 2: completar fichas y portadas que falten, de a 4 hilos, publicando cada 8 s."""
        self._stop_fichas = threading.Event(); stop = self._stop_fichas
        pend = [g for g in self.juegos if not g.get("cover") or (not g.get("desc") and (g.get("appid") or g.get("steam_hint") or g["store"] not in ("Riot", "Battle.net")))]
        self.estado.update(fase="fichas", hecho=0, total=len(pend), msg="Bajando fichas y portadas…")
        ultimo = [time.time()]
        def uno(g):
            if stop.is_set(): return
            try:
                if not g.get("appid") and not g.get("steam_hint") and g["store"] not in ("Riot",):
                    g["steam_hint"] = steam.buscar_appid(g["name"])
                aid = g.get("appid") or g.get("steam_hint")
                if aid and not g.get("desc"):
                    self._aplicar_ficha(g, steam.ficha(aid, self.cfg.get("idioma", "spanish")))
                if not g.get("cover"):
                    covers.asegurar(g)
            except Exception as e:
                paths.log("ficha", g.get("name"), e)
            self.estado["hecho"] += 1
            if time.time() - ultimo[0] > 8:
                ultimo[0] = time.time(); self._publicar()
        with ThreadPoolExecutor(max_workers=4) as ex:
            list(ex.map(uno, pend))
        if not stop.is_set():
            self.juegos = [g for g in self.juegos if g.get("tipo", "game") in ("game", "")]
            self.estado.update(fase="listo", msg="")
            self._publicar()

    def _publicar(self):
        self.estado["version"] += 1
        try:
            build.escribir(self.juegos, self.tiendas, self.cfg, self.estado)
        except Exception as e:
            paths.log("build", e)

    # ---------- vigilancia de cambios (instalar/desinstalar fuera de la app) ----------
    def huella(self):
        partes = [steam.huella_instalados()]
        partes += sorted(glob.glob(r"C:\ProgramData\Epic\EpicGamesLauncher\Data\Manifests\*.item"))
        try: partes.append("riot|" + "|".join(sorted(os.listdir(r"C:\Riot Games"))))
        except OSError: pass
        for ruta in (r"SOFTWARE\WOW6432Node\Blizzard Entertainment", r"SOFTWARE\WOW6432Node\Rockstar Games"):
            partes.append(ruta + "|" + "|".join(sorted(detect.reg_hijas(detect.HKLM, ruta))))
        partes.append("|".join(sorted(str(e.get("DisplayName")) for e in detect.uninstall_entries() if "electronic arts" in str(e.get("Publisher", "")).lower() or str(e.get("_key", "")).startswith("Uplay Install"))))
        return "\n".join(partes)

    def vigilar(self):
        antes = self.huella()
        while True:
            time.sleep(12)
            try:
                ahora = self.huella()
                if ahora != antes:
                    antes = ahora
                    self.escanear()
            except Exception as e:
                paths.log("vigilar", e)

    # ---------- versión nueva ----------
    def version_nueva(self):
        repo = self.cfg.get("repo")
        if not repo: return None
        cache = os.path.join(paths.CACHE, "version_remota.json")
        try:
            d = json.load(open(cache))
            if time.time() - d.get("ts", 0) < 86400: return d.get("tag") if d.get("tag") and d["tag"].lstrip("v") != VERSION else None
        except Exception: pass
        try:
            j = steam.http_json("https://api.github.com/repos/%s/releases/latest" % repo, 15)
            tag = j.get("tag_name", "")
            json.dump({"ts": time.time(), "tag": tag}, open(cache, "w"))
            return tag if tag and tag.lstrip("v") != VERSION else None
        except Exception:
            return None

NUC = Nucleo()

class Api:
    """Lo que llama la página por window.pywebview.api.*"""
    def datos(self):
        return {"juegos": [build.publico(g) for g in NUC.juegos], "discos": build.discos(NUC.juegos), "tiendas": NUC.tiendas, "estado": NUC.estado}

    def estado(self):
        return NUC.estado

    def config(self):
        c = {k: v for k, v in NUC.cfg.items() if not k.startswith("_")}
        c["launchers_vista"] = NUC.cfg.get("_launchers_vista", [])
        c["steam_user"] = NUC.cfg.get("_steam_user", "")
        c["version"] = VERSION
        return c

    def guardar_config(self, c):
        for k in ("steam_api_key", "steam_id", "cerrar_launchers", "idioma"):
            if k in c: NUC.cfg[k] = c[k]
        if "launchers" in c:  # {"Steam": "ruta"} -> solo las que el usuario escribió
            NUC.cfg["launchers"] = {n: {"exe": p} for n, p in c["launchers"].items() if p}
        NUC.cfg["primer_arranque"] = False
        paths.guardar({k: v for k, v in NUC.cfg.items() if not k.startswith("_")})
        threading.Thread(target=NUC.escanear, daemon=True).start()
        return True

    def reescanear(self):
        threading.Thread(target=NUC.escanear, daemon=True).start()
        return True

    def version_nueva(self):
        return NUC.version_nueva()

    def preferencia(self, clave, valor):
        """Guarda una preferencia suelta. Cambiar el idioma rehace las fichas de Steam (vienen traducidas de la tienda)."""
        if clave not in ("tema", "idioma", "cerrar_launchers"):
            return False
        cambio_idioma = clave == "idioma" and valor != NUC.cfg.get("idioma")
        NUC.cfg[clave] = valor
        paths.guardar({k: v for k, v in NUC.cfg.items() if not k.startswith("_")})
        if cambio_idioma:
            for f in glob.glob(os.path.join(steam.CACHE_STEAM, "*.json")):
                try: os.remove(f)
                except OSError: pass
            for g in NUC.juegos:
                for k in ("desc", "genres", "anio", "dev", "reqGB", "meta", "revPct", "revN", "revTxt"):
                    g.pop(k, None)
            threading.Thread(target=NUC.escanear, daemon=True).start()
        else:
            NUC._publicar()
        return True

    def desinstalar_app(self):
        """Lanza el desinstalador de Windows de SantiStacks (solo si se instaló con el Setup)."""
        if getattr(sys, "frozen", False):
            carpeta = os.path.dirname(sys.executable)
            for n in ("unins000.exe", "unins001.exe"):
                u = os.path.join(carpeta, n)
                if os.path.exists(u):
                    subprocess.Popen([u]); return True
        os.startfile("ms-settings:appsfeatures"); return False

    def desvincular(self, nombre, fuera=True):
        """Saca (o vuelve a poner) una tienda de SantiStacks. No toca nada del launcher."""
        d = set(NUC.cfg.get("desvinculadas") or [])
        (d.add if fuera else d.discard)(nombre)
        NUC.cfg["desvinculadas"] = sorted(d)
        paths.guardar({k: v for k, v in NUC.cfg.items() if not k.startswith("_")})
        threading.Thread(target=NUC.escanear, daemon=True).start()
        return True


    def abrir_url(self, url):
        if re.match(r"https?://", url): os.startfile(url)
        return True

    def abrir_datos(self):
        os.startfile(paths.DATA); return True

    def accion(self, q):
        """tipo=run|install|uninstall&appid=N (Steam) · lanzar=id (otras tiendas) · abrir=Tienda (launcher) · abrir=apps (Programas de Windows)."""
        q = urllib.parse.parse_qs(q)
        tipo, appid, que, lz = q.get("tipo", [""])[0], q.get("appid", [""])[0], q.get("abrir", [""])[0], q.get("lanzar", [""])[0]
        vig = bool(NUC.cfg.get("cerrar_launchers", True))
        if tipo in ("install", "uninstall", "run") and re.fullmatch(r"\d{1,9}", appid):
            uri = "steam://%s/%s" % (tipo, appid)
            if tipo == "run": watch.lanzar("Steam", "", lambda: os.startfile(uri), NUC.launchers, vig)
            else: os.startfile(uri)
            return True
        if que == "apps":
            os.startfile("ms-settings:appsfeatures"); return True
        des = q.get("desinstalar", [""])[0]
        if des:  # desinstalar un juego de otra tienda: comando propio si la tienda lo tiene, si no Aplicaciones instaladas de Windows
            g = next((x for x in NUC.juegos if x["id"] == des), None)
            u = g.get("uninstall") if g else None
            if isinstance(u, list): subprocess.Popen(u, cwd=os.path.dirname(u[0]))
            elif u: os.startfile(u)
            else: os.startfile("ms-settings:appsfeatures")
            return True
        if que in NUC.launchers:
            os.startfile(NUC.launchers[que]["abrir"]); return True
        if lz:
            g = next((x for x in NUC.juegos if x["id"] == lz and x.get("launch")), None)
            if not g: return False
            d = g["launch"]
            arrancar = (lambda: subprocess.Popen(d, cwd=os.path.dirname(d[0]))) if isinstance(d, list) else (lambda: os.startfile(d))
            watch.lanzar(g["store"], g.get("dir", "") if g.get("installed") else "", arrancar, NUC.launchers, vig)
            return True
        return False

def _poner_icono(ventana, icono):
    try:
        import clr
        clr.AddReference("System.Drawing")
        from System import Action
        from System.Drawing import Icon
        f = ventana.native
        f.Invoke(Action(lambda: setattr(f, "Icon", Icon(icono))))
    except Exception:
        pass

def main():
    icono = os.path.join(paths.ASSETS, "icon.ico")
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("SantiStacks")
    except Exception:
        pass
    # primera pantalla enseguida (con lo que haya en caché); el escaneo real arranca al abrir
    if not os.path.exists(paths.HTML):
        NUC.estado.update(fase="escaneando", msg="Preparando la biblioteca…")
        build.escribir([], [], NUC.cfg, NUC.estado)
    v = webview.create_window("SantiStacks", pathlib.Path(paths.HTML).as_uri(), js_api=Api(), width=1400, height=900,
                              min_size=(820, 520), background_color="#f2f2ef")
    NUC.ventana = v
    v.events.shown += lambda: _poner_icono(v, icono)
    def arranque():
        NUC.escanear()
        threading.Thread(target=NUC.vigilar, daemon=True).start()
    webview.start(lambda: threading.Thread(target=arranque, daemon=True).start(), icon=icono)
