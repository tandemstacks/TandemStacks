# -*- coding: utf-8 -*-
"""Arma los catálogos públicos de las tiendas para la sección Explorar de la app.

Lo corre GitHub una vez por semana (.github/workflows/catalogos.yml) y deja los archivos en docs/catalogo/,
que se publican con la landing. La app los baja de ahí: nadie tiene que iniciar sesión en ninguna tienda.

Formato de cada juego (claves cortas para que el archivo pese poco):
  i = id en la tienda, t = título, s = slug de la página, c = portada vertical, y = año, g = géneros
"""
import json, os, re, time, urllib.parse, urllib.request

SALIDA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs", "catalogo")
UA = {"User-Agent": "TasloStacks (+https://github.com/taslostacks/TasloStacks)"}
# Regla del dueño (07/11/2026): los juegos +18 por contenido sexual no aparecen en el catálogo. x = marcado para sacar.
GOG_ADULTOS = {"nsfw", "hentai"}  # "sexual-content" y "nudity" no sirven: incluyen Disco Elysium, Cyberpunk...
STEAM_ETIQUETAS = ("Hentai", "NSFW", "Sexual Content", "Nudity")  # solo para saber a quiénes preguntarle a la tienda: traen falsos positivos
STEAM_ADULTOS = {3, 4}  # avisos de contenido de la tienda: 3 = solo adultos, sexual; 4 = desnudos o sexo frecuentes
STEAM_VISTOS = os.path.join(SALIDA, "steam_adultos.json")  # appid -> es +18, para no volver a preguntar cada semana

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
                           "y": (p.get("releaseDate") or "")[:4], "g": [x["name"] for x in p.get("genres", [])][:3],
                           **({"x": 1} if GOG_ADULTOS & {x["slug"] for x in p.get("tags", [])} else {})})
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

def steam_adultos(juegos):
    """Marca los +18 de Steam. Pregunta solo por los que tienen etiquetas sospechosas (la tienda deja 200 consultas cada 5 minutos)."""
    try:
        vistos = json.load(open(STEAM_VISTOS, encoding="utf-8"))
    except Exception:
        vistos = {}
    ids, dudosos = {j["i"] for j in juegos}, set()
    for t in STEAM_ETIQUETAS:
        dudosos |= set(bajar("https://steamspy.com/api.php?request=tag&tag=" + urllib.parse.quote(t))) & ids
        time.sleep(1.2)
    faltan = sorted(dudosos - set(vistos))
    print("Steam: %d dudosos, faltan preguntar %d" % (len(dudosos), len(faltan)), flush=True)
    for n, a in enumerate(faltan):
        while True:
            try:
                r = urllib.request.urlopen(urllib.request.Request("https://store.steampowered.com/api/appdetails?cc=US&l=english&appids=" + a, headers=UA), timeout=30)
                d = (json.loads(r.read()).get(a) or {}).get("data") or {}
                vistos[a] = bool(STEAM_ADULTOS & set((d.get("content_descriptors") or {}).get("ids") or []))
                break
            except Exception as e:
                print("Steam: esperando 5 minutos (%s)" % e, flush=True)
                time.sleep(300)
        time.sleep(2)
        if n % 50 == 49:
            json.dump(vistos, open(STEAM_VISTOS, "w", encoding="utf-8"))
            print("Steam: %d de %d" % (n + 1, len(faltan)), flush=True)
    os.makedirs(SALIDA, exist_ok=True)
    json.dump(vistos, open(STEAM_VISTOS, "w", encoding="utf-8"))
    for j in juegos:
        if vistos.get(j["i"]): j["x"] = 1
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

def itch(paginas=10):
    """Los más vendidos y mejor puntuados de itch.io para Windows (sus listados públicos en RSS, 36 por página).
    i = link de la página del juego; pr = precio tal cual lo publica itch."""
    juegos, vistos = [], set()
    for lista, n in (("top-sellers", paginas), ("top-rated", paginas // 2)):
        for p in range(1, n + 1):
            x = ""
            for intento in range(3):  # itch a veces corta si se le pide seguido
                try:
                    x = urllib.request.urlopen(urllib.request.Request("https://itch.io/games/%s.xml?page=%d" % (lista, p), headers=UA), timeout=30).read().decode("utf-8", "replace")
                    break
                except Exception as e:
                    print("itch.io %s página %d: %s" % (lista, p, e), flush=True); time.sleep(5 * (intento + 1))
            if not x:
                break
            for it in re.findall(r"<item>(.*?)</item>", x, re.S):
                val = lambda k: (re.search(r"<%s>(.*?)</%s>" % (k, k), it, re.S) or [None, ""])[1].strip()
                link, titulo = val("link"), val("plainTitle")
                if not link or link in vistos or "<windows>yes</windows>" not in it:
                    continue
                vistos.add(link)
                precio = val("price")
                juegos.append({"i": link, "t": titulo, "c": val("imageurl"), "pr": "" if precio in ("", "$0.00") else precio})
            time.sleep(0.5)
    return juegos

def _pagina(url):
    for intento in range(3):
        try:
            return urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (TasloStacks)"}), timeout=30).read().decode("utf-8", "replace")
        except Exception:
            time.sleep(4 * (intento + 1))
    return ""

def _en_paralelo(f, lista, hilos=4):
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(hilos) as ex:
        return [r for r in ex.map(f, lista) if r]

EDICION = re.compile(r"\s+(standard|deluxe|gold|ultimate|complete|premium|collector'?s|digital deluxe)\s+edition$", re.I)

def ubisoft():
    """Juegos de PC de la tienda de Ubisoft. Su mapa del sitio lista los productos; cada página dice si es un juego, si es
    para adultos, el precio en dólares y la portada. Las ediciones de un mismo juego quedan en una sola tarjeta."""
    mapa = _pagina("https://store.ubisoft.com/us/sitemap_0.xml")
    urls = sorted(set(re.findall(r"<loc>(https://store\.ubisoft\.com/us/[a-z0-9-]+/[0-9a-f]{24}\.html)", mapa)))
    def leer(url):
        h = _pagina(url)
        t = re.search(r"<title>Buy (.+?) for PC \|", h)
        if not t or '"productTypeDetail":"games"' not in h or '"adultgame":"yes"' in h:
            return None
        titulo = EDICION.sub("", html_texto(t.group(1)))
        precio = re.search(r'"price":"([\d.]+)","priceCurrency":"USD"', h)
        img = re.search(r'og:image" content="([^"]+)"', h)
        return {"i": url, "t": titulo, "c": img.group(1) if img else "", "pr": "US$ " + precio.group(1) if precio else ""}
    vistos, juegos = set(), []
    for j in _en_paralelo(leer, urls):
        if norm(j["t"]) not in vistos:
            vistos.add(norm(j["t"])); juegos.append(j)
    print("ubisoft", len(juegos), "juegos de", len(urls), "páginas", flush=True)
    return juegos

def ea():
    """Juegos de PC de EA: su mapa del sitio lista las páginas de cada juego; se quedan las que se compran ("Buy ...")
    y se juegan con la app de EA."""
    mapa = _pagina("https://www.ea.com/sitemap-en-us.xml")
    urls = sorted(set(re.findall(r"<loc>(https://www\.ea\.com/games/[a-z0-9-]+/[a-z0-9-]+)</loc>", mapa)))
    def leer(url):
        h = _pagina(url)
        t = re.search(r"<title[^>]*>Buy (.+?) - Electronic Arts", h)
        if not t or "EA app" not in h:
            return None
        return {"i": url, "t": EDICION.sub("", html_texto(t.group(1)))}
    vistos, juegos = set(), []
    for j in _en_paralelo(leer, urls):
        if norm(j["t"]) not in vistos:
            vistos.add(norm(j["t"])); juegos.append(j)
    print("ea", len(juegos), "juegos de", len(urls), "páginas", flush=True)
    return juegos

def html_texto(t):
    import html
    return re.sub(r"[™®]", "", html.unescape(t)).strip()

# Battle.net y Rockstar no tienen catálogo público: son pocos juegos de PC y se listan a mano, con su página de compra
# (verificadas el 07/11/2026). "sa" = appid de Steam, solo para tomar la portada si el juego también está ahí.
BATTLENET = [("World of Warcraft", "world-of-warcraft-subscription", None), ("Diablo IV", "diablo-iv", 2344520),
             ("Diablo II: Resurrected", "diablo-ii-resurrected", None), ("Diablo III", "diablo-iii", None),
             ("Warcraft III: Reforged", "warcraft-iii-reforged", None), ("Call of Duty: Black Ops 6", "call-of-duty-black-ops-6", 2933620),
             ("Crash Bandicoot 4: It's About Time", "crash-bandicoot-4-its-about-time", 1378990)]
ROCKSTAR = [("Grand Theft Auto V", "buy-gta-v", 271590), ("Red Dead Redemption 2", "buy-red-dead-redemption-2", 1174180),
            ("Red Dead Redemption", "buy-red-dead-redemption", 2668510), ("L.A. Noire", "buy-la-noire", 110800),
            ("Max Payne 3", "buy-max-payne-3", 204100), ("Bully: Scholarship Edition", "buy-bully-scholarship-edition", 12200)]
PORTADA_STEAM = "https://steamcdn-a.akamaihd.net/steam/apps/%s/library_600x900.jpg"

def fijos(lista, base):
    return [{"i": base + slug, "t": t, "c": PORTADA_STEAM % sa if sa else ""} for t, slug, sa in lista]

def norm(n):
    """Igual que norm() de la plantilla: mismo juego en otra tienda = mismo nombre normalizado."""
    n = re.sub(r"[™®©]", "", n.lower()).replace("&", " and ")
    n = re.sub(r"[-:–]?\s*(the )?(definitive|complete|special|celebration|game of the year|goty|enhanced|deluxe|remastered|director'?s cut|steam|legacy)( edition)?\b", "", n)
    return re.sub(r"[^a-z0-9]+", " ", n).strip()

def juntar(gog_, steam_, xbox_, otras=()):
    """Un juego por nombre, con el id de cada tienda donde está: st = {"GOG": [id, slug], "Steam": appid, "Xbox": id,
    "itch.io" / "Battle.net" / "Rockstar": link de su página}. Portada: la de GOG o Xbox si hay; si no, la de Steam por appid.
    pr = precios que vienen en el catálogo (itch.io), para las tiendas sin consulta de precios."""
    todos, fuera = {}, set()
    for tienda, lista in (("GOG", gog_), ("Steam", steam_), ("Xbox", xbox_)) + tuple(otras):
        for j in lista:
            k = norm(j["t"])
            if not k: continue
            if j.get("x"):  # marcado en una tienda: se va de todas
                fuera.add(k); continue
            e = todos.setdefault(k, {"t": j["t"], "st": {}})
            e["st"].setdefault(tienda, [j["i"], j["s"]] if tienda == "GOG" else j["i"])
            if not e.get("c") and j.get("c"): e["c"] = j["c"]
            if j.get("pr"): e.setdefault("pr", {})[tienda] = j["pr"]
            for x in ("y", "g"):
                if j.get(x) and not e.get(x): e[x] = j[x]
    for e in todos.values():
        if not e.get("c") and "Steam" in e["st"]:
            e["c"] = "https://steamcdn-a.akamaihd.net/steam/apps/%s/library_600x900.jpg" % e["st"]["Steam"]
    return [e for k, e in todos.items() if k not in fuera]

def guardar(tienda, juegos):
    os.makedirs(SALIDA, exist_ok=True)
    with open(os.path.join(SALIDA, tienda + ".json"), "w", encoding="utf-8") as f:
        json.dump({"tienda": tienda, "fecha": time.strftime("%Y-%m-%d"), "juegos": juegos}, f, ensure_ascii=False, separators=(",", ":"))
    print(tienda, len(juegos), "juegos")

if __name__ == "__main__":
    g, s, x = gog(), steam_adultos(steam()), xbox()
    otras = (("itch.io", itch()), ("Battle.net", fijos(BATTLENET, "https://us.shop.battle.net/en-us/product/")),
             ("Rockstar", fijos(ROCKSTAR, "https://store.rockstargames.com/game/")), ("Ubisoft", ubisoft()), ("EA", ea()))
    guardar("gog", [j for j in g if not j.get("x")])
    guardar("todos", juntar(g, s, x, otras))
