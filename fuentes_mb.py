"""Repite el descubrimiento solo para las cadenas con software Mindbody, y fusiona el resultado en web/cadenas_fuentes.json."""
import json
from concurrent.futures import ThreadPoolExecutor

import fuentes as F

inv = json.load(open("web/cadenas_inventario.json", encoding="utf-8"))["filas"]
mb = [(f["cadena"], f["web"]) for f in inv if f.get("web") and f.get("estado") == "ok"
      and any("mindbody" in s.lower() for s in f.get("software", []))]
print(len(mb), "cadenas con Mindbody:", [c for c, _ in mb])
with ThreadPoolExecutor(8) as ex:
    res = list(ex.map(lambda t: F.descubrir(*t), mb))
ruta = "web/cadenas_fuentes.json"
datos = json.load(open(ruta, encoding="utf-8"))["cadenas"]
nuevos = {r["cadena"]: r for r in res}
for r in datos:
    if r["cadena"] in nuevos:
        r["fuentes"] = [f for f in r["fuentes"] if f["plataforma"] != "mindbody"] + \
                       [f for f in nuevos[r["cadena"]]["fuentes"] if f["plataforma"] == "mindbody"]
json.dump({"cadenas": datos}, open(ruta, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
for r in res:
    print(r["cadena"], [(f["plataforma"], f.get("site_id"), f.get("clases_2d")) for f in r["fuentes"] if f["plataforma"] == "mindbody"])
