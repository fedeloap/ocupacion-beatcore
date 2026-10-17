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
zonas = {z for _, z in CIUDADES}
for m in idx["meses"]:
    d = json.load(open(f"public/data/clases_{m['mes']}.json", encoding="utf-8"))
    for j in range(d["n"]):
        f = dic["fecha"][d["f"][j]]
        if not (DESDE <= f <= HASTA):
            continue
        z = dic["centro"][d["c"][j]]
        disc = dic["disc"][d["d"][j]]
        if z not in zonas or disc not in ("Lagree", "Reformer"):
            continue
        e = est[d["e"][j]]
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

os.makedirs("informes", exist_ok=True)
ruta = os.path.join("informes", f"lagree_reformer_valencia_barcelona_{DESDE}_{HASTA}.xlsx")
wb.save(ruta)
print(ruta)
