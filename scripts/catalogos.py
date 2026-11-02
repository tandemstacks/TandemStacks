# -*- coding: utf-8 -*-
"""Arma los catálogos públicos de las tiendas para la sección Explorar de la app.

Lo corre GitHub una vez por semana (.github/workflows/catalogos.yml) y deja los archivos en docs/catalogo/,
que se publican con la landing. La app los baja de ahí: nadie tiene que iniciar sesión en ninguna tienda.

Formato de cada juego (claves cortas para que el archivo pese poco):
  i = id en la tienda, t = título, s = slug de la página, c = portada vertical, y = año, g = géneros
"""
import json, os, time, urllib.request

SALIDA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs", "catalogo")
UA = {"User-Agent": "TasloStacks (+https://github.com/taslostacks/TasloStacks)"}

def bajar(url):
    for intento in range(4):
        try:
            return json.loads(urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30).read())
        except Exception:
            time.sleep(3 * (intento + 1))
    raise RuntimeError("no se pudo bajar " + url)

def gog():
    """Catálogo público de gog.com (el mismo que usa su web), ordenado por lo más visto."""
    base = "https://catalog.gog.com/v1/catalog?limit=48&order=desc:trending&productType=in:game&countryCode=US&locale=en-US&currencyCode=USD&page=%d"
    juegos, pagina, paginas = [], 1, 1
    while pagina <= paginas:
        d = bajar(base % pagina)
        paginas = d.get("pages", 1)
        for p in d.get("products", []):
            juegos.append({"i": p["id"], "t": p["title"], "s": p.get("slug", ""), "c": p.get("coverVertical", ""),
                           "y": (p.get("releaseDate") or "")[:4], "g": [x["name"] for x in p.get("genres", [])][:3]})
        pagina += 1
        time.sleep(0.4)  # sin apuro: no cargarle el servidor a GOG
    return juegos

def guardar(tienda, juegos):
    os.makedirs(SALIDA, exist_ok=True)
    with open(os.path.join(SALIDA, tienda + ".json"), "w", encoding="utf-8") as f:
        json.dump({"tienda": tienda, "fecha": time.strftime("%Y-%m-%d"), "juegos": juegos}, f, ensure_ascii=False, separators=(",", ":"))
    print(tienda, len(juegos), "juegos")

if __name__ == "__main__":
    guardar("gog", gog())
