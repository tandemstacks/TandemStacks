"""Íconos de Ubisoft entre todos (15/11/2026, pedido del dueño).

Ubisoft no deja leer la biblioteca (está cifrada), pero Ubisoft Connect baja un ícono por cada juego de la cuenta a
`data\\<código>.ico`, y el código es el mismo en todas las PC. Cuando un juego está instalado, Windows sabe su nombre y su
ícono (el DisplayIcon de "Programas instalados"): de ahí sale el par código → nombre sin preguntarle nada a nadie.

- Aprendidos en esta PC: `cache/ubi_pares.json` (sirven aunque después lo desinstales).
- Tabla de todos: `catalogo/ubisoft_iconos.json` en la landing (la arma el dueño con lo que llega). Se baja 1 vez por día.
- Compartir (apagado por defecto, `compartir_ubisoft` en la config): solo se mandan pares que la tabla todavía no tiene,
  cada uno una sola vez, a un Formulario de Google. Se manda código del ícono, nombre del juego, número de Ubisoft y la
  versión de la app. Nada de la cuenta, el usuario ni la PC. Sin claves: el formulario es público."""
import os, json, time, urllib.request, urllib.parse
from . import paths, VERSION

PARES = os.path.join(paths.CACHE, "ubi_pares.json")
REMOTO = os.path.join(paths.CACHE, "ubi_iconos_remoto.json")
ENVIADOS = os.path.join(paths.CACHE, "ubi_enviados.json")
URL_TABLA = "https://tandemstacks.github.io/TandemStacks/catalogo/ubisoft_iconos.json"
# Formulario de Google del proyecto (cuenta tandemstacks). Cada campo tiene su "entry.<número>".
FORM = "https://docs.google.com/forms/d/e/1FAIpQLSfw5ijNXW7OJRz3hY9S_aLTu8EA14QzAPlCvTK2qk4o2bGyYw/formResponse"
CAMPOS = {"codigo": "entry.1912621861", "nombre": "entry.640217272", "id": "entry.171040126", "version": "entry.1315843040"}

def _leer(f, defecto):
    try:
        with open(f, encoding="utf-8") as a: return json.load(a)
    except Exception: return defecto

def _escribir(f, d):
    try:
        tmp = f + ".tmp"
        with open(tmp, "w", encoding="utf-8") as a: json.dump(d, a, ensure_ascii=False)
        os.replace(tmp, f)
    except OSError: pass

def aprendidos():
    """{código: {"n": nombre, "id": número de Ubisoft}} aprendidos en esta PC."""
    return _leer(PARES, {})

def aprender(nuevos):
    """Suma pares de juegos instalados (los llama stores.ubisoft en cada escaneo)."""
    if not nuevos: return
    d = aprendidos()
    if all(d.get(k) == v for k, v in nuevos.items()): return
    d.update(nuevos)
    _escribir(PARES, d)

def tabla():
    """La tabla de todos (la última bajada). {código: {"n", "id"}}."""
    return _leer(REMOTO, {}).get("iconos", {})

def _bajar_tabla():
    try:
        if time.time() - os.path.getmtime(REMOTO) < 86400: return
    except OSError: pass
    try:
        with urllib.request.urlopen(urllib.request.Request(URL_TABLA, headers={"User-Agent": "TandemStacks"}), timeout=20) as r:
            d = json.loads(r.read().decode("utf-8"))
        if isinstance(d.get("iconos"), dict): _escribir(REMOTO, d)
    except Exception as e:
        paths.log("ubisoft tabla", e)

def _enviar(cfg):
    if not cfg.get("compartir_ubisoft") or not FORM or not all(CAMPOS.values()): return 0
    ya, conocidos = set(_leer(ENVIADOS, [])), tabla()
    from .stores import UBI_ICONOS
    n = 0
    for cod, v in aprendidos().items():
        if cod in ya or cod in conocidos or cod in UBI_ICONOS: continue
        datos = urllib.parse.urlencode({CAMPOS["codigo"]: cod, CAMPOS["nombre"]: v.get("n", ""),
                                        CAMPOS["id"]: v.get("id", ""), CAMPOS["version"]: VERSION}).encode()
        try:
            urllib.request.urlopen(urllib.request.Request(FORM, data=datos, headers={"User-Agent": "TandemStacks"}), timeout=20).close()
            ya.add(cod); n += 1
        except Exception as e:
            paths.log("ubisoft compartir", e); break
    if n: _escribir(ENVIADOS, sorted(ya))
    return n

def tanda(cfg):
    """En segundo plano después de cada escaneo: baja la tabla (1 vez por día) y, si está permitido, manda lo nuevo."""
    _bajar_tabla()
    n = _enviar(cfg)
    if n: paths.log("ubisoft: pares compartidos", n)
