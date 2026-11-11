# -*- coding: utf-8 -*-
"""Escalera de ajustes: mejorar el rendimiento de un juego de a un paso por partida (pedido del dueño, 10/11/2026).

Sin IA: reglas fijas sobre los números de Pulso.
1. Se mira qué frena en la última partida (procesador, placa o memoria de video).
2. Se propone UN paso: si es de NVIDIA lo aplica TandemStacks (con respaldo); si es del juego, se dice qué tocar
   (con la app de NVIDIA instalada: mover su barra Rendimiento/Calidad, que ya sabe qué bajar en cada juego).
3. La partida siguiente se compara con la de antes del paso: si mejoró se deja; si no, se propone volverlo atrás.
Se para cuando el semáforo de Pulso queda en verde.
"""
import os, json, datetime
from . import paths, pulso, nvidia

ARCHIVO = os.path.join(os.path.dirname(paths.CONFIG), "escalera.json")
NVAPP = os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), r"NVIDIA Corporation\NVIDIA App\CEF\NVIDIA App.exe")
MAX_BARRA = 3  # cuántas veces se propone bajar la barra de la app de NVIDIA

def _leer():
    try:
        with open(ARCHIVO, encoding="utf-8") as f: return json.load(f)
    except (OSError, ValueError):
        return {}

def _escribir(d):
    with open(ARCHIVO + ".tmp", "w", encoding="utf-8") as f: json.dump(d, f, ensure_ascii=False, indent=1)
    os.replace(ARCHIVO + ".tmp", ARCHIVO)

def hay_app_nvidia():
    return os.path.exists(NVAPP)

def cuello(u):
    """Qué frena la partida: 'vram', 'placa', 'procesador' o '' si no se sabe."""
    if (u.get("vramMaxPct") or 0) >= 92: return "vram"
    if (u.get("gpuUso") or 0) >= 90: return "placa"
    if (u.get("cpuNucleoMaxMax") or u.get("cpuNucleoMax") or 0) >= 85 or (u.get("cpuUso") or 0) >= 70: return "procesador"
    return "placa" if (u.get("gpuUso") or 0) >= 75 else "procesador"

# pasos del juego (sin la app de NVIDIA): qué tocar en el menú de gráficos, según qué frena
JUEGO = {
    "procesador": [("vision", "Distancia de visión → media", "Es lo que más carga al procesador: menos cosas lejanas para calcular."),
                   ("sombras", "Sombras → medio", "Las sombras también le cuestan al procesador (sobre todo en Unreal Engine 5)."),
                   ("efectos", "Efectos y partículas → bajo", "Explosiones, humo y partículas los calcula el procesador."),
                   ("reflex", "NVIDIA Reflex → activado (si el juego lo tiene)", "Hace que el procesador no se adelante a la placa: menos trabas y menos demora.")],
    "placa": [("escalado", "DLSS o FSR → Calidad", "La placa dibuja menos píxeles y los completa: más FPS casi sin perder calidad."),
              ("sombras", "Sombras → medio", "Es de lo más pesado para la placa."),
              ("ilum", "Iluminación global / reflejos → medio", "Lumen y el trazado de rayos son lo más caro para la placa."),
              ("posproc", "Posprocesado y niebla → bajo", "Se nota poco y libera a la placa.")],
    "vram": [("texturas", "Texturas → un nivel menos", "La memoria de video llegó al tope: el juego tiene que traer texturas del disco y se traba."),
             ("escalado", "DLSS o FSR → Calidad", "Dibujar a menos resolución también usa menos memoria de video.")],
}

def _pasos(gid, u):
    """Lista ordenada de pasos posibles para este juego ahora."""
    out = []
    if nvidia.valor_puesto(gid, nvidia.FPS_LIMITE):
        out.append({"k": "nv_sin_tope", "tipo": "nvidia", "que": "Sacar el límite de FPS que puso TandemStacks",
                    "por": "Con el tope los tirones fuertes siguieron: no los arregla y te saca FPS."})
    ya = nvidia.aplicado(gid) or {}
    puestos = {a["id"] for a in ya.get("antes", [])}
    if nvidia.hay_nvidia() and nvidia.CACHE_SOMBREADORES not in puestos and ((u.get("tironesMin") or 0) >= 5 or (u.get("discoMBsMax") or 0) > 150):
        out.append({"k": "nv_cache", "tipo": "nvidia", "que": "Caché de sombreadores sin límite (NVIDIA, toda la PC)",
                    "por": "Los tirones con mucha lectura de disco suelen ser sombreadores que se arman mientras jugás."})
    c = cuello(u)
    if hay_app_nvidia() and c != "vram":
        for i in range(1, MAX_BARRA + 1):
            out.append({"k": "barra%d" % i, "tipo": "barra", "que": "App de NVIDIA → Gráficos → este juego: mové la barra 2 marcas %shacia «Performance»" % ("más " if i > 1 else ""),
                        "por": "Baja de una vez lo que más pesa (sombras, distancia, efectos) con los valores que NVIDIA probó para tu placa. Lo que frena es %s." % ("el procesador" if c == "procesador" else "la placa"),
                        "volver": "Volvé la barra 2 marcas hacia «Quality»."})
    for k, que, por in JUEGO[c]:
        out.append({"k": "juego_" + k, "tipo": "juego", "que": "En el juego: " + que, "por": por, "volver": "Volvé ese ajuste del juego a como estaba."})
    return out

def _comparar(antes, despues):
    """'mejor', 'peor' o 'igual' entre dos partidas (tirones por minuto y 1 % más lento; los FPS solo si caen mucho)."""
    ta, td = antes.get("tironesMin"), despues.get("tironesMin")
    la, ld = antes.get("fps1low"), despues.get("fps1low")
    fa, fd = antes.get("fps"), despues.get("fps")
    if ta is None or td is None: return "sinDatos"
    mejor = td <= ta * 0.85 or (la and ld and ld >= la * 1.15)
    peor = td >= ta * 1.15 or (la and ld and ld <= la * 0.85) or (fa and fd and fd < fa * 0.8)
    return "peor" if peor and not mejor else "mejor" if mejor and not peor else "igual"

def estado(gid):
    """Lo que muestra la ficha: el paso en prueba y su resultado, o el próximo paso. None si no hay partidas con FPS."""
    ps = [p for p in pulso.historial(gid) if p.get("fps")]
    if not ps: return None
    d = _leer().get(gid, {"hechos": [], "prueba": None})
    u = ps[-1]
    pr = d.get("prueba")
    if pr:
        despues = [p for p in ps if p["fecha"] > pr["base"]["fecha"]]
        if not despues:
            return {"prueba": pr, "esperando": True}
        r = _comparar(pr["base"], despues[0])
        return {"prueba": pr, "resultado": r, "partida": despues[0], "base": pr["base"]}
    if u.get("estado") == "verde" and (u.get("tironesMin") or 0) < 5:
        return {"verde": True, "partida": u}
    hechos = set(d.get("hechos", []))
    sig = next((p for p in _pasos(gid, u) if p["k"] not in hechos), None)
    return {"siguiente": sig, "partida": u, "cuello": cuello(u), "fin": sig is None}

def empezar(gid):
    """Arranca el próximo paso: lo de NVIDIA lo aplica; lo del juego queda anotado para que la persona lo toque."""
    e = estado(gid)
    if not e or not e.get("siguiente"): return None
    p, u = e["siguiente"], e["partida"]
    if p["k"] == "nv_sin_tope":
        p["valorAntes"] = nvidia.valor_puesto(gid, nvidia.FPS_LIMITE)
        nvidia.restaurar(gid, nvidia.FPS_LIMITE)
    elif p["k"] == "nv_cache":
        nvidia.cambiar(gid, u["exe"], u.get("juego") or gid, [{"id": nvidia.CACHE_SOMBREADORES, "valor": 0xFFFFFFFF, "global": True, "que": p["que"]}])
    todo = _leer()
    d = todo.setdefault(gid, {"hechos": [], "prueba": None})
    d["prueba"] = {**p, "base": {k: u.get(k) for k in ("fecha", "fps", "fps1low", "tironesMin", "gpuUso", "cpuUso")},
                   "desde": datetime.datetime.now().strftime("%Y-%m-%d %H:%M")}
    _escribir(todo)
    paths.log("escalera: paso", gid, p["k"])
    return d["prueba"]

def resolver(gid, dejar):
    """Cierra el paso en prueba: lo deja, o lo vuelve atrás (lo de NVIDIA lo vuelve TandemStacks)."""
    todo = _leer()
    d = todo.get(gid)
    if not d or not d.get("prueba"): return False
    p = d["prueba"]
    if not dejar:
        if p["k"] == "nv_sin_tope" and p.get("valorAntes"):
            u = (pulso.historial(gid) or [{}])[-1]
            nvidia.cambiar(gid, u.get("exe", ""), u.get("juego") or gid, [{"id": nvidia.FPS_LIMITE, "valor": p["valorAntes"], "global": False, "que": "Límite de %d FPS" % p["valorAntes"]}])
        elif p["k"] == "nv_cache":
            nvidia.restaurar(gid, nvidia.CACHE_SOMBREADORES)
    d.setdefault("hechos", []).append(p["k"])
    d.setdefault("historial", []).append({"k": p["k"], "que": p["que"], "dejado": dejar, "fecha": datetime.datetime.now().strftime("%Y-%m-%d %H:%M")})
    d["prueba"] = None
    _escribir(todo)
    paths.log("escalera:", gid, p["k"], "dejado" if dejar else "vuelto atrás")
    return True

def en_prueba(gid):
    """Texto del paso que se está probando (para anotarlo en la partida)."""
    p = (_leer().get(gid) or {}).get("prueba")
    return p["que"] if p else None
