"""
Filtra web/cadenas_centros.json dejando solo los centros de España (JSON-LD de la ficha: addressCountry / timezone).
Las cadenas internacionales (FS8, F45, Barry's, LevelOut...) listan sedes de todo el mundo en su web.
"""
import json
import re
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse

import requests

H = {"User-Agent": "Mozilla/5.0 (compatible; BeatCoreResearch/1.0)"}
ES_TZ = ("Europe/Madrid", "Atlantic/Canary", "Africa/Ceuta")


def pais(url):
    try:
        h = requests.get(url, headers=H, timeout=25).text
    except Exception:
        return None
    c = re.findall(r'"addressCountry"\s*:\s*"?\\?"?([A-Za-z ]{2,20})', h)
    tz = [t.replace("\\/", "/") for t in re.findall(r'"timezone"\s*:\s*"([^"]+)"', h)]
    if tz and any(t.startswith(ES_TZ) for t in tz):
        return "ES"
    if c:
        v = c[0].strip().upper()
        return "ES" if v in ("ES", "ESP", "SPAIN", "ESPAÑA") else v
    m = re.search(r"f45training\.com/([a-z]{2})/", url)
    if m:
        return m.group(1).upper()
    return None


def main(ruta="web/cadenas_centros.json"):
    d = json.load(open(ruta, encoding="utf-8"))
    urls = sorted({c["url"] for r in d.values() for c in r["centros"]})
    with ThreadPoolExecutor(10) as ex:
        paises = dict(zip(urls, ex.map(pais, urls)))
    tot = ok = 0
    for cad, r in d.items():
        nuevos = []
        for c in r["centros"]:
            p = paises.get(c["url"])
            tot += 1
            # país desconocido: se conserva (las cadenas de la lista son españolas) y se marca para revisar
            if p == "ES" or p is None:
                c["pais"] = p or "?"
                nuevos.append(c)
                ok += 1
        r["centros_mundo"] = len(r["centros"])
        r["centros"] = nuevos
    json.dump(d, open(ruta, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"{ok} de {tot} centros son de España")
    for cad, r in sorted(d.items(), key=lambda kv: -len(kv[1]["centros"])):
        if r["centros"]:
            print(f"  {cad}: {len(r['centros'])} de {r['centros_mundo']}")


if __name__ == "__main__":
    main()
