# -*- coding: utf-8 -*-
"""Precios de No comprados en GOG, Steam y Xbox, en el país de Windows. Se piden solo para la página que se ve
(24 juegos) y quedan 6 horas en memoria: los precios cambian seguido, no vale la pena guardarlos en disco.
Cada precio vuelve como {"txt": "$U 740,00"} (Steam ya lo da escrito) o {"v": 4.99, "m": "USD"} para que la página
lo escriba en su idioma; "gratis" y "pass" (Game Pass) son marcas. "d" es el descuento en %."""
import ctypes, json, threading, time, urllib.parse
from concurrent.futures import ThreadPoolExecutor
from . import paths
from .steam import http_json

VIDA = 6 * 3600
_cache, _lock = {}, threading.Lock()

def pais():
    """Código de dos letras del país configurado en Windows (UY, AR, ES...)."""
    try:
        buf = ctypes.create_unicode_buffer(10)
        if ctypes.windll.kernel32.GetUserDefaultGeoName(buf, 10) and len(buf.value) == 2:
            return buf.value.upper()
    except Exception:
        pass
    return "US"

def _steam(ids, cc):
    req = {"ids": [{"appid": int(a)} for a in ids], "context": {"language": "spanish", "country_code": cc}, "data_request": {}}
    j = http_json("https://api.steampowered.com/IStoreBrowseService/GetItems/v1?input_json=" + urllib.parse.quote(json.dumps(req)), 20)
    out = {}
    for it in (j.get("response") or {}).get("store_items", []):
        o = it.get("best_purchase_option") or {}
        if it.get("is_free"): out[str(it.get("appid"))] = {"gratis": 1}
        elif o.get("formatted_final_price"): out[str(it.get("appid"))] = {"txt": o["formatted_final_price"], "d": o.get("discount_pct") or 0}
    return out

def _gog(ids, cc):
    j = http_json("https://api.gog.com/products/prices?ids=%s&countryCode=%s" % (",".join(ids), cc), 20)
    out = {}
    for it in (j.get("_embedded") or {}).get("items", []):
        e = it.get("_embedded") or {}
        p = (e.get("prices") or [{}])[0]
        fin, base = (int((p.get(k) or "0 ").split()[0] or 0) for k in ("finalPrice", "basePrice"))
        mon = (p.get("currency") or {}).get("code", "USD")
        out[str((e.get("product") or {}).get("id"))] = {"gratis": 1} if not base else {"v": fin / 100, "m": mon, "d": round(100 - fin * 100 / base) if fin < base else 0}
    return out

def _xbox(ids, cc):
    j = http_json("https://displaycatalog.mp.microsoft.com/v7.0/products?bigIds=%s&market=%s&languages=es-es" % (",".join(ids), cc), 20)
    out = {}
    for p in j.get("Products", []):
        pr = (((p.get("DisplaySkuAvailabilities") or [{}])[0].get("Availabilities") or [{}])[0].get("OrderManagementData") or {}).get("Price") or {}
        v, base = pr.get("ListPrice"), pr.get("MSRP") or 0
        # el catálogo es de PC Game Pass: sin precio propio se juega con la suscripción
        out[p["ProductId"]] = {"pass": 1} if not v else {"v": v, "m": pr.get("CurrencyCode", "USD"), "d": round(100 - v * 100 / base) if base and v < base else 0}
    return out

PEDIR = {"Steam": (_steam, 100), "GOG": (_gog, 50), "Xbox": (_xbox, 20)}

def de(items):
    """items = [{"k": clave de la página, "st": {"GOG": [id, slug], "Steam": appid, "Xbox": id}}] → {k: {tienda: precio}}."""
    cc, ahora = pais(), time.time()
    faltan = {t: [] for t in PEDIR}
    for it in items:
        for t, v in (it.get("st") or {}).items():
            gid = str(v[0] if isinstance(v, list) else v)
            if t in PEDIR and gid and ahora - _cache.get((cc, t, gid), (0, None))[0] > VIDA:
                faltan[t].append(gid)
    def pedir(t):
        f, lote = PEDIR[t]
        ids = list(dict.fromkeys(faltan[t]))
        for i in range(0, len(ids), lote):
            try:
                r = f(ids[i:i + lote], cc)
            except Exception as e:
                paths.log("precios", t, e); continue
            with _lock:
                for gid in ids[i:i + lote]:
                    _cache[(cc, t, gid)] = (ahora, r.get(gid))  # None = la tienda no lo vende en este país
    with ThreadPoolExecutor(3) as ex:
        list(ex.map(pedir, [t for t in PEDIR if faltan[t]]))
    out = {}
    for it in items:
        p = {}
        for t, v in (it.get("st") or {}).items():
            gid = str(v[0] if isinstance(v, list) else v)
            val = _cache.get((cc, t, gid), (0, None))[1]
            if val: p[t] = val
        out[str(it.get("k"))] = p
    return out
