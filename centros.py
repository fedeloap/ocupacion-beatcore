"""
Descubre TODOS los centros de cada cadena (toda España) a partir del sitemap de su web: cada ficha de centro
suele llevar el identificador de su agenda (Glofox, Momence, bsport, Mindbody, AimHarder, Trainingym, Mariana Tek).

Entrada : web/cadenas_inventario.json (webs)
Salida  : web/cadenas_centros.json  -> {cadena: {"fichas": N, "centros": [{nombre, url, plataforma, ...ids...}]}}
Solo páginas y endpoints públicos. Todo lo que no se localiza queda sin dato.
"""

import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse

import requests

import fuentes as F

H = F.H
PAT_CENTRO = re.compile(r"/(centros?|studios?|clubs?|locations?|location|sedes?|gimnasios?|estudios?|centres?|ubicaciones?|"
                        r"find-a-studio|nuestros-centros|encuentra)/[^/]+/?$", re.I)
PAT_INDICE = re.compile(r"/(centros?|studios?|clubs?|locations?|sedes?|gimnasios?|estudios?|centres?|ubicaciones?)/?$", re.I)
MAX_FICHAS = 400


def sitemap_urls(web):
    base = re.match(r"https?://[^/]+", web).group(0)
    cola = [base + "/sitemap.xml", base + "/sitemap_index.xml", base + "/wp-sitemap.xml"]
    try:
        rb = requests.get(base + "/robots.txt", headers=H, timeout=15)
        cola += re.findall(r"(?im)^sitemap:\s*(\S+)", rb.text)
    except Exception:
        pass
    vistos, urls = set(), []
    while cola and len(vistos) < 25:
        u = cola.pop(0)
        if u in vistos:
            continue
        vistos.add(u)
        try:
            r = requests.get(u, headers=H, timeout=20)
        except Exception:
            continue
        if r.status_code != 200 or "<loc>" not in r.text:
            continue
        for loc in re.findall(r"<loc>\s*(.*?)\s*</loc>", r.text):
            loc = loc.replace("&amp;", "&")
            if loc.endswith(".xml") or "sitemap" in urlparse(loc).path.lower():
                cola.append(loc)
            else:
                urls.append(loc)
    return urls


def fichas_centro(web):
    urls = sitemap_urls(web)
    f = sorted({u.split("#")[0] for u in urls if PAT_CENTRO.search(urlparse(u).path)})
    # webs globales (F45...): si el sitemap separa por país, solo se rastrea /es/
    es = [u for u in f if re.search(r"/es/", urlparse(u).path)]
    return (es or f)[:MAX_FICHAS]


def ids_pagina(html):
    """(plataforma, id) encontrados en una ficha de centro, sin duplicados."""
    out = []
    out += [("glofox", i) for i in re.findall(r"branch/([0-9a-f]{24})/(?:classes|memberships|trainers|lead|bookings|credits)", html)]
    out += [("momence", i) for i in F.ids_momence(html)]
    out += [("bsport", i) for i in F.ids_bsport(html)]
    out += [("mindbody", i) for i in F.ids_mindbody(html)]
    out += [("aimharder", i) for i in F.ids_aimharder(html)]
    out += [("trainingym", i) for i in F.ids_trainingym(html)]
    out += [("marianatek", i) for i in F.ids_mariana(html)]
    seen, res = set(), []
    for x in out:
        if x not in seen:
            seen.add(x)
            res.append(x)
    return res


def ver_glofox(branch):
    try:
        r = requests.post("https://api.glofox.com/2.0/login", headers={**H, "Content-Type": "application/json", "Accept": "application/json"},
                          json={"branch_id": branch, "login": "GUEST", "password": "GUEST"}, timeout=30)
        tok = r.json().get("token")
        a = int(time.time())
        e = requests.get(f"https://api.glofox.com/2.0/events?start={a}&end={a + 7 * 86400}&page=1&private=false&sort_by=time_start",
                         headers={**H, "Authorization": f"Bearer {tok}", "Accept": "application/json"}, timeout=30)
        n = len(e.json().get("data", []))
        return {"clases_7d": n} if n else None
    except Exception:
        return None


def verifica(plat, i):
    if plat == "glofox":
        return ver_glofox(i)
    if plat == "momence":
        return F.ver_momence(i)
    if plat == "bsport":
        return F.ver_bsport(i)
    if plat == "mindbody":
        return F.ver_mindbody(i)
    if plat == "aimharder":
        return F.ver_aimharder(i)
    if plat == "trainingym":
        return F.ver_trainingym(i)
    return None  # marianatek se resuelve por tenant en fuentes_build


def procesa_cadena(cadena, web):
    urls = fichas_centro(web)
    res = {"fichas": len(urls), "centros": []}
    if not urls:
        return cadena, res

    def pag(u):
        r = F.get(u)
        if r is None or r.status_code >= 400:
            return u, []
        return u, ids_pagina(r.text)

    with ThreadPoolExecutor(8) as ex:
        paginas = list(ex.map(pag, urls))
    # un id que aparece en varias fichas es un enlace cruzado: se asigna a la ficha donde es el único de su plataforma
    cuenta = {}
    for u, ids in paginas:
        for x in ids:
            cuenta[x] = cuenta.get(x, 0) + 1
    asignado = {}
    for u, ids in paginas:
        propios = [x for x in ids if cuenta[x] == 1]
        for x in (propios or ids):
            asignado.setdefault(x, u)
    verificados = {}
    for (plat, i), u in asignado.items():
        v = verifica(plat, i)
        if v is not None or plat == "marianatek":
            verificados[(plat, i)] = (u, v)
    for (plat, i), (u, v) in verificados.items():
        slug = urlparse(u).path.rstrip("/").rsplit("/", 1)[-1]
        res["centros"].append({"nombre": slug, "url": u, "plataforma": plat, "id": i, **(v or {})})
    return cadena, res


def main(salida="web/cadenas_centros.json", solo=None):
    inv = json.load(open("web/cadenas_inventario.json", encoding="utf-8"))["filas"]
    tareas = [(f["cadena"], f["web"]) for f in inv if f.get("web") and f.get("estado") == "ok"]
    if solo:
        tareas = [t for t in tareas if t[0] in solo]
    out = {}
    try:  # al rehacer solo algunas cadenas se conserva lo ya descubierto de las demás
        out = json.load(open(salida, encoding="utf-8"))
    except Exception:
        out = {}
    with ThreadPoolExecutor(4) as ex:
        for cadena, res in ex.map(lambda t: procesa_cadena(*t), tareas):
            out[cadena] = res
            print(f"{cadena}: {res['fichas']} fichas, {len(res['centros'])} centros con agenda", flush=True)
    json.dump(out, open(salida, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main(solo=sys.argv[1:] or None)
