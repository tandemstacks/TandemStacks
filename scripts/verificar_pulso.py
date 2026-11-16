"""Comprueba que los números de Pulso son reales: recalcula una partida desde sus datos crudos, con un cálculo
escrito aparte (no usa pulso.resumir), y lo compara con lo que guardó la app y muestra la ficha.

Uso:
  1) python scripts/verificar_pulso.py --preparar      (la próxima partida guarda sus datos crudos)
  2) jugar unos minutos con el contador de FPS de Steam o NVIDIA prendido y anotar más o menos cuánto marca
  3) python scripts/verificar_pulso.py [--overlay 90]  (compara la última partida guardada)
"""
import os, sys, csv, json, glob, statistics, argparse

TMP = os.path.join(os.environ["LOCALAPPDATA"], "TandemStacks", "cache", "pulso")
CRUDO, MARCA = os.path.join(TMP, "crudo"), os.path.join(TMP, "guardar_crudo.txt")

def tramos_afk(muestras, inicio):
    """Ratos AFK (2 min o más sin tocar nada), en segundos desde el inicio: [(desde, hasta)]."""
    return [(m["t"] - m["inactivo"] - inicio, m["t"] - inicio) for m in muestras
            if isinstance(m.get("inactivo"), (int, float)) and m["inactivo"] >= 120 and m.get("t")]

def cuadros(carpeta, pid, exe, afk=()):
    """Tiempos de cada cuadro del juego (ms), leídos con DictReader (otro camino que el de la app)."""
    arch = glob.glob(os.path.join(carpeta, "fps_*.csv"))
    if not arch: sys.exit("No está el CSV de PresentMon en " + carpeta)
    ms, gpu = [], []
    with open(arch[0], newline="", encoding="utf-8-sig", errors="ignore") as f:
        for r in csv.DictReader(f):
            r = {(k or "").strip().lower(): v for k, v in r.items()}
            if r.get("processid") != str(pid) and (r.get("application") or "").lower() != os.path.basename(exe).lower():
                continue
            try: v = float(r.get("msbetweenpresents") or r.get("frametime") or "")
            except ValueError: continue
            try: mo = float(r.get("timeinseconds") or 0)
            except ValueError: mo = 0
            if any(a <= mo <= b for a, b in afk): continue
            if 0 < v < 30000:
                ms.append(v)
                try: gpu.append(min(1.0, float(r["msgpuactive"]) / v))
                except (KeyError, ValueError, TypeError): pass
    return ms, gpu

def calcular(ms, gpu, muestras):
    jug = sorted(x for x in ms if x < 2000)  # 2 s o más = pausa (carga, menú)
    seg, med = sum(jug) / 1000, statistics.median(jug)
    n1, n01 = max(1, len(jug) // 100), max(1, len(jug) // 1000)
    corte = max(50, 2.5 * med)
    r = {"cuadros": len(jug), "minutosJugados": seg / 60, "fps": len(jug) / seg, "fpsTipico": 1000 / med,
         "fps1low": 1000 / statistics.mean(jug[-n1:]), "fps01low": 1000 / statistics.mean(jug[-n01:]),
         "msPeor": jug[-1], "tirones": sum(1 for x in jug if x > corte),
         "parejos": 100 * sum(1 for x in jug if x < 1.5 * med) / len(jug)}
    r["tironesMin"] = r["tirones"] / max(seg / 60, 0.1)
    if gpu: r["placaOcupada"] = 100 * statistics.median(gpu)
    for k, nom in (("gpu_uso", "gpuUso"), ("cpu", "cpuUso"), ("ram", "ram"), ("gpu_temp", "gpuTemp")):
        v = [m[k] for m in muestras if isinstance(m.get(k), (int, float))]
        if v: r[nom] = statistics.mean(v)
    return r

def main():
    a = argparse.ArgumentParser()
    a.add_argument("--preparar", action="store_true")
    a.add_argument("--overlay", type=float, help="FPS aproximados que marcaba el contador de Steam/NVIDIA")
    a.add_argument("carpeta", nargs="?")
    o = a.parse_args()
    if o.preparar:
        os.makedirs(TMP, exist_ok=True)
        open(MARCA, "w").write("La próxima partida guarda sus datos crudos en cache/pulso/crudo\n")
        print("Listo: la próxima partida (con Pulso prendido) guarda sus datos crudos.")
        return
    carpetas = sorted(glob.glob(os.path.join(CRUDO, "*")), key=os.path.getmtime)
    carpeta = o.carpeta or (carpetas[-1] if carpetas else None)
    if not carpeta: sys.exit("Todavía no hay partidas guardadas en crudo. Corré primero con --preparar y jugá.")
    m = json.load(open(os.path.join(carpeta, "muestras.json"), encoding="utf-8"))
    app = json.load(open(os.path.join(carpeta, "resumen.json"), encoding="utf-8"))
    afk = tramos_afk(m["muestras"], m["inicio"])
    ms, gpu = cuadros(carpeta, m["pid"], m["exe"], afk)
    if len(ms) < 100: sys.exit("Muy pocos cuadros en el CSV (%d): PresentMon no grabó el juego." % len(ms))
    jugando = [x for x in m["muestras"] if not any(a <= x.get("t", 0) - m["inicio"] <= b for a, b in afk)] or m["muestras"]
    yo = calcular(ms, gpu, jugando)
    print("Partida:", app.get("juego"), app.get("fecha"), "| carpeta:", carpeta)
    print("%-15s %10s %10s  %s" % ("dato", "app", "recalc.", ""))
    malos = 0
    for k, v in yo.items():
        if k not in app: continue
        dif = abs(app[k] - v) / max(abs(v), 1e-9)
        ok = dif <= 0.02 or abs(app[k] - v) <= 0.15  # 2 % o el redondeo de la app
        malos += not ok
        print("%-15s %10.1f %10.1f  %s" % (k, app[k], v, "OK" if ok else "NO COINCIDE"))
    if o.overlay:
        dif = abs(app["fps"] - o.overlay) / o.overlay
        print("\nContador externo: %.0f FPS vs Pulso %.1f FPS -> %s" % (o.overlay, app["fps"],
              "parecido" if dif <= 0.10 else "DIFERENTE (%.0f %%)" % (100 * dif)))
    print("\nResultado:", "todo coincide" if not malos else "%d datos no coinciden" % malos)

if __name__ == "__main__":
    main()
