"""Excel de Lagree y Pilates Reformer con una hoja por ciudad (Valencia y Barcelona), sacado de los datos de la web (public/data).
Cada ciudad es la zona BeatCore de esa ciudad: Valencia = zona Valencia (Ruzafa), Barcelona = zona Diagonal.
Uso:  python informe_ciudades.py 2026-10-11 2026-10-16
"""
import collections
import json
import os
import sys

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

DESDE = sys.argv[1] if len(sys.argv) > 1 else "2026-10-11"
HASTA = sys.argv[2] if len(sys.argv) > 2 else "2026-10-16"
CIUDADES = [("Valencia", "Valencia"), ("Barcelona", "Diagonal")]       # (hoja, zona en la web)
DISCS = [("Lagree", "Lagree (incluye BeatCore)"), ("Reformer", "Pilates Reformer")]

idx = json.load(open("public/data/clases.json", encoding="utf-8"))
est, dic = idx["estudios"], idx["dic"]
acc = collections.defaultdict(lambda: [0, 0, 0.0, 0.0])      # clases, con reservas, reservas, plazas
todo = collections.defaultdict(lambda: [0, 0.0])             # clases y reservas de cualquier disciplina, por centro
zonas = {z for _, z in CIUDADES}
for m in idx["meses"]:
    d = json.load(open(f"public/data/clases_{m['mes']}.json", encoding="utf-8"))
    for j in range(d["n"]):
        f = dic["fecha"][d["f"][j]]
        if not (DESDE <= f <= HASTA):
            continue
        z = dic["centro"][d["c"][j]]
        disc = dic["disc"][d["d"][j]]
        if z not in zonas:
            continue
        e = est[d["e"][j]]
        t_ = todo[(z, e["n"])]
        t_[0] += 1
        if d["r"][j] is not None and d["a"][j]:
            t_[1] += d["r"][j]
        if disc not in ("Lagree", "Reformer"):
            continue
        x = acc[(z, disc, e["n"], e["p"])]
        x[0] += 1
        if d["r"][j] is not None and d["a"][j]:
            x[1] += 1
            x[2] += d["r"][j]
            x[3] += d["a"][j]

AZUL = PatternFill("solid", fgColor="1F4E78")
GRIS = PatternFill("solid", fgColor="E7E6E6")
VERDE = PatternFill("solid", fgColor="E2EFDA")
NEG = Font(bold=True)
BLANCO = Font(bold=True, color="FFFFFF")
COLS = ["Centro", "Clases dadas", "Reservas", "Media de gente por clase", "Plazas por clase", "Ocupación",
        "% de las reservas de la disciplina en la ciudad", "% de las reservas de las dos disciplinas en la ciudad"]


def cab(ws, r, textos):
    for i, t in enumerate(textos, 1):
        c = ws.cell(r, i, t)
        c.font, c.fill = BLANCO, AZUL
        c.alignment = Alignment(wrap_text=True, vertical="center", horizontal="center")
    ws.row_dimensions[r].height = 55


def sumar(filas):
    t = [0, 0, 0.0, 0.0]
    for f in filas:
        for k in range(4):
            t[k] += f[k]
    return t


def calc(x):
    m = x[1]
    return (x[2] / m if m else None, x[3] / m if m else None, x[2] / x[3] if x[3] else None)


def fila(ws, r, nombre, x, base_disc, base_ciudad, negrita=False, relleno=None):
    me, pl, oc = calc(x)
    vals = [nombre, x[0], x[2] if x[1] else None, me, pl, oc,
            (x[2] / base_disc) if (base_disc and x[1]) else None, (x[2] / base_ciudad) if (base_ciudad and x[1]) else None]
    for i, v in enumerate(vals, 1):
        c = ws.cell(r, i, v)
        if negrita:
            c.font = NEG
        if relleno:
            c.fill = relleno
    for col, fmt in ((4, "0.0"), (5, "0.0"), (6, "0%"), (7, "0.0%"), (8, "0.0%")):
        ws.cell(r, col).number_format = fmt


wb = Workbook()
wb.remove(wb.active)
for hoja, zona in CIUDADES:
    ws = wb.create_sheet(hoja)
    ct = sumar([v for k, v in acc.items() if k[0] == zona])
    ws["A1"] = f"{hoja}: Lagree y Pilates Reformer"
    ws["A1"].font = Font(bold=True, size=14)
    ws["A2"] = (f"Periodo: del {DESDE} al {HASTA}. Zona BeatCore de {hoja}. Datos de la web (clases ya dadas). BeatCore está dentro de Lagree. "
                "Reservas = gente apuntada a clases ya dadas, no asistencia.")
    ws["A3"] = "Media por clase, plazas por clase y ocupación se calculan sobre las clases con reservas conocidas (los centros de bsport no publican reservas)."
    r = 5
    ws.cell(r, 1, f"Total de {hoja}").font = NEG
    r += 1
    cab(ws, r, ["Disciplina", "Clases dadas", "Reservas", "Media de gente por clase", "Plazas por clase", "Ocupación",
                "% de las reservas de las dos disciplinas", "Centros"])
    for d, nom in DISCS:
        r += 1
        x = sumar([v for k, v in acc.items() if k[0] == zona and k[1] == d])
        me, pl, oc = calc(x)
        n_c = len({k[2] for k in acc if k[0] == zona and k[1] == d})
        for i, v in enumerate([nom, x[0], x[2] if x[1] else None, me, pl, oc, x[2] / ct[2] if ct[2] and x[1] else None, n_c], 1):
            ws.cell(r, i, v)
        for col, fmt in ((4, "0.0"), (5, "0.0"), (6, "0%"), (7, "0.0%")):
            ws.cell(r, col).number_format = fmt
    r += 1
    me, pl, oc = calc(ct)
    for i, v in enumerate([f"Total {hoja}", ct[0], ct[2] if ct[1] else None, me, pl, oc, 1.0 if ct[1] else None], 1):
        c = ws.cell(r, i, v)
        c.font, c.fill = NEG, GRIS
    for col, fmt in ((4, "0.0"), (5, "0.0"), (6, "0%"), (7, "0.0%")):
        ws.cell(r, col).number_format = fmt
    r += 2
    for d, nom in DISCS:
        filas = sorted([(k[2], k[3], v) for k, v in acc.items() if k[0] == zona and k[1] == d], key=lambda t: -t[2][2])
        dt = sumar([v for _, _, v in filas])
        ws.cell(r, 1, f"{nom} en {hoja} (centros ordenados por reservas)").font = Font(bold=True, size=12)
        r += 1
        cab(ws, r, COLS)
        for n, (nombre, propio, v) in enumerate(filas):
            r += 1
            fila(ws, r, nombre + (" (BeatCore)" if propio else ""), v, dt[2], ct[2], relleno=VERDE if n < 5 and v[1] else None)
        r += 1
        fila(ws, r, f"Total {nom}", dt, dt[2], ct[2], negrita=True, relleno=GRIS)
        r += 2
    ws.cell(r, 1, "Verde = los 5 centros con más reservas de esa disciplina en la ciudad.")
    for i, a in enumerate([44, 14, 12, 16, 14, 12, 24, 26], 1):
        ws.column_dimensions[get_column_letter(i)].width = a

# ---------------- Valencia: distancias de todos los estudios de Pilates y Lagree (al final de la hoja)
import pandas as pd
ws = wb["Valencia"]
cat = pd.read_csv("web/estudios.csv")
ub = json.load(open("web/ubicaciones.json", encoding="utf-8"))
rx = "eformer|pilates|lagree"
v = cat[(cat["zona"] == "Valencia") & (cat["disciplina"].fillna("").str.contains(rx, case=False) | cat["estudio"].str.contains(rx, case=False))]
filas = []
for _, r_ in v.iterrows():
    filas.append((r_["estudio"], 0 if r_.get("propio") in (True, "True", 1) else (None if pd.isna(r_["distancia_m"]) else int(r_["distancia_m"])),
                  r_["disciplina"] if isinstance(r_["disciplina"], str) else "", r_["plataforma"] if isinstance(r_["plataforma"], str) else ""))
# centros de cadenas con coordenadas (Glofox) que están en Valencia ciudad y no salen en el catálogo
nombres = {f[0].lower() for f in filas}
for k, x in ub.items():
    if k != "_sedes" and x.get("provincia") == "Valencia" and x.get("dist_bc_m") is not None and k.lower() not in nombres and "PILATES" in k.upper():
        filas.append((k, x["dist_bc_m"], "Pilates reformer", "Glofox"))
filas.sort(key=lambda t: (t[1] is None, t[1] or 0))
MOTIVO = {"TIMP": "Agenda con login: no se puede leer", "Wix": "Sin agenda pública que podamos leer", "Virtuagym": "Sin agenda pública que podamos leer",
          "No identificada": "No se ha localizado su agenda pública", "bsport": "Solo dice si la clase está llena: no hay reservas",
          "App propia": "Solo en su app", "Tribu": "Sin agenda pública que podamos leer"}
datos = collections.defaultdict(lambda: [0, 0.0])
for (z, d_, n_, p_), x in acc.items():
    if z == "Valencia":
        datos[n_][0] += x[0]
        datos[n_][1] += x[2] if x[1] else 0
r = ws.max_row + 3
ws.cell(r, 1, "Estudios de Pilates y Lagree en Valencia, por distancia a BeatCore Ruzafa").font = Font(bold=True, size=12)
r += 1
cab(ws, r, ["Estudio", "Distancia a BeatCore (m)", "Disciplina (catálogo)", "Plataforma de reservas", "Clases dadas (11-16/10)", "Reservas", "¿Vemos sus reservas?"])
for nombre, dist, disc, plat in filas:
    r += 1
    cl, rs = datos.get(nombre, [0, 0.0])
    tc, tr = todo.get(("Valencia", nombre), [0, 0.0])
    if rs > 0:
        ve = "Sí"
    elif tc > 0:
        ve = f"Hay agenda ({tc} clases dadas, {tr:.0f} reservas), pero sus clases no son Reformer ni Lagree"
        cl, rs = tc, tr
    else:
        ve = MOTIVO.get(plat, "No hay datos de reservas") if plat else "No hay datos de reservas"
    for i, val in enumerate([nombre, dist, disc, plat or "–", cl or None, rs or None, ve], 1):
        ws.cell(r, i, val)
    ws.cell(r, 2).number_format = "#,##0"
r += 2
ws.cell(r, 1, "Distancia = metros en línea recta hasta el BeatCore más cercano (en Valencia, BeatCore Ruzafa).")
ws.column_dimensions["G"].width = 62

os.makedirs("informes", exist_ok=True)
ruta = os.path.join("informes", f"lagree_reformer_valencia_barcelona_{DESDE}_{HASTA}.xlsx")
try:
    wb.save(ruta)
except PermissionError:          # el Excel está abierto: se guarda con otro nombre
    ruta = ruta.replace(".xlsx", "_con_distancias.xlsx")
    wb.save(ruta)
print(ruta)
