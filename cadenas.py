"""
Inventario de cadenas (nacional): web, software de reservas, centros y precios publicados.

Entrada:
  web/cadenas_lista.txt     una cadena por línea (la lista de Fede)
  web/cadenas_webs.csv      cadena,web  (web oficial verificada; opcional, manda sobre lo descubierto)
  web/estudios.csv          catálogo (web y plataforma de los estudios ya conocidos)
Salida:
  public/data/cadenas.json  una fila por cadena (columnar)

Solo datos públicos: páginas web abiertas, sin login ni saltarse protecciones. Si una web devuelve
403, captcha o Cloudflare con desafío, se anota y se deja en blanco.
Todo lo que no se sabe queda vacío: no se inventa.
"""

import csv
import json
import os
import re
import sys
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from html import unescape
from urllib.parse import urljoin, urlparse

import pandas as pd
import requests

H = {"User-Agent": "Mozilla/5.0 (compatible; BeatCoreResearch/1.0; +https://github.com/fedeloap/ocupacion-beatcore)"}
TIMEOUT = 15
MAX_PAGINAS = 9

# plataforma: patrón que aparece en el HTML (scripts, iframes, enlaces)
SOFTWARE = {
    "Momence": r"momence\.com",
    "Mindbody": r"mindbodyonline|healcode|brandedweb|clients\.mindbody",
    "Glofox": r"glofox\.com",
    "Mariana Tek": r"marianatek\.com",
    "bsport": r"bsport\.io|bsport\.fr",
    "Eversports": r"eversports\.",
    "AimHarder": r"aimharder\.com",
    "Wodbuster": r"wodbuster\.com",
    "Harbiz": r"harbiz\.io",
    "Trainingym": r"trainingym\.com",
    "TIMP": r"timp\.pro|timpgym|app\.timp",
    "Virtuagym": r"virtuagym\.com",
    "Wix Bookings": r"wixbookings|booking\.wix|wixapps",
    "Acuity": r"acuityscheduling",
    "Momoyoga": r"momoyoga",
    "PushPress": r"pushpress",
    "Fitogram": r"fitogram",
    "Bewe": r"bewe\.",
    "Viday": r"viday",
    "Gymdesk/ABC": r"abcfitness|gymdesk",
    "Bookeo": r"bookeo\.com",
    "Setmore/Calendly": r"setmore|calendly\.com",
    "Cliclu": r"cliclu",
    "Provis": r"provis",
    "Reservo": r"reservo\.",
    "Simplybook": r"simplybook",
    "Fitnessmanager": r"fitnessmanager",
    "Gymcloud": r"gymcloud",
}
# plataformas cuya agenda se puede leer hoy sin login (las que ya captura capture.py)
CAPTURABLES = {"Momence", "Mindbody", "Glofox", "Mariana Tek", "bsport"}
FUERA = {"Eversports", "AimHarder", "Wodbuster", "Harbiz", "Trainingym", "TIMP"}  # reglas de CLAUDE.md

RX_LINK = re.compile(r"""(?:href|src|data-src|action)\s*=\s*["']([^"'#]+)""", re.I)
RX_CLAVE = re.compile(r"horario|reserv|schedul|clase|book|calend|tarifa|precio|price|bono|membres|abono|cuota|centros|studios|"
                      r"locations|ubicac|sedes|clubs|encuentra|nuestros|donde|where", re.I)
RX_CENTRO = re.compile(r"/(centros?|studios?|clubs?|locations?|sedes?|gimnasios?|estudios?|centres?|ubicaciones?)/[a-z0-9\-_%]+/?$", re.I)
RX_EURO = re.compile(r"(\d{1,3}(?:[.,]\d{1,2})?)\s?(?:€|eur\b|euros)", re.I)
RX_EURO2 = re.compile(r"(?:€)\s?(\d{1,3}(?:[.,]\d{1,2})?)", re.I)
RX_TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.S | re.I)


def norm(s):
    s = unicodedata.normalize("NFD", str(s)).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"\(.*?\)", " ", s)
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", s)).strip()


def dominio(url):
    h = urlparse(url).netloc.lower()
    return h[4:] if h.startswith("www.") else h


def raiz(url):
    try:
        p = urlparse(url)
        return f"{p.scheme}://{p.netloc}/"
    except Exception:
        return ""


def get(url):
    try:
        r = requests.get(url, headers=H, timeout=TIMEOUT, allow_redirects=True)
        return r
    except Exception:
        return None


def euros(texto):
    t = re.sub(r"<script.*?</script>|<style.*?</style>", " ", texto, flags=re.S | re.I)
    t = unescape(re.sub(r"<[^>]+>", " ", t))
    vals = []
    for m in list(RX_EURO.finditer(t)) + list(RX_EURO2.finditer(t)):
        try:
            v = float(m.group(1).replace(",", "."))
        except ValueError:
            continue
        if 3 <= v <= 600:
            vals.append(v)
    return vals


def analizar(cadena, web):
    out = {"cadena": cadena, "web": web, "estado": "", "titulo": "", "software": [], "capturable": "",
           "centros_n": None, "centros_ejemplos": [], "precios_url": "", "precios": [], "paginas": 0}
    if not web:
        out["estado"] = "sin web"
        return out
    r = get(web)
    if r is None:
        out["estado"] = "no responde"
        return out
    if r.status_code in (401, 403, 429) or "just a moment" in r.text[:2000].lower():
        out["estado"] = f"bloqueada ({r.status_code})"
        return out
    if r.status_code >= 400:
        out["estado"] = f"error {r.status_code}"
        return out
    base = r.url
    dom = dominio(base)
    htmls = {base: r.text}
    m = RX_TITLE.search(r.text)
    out["titulo"] = unescape(m.group(1)).strip()[:90] if m else ""
    # enlaces de interés de la home
    enlaces = []
    for href in RX_LINK.findall(r.text):
        u = urljoin(base, href.strip())
        if u.startswith("http") and RX_CLAVE.search(u):
            if dominio(u) == dom or any(re.search(rx, u, re.I) for rx in SOFTWARE.values()):
                enlaces.append(u.split("?")[0])
    vistos = []
    for u in enlaces:
        if u not in vistos and u != base:
            vistos.append(u)
    for u in vistos[: MAX_PAGINAS - 1]:
        rr = get(u)
        if rr is not None and rr.status_code < 400 and "text/html" in rr.headers.get("content-type", "text/html"):
            htmls[rr.url] = rr.text
    out["paginas"] = len(htmls)
    todo = "\n".join(htmls.values())
    out["software"] = sorted(k for k, rx in SOFTWARE.items() if re.search(rx, todo, re.I))
    cap = [s for s in out["software"] if s in CAPTURABLES]
    fuera = [s for s in out["software"] if s in FUERA]
    out["capturable"] = ("sí: " + ", ".join(cap)) if cap else (("no (regla): " + ", ".join(fuera)) if fuera else "")
    # centros: el grupo de enlaces con patrón /centros/xxx más numeroso
    locs = set()
    for h in htmls.values():
        for href in RX_LINK.findall(h):
            u = urljoin(base, href.strip()).split("?")[0].split("#")[0]
            if dominio(u) == dom and RX_CENTRO.search(urlparse(u).path):
                locs.add(u.rstrip("/"))
    if locs:
        out["centros_n"] = len(locs)
        out["centros_ejemplos"] = sorted(locs)[:3]
    # sitemap como apoyo
    if out["centros_n"] is None:
        sm = get(raiz(base) + "sitemap.xml")
        if sm is not None and sm.status_code == 200 and "<loc>" in sm.text:
            urls = re.findall(r"<loc>(.*?)</loc>", sm.text)
            l2 = {u.rstrip("/") for u in urls if RX_CENTRO.search(urlparse(u).path)}
            if l2:
                out["centros_n"] = len(l2)
                out["centros_ejemplos"] = sorted(l2)[:3]
    # precios: páginas con € y palabras de tarifa
    mejor = ("", [])
    for u, h in htmls.items():
        if re.search(r"tarifa|precio|price|bono|membres|abono|cuota|comprar", u, re.I) or True:
            v = euros(h)
            if len(v) > len(mejor[1]) and re.search(r"tarifa|precio|price|bono|membres|abono|cuota|comprar|plan", u, re.I):
                mejor = (u, v)
    if not mejor[1]:
        for u, h in htmls.items():
            v = euros(h)
            if len(v) > len(mejor[1]):
                mejor = (u, v)
    out["precios_url"] = mejor[0]
    out["precios"] = sorted(set(mejor[1]))[:14]
    out["estado"] = "ok"
    return out


def webs_conocidas():
    """cadena -> web: catálogo (marca/estudio) y overrides de web/cadenas_webs.csv."""
    lista = [l.strip() for l in open("web/cadenas_lista.txt", encoding="utf-8") if l.strip()]
    cat = pd.read_csv("web/estudios.csv")
    cat["n_estudio"] = cat["estudio"].map(norm)
    cat["n_marca"] = cat["marca"].map(norm)
    ig = re.compile(r"instagram\.com|facebook\.com|mtrbio|linktr\.ee|google\.com/maps|wa\.me", re.I)
    res = {}
    for c in lista:
        n = norm(c)
        if not n:
            continue
        m = cat[(cat.n_marca == n) | cat.n_marca.str.contains(r"\b" + re.escape(n) + r"\b", regex=True) |
                cat.n_estudio.str.contains(r"\b" + re.escape(n) + r"\b", regex=True)]
        webs = [w for w in m.web.dropna() if isinstance(w, str) and w.startswith("http") and not ig.search(w)]
        if webs:
            res[c] = raiz(webs[0])
    if os.path.exists("web/cadenas_webs.csv"):
        for row in csv.DictReader(open("web/cadenas_webs.csv", encoding="utf-8")):
            if row.get("web", "").strip():
                res[row["cadena"].strip()] = row["web"].strip()
            elif row["cadena"].strip() in res:
                del res[row["cadena"].strip()]
    return lista, res


def main(salida="public/data/cadenas.json"):
    lista, webs = webs_conocidas()
    with ThreadPoolExecutor(12) as ex:
        filas = list(ex.map(lambda c: analizar(c, webs.get(c, "")), lista))
    os.makedirs(os.path.dirname(salida), exist_ok=True)
    json.dump({"filas": filas}, open(salida, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    ok = sum(1 for f in filas if f["estado"] == "ok")
    print(f"{len(filas)} cadenas; con web analizada: {ok}; con software: {sum(1 for f in filas if f['software'])}; "
          f"con centros: {sum(1 for f in filas if f['centros_n'])}; con precios: {sum(1 for f in filas if f['precios'])}")
    return filas


if __name__ == "__main__":
    main(*(sys.argv[1:2]))
