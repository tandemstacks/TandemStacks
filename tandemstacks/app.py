# -*- coding: utf-8 -*-
"""Ventana de TandemStacks (pywebview) + escaneo de bibliotecas en segundo plano + API que usa la página."""
import os, re, sys, json, time, glob, ctypes, pathlib, threading, subprocess, urllib.parse, urllib.request
from concurrent.futures import ThreadPoolExecutor
import webview
from . import paths, steam, stores, covers, detect, build, watch, inicio, fichas, pulso, nvidia, escalera, VERSION
from . import precios as precios_tiendas

ORDEN_TIENDAS = ["Steam", "Epic", "EA", "Xbox", "Riot", "Battle.net", "Rockstar", "Ubisoft", "GOG", "Amazon", "itch.io", "Google Play"]

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
            local = False
            if bib is None and (self.launchers["Steam"]["ok"] or inst):
                bib = steam.biblioteca_local()  # sin clave: lo que Steam guardó de tu biblioteca en la PC
                local = bib is not None
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
            steam_info = ("%d juegos · sin clave API puede faltar alguno" % len(bib)) if local else ("%d juegos" % len(bib)) if bib is not None else ("%d instalados · sin clave API no se ve la biblioteca completa" % len(inst) if not self.cfg.get("steam_api_key") else "%d instalados · la clave o el perfil no dejaron leer la biblioteca" % len(inst))
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
            paso("Google Play")
            try: juegos += stores.google_play()
            except Exception as e: paths.log("google play", e)
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
            solo_inst = {"EA", "Xbox", "Ubisoft", "Amazon", "Google Play"}
            self.tiendas = []
            for n in ORDEN_TIENDAS:
                l = self.launchers[n]
                if n == "Steam": info, st = steam_info, ("ok" if bib is not None else "parcial") if l["ok"] else "no"
                elif n == "Ubisoft": info, st = ("%d juegos (Ubisoft guarda tu biblioteca cifrada: se ven los instalados y los que TandemStacks reconoce por su ícono)" % cuenta(n)), ("parcial" if l["ok"] else "no")
                elif n in solo_inst: info, st = ("%d instalados (%s)" % (cuenta(n), "%s guarda tu biblioteca cifrada: solo se ven los instalados" % n if n in ("Ubisoft", "Amazon", "Google Play") else "la tienda no deja leer la biblioteca completa")), ("parcial" if l["ok"] else "no")
                else: info, st = ("%d juegos" % cuenta(n)), ("ok" if l["ok"] else "no")
                if not l["ok"]: info = "launcher no instalado" + (" · %d juegos" % cuenta(n) if cuenta(n) else "")
                if n in fuera: st, info = "no", "desvinculada (clic para volver a vincular)"
                self.tiendas.append({"n": n, "c": l["color"], "st": st, "info": info, "ok": l["ok"], "bajar": l["bajar"], "fuera": n in fuera,
                                     "sinClave": n == "Steam" and not self.cfg.get("steam_api_key")})  # sin clave Steam no deja ver los no instalados
            self.estado.update(fase="listo", msg="", de="")
            self._publicar()
            stores.guardar_tamanos(self.juegos)
        if con_fichas:
            threading.Thread(target=self._fichas, daemon=True).start()

    def _aplicar_ficha(self, g, f):
        for k in ("desc", "genres", "anio", "dev", "reqGB", "revPct", "revN", "tipo"):
            if f.get(k) not in (None, "", []) and g.get(k) in (None, "", []):
                g[k] = f[k]

    def _fichas(self):
        """Fase 2: completar fichas y portadas que falten, de a 4 hilos, publicando cada 8 s."""
        self._stop_fichas = threading.Event(); stop = self._stop_fichas
        # solo lo que hace falta para la pantalla: portadas que faltan y fichas de los instalados.
        # La ficha de los demás se baja al abrirla (Api.ficha) y no se guarda acá: al cerrarla se suelta.
        pend = [g for g in self.juegos if (not g.get("cover") and not covers.sin_portada(g)) or (g.get("installed") and g.get("appid") and not g.get("desc"))]
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
                if g.get("installed") and g.get("appid") and not g.get("desc"):
                    self._aplicar_ficha(g, steam.ficha(g["appid"], self.cfg.get("idioma", "spanish")))
                if g.get("steam_hint") and "steam:%s" % g["steam_hint"] not in covers._links:
                    covers.steam_exactas([g["steam_hint"]])
                if not g.get("cover") or g.get("steam_hint"):
                    covers.asegurar(g)
            except Exception as e:
                paths.log("ficha", g.get("name"), e)
            self.estado["hecho"] += 1
            if time.time() - ultimo[0] > 30:  # la página se redibuja entera con cada aviso: cada 30 s alcanza
                ultimo[0] = time.time(); self._publicar()
        with ThreadPoolExecutor(max_workers=4) as ex:
            list(ex.map(uno, pend))
        if not stop.is_set():
            self.juegos = [g for g in self.juegos if g.get("tipo", "game") in ("game", "")]
            self.estado.update(fase="listo", msg="", de="")
            self._publicar()

    def _publicar(self, forzar=False):
        self.estado["version"] += 1
        if self.estado.get("fase") == "fichas" and not forzar:
            return  # la página abierta pide datos(); el archivo se escribe una vez, al terminar
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
        partes.append("xbox|" + _subclaves(detect.HKLM, r"SOFTWARE\Microsoft\GamingServices\PackageRepository\Root"))
        try: partes.append("riot|" + "|".join(sorted(os.listdir(r"C:\Riot Games"))))
        except OSError: pass
        for ruta in (r"SOFTWARE\WOW6432Node\Blizzard Entertainment", r"SOFTWARE\WOW6432Node\Rockstar Games"):
            partes.append(ruta + "|" + _subclaves(detect.HKLM, ruta))
        partes.append(stores.huella_bases())
        partes.append("gog|" + _subclaves(detect.HKLM, r"SOFTWARE\WOW6432Node\GOG.com\Games"))
        for c, _ in stores.gplay_carpetas():  # Google Play: un juego nuevo deja un acceso directo (la carpeta cambia de fecha)
            for d in (c, os.path.join(c, "Google Play Games")):  # los accesos van a su subcarpeta: su fecha no cambia la de arriba
                try: partes.append("gplay|%s" % os.path.getmtime(d))
                except OSError: pass
        # EA y Ubisoft: "Programas instalados" se relee entero solo si Windows anotó un cambio en esas claves
        firma = tuple(_escrita(h, r) for h, r in _DESINS)
        if firma != self._desins[0]:
            self._desins = (firma, "|".join(sorted(str(e.get("DisplayName")) for e in detect.uninstall_entries() if "electronic arts" in str(e.get("Publisher", "")).lower() or str(e.get("_key", "")).startswith("Uplay Install"))))
        partes.append(self._desins[1])
        return "\n".join(partes)

    _desins = (None, "")
    aviso = None  # lo que se muestra al volver a TandemStacks después de jugar

    def al_medir(self, g, s):
        """Pulso terminó una partida (g = juego y s = resumen) o watch liberó cosas al cerrarla (g = None y s = lo liberado)."""
        with _aviso_candado:  # lo llaman Pulso y watch desde hilos distintos
            viejo = self.aviso or {}
            reciente = time.time() - viejo.get("t", 0) < 300  # lo de la misma partida llega con pocos minutos de diferencia
            a = dict(viejo) if reciente else {}
            if g:
                prev = [p for p in pulso.historial(g["id"])[:-1] if p.get("fps")]
                for k in ("juego", "id", "estado", "causas", "fps", "fpsAntes", "minutos"): a.pop(k, None)
                a.update(juego=g.get("name"), id=g["id"], estado=s.get("estado"), causas=s.get("causas", [])[:3], fps=s.get("fps"),
                         fpsAntes=prev[-1]["fps"] if prev else None, minutos=s.get("minutos"))
            else:
                a.update(ram_mb=round(a.get("ram_mb", 0) + s.get("ram_mb", 0)), disco_mb=round(a.get("disco_mb", 0) + s.get("disco_mb", 0), 1))
            a["t"] = time.time()
            self.aviso = a

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
            if self.cfg.get("sin_accesos", True):
                try:
                    if not self.cfg.get("_accesos_desde"):  # solo los accesos nuevos: los que ya estaban son del usuario
                        self.cfg["accesos_desde"] = self.cfg.get("accesos_desde") or time.time()
                        self.cfg["_accesos_desde"] = True
                        paths.guardar({k: v for k, v in self.cfg.items() if not k.startswith("_")})
                    fuera = stores.sacar_accesos(self.juegos, self.cfg["accesos_desde"])
                    if fuera: paths.log("accesos del escritorio a la papelera:", ", ".join(fuera))
                except Exception as e:
                    paths.log("accesos", e)
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
        """Link del instalador (TandemStacks-Setup-x.y.z.exe) dentro de una release de GitHub."""
        for a in release.get("assets") or []:
            if re.match(r"(TandemStacks|TasloStacks|SantiStacks)-Setup-.*\.exe$", a.get("name", ""), re.I):
                return a.get("browser_download_url", "")
        return ""

    def actualizar(self, solo=False):
        """Baja el instalador nuevo mostrando el avance, lo corre en silencio y cierra la app (el instalador la vuelve a abrir).
        solo=True: es la actualización automática al abrir; si falla, la app sigue igual sin abrir páginas."""
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
            self.estado.update(msg="Instalando la versión nueva: TandemStacks se cierra y vuelve a abrir sola…", hecho=0, total=0)
            time.sleep(2)  # que la página llegue a mostrar el mensaje
            # si se instaló "para todos los usuarios" (Program Files), el instalador en silencio por defecto pone una copia
            # aparte solo para este usuario y los accesos siguen abriendo la vieja: hay que pedirle que pise la de todos
            todos = _en_program_files(sys.executable)
            args = ["/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CLOSEAPPLICATIONS", "/ALLUSERS" if todos else "/CURRENTUSER"]
            if todos:  # necesita permisos de administrador: Windows pregunta
                if ctypes.windll.shell32.ShellExecuteW(None, "runas", destino, " ".join(args), None, 1) <= 32:
                    raise RuntimeError("no se dieron permisos de administrador para actualizar")
            else:
                subprocess.Popen([destino] + args, creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP)
            time.sleep(1)
            os._exit(0)
        except Exception as e:
            paths.log("actualizar", e)
            self.estado.update(fase="listo", msg="", de="", hecho=0, total=0)
            if not solo:
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
        try: abiertas = [t for t in ORDEN_TIENDAS if t in watch.abiertos({n: d for n, d in NUC.launchers.items() if d["ok"]})]
        except Exception: abiertas = []
        try: bajando = steam.descargas()
        except Exception: bajando = []
        try: bajando += stores.epic_descargas("Epic" in abiertas)  # se reusa la lista de procesos de watch
        except Exception as e: paths.log("descargas epic", e)
        try:  # las demás tiendas: no dicen qué ni cuánto falta, pero sí a qué velocidad escriben en el disco
            for t, v in watch.descargando(NUC.launchers).items():
                if t in ("Steam", "Epic") and any(d.get("id", "").startswith("epic_") == (t == "Epic") for d in bajando):
                    continue  # Steam y Epic ya muestran nombre y porcentaje
                bajando.append({"tienda": t, "vel": v})
        except Exception as e: paths.log("descargas", e)
        return dict(NUC.estado, jugado=round(NUC.jugado), descargas=bajando, aviso=NUC.aviso, pc=_en_vivo(), abiertas=abiertas)

    def top(self, tipo):
        """Para la ventana grande de los relojes: qué programas usan más procesador o RAM."""
        if tipo not in ("cpu", "ram"): return []
        if tipo == "cpu" and not _procs_top:
            _top("cpu"); time.sleep(0.6)  # la primera vez hacen falta dos mediciones
        return _top(tipo)

    def soltar_top(self):
        _procs_top.clear(); return True  # al cerrar la ventana se sueltan los procesos guardados

    def cerrar_tiendas(self):
        """Botón "Cerrar tiendas": cierra todos los launchers abiertos (a la vez: Steam tarda unos segundos en apagarse).
        Con un juego andando no toca nada: puede necesitar su tienda."""
        if watch.en_curso(NUC.juegos):
            return {"juego": True}
        lanz = {n: d for n, d in NUC.launchers.items() if d["ok"]}
        abiertas = list(watch.abiertos(lanz))
        res = {}
        hilos = [threading.Thread(target=lambda t=t: res.__setitem__(t, watch.cerrar(t, lanz)), daemon=True) for t in abiertas]
        for h in hilos: h.start()
        for h in hilos: h.join(30)
        mb = sum(res.values())
        if abiertas: watch._anotar(launchers=len(abiertas), ram_mb=mb)
        return {"cerradas": len(abiertas), "mb": round(mb)}

    def aviso_visto(self):
        NUC.aviso = None
        return True

    def pulso(self, ids):
        """Las partidas medidas de cada juego de la tarjeta, pedidas al abrir la ficha. {id: [partidas, la última al final]}"""
        return {i: pulso.historial(i)[-2:] for i in ids or []}  # la ficha usa solo las dos últimas

    def partidas(self, ids):
        """Todas las partidas guardadas (hasta 200 por juego), solo al abrir el historial."""
        return {i: pulso.historial(i) for i in ids or []}

    def partidas_cuenta(self, ids):
        return sum(len(pulso.historial(i)) for i in ids or [])

    def escalera(self, gid):
        """Para la ficha: el paso de ajuste en prueba (con su resultado) o el próximo, y lo que TandemStacks tocó en NVIDIA."""
        try:
            return {"e": escalera.estado(gid), "nv": nvidia.aplicado(gid), "app": escalera.hay_app_nvidia()}
        except Exception as e:
            paths.log("escalera", e); return {}

    def escalera_empezar(self, gid):
        if watch.en_curso(NUC.juegos): return {"error": "juego"}
        try: return {"ok": escalera.empezar(gid)}
        except Exception as e:
            paths.log("escalera empezar", e); return {"error": str(e)}

    def escalera_resolver(self, gid, dejar):
        if watch.en_curso(NUC.juegos): return {"error": "juego"}
        try: return {"ok": escalera.resolver(gid, bool(dejar))}
        except Exception as e:
            paths.log("escalera resolver", e); return {"error": str(e)}

    def abrir_app_nvidia(self):
        if escalera.hay_app_nvidia(): os.startfile(escalera.NVAPP); return True
        return False

    def nvidia_deshacer(self, gid):
        try: return {"ok": nvidia.deshacer(gid)}
        except Exception as e:
            paths.log("nvidia deshacer", e); return {"error": str(e)}

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
        for k in ("steam_api_key", "steam_id", "cerrar_launchers", "cerrar_otros", "limpiar", "sin_accesos", "pulso", "inicio_windows", "idioma"):
            if k in c: NUC.cfg[k] = c[k]
        if "launchers" in c:  # {"Steam": "ruta"} -> solo las que el usuario escribió
            NUC.cfg["launchers"] = {n: {"exe": p} for n, p in c["launchers"].items() if p}
        NUC.cfg["primer_arranque"] = False
        paths.guardar({k: v for k, v in NUC.cfg.items() if not k.startswith("_")})
        _con_windows(NUC.cfg.get("inicio_windows", True))
        threading.Thread(target=NUC.escanear, daemon=True).start()
        return True

    def ahorro(self):
        """El medidor: launchers cerrados, memoria y disco liberados desde que se usa TandemStacks."""
        return watch.ahorro()

    def reescanear(self):
        threading.Thread(target=NUC.escanear, daemon=True).start()
        return True

    def version_nueva(self):
        return NUC.version_nueva()

    def preferencia(self, clave, valor):
        """Guarda una preferencia suelta. Cambiar el idioma rehace las fichas de Steam (vienen traducidas de la tienda)."""
        if clave not in ("tema", "idioma", "cerrar_launchers", "cerrar_otros", "limpiar", "primer_arranque"):
            return False
        cambio_idioma = clave == "idioma" and valor != NUC.cfg.get("idioma")
        NUC.cfg[clave] = valor
        paths.guardar({k: v for k, v in NUC.cfg.items() if not k.startswith("_")})
        if cambio_idioma:
            for g in NUC.juegos:  # las fichas del otro idioma quedan en su caché; acá se sacan los textos viejos
                for k in ("desc", "genres", "anio", "dev", "reqGB", "revPct", "revN"):
                    g.pop(k, None)
            NUC._publicar(True)  # la página recarga enseguida: que ya encuentre el idioma nuevo (si no, el interruptor salta)
            threading.Thread(target=NUC.escanear, daemon=True).start()
        else:
            NUC._publicar(True)
        return True

    def desinstalar_app(self):
        """Lanza el desinstalador de Windows de TandemStacks (solo si se instaló con el Setup)."""
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
        """Saca (o vuelve a poner) una tienda de TandemStacks. No toca nada del launcher."""
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
                d = steam.http_json("https://tandemstacks.github.io/TandemStacks/catalogo/%s.json" % tienda, 30)
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
            if ok("GOG"): os.startfile("goggalaxy://openGameView/" + gid); return "GOG"
            elif re.fullmatch(r"[a-z0-9_]{1,120}", str(slug)): os.startfile("https://www.gog.com/en/game/" + slug)
            return True
        if tienda == "Steam" and re.fullmatch(r"\d{1,9}", gid):
            os.startfile(("steam://store/" if ok("Steam") else "https://store.steampowered.com/app/") + gid)
            return "Steam" if ok("Steam") else True
        # itch.io, Battle.net, Rockstar, Ubisoft y EA: el catálogo trae el link de la página de compra; solo se abren sus dominios
        if tienda in ("itch.io", "Battle.net", "Rockstar", "Ubisoft", "EA") and re.match(r"https://([a-z0-9-]+\.itch\.io|itch\.io|us\.shop\.battle\.net|store\.rockstargames\.com|store\.ubisoft\.com|www\.ea\.com)/", gid):
            os.startfile(gid); return True
        if tienda == "Xbox" and re.fullmatch(r"[0-9A-Z]{12}", gid):
            os.startfile("ms-windows-store://pdp/?productid=" + gid); return True
        return False

    def precios(self, items):
        """Precios de la página de No comprados que se está viendo (ver precios.py)."""
        try: return precios_tiendas.de(items or [])
        except Exception as e:
            paths.log("precios", e); return {}

    def ofertas(self):
        """Juegos con descuento hoy en GOG y Steam, para el interruptor Descuento de No comprados."""
        try: return precios_tiendas.ofertas()
        except Exception as e:
            paths.log("ofertas", e); return {}

    def esperar_tienda(self, tienda):
        """La página la llama después de abrir una tienda y queda en espera: vuelve cuando el launcher ya está corriendo
        (o a los 12 s: algunos juegos arrancan sin su launcher), así no se toca dos veces mientras se abre."""
        l = NUC.launchers.get(tienda) or {}
        if not l.get("ok") or not l.get("procs"):
            time.sleep(1.5); return False
        fin = time.time() + 12
        while time.time() < fin:
            if watch.abiertos({tienda: l}):
                time.sleep(1.5)  # que llegue a mostrar su ventana
                return True
            time.sleep(0.5)
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
            return "Steam"
        des = q.get("desinstalar", [""])[0]
        if des:  # desinstalar un juego de otra tienda: comando propio si la tienda lo tiene, si no Aplicaciones instaladas de Windows
            g = next((x for x in NUC.juegos if x["id"] == des), None)
            u = g.get("uninstall") if g else None
            if isinstance(u, list): subprocess.Popen(u, cwd=os.path.dirname(u[0]))
            elif u: os.startfile(u)
            else: os.startfile("ms-settings:appsfeatures")
            return g["store"] if u and g else True
        if que in NUC.launchers:
            os.startfile(NUC.launchers[que]["abrir"]); return que
        if lz:
            g = next((x for x in NUC.juegos if x["id"] == lz and x.get("launch")), None)
            if not g: return False
            d = g["launch"]
            if isinstance(d, list): subprocess.Popen(d, cwd=os.path.dirname(d[0]))
            else: os.startfile(d)
            return g["store"]  # la página espera a que abra su launcher
        return False

_DESINS = ((detect.HKLM, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
           (detect.HKLM, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
           (detect.HKCU, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"))

_aviso_candado = threading.Lock()
_red = [0, 0, 0.0]
_cpu = [0.0, 0.0]  # tiempo ocupado y total del procesador en la consulta anterior  # bytes bajados, subidos y cuándo, para calcular la velocidad entre dos consultas
_disco = [0, 0, 0, 0]
_gpu = [None]  # None: sin probar · True: hay NVIDIA · False: no hay (no se vuelve a llamar a nvidia-smi)
_procs_top = {}  # pid: proceso, para medir el procesador de cada programa contra la consulta anterior

def _top(tipo):
    """Los 6 programas que más usan procesador o RAM ahora (sumando las ventanas/procesos de un mismo programa).
    Se pide solo con la ventana grande de una gráfica abierta."""
    import psutil
    suma, vivos = {}, set()
    for p in psutil.process_iter(["name", "memory_info"]):
        try:
            n = p.info["name"] or "?"
            if n.lower() in ("system idle process", "idle"): continue
            vivos.add(p.pid)
            if tipo == "ram":
                v = (p.info["memory_info"].rss if p.info["memory_info"] else 0) / 1048576
            else:
                q = _procs_top.get(p.pid)
                if not q or q.create_time() != p.create_time():
                    q = _procs_top[p.pid] = p; q.cpu_percent(None); continue
                v = q.cpu_percent(None) / psutil.cpu_count()
            suma[n] = suma.get(n, 0) + v
        except Exception:
            pass
    for pid in [x for x in _procs_top if x not in vivos]: _procs_top.pop(pid, None)
    return [[re.sub(r"\.exe$", "", n, flags=re.I), round(v, 1)] for n, v in sorted(suma.items(), key=lambda x: -x[1])[:6] if v > 0]

def _en_vivo():
    """Procesador, RAM y red en este momento (lo pide la página cada 4 s, solo con la ventana a la vista). Leerlo no gasta casi nada."""
    import psutil
    try:
        m, n, t = psutil.virtual_memory(), psutil.net_io_counters(), time.time()
        dt = t - _red[2] if _red[2] else 0
        baja, sube = ((n.bytes_recv - _red[0]) / dt, (n.bytes_sent - _red[1]) / dt) if dt > 0 else (0, 0)
        _red[:] = [n.bytes_recv, n.bytes_sent, t]
        # procesador: se calcula contra la consulta anterior. psutil.cpu_percent() guarda eso por hilo y cada consulta
        # de la página llega en un hilo nuevo, así que siempre daba 0
        c = psutil.cpu_times()
        ocupado, total = c.user + c.system + getattr(c, "interrupt", 0) + getattr(c, "dpc", 0), sum(c)
        cpu = 100 * (ocupado - _cpu[0]) / (total - _cpu[1]) if _cpu[1] and total > _cpu[1] else 0
        _cpu[:] = [ocupado, total]
        # disco: bytes leídos y escritos por segundo, y cuánto del tiempo estuvo ocupado (read_time + write_time, en ms)
        d = psutil.disk_io_counters()
        dl = (d.read_bytes - _disco[0]) / dt if dt > 0 and _disco[2] else 0
        de = (d.write_bytes - _disco[1]) / dt if dt > 0 and _disco[2] else 0
        ocup = min(100, (d.read_time + d.write_time - _disco[3]) / (dt * 10)) if dt > 0 and _disco[2] else 0
        _disco[:] = [d.read_bytes, d.write_bytes, t, d.read_time + d.write_time]
        out = {"cpu": max(0, min(100, round(cpu))), "ram": round(m.percent), "ramGB": round(m.used / 1073741824, 1),
               "ramTotal": round(m.total / 1073741824), "baja": max(0, round(baja)), "sube": max(0, round(sube)),
               "dlee": max(0, round(dl)), "descr": max(0, round(de)), "dOcup": max(0, round(ocup))}
        # placa de video: solo NVIDIA (nvidia-smi viene con el driver). Si no está, no se vuelve a probar
        if _gpu[0] is not False:
            v = pulso.nvsmi()
            if v:
                _gpu[0] = True
                out.update(gpu=round(v["gpu_uso"]), vram=round(v["vram"] / 1024, 1), vramTotal=round(v["vram_total"] / 1024),
                           vramPct=round(100 * v["vram"] / v["vram_total"]) if v["vram_total"] else 0,
                           gpuTemp=round(v["gpu_temp"]), gpuW=round(v["gpu_w"]))
            elif _gpu[0] is None:
                _gpu[0] = False
        return out
    except Exception:
        return None

def _con_windows(si):
    """Abrir TandemStacks al iniciar Windows (minimizada), con la clave Run del usuario. Solo el programa instalado."""
    if not getattr(sys, "frozen", False): return
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run", 0, winreg.KEY_SET_VALUE) as k:
            if si: winreg.SetValueEx(k, "TandemStacks", 0, winreg.REG_SZ, '"%s" --inicio' % sys.executable)
            else:
                try: winreg.DeleteValue(k, "TandemStacks")
                except OSError: pass
    except OSError as e:
        paths.log("inicio con windows", e)

def _podar_cache():
    """Las fichas guardadas valen 30 días: las más viejas se borran al abrir, así la carpeta no crece sin límite."""
    limite = time.time() - 30 * 86400
    for carpeta in (os.path.join(paths.CACHE, "fichas"), os.path.join(paths.CACHE, "steam")):
        for raiz, _, archivos in os.walk(carpeta):
            for a in archivos:
                f = os.path.join(raiz, a)
                try:
                    if os.path.getmtime(f) < limite: os.remove(f)
                except OSError: pass

def _escrita(hive, ruta):
    """Cuándo Windows cambió por última vez esa clave (agregar o sacar una subclave la actualiza)."""
    import winreg
    try:
        with winreg.OpenKey(hive, ruta) as k: return winreg.QueryInfoKey(k)[2]
    except OSError: return None

def _subclaves(hive, ruta):
    """Solo los nombres de las subclaves, sin leer sus valores (para la huella de cada 12 s)."""
    import winreg
    try:
        with winreg.OpenKey(hive, ruta) as k:
            return "|".join(sorted(winreg.EnumKey(k, i) for i in range(winreg.QueryInfoKey(k)[0])))
    except OSError: return ""

def _en_program_files(ruta):
    """True si TandemStacks está instalada para todos los usuarios (Program Files) y no solo para este."""
    bases = [os.environ.get(v, "") for v in ("ProgramFiles", "ProgramFiles(x86)", "ProgramW6432")]
    r = os.path.abspath(ruta).lower()
    return any(b and r.startswith(os.path.abspath(b).lower() + os.sep) for b in bases)

def _tamano_inicial():
    """Arranca grande según la pantalla (60 % del ancho y 85 % del alto) y centrada, nunca menos de 1400 × 900 ni más de lo que entra."""
    try:
        p = webview.screens[0]
        w, h = int(min(max(p.width * 0.6, 1400), p.width * 0.92)), int(min(max(p.height * 0.85, 900), p.height * 0.92))
        return w, h, max(0, (p.width - w) // 2), max(0, (p.height - h) // 2 - 20)  # un poco más arriba por la barra de tareas
    except Exception:
        return 1400, 900, None, None

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

def _ya_abierta():
    """Una sola TandemStacks por usuario: si ya hay una, se trae su ventana al frente y esta se cierra.
    Dos copias vigilarían juegos, cerrarían launchers y escribirían el nivel cada una por su lado."""
    k32, u32 = ctypes.windll.kernel32, ctypes.windll.user32
    Main._mutex = k32.CreateMutexW(None, False, r"Local\TandemStacks_una_sola")
    if k32.GetLastError() != 183:  # ERROR_ALREADY_EXISTS
        return False
    hallada = []
    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    def ver(h, _):
        b = ctypes.create_unicode_buffer(256); u32.GetWindowTextW(h, b, 256)
        if b.value.startswith("TandemStacks") and u32.IsWindowVisible(h):
            pid = ctypes.c_ulong(); u32.GetWindowThreadProcessId(h, ctypes.byref(pid))
            try:  # que sea la ventana del otro TandemStacks.exe (no el Explorador en una carpeta con ese nombre)
                import psutil
                if pid.value != os.getpid() and psutil.Process(pid.value).name().lower() == "tandemstacks.exe":
                    hallada.append(h); return False
            except Exception: pass
        return True
    u32.EnumWindows(ver, None)
    if hallada and "--inicio" not in sys.argv:
        u32.ShowWindow(hallada[0], 9)  # SW_RESTORE
        u32.SetForegroundWindow(hallada[0])
    return True

class Main:
    _mutex = None

def main():
    if _ya_abierta():
        return
    icono = os.path.join(paths.ASSETS, "icon.ico")
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("TandemStacks")
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
    ancho, alto, x, y = _tamano_inicial()
    con_windows = "--inicio" in sys.argv  # la abrió Windows al iniciar: arranca minimizada y dormida
    v = webview.create_window("TandemStacks %s" % VERSION, pathlib.Path(paths.HTML).as_uri(), js_api=Api(), width=ancho, height=alto, x=x, y=y,
                              min_size=(820, 520), background_color="#f2f2ef", minimized=con_windows)
    v.events.shown += lambda: _poner_icono(v, icono)
    if con_windows: v.events.shown += lambda: _minimizada(v, True)
    v.events.minimized += lambda: _minimizada(v, True)
    v.events.restored += lambda: _minimizada(v, False)
    v.events.maximized += lambda: _minimizada(v, False)  # una ventana maximizada vuelve por acá al sacarla de la barra
    def arranque():
        # versión nueva: se actualiza sola al abrir, sin preguntar (pedido del dueño, 07/11/2026). Solo el programa instalado,
        # no corriendo desde el código. Si la descarga o la instalación fallan, la app sigue con la versión que tiene.
        if getattr(sys, "frozen", False):
            try:
                if NUC.version_nueva():
                    NUC.actualizar(solo=True)
            except Exception as e:
                paths.log("actualizar al abrir", e)
        try:
            NUC.escanear()
        except Exception:
            import traceback; paths.log("escaneo inicial", traceback.format_exc())  # sin esto un error deja la página vieja sin rastro
        threading.Thread(target=NUC.vigilar, daemon=True).start()
        threading.Thread(target=_podar_cache, daemon=True).start()
        _con_windows(NUC.cfg.get("inicio_windows", True))
        threading.Thread(target=watch.vigilar, daemon=True, args=(lambda: [g for g in NUC.juegos if g.get("installed")], lambda: NUC.launchers,
                                                                 lambda: NUC.cfg, NUC.sumar_jugado,
                                                                 None,  # al abrir un juego la ventana queda como está (pedido del dueño 10/11/2026); si la minimizás, se duerme igual
                                                                 NUC.al_medir)).start()
    covers.limpiar_descargadas()
    # private_mode=False: el visor guarda en disco su caché (portadas ya vistas) entre sesiones
    # el visor (WebView2) sin lo que no usamos: caché de imágenes con tope de 64 MB (antes crecía sin límite, 175 MB medidos),
    # sin aceleración gráfica (medido: el proceso de gráficos bajaba de 119 a 21 MB, el visor de 315 a 201 MB),
    # sin descargas de componentes ni funciones de Edge en segundo plano. Se puede pisar con la variable de entorno.
    os.environ.setdefault("WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS",
                          "--disk-cache-size=67108864 --disable-gpu --disable-background-networking --disable-component-update "
                          "--disable-features=Translate,msEdgeTranslate,msSmartScreenProtection,OptimizationHints,MediaRouter,msShoppingTrigger,msEdgeSidebarV2")
    webview.start(lambda: threading.Thread(target=arranque, daemon=True).start(), icon=icono,
                  private_mode=False, storage_path=os.path.join(paths.DATA, "visor"))
