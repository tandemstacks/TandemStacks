# -*- coding: utf-8 -*-
"""Ventana de TasloStacks (pywebview) + escaneo de bibliotecas en segundo plano + API que usa la página."""
import os, re, sys, json, time, glob, ctypes, pathlib, threading, subprocess, urllib.parse, urllib.request
from concurrent.futures import ThreadPoolExecutor
import webview
from . import paths, steam, stores, covers, detect, build, watch, inicio, fichas, VERSION

ORDEN_TIENDAS = ["Steam", "Epic", "EA", "Xbox", "Riot", "Battle.net", "Rockstar", "Ubisoft", "GOG", "Amazon", "itch.io"]

class Nucleo:
    def __init__(self):
        self.cfg = paths.cargar()
        self.launchers = {}
        self.minimizada = False
        try: self.jugado = float(json.load(open(paths.NIVEL, encoding="utf-8"))["segundos"])
        except Exception: self.jugado = 0.0
        self._guardado = time.time()
        self.juegos = []
        self.tiendas = []
        self.estado = {"fase": "inicio", "hecho": 0, "total": 0, "version": 0, "msg": "", "de": ""}
        self.lock = threading.Lock()
        self._stop_fichas = threading.Event()

    # ---------- escaneo ----------
    def escanear(self, con_fichas=True):
        """Fase 1 (segundos): launchers + juegos + lo instalado. Fase 2 (minutos, en hilos): fichas y portadas."""
        with self.lock:
            self._stop_fichas.set()
            self.estado.update(fase="escaneando", msg="Buscando launchers instalados…", de="", hecho=0, total=0)
            paso = lambda n: self.estado.update(msg="Leyendo juegos de %s…", de=n)  # la pantalla de carga muestra qué está haciendo
            self.launchers = detect.detectar(self.cfg)
            # ya, no al final del escaneo: la bienvenida los muestra apenas abre
            self.cfg["_launchers_vista"] = [{"n": n, "exe": self.launchers[n]["exe"], "ok": self.launchers[n]["ok"], "manual": self.launchers[n]["manual"]} for n in ORDEN_TIENDAS]
            paso("Steam")
            sid, persona = steam.usuario()
            if not self.cfg.get("steam_id") and sid:
                self.cfg["steam_id"] = sid
            self.cfg["_steam_user"] = persona
            juegos = []
            # Steam
            inst = steam.instalados()
            bib = steam.biblioteca(self.cfg.get("steam_api_key"), self.cfg.get("steam_id")) if self.launchers["Steam"]["ok"] or inst else None
            vistos = set()
            jugado = steam.tiempos(self.cfg.get("steam_id"))  # horas y última vez, de los archivos de Steam (sin red)
            for aid, nombre, mins, ult in (bib or []):
                if aid not in inst and steam.NO_JUEGO.search(nombre or ""):
                    continue
                if mins or ult: jugado[aid] = (max(mins, jugado.get(aid, (0, 0))[0]), max(ult, jugado.get(aid, (0, 0))[1]))  # la Web API suma otras PC
                g = {"id": aid, "appid": aid, "name": nombre, "store": "Steam", "installed": False, "launch": "steam://run/" + aid}
                if aid in inst:
                    g.update(installed=True, sizeGB=inst[aid]["gb"], drive=inst[aid]["drive"], dir=inst[aid]["dir"])
                juegos.append(g); vistos.add(aid)
            for aid, i in inst.items():
                if aid not in vistos:
                    juegos.append({"id": aid, "appid": aid, "name": i["name"], "store": "Steam", "installed": True, "sizeGB": i["gb"], "drive": i["drive"], "dir": i["dir"], "launch": "steam://run/" + aid})
            for g in juegos:
                mins, ult = jugado.get(g["appid"], (0, 0))
                if mins: g["horas"] = round(mins / 60, 1)
                if ult: g["ultima"] = ult
            steam_info = ("%d juegos" % len(bib)) if bib is not None else ("%d instalados · sin clave API no se ve la biblioteca completa" % len(inst) if not self.cfg.get("steam_api_key") else "%d instalados · la clave o el perfil no dejaron leer la biblioteca" % len(inst))
            # otras tiendas
            paso("Epic")
            try: juegos += stores.epic()
            except Exception as e: paths.log("epic", e)
            paso("EA")
            try: juegos += stores.ea()
            except Exception as e: paths.log("ea", e)
            paso("Xbox")
            try: juegos += stores.xbox()
            except Exception as e: paths.log("xbox", e)
            paso("Riot")
            try: juegos += stores.riot(self.launchers["Riot"]["exe"])
            except Exception as e: paths.log("riot", e)
            paso("Battle.net")
            try: juegos += stores.battlenet(self.launchers["Battle.net"]["exe"])
            except Exception as e: paths.log("bnet", e)
            paso("Rockstar")
            try: juegos += stores.rockstar()
            except Exception as e: paths.log("rockstar", e)
            paso("Ubisoft")
            try: juegos += stores.ubisoft()
            except Exception as e: paths.log("ubisoft", e)
            paso("GOG")
            try: juegos += stores.gog(self.launchers["GOG"]["exe"] if self.launchers["GOG"]["ok"] else "")
            except Exception as e: paths.log("gog", e)
            paso("Amazon")
            try: juegos += stores.amazon()
            except Exception as e: paths.log("amazon", e)
            paso("itch.io")
            try: juegos += stores.itch()
            except Exception as e: paths.log("itch", e)
            self.estado.update(msg="Armando la biblioteca…", de="")
            # fichas ya cacheadas + portadas ya bajadas (instantáneo). La ficha de Steam es solo para juegos de Steam:
            # los de otras tiendas muestran lo de su tienda (steam_hint queda solo para la portada)
            for g in juegos:
                f = steam.ficha_cacheada(g["appid"], self.cfg.get("idioma", "spanish")) if g.get("appid") else None
                if f: self._aplicar_ficha(g, f)
                g["cover"] = covers.rapida(g)  # link, sin descargar
            juegos = [g for g in juegos if g.get("tipo", "game") in ("game", "")]  # fuera DLC, demos, bandas sonoras, herramientas
            fuera = set(self.cfg.get("desvinculadas") or [])
            juegos = [g for g in juegos if g["store"] not in fuera]
            self.juegos = juegos
            # resumen de tiendas
            cuenta = lambda s: sum(1 for g in juegos if g["store"] == s)
            solo_inst = {"EA", "Xbox", "Ubisoft", "Amazon"}
            self.tiendas = []
            for n in ORDEN_TIENDAS:
                l = self.launchers[n]
                if n == "Steam": info, st = steam_info, ("ok" if bib is not None else "parcial") if l["ok"] else "no"
                elif n == "Ubisoft": info, st = ("%d juegos (Ubisoft guarda tu biblioteca cifrada: se ven los instalados y los que TasloStacks reconoce por su ícono)" % cuenta(n)), ("parcial" if l["ok"] else "no")
                elif n in solo_inst: info, st = ("%d instalados (%s)" % (cuenta(n), "%s guarda tu biblioteca cifrada: solo se ven los instalados" % n if n in ("Ubisoft", "Amazon") else "la tienda no deja leer la biblioteca completa")), ("parcial" if l["ok"] else "no")
                else: info, st = ("%d juegos" % cuenta(n)), ("ok" if l["ok"] else "no")
                if not l["ok"]: info = "launcher no instalado" + (" · %d juegos" % cuenta(n) if cuenta(n) else "")
                if n in fuera: st, info = "no", "desvinculada (clic para volver a vincular)"
                self.tiendas.append({"n": n, "c": l["color"], "st": st, "info": info, "ok": l["ok"], "bajar": l["bajar"], "fuera": n in fuera})
            self.estado.update(fase="listo", msg="", de="")
            self._publicar()
        if con_fichas:
            threading.Thread(target=self._fichas, daemon=True).start()

    def _aplicar_ficha(self, g, f):
        for k in ("desc", "genres", "anio", "dev", "reqGB", "revPct", "revN", "tipo"):
            if f.get(k) not in (None, "", []) and g.get(k) in (None, "", []):
                g[k] = f[k]

    def _fichas(self):
        """Fase 2: completar fichas y portadas que falten, de a 4 hilos, publicando cada 8 s."""
        self._stop_fichas = threading.Event(); stop = self._stop_fichas
        pend = [g for g in self.juegos if not g.get("cover") or (g.get("appid") and not g.get("desc"))]
        self.estado.update(fase="fichas", hecho=0, total=len(pend), msg="Buscando portadas en Steam…", de="")
        try:  # portadas exactas de Steam: pocos pedidos para toda la biblioteca
            covers.steam_exactas([g.get("appid") or g.get("steam_hint") for g in self.juegos])
            for g in self.juegos:
                g["cover"] = covers.rapida(g) or g.get("cover", "")
            self._publicar()
        except Exception as e:
            paths.log("steam_exactas", e)
        ultimo = [time.time()]
        def uno(g):
            if stop.is_set(): return
            self.estado.update(msg="Bajando ficha de %s…" if g.get("cover") else "Bajando ficha y portada de %s…", de=g.get("name") or "")
            try:
                if not g.get("cover") and not g.get("appid") and not g.get("steam_hint") and g["store"] not in ("Riot",):
                    g["steam_hint"] = steam.buscar_appid(g["name"])  # solo para la portada
                if g.get("appid") and not g.get("desc"):
                    self._aplicar_ficha(g, steam.ficha(g["appid"], self.cfg.get("idioma", "spanish")))
                if g.get("steam_hint") and "steam:%s" % g["steam_hint"] not in covers._links:
                    covers.steam_exactas([g["steam_hint"]])
                if not g.get("cover") or g.get("steam_hint"):
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
            self.estado.update(fase="listo", msg="", de="")
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
        partes += sorted(glob.glob(os.path.join(stores.EPIC_DATA, "Manifests", "*.item")))
        try: partes.append("epic|%s" % os.path.getmtime(os.path.join(stores.EPIC_DATA, "Catalog", "catcache.bin")))  # juegos nuevos en la cuenta
        except OSError: pass
        partes.append("xbox|" + "|".join(sorted(detect.reg_hijas(detect.HKLM, r"SOFTWARE\Microsoft\GamingServices\PackageRepository\Root"))))
        try: partes.append("riot|" + "|".join(sorted(os.listdir(r"C:\Riot Games"))))
        except OSError: pass
        for ruta in (r"SOFTWARE\WOW6432Node\Blizzard Entertainment", r"SOFTWARE\WOW6432Node\Rockstar Games"):
            partes.append(ruta + "|" + "|".join(sorted(detect.reg_hijas(detect.HKLM, ruta))))
        partes.append(stores.huella_bases())
        partes.append("gog|" + "|".join(sorted(detect.reg_hijas(detect.HKLM, r"SOFTWARE\WOW6432Node\GOG.com\Games"))))
        partes.append("|".join(sorted(str(e.get("DisplayName")) for e in detect.uninstall_entries() if "electronic arts" in str(e.get("Publisher", "")).lower() or str(e.get("_key", "")).startswith("Uplay Install"))))
        return "\n".join(partes)

    def sumar_jugado(self, seg):
        """Contador de horas para el nivel. Se escribe como mucho una vez por minuto."""
        self.jugado += seg
        if time.time() - self._guardado < 60:
            return
        self._guardado = time.time()
        try:
            with open(paths.NIVEL + ".tmp", "w", encoding="utf-8") as f:
                json.dump({"segundos": round(self.jugado)}, f)
            os.replace(paths.NIVEL + ".tmp", paths.NIVEL)
        except OSError as e:
            paths.log("nivel", e)

    def vigilar(self):
        antes = self.huella()
        while True:
            time.sleep(60 if self.minimizada else 12)
            try:
                ahora = self.huella()
                if ahora != antes:
                    antes = ahora
                    self.escanear()
            except Exception:
                import traceback; paths.log("vigilar", traceback.format_exc())

    # ---------- versión nueva ----------
    @staticmethod
    def _link_setup(release):
        """Link del instalador (TasloStacks-Setup-x.y.z.exe) dentro de una release de GitHub."""
        for a in release.get("assets") or []:
            if re.match(r"(TasloStacks|SantiStacks)-Setup-.*\.exe$", a.get("name", ""), re.I):
                return a.get("browser_download_url", "")
        return ""

    def actualizar(self):
        """Baja el instalador nuevo mostrando el avance, lo corre en silencio y cierra la app (el instalador la vuelve a abrir)."""
        try:
            j = steam.http_json("https://api.github.com/repos/%s/releases/latest" % self.cfg.get("repo"), 15)
            url = self._link_setup(j)
            if not url: raise RuntimeError("la release no tiene instalador")
            destino = os.path.join(os.environ.get("TEMP", paths.DATA), os.path.basename(urllib.parse.urlparse(url).path))
            self.estado.update(fase="actualizando", msg="Descargando la actualización…", de="", hecho=0, total=0)
            with urllib.request.urlopen(urllib.request.Request(url, headers=steam.UA), timeout=30) as r, open(destino, "wb") as f:
                self.estado["total"] = int(r.headers.get("Content-Length") or 0)
                while True:
                    b = r.read(256 * 1024)
                    if not b: break
                    f.write(b); self.estado["hecho"] += len(b)
            self.estado.update(msg="Instalando la versión nueva: TasloStacks se cierra y vuelve a abrir sola…", hecho=0, total=0)
            time.sleep(2)  # que la página llegue a mostrar el mensaje
            subprocess.Popen([destino, "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CLOSEAPPLICATIONS"],
                             creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP)
            time.sleep(1)
            os._exit(0)
        except Exception as e:
            paths.log("actualizar", e)
            self.estado.update(fase="listo", msg="", de="", hecho=0, total=0)
            os.startfile("https://github.com/%s/releases/latest" % self.cfg.get("repo"))  # plan B: la página de descarga

    def version_nueva(self):
        # solo avisa si la de GitHub es MÁS nueva (no alcanza con que sea distinta: la caché puede tener una vieja)
        num = lambda t: tuple(int(x) for x in re.findall(r"\d+", t or ""))
        mas_nueva = lambda tag: tag if tag and num(tag) > num(VERSION) else None
        repo = self.cfg.get("repo")
        if not repo: return None
        cache = os.path.join(paths.CACHE, "version_remota.json")
        try:
            d = json.load(open(cache))
            if d.get("repo") == repo and time.time() - d.get("ts", 0) < 3600: return mas_nueva(d.get("tag"))  # 1 hora: con 1 día una versión recién publicada tardaba en avisarse
        except Exception: pass
        try:
            j = steam.http_json("https://api.github.com/repos/%s/releases/latest" % repo, 15)
            tag = j.get("tag_name", "")
            json.dump({"ts": time.time(), "repo": repo, "tag": tag, "setup": self._link_setup(j)}, open(cache, "w"))
            return mas_nueva(tag)
        except Exception:
            return None

NUC = Nucleo()

class Api:
    """Lo que llama la página por window.pywebview.api.*"""
    def datos(self):
        return {"juegos": [build.publico(g, NUC.cfg.get("idioma", "spanish")) for g in NUC.juegos], "discos": build.discos(NUC.juegos), "tiendas": NUC.tiendas, "estado": NUC.estado}

    def estado(self):
        """Lo pide la página cada pocos segundos, solo con la ventana a la vista (minimizada queda suspendida)."""
        try: bajando = steam.descargas()
        except Exception: bajando = []
        return dict(NUC.estado, jugado=round(NUC.jugado), descargas=bajando)

    def ficha(self, ids):
        """Datos de la tienda de cada juego de la tarjeta, pedidos al abrir la ficha (con caché). {id: {...}}"""
        out = {}
        for i in ids or []:
            g = next((x for x in NUC.juegos if x["id"] == i), None)
            if g:
                try: out[i] = fichas.de(g, NUC.cfg)
                except Exception as e: paths.log("ficha", i, e)
        return out

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
        if clave not in ("tema", "idioma", "cerrar_launchers", "primer_arranque"):
            return False
        cambio_idioma = clave == "idioma" and valor != NUC.cfg.get("idioma")
        NUC.cfg[clave] = valor
        paths.guardar({k: v for k, v in NUC.cfg.items() if not k.startswith("_")})
        if cambio_idioma:
            for g in NUC.juegos:  # las fichas del otro idioma quedan en su caché; acá se sacan los textos viejos
                for k in ("desc", "genres", "anio", "dev", "reqGB", "revPct", "revN"):
                    g.pop(k, None)
            NUC._publicar()  # la página recarga enseguida: que ya encuentre el idioma nuevo (si no, el interruptor salta)
            threading.Thread(target=NUC.escanear, daemon=True).start()
        else:
            NUC._publicar()
        return True

    def desinstalar_app(self):
        """Lanza el desinstalador de Windows de TasloStacks (solo si se instaló con el Setup)."""
        if getattr(sys, "frozen", False):
            carpeta = os.path.dirname(sys.executable)
            for n in ("unins000.exe", "unins001.exe"):
                u = os.path.join(carpeta, n)
                if os.path.exists(u):
                    subprocess.Popen([u]); return True
        os.startfile("ms-settings:appsfeatures"); return False

    def inicio_estado(self):
        """Launchers que arrancan con Windows (activos o ya deshabilitados)."""
        return inicio.estado()

    def quitar_inicio(self):
        r = inicio.quitar_todos(); paths.log("quitar inicio:", r); return r

    def desvincular(self, nombre, fuera=True):
        """Saca (o vuelve a poner) una tienda de TasloStacks. No toca nada del launcher."""
        d = set(NUC.cfg.get("desvinculadas") or [])
        (d.add if fuera else d.discard)(nombre)
        NUC.cfg["desvinculadas"] = sorted(d)
        paths.guardar({k: v for k, v in NUC.cfg.items() if not k.startswith("_")})
        threading.Thread(target=NUC.escanear, daemon=True).start()
        return True


    def actualizar(self):
        """Botón Actualizar del aviso. Con el programa instalado baja e instala solo; corriendo desde el código abre la página."""
        if not getattr(sys, "frozen", False):
            os.startfile("https://github.com/%s/releases/latest" % NUC.cfg.get("repo")); return "web"
        threading.Thread(target=NUC.actualizar, daemon=True).start()
        return "ok"

    def abrir_url(self, url):
        if re.match(r"(https?://|mailto:|steam://openurl/https://)", url): os.startfile(url)  # steam://openurl abre la página dentro de Steam (con tu sesión)
        return True

    def catalogo(self, tienda):
        """Catálogo público de una tienda para Explorar. Lo arma GitHub cada semana (scripts/catalogos.py) y se publica con
        la landing; acá se guarda 1 día en la caché. Marca con "tuyo" los que ya están en tu biblioteca."""
        if tienda not in ("gog", "todos"): return None
        cache = os.path.join(paths.CACHE, "catalogo_%s.json" % tienda)
        d = None
        try:
            if time.time() - os.path.getmtime(cache) < 86400: d = json.load(open(cache, encoding="utf-8"))
        except Exception: pass
        if d is None:
            try:
                d = steam.http_json("https://taslostacks.github.io/TasloStacks/catalogo/%s.json" % tienda, 30)
                json.dump(d, open(cache, "w", encoding="utf-8"), ensure_ascii=False)
            except Exception as e:
                paths.log("catalogo", tienda, e)
                try: d = json.load(open(cache, encoding="utf-8"))  # sin internet: el último que se bajó
                except Exception: return None
        tuyos = {g["id"] for g in NUC.juegos}
        for j in d.get("juegos", []):  # además del nombre (lo compara la página), por id de tienda
            st = j.get("st") or {"GOG": [j.get("i"), j.get("s")]}
            if "gog_" + str((st.get("GOG") or [""])[0]) in tuyos or str(st.get("Steam", "-")) in tuyos: j["tuyo"] = 1
        return d

    def ver_en_tienda(self, tienda, gid, slug=""):
        """Abre la página del juego en el launcher de la tienda (ahí dice Comprar o Instalar según tu cuenta) o en su web."""
        ok = lambda n: NUC.launchers.get(n, {}).get("ok")
        gid = str(gid)
        if tienda.lower() == "gog" and re.fullmatch(r"\d{1,12}", gid):
            if ok("GOG"): os.startfile("goggalaxy://openGameView/" + gid)
            elif re.fullmatch(r"[a-z0-9_]{1,120}", str(slug)): os.startfile("https://www.gog.com/en/game/" + slug)
            return True
        if tienda == "Steam" and re.fullmatch(r"\d{1,9}", gid):
            os.startfile(("steam://store/" if ok("Steam") else "https://store.steampowered.com/app/") + gid); return True
        if tienda == "Xbox" and re.fullmatch(r"[0-9A-Z]{12}", gid):
            os.startfile("ms-windows-store://pdp/?productid=" + gid); return True
        return False

    def abrir_datos(self):
        os.startfile(paths.DATA); return True

    def accion(self, q):
        """tipo=run|install|uninstall&appid=N (Steam) · lanzar=id · desinstalar=id (otras tiendas) · abrir=Tienda (launcher)."""
        q = urllib.parse.parse_qs(q)
        tipo, appid, que, lz = q.get("tipo", [""])[0], q.get("appid", [""])[0], q.get("abrir", [""])[0], q.get("lanzar", [""])[0]
        if tipo in ("install", "uninstall", "run") and re.fullmatch(r"\d{1,9}", appid):
            uri = "steam://%s/%s" % (tipo, appid)
            os.startfile(uri)
            return True
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
            if isinstance(d, list): subprocess.Popen(d, cwd=os.path.dirname(d[0]))
            else: os.startfile(d)
            return True
        return False

def _minimizada(ventana, si):
    """Minimizada no se ve nada: el visor baja su memoria y se suspende, así la página tampoco queda consultando."""
    NUC.minimizada = si
    try:
        from System import Action
        from Microsoft.Web.WebView2.Core import CoreWebView2MemoryUsageTargetLevel as Nivel
        f = ventana.native
        def hacer():
            w = f.webview
            if si:
                w.Visible = False
                w.CoreWebView2.MemoryUsageTargetLevel = Nivel.Low
                w.CoreWebView2.TrySuspendAsync()
            else:
                w.CoreWebView2.Resume()
                w.CoreWebView2.MemoryUsageTargetLevel = Nivel.Normal
                w.Visible = True
        f.Invoke(Action(hacer))
    except Exception as e:
        paths.log("minimizada", si, e)

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
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("TasloStacks")
    except Exception:
        pass
    # primera pantalla enseguida (con lo que haya en caché); el escaneo real arranca al abrir
    # si la plantilla cambió (versión nueva) la página guardada es de la anterior: se rehace, si no la ventana
    # mostraba la pantalla vieja hasta el próximo arranque
    import hashlib
    marca = os.path.join(paths.CACHE, "plantilla.txt")
    huella = hashlib.md5(open(os.path.join(paths.ASSETS, "template.html"), "rb").read()).hexdigest()
    try: vieja = open(marca).read()
    except OSError: vieja = ""
    if not os.path.exists(paths.HTML) or vieja != huella:
        NUC.estado.update(fase="escaneando", msg="Preparando la biblioteca…")
        build.escribir([], [], NUC.cfg, NUC.estado)
        try: open(marca, "w").write(huella)
        except OSError: pass
    v = webview.create_window("TasloStacks %s" % VERSION, pathlib.Path(paths.HTML).as_uri(), js_api=Api(), width=1400, height=900,
                              min_size=(820, 520), background_color="#f2f2ef")
    v.events.shown += lambda: _poner_icono(v, icono)
    v.events.minimized += lambda: _minimizada(v, True)
    v.events.restored += lambda: _minimizada(v, False)
    v.events.maximized += lambda: _minimizada(v, False)  # una ventana maximizada vuelve por acá al sacarla de la barra
    def arranque():
        try:
            NUC.escanear()
        except Exception:
            import traceback; paths.log("escaneo inicial", traceback.format_exc())  # sin esto un error deja la página vieja sin rastro
        threading.Thread(target=NUC.vigilar, daemon=True).start()
        threading.Thread(target=watch.vigilar, daemon=True, args=(lambda: [g.get("dir") for g in NUC.juegos if g.get("installed")], lambda: NUC.launchers,
                                                                 lambda: bool(NUC.cfg.get("cerrar_launchers", True)), NUC.sumar_jugado)).start()
    covers.limpiar_descargadas()
    # private_mode=False: el visor guarda en disco su caché (portadas ya vistas) entre sesiones
    webview.start(lambda: threading.Thread(target=arranque, daemon=True).start(), icon=icono,
                  private_mode=False, storage_path=os.path.join(paths.DATA, "visor"))
