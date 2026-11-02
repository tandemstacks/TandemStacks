# -*- coding: utf-8 -*-
"""Arma los catálogos públicos de las tiendas para la sección Explorar de la app.

Lo corre GitHub una vez por semana (.github/workflows/catalogos.yml) y deja los archivos en docs/catalogo/,
que se publican con la landing. La app los baja de ahí: nadie tiene que iniciar sesión en ninguna tienda.

Formato de cada juego (claves cortas para que el archivo pese poco):
  i = id en la tienda, t = título, s = slug de la página, c = portada vertical, y = año, g = géneros
"""
import json, os, re, time, urllib.request

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

def steam(paginas=10):
    """Los juegos de Steam con más jugadores (SteamSpy, público). Pide 1 página por minuto: es lo que SteamSpy permite."""
    juegos = []
    for p in range(paginas):
        if p: time.sleep(61)
        for j in bajar("https://steamspy.com/api.php?request=all&page=%d" % p).values():
            if j.get("name"):
                juegos.append({"i": str(j["appid"]), "t": j["name"]})
    return juegos

def xbox():
    """Los juegos de PC Game Pass (lista pública de xbox.com) con su póster de la Microsoft Store."""
    ids = [x["id"] for x in bajar("https://catalog.gamepass.com/sigls/v2?id=fdd9e2a7-0fee-49f6-ad69-4354098401ff&language=en-us&market=US") if "id" in x]
    juegos = []
    for k in range(0, len(ids), 20):
        d = bajar("https://displaycatalog.mp.microsoft.com/v7.0/products?bigIds=%s&market=US&languages=en-us" % ",".join(ids[k:k + 20]))
        for p in d.get("Products", []):
            lp = (p.get("LocalizedProperties") or [{}])[0]
            poster = next((i["Uri"] for i in lp.get("Images", []) if i.get("ImagePurpose") == "Poster"), "")
            juegos.append({"i": p["ProductId"], "t": lp.get("ProductTitle", ""), "c": ("https:" + poster) if poster.startswith("//") else poster})
        time.sleep(0.3)
    return juegos

def norm(n):
    """Igual que norm() de la plantilla: mismo juego en otra tienda = mismo nombre normalizado."""
    n = re.sub(r"[™®©]", "", n.lower()).replace("&", " and ")
    n = re.sub(r"[-:–]?\s*(the )?(definitive|complete|special|celebration|game of the year|goty|enhanced|deluxe|remastered|director'?s cut|steam|legacy)( edition)?\b", "", n)
    return re.sub(r"[^a-z0-9]+", " ", n).strip()

def juntar(gog_, steam_, xbox_):
    """Un juego por nombre, con el id de cada tienda donde está: st = {"GOG": [id, slug], "Steam": appid, "Xbox": id}.
    Portada: la de GOG o Xbox si hay; si no, la de Steam por appid."""
    todos = {}
    for tienda, lista in (("GOG", gog_), ("Steam", steam_), ("Xbox", xbox_)):
        for j in lista:
            k = norm(j["t"])
            if not k: continue
            e = todos.setdefault(k, {"t": j["t"], "st": {}})
            e["st"].setdefault(tienda, [j["i"], j["s"]] if tienda == "GOG" else j["i"])
            if not e.get("c") and j.get("c"): e["c"] = j["c"]
            for x in ("y", "g"):
                if j.get(x) and not e.get(x): e[x] = j[x]
    for e in todos.values():
        if not e.get("c") and "Steam" in e["st"]:
            e["c"] = "https://steamcdn-a.akamaihd.net/steam/apps/%s/library_600x900.jpg" % e["st"]["Steam"]
    return list(todos.values())

def guardar(tienda, juegos):
    os.makedirs(SALIDA, exist_ok=True)
    with open(os.path.join(SALIDA, tienda + ".json"), "w", encoding="utf-8") as f:
        json.dump({"tienda": tienda, "fecha": time.strftime("%Y-%m-%d"), "juegos": juegos}, f, ensure_ascii=False, separators=(",", ":"))
    print(tienda, len(juegos), "juegos")

if __name__ == "__main__":
    g, s, x = gog(), steam(), xbox()
    guardar("gog", g)
    guardar("todos", juntar(g, s, x))
