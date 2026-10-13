"""
Descubre, para cada cadena de web/cadenas_lista.txt, de dónde se puede leer su agenda pública de clases
(Momence, bsport, Mindbody, Glofox, Mariana Tek, AimHarder) y comprueba que responde sin login.

Entrada : web/cadenas_inventario.json (webs) y web/cadenas_webs.csv
Salida  : web/cadenas_fuentes.json  -> [{cadena, estudio, plataforma, ...ids..., verificado, nota}]
Solo páginas y endpoints públicos. Si algo pide login o devuelve un desafío anti-bot, no se usa y se anota.
"""

import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from html import unescape
from urllib.parse import urljoin, urlparse

import requests

H = {"User-Agent": "Mozilla/5.0 (compatible; BeatCoreResearch/1.0; +https://github.com/fedeloap/ocupacion-beatcore)",
     "Accept": "text/html,application/json;q=0.9,*/*;q=0.8"}
J = {**H, "Accept": "application/json, text/plain, */*"}
MAX_PAGINAS = 30

RX_LINK = re.compile(r"""(?:href|src|data-src|data-url|action)\s*=\s*["']([^"'#]+)""", re.I)
RX_PRIO = re.compile(r"horario|reserv|schedul|clase|book|calend|centros?|studios?|locations?|sedes?|clubs?|contacto|encuentra|"
                     r"tarifa|precio|price|bono|membres|abono|cuota|app|comprar|unete|prueba|class", re.I)
RX_EXT = re.compile(r"momence\.com|bsport\.io|mindbodyonline|healcode|glofox|marianatek|aimharder\.com|wodbuster|"
                    r"harbiz|trainingym|timp|eversports|virtuagym|bookeo|wix", re.I)
BIN = re.compile(r"\.(jpe?g|png|gif|webp|svg|pdf|mp4|zip|css|ico|woff2?)(\?|$)", re.I)


def get(url, json_=False, **kw):
    try:
        return requests.get(url, headers=J if json_ else H, timeout=15, allow_redirects=True, **kw)
    except Exception:
        return None


def dom(u):
    h = urlparse(u).netloc.lower()
    return h[4:] if h.startswith("www.") else h


def rastrear(web, max_paginas=None):
    """HTML de la home y hasta max_paginas páginas internas/embebidas relevantes (BFS, prioridad por palabras clave)."""
    max_paginas = max_paginas or MAX_PAGINAS
    r = get(web)
    if r is None or r.status_code >= 400:
        return {}
    base, d0 = r.url, dom(r.url)
    paginas, cola, vistos = {base: r.text}, [], {base}

    def anadir(texto, url_base):
        for href in RX_LINK.findall(texto):
            u = urljoin(url_base, unescape(href.strip())).split("#")[0]
            if not u.startswith("http") or BIN.search(u) or u in vistos:
                continue
            interno = dom(u) == d0
            if interno or RX_EXT.search(u):
                vistos.add(u)
                cola.append((0 if RX_PRIO.search(u) else 1, u))

    anadir(r.text, base)
    while cola and len(paginas) < max_paginas:
        cola.sort(key=lambda x: x[0])
        _, u = cola.pop(0)
        rr = get(u)
        if rr is None or rr.status_code >= 400 or "text/html" not in rr.headers.get("content-type", "text/html"):
            continue
        paginas[rr.url] = rr.text
        if dom(rr.url) == d0 and len(paginas) < max_paginas:
            anadir(rr.text, rr.url)
    return paginas


# ---------- extractores de identificadores ----------
def ids_momence(txt):
    ids = set(re.findall(r"""host[_-]?id["'\s:=]+["']?(\d{3,8})""", txt, re.I))
    ids |= set(re.findall(r"""momence\.com/[^"'\s<>]*?host[/=_-]?(\d{3,8})""", txt, re.I))
    return sorted(ids)


def ids_bsport(txt):
    ids = set(re.findall(r"""company[_-]?(?:id)?["'\s:=/]+["']?(\d{2,7})""", txt, re.I) if "bsport" in txt.lower() else [])
    ids |= set(re.findall(r"""bsport\.io/[^"'\s<>]*?company[=/](\d{2,7})""", txt, re.I))
    return sorted(ids)


def ids_glofox(txt):
    return sorted(set(re.findall(r"glofox\.com/[^\"'\s<>]*?branch/([0-9a-f]{24})", txt, re.I))
                  | set(re.findall(r"""(?:data-branch|branch[_-]?id)["'\s:=]+["']?([0-9a-f]{24})""", txt, re.I)))


def ids_mariana(txt):
    ten = set(re.findall(r"https?://([a-z0-9\-]+)\.marianatek\.com", txt, re.I)) - {"www", "api", "app"}
    return sorted(ten)


def ids_aimharder(txt):
    return sorted(set(re.findall(r"https?://([a-z0-9\-]+)\.aimharder\.com", txt, re.I)) - {"www", "app", "api"})


def ids_trainingym(txt):
    return sorted(set(re.findall(r"easy\.trainingym\.com/([A-Za-z0-9_.\-]+)/", txt)) - {"assets", "api"})


def ver_trainingym(code):
    """Calendario público de reservas (easy): plazas y reservas por clase sin login."""
    r = get(f"https://center.trainingym.com/api/v1/public/center/{code}", True)
    if r is None or r.status_code != 200:
        return None
    try:
        c = r.json()
        tok = c["publicToken"]
    except Exception:
        return None
    d1 = datetime.now().date()
    x = get("https://booking.trainingym.com/api/v2/calendar/totem/notauth", True,
            params={"centerToken": tok, "startDateTime": d1.isoformat(), "endDateTime": (d1 + timedelta(days=3)).isoformat(), "forceViewMap": "true"})
    if x is None or x.status_code != 200:
        return None
    try:
        n = sum(len(d.get("schedules") or []) for d in x.json().get("calendar", []))
    except Exception:
        return None
    return {"nombre": c.get("name"), "clases_3d": n} if n else None


def ids_mindbody(txt):
    ids = set(re.findall(r"""(?:site[_-]?id|data-site-id|studio[_-]?id|mb_site_id|location[_-]?id)["'\s:=]+["']?(\d{4,8})""", txt, re.I))
    ids |= set(re.findall(r"mindbodyonline\.com/[^\"'\s<>]*?(?:studioid|siteID)=(\d{4,8})", txt, re.I))
    # los site id de Mindbody España son de 7 cifras (57xxxxx): se verifican contra la agenda pública
    return sorted(i for i in ids if len(i) == 7)


# ---------- verificación (sin login) ----------
def ver_momence(hid):
    a = datetime.now(timezone.utc)
    b = a + timedelta(days=7)
    f = lambda d: d.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    r = get(f"https://readonly-api.momence.com/host-plugins/host/{hid}/host-schedule/sessions?fromDate={f(a)}&toDate={f(b)}&pageSize=50&page=0", True)
    if r is None or r.status_code != 200:
        return None
    try:
        p = r.json().get("payload", [])
    except Exception:
        return None
    sedes = sorted({x.get("location") or "" for x in p})
    return {"clases_7d": len(p), "sedes": sedes} if p else None


def ver_bsport(cid):
    a = datetime.now(timezone.utc).date()
    r = get(f"https://api.production.bsport.io/book/v1/offer/?company={cid}&min_date={a}&max_date={a + timedelta(days=7)}&page_size=50", True)
    if r is None or r.status_code != 200:
        return None
    try:
        j = r.json()
    except Exception:
        return None
    res = j.get("results", [])
    est = sorted({str(x.get("establishment")) for x in res})
    return {"clases_7d": j.get("count", len(res)), "establecimientos": est} if res else None


def ver_mariana(tenant):
    url, locs = f"https://{tenant}.marianatek.com/api/customer/v1/locations?page_size=100", []
    for _ in range(10):
        r = get(url, True)
        if r is None or r.status_code != 200:
            break
        try:
            j = r.json()
        except Exception:
            break
        locs += j.get("results", j if isinstance(j, list) else [])
        url = (j.get("links") or {}).get("next") or j.get("next") if isinstance(j, dict) else None
        if not url:
            break
    # solo sedes en España (zona horaria de Madrid o dirección en España)
    def es(x):
        dir_ = " ".join(x.get("formatted_address") or []) if isinstance(x.get("formatted_address"), list) else str(x.get("formatted_address"))
        return str(x.get("timezone", "")).startswith("Europe/Madrid") or re.search(r"\b(spain|españa)\b", dir_, re.I) is not None
    out = [{"id": str(x.get("id")), "nombre": x.get("name")} for x in locs if isinstance(x, dict) and es(x)]
    return {"locations": out} if out else None


def ver_aimharder(sub):
    r = get(f"https://{sub}.aimharder.com/schedule")
    if r is None or r.status_code != 200:
        return None
    ids = set(re.findall(r"""(?:box|boxId|idBox|box_id)["']?\s*[:=]\s*["']?(\d{3,7})""", r.text))
    d = (datetime.now() + timedelta(days=1)).strftime("%Y%m%d")
    s = requests.Session()
    s.headers.update({**J, "X-Requested-With": "XMLHttpRequest"})
    s.get(f"https://{sub}.aimharder.com/schedule", timeout=15)
    for bid in sorted(ids):
        try:
            x = s.get(f"https://{sub}.aimharder.com/api/bookings?day={d}&familyId=&box={bid}", timeout=15)
            j = x.json()
        except Exception:
            continue
        if isinstance(j, dict) and "bookings" in j:
            return {"box": bid, "clases_dia": len(j["bookings"]), "nombre": (j["bookings"][0].get("boxName") if j["bookings"] else "")}
    return None


def ver_mindbody(site):
    body = {"location_ref_json": json.dumps({"mb_site_id": int(site), "mb_location_id": 1, "inventory_source": "MB"}),
            "start_time_from": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z"),
            "start_time_to": (datetime.now(timezone.utc) + timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%S.000Z"),
            "location_timezone": "Europe/Madrid"}
    try:
        r = requests.post("https://prod-mkt-gateway.mindbody.io/v1/location/schedules", json=body, timeout=20,
                          headers={**J, "Content-Type": "application/json", "Origin": "https://www.mindbodyonline.com",
                                   "Referer": "https://www.mindbodyonline.com/"})
        d = r.json().get("data", [])
    except Exception:
        return None
    n = sum(1 for x in d if (x.get("attributes") or {}).get("subType") == "class_time")
    return {"clases_2d": n} if n else None


def descubrir(cadena, web, max_paginas=None):
    paginas = rastrear(web, max_paginas)
    txt = "\n".join(paginas.values())
    out = {"cadena": cadena, "web": web, "paginas": len(paginas), "fuentes": []}
    for hid in ids_momence(txt)[:6]:
        v = ver_momence(hid)
        if v:
            out["fuentes"].append({"plataforma": "momence", "host_id": int(hid), **v})
    for cid in ids_bsport(txt)[:6]:
        v = ver_bsport(cid)
        if v:
            out["fuentes"].append({"plataforma": "bsport", "company_id": int(cid), **v})
    for t in ids_mariana(txt)[:4]:
        v = ver_mariana(t)
        if v:
            out["fuentes"].append({"plataforma": "marianatek", "tenant": t, **v})
    for sub in ids_aimharder(txt)[:12]:
        v = ver_aimharder(sub)
        if v:
            out["fuentes"].append({"plataforma": "aimharder", "subdominio": sub, **v})
    for code in ids_trainingym(txt)[:10]:
        v = ver_trainingym(code)
        if v:
            out["fuentes"].append({"plataforma": "trainingym", "centro_code": code, **v})
    for gid in ids_glofox(txt)[:6]:
        out["fuentes"].append({"plataforma": "glofox", "branch_id": gid, "verificado": False})
    for site in ids_mindbody(txt)[:4]:
        v = ver_mindbody(site)
        if v:
            out["fuentes"].append({"plataforma": "mindbody", "site_id": int(site), **v})
    return out


def main(salida="web/cadenas_fuentes.json"):
    inv = json.load(open("web/cadenas_inventario.json", encoding="utf-8"))["filas"]
    tareas = [(f["cadena"], f["web"]) for f in inv if f.get("web") and f.get("estado") == "ok"]
    with ThreadPoolExecutor(10) as ex:
        res = list(ex.map(lambda t: descubrir(*t), tareas))
    json.dump({"cadenas": res}, open(salida, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    con = [r for r in res if r["fuentes"]]
    print(f"{len(res)} webs rastreadas; {len(con)} con alguna agenda pública verificada")
    por = {}
    for r in con:
        for f in r["fuentes"]:
            por[f["plataforma"]] = por.get(f["plataforma"], 0) + 1
    print(por)


if __name__ == "__main__":
    main(*(sys.argv[1:2]))
