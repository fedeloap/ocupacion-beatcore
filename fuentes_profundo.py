"""
Descubrimiento profundo: para las cadenas cuyo software de reservas tiene agenda pública, rastrea hasta 250 páginas
de su web (todas las fichas de centro) para sacar los identificadores de TODOS sus centros en España.
Salida: web/cadenas_fuentes_prof.json (la lee fuentes_build.py junto a cadenas_fuentes.json y cadenas_red.json).
"""
import json
import sys
from concurrent.futures import ThreadPoolExecutor

import fuentes as F

PUBLICAS = {"momence", "mindbody", "bsport", "glofox", "mariana tek", "aimharder", "trainingym"}

inv = json.load(open("web/cadenas_inventario.json", encoding="utf-8"))["filas"]
try:
    nac = json.load(open("studios_cadenas.json", encoding="utf-8"))
except Exception:
    nac = {}
con_fuente = {e["estudio"].split(" ")[0].upper() for k, v in nac.items() if isinstance(v, list) for e in v}
tareas = []
for f in inv:
    if not (f.get("web") and f.get("estado") == "ok"):
        continue
    sw = {s.lower() for s in f.get("software", [])}
    if sw & PUBLICAS or f["cadena"].split(" ")[0].upper() in con_fuente:
        tareas.append((f["cadena"], f["web"]))
if len(sys.argv) > 1:
    tareas = [t for t in tareas if t[0] in sys.argv[1:]]
print(len(tareas), "cadenas:", [c for c, _ in tareas], flush=True)
with ThreadPoolExecutor(8) as ex:
    res = list(ex.map(lambda t: F.descubrir(t[0], t[1], 250), tareas))
json.dump({"cadenas": res}, open("web/cadenas_fuentes_prof.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
for r in res:
    c = {}
    for f in r["fuentes"]:
        c[f["plataforma"]] = c.get(f["plataforma"], 0) + 1
    print(r["cadena"], r["paginas"], "pág.", c, flush=True)
