"""Excel de Lagree y Pilates Reformer con una hoja por zona/ciudad, sacado de los datos de la web (public/data) y del catálogo.
Cada hoja: totales, y las tablas de Lagree y Pilates Reformer con TODOS los estudios de la zona (a menos de 1 km de un BeatCore),
también los que no publican reservas (salen en blanco, con su distancia y una nota). Se dejan fuera yoga y hot yoga.
Uso:  python informe_ciudades.py 2026-10-11 2026-10-16 "Valencia:Valencia,Barcelona:Diagonal"
"""
import collections
import json
import os
import re
import sys

import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

DESDE = sys.argv[1] if len(sys.argv) > 1 else "2026-10-11"
HASTA = sys.argv[2] if len(sys.argv) > 2 else "2026-10-16"
ARG = sys.argv[3] if len(sys.argv) > 3 else "Valencia:Valencia,Barcelona:Diagonal"
CIUDADES = [tuple(x.split(":")) for x in ARG.split(",")]                 # (hoja, zona en la web)
DISCS = [("Lagree", "Lagree (incluye BeatCore)"), ("Reformer", "Pilates Reformer")]

idx = json.load(open("public/data/clases.json", encoding="utf-8"))
est, dic = idx["estudios"], idx["dic"]
acc = collections.defaultdict(lambda: [0, 0, 0.0, 0.0])      # (zona, disc, estudio, propio) -> clases, con reservas, reservas, plazas
todo = collections.defaultdict(lambda: [0, 0.0])             # (zona, estudio) -> clases y reservas de cualquier disciplina
zonas = {z for _, z in CIUDADES}
for m in idx["meses"]:
    d = json.load(open(f"public/data/clases_{m['mes']}.json", encoding="utf-8"))
    for j in range(d["n"]):
        f = dic["fecha"][d["f"][j]]
        if not (DESDE <= f <= HASTA):
            continue
        z = dic["centro"][d["c"][j]]
        if z not in zonas:
            continue
        disc = dic["disc"][d["d"][j]]
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

cat = pd.read_csv("web/estudios.csv")
ub = json.load(open("web/ubicaciones.json", encoding="utf-8"))
dist_cat = {}
for _, r_ in cat.iterrows():
    if r_.get("propio") in (True, "True", 1):
        dist_cat[(r_["zona"], str(r_["estudio"]).lower())] = 0
    elif not pd.isna(r_["distancia_m"]):
        dist_cat[(r_["zona"], str(r_["estudio"]).lower())] = int(r_["distancia_m"])
plat_cat = {(r_["zona"], str(r_["estudio"]).lower()): (r_["plataforma"] if isinstance(r_["plataforma"], str) else "") for _, r_ in cat.iterrows()}


def distancia(zona, nombre):
    d_ = dist_cat.get((zona, nombre.lower()))
    if d_ is None and nombre in ub and ub[nombre].get("dist_bc_m") is not None:
        d_ = ub[nombre]["dist_bc_m"]
    return d_


def candidatos(zona, disc):
    """Estudios del catálogo en la zona que son de esa disciplina, aunque no tengamos sus reservas. Fuera yoga y hot yoga."""
    v = cat[cat["zona"] == zona]
    out = []
    for _, r_ in v.iterrows():
        if r_.get("propio") in (True, "True", 1):
            continue                      # BeatCore es Lagree y sale por sus datos, no como candidato de Reformer
        dis = r_["disciplina"] if isinstance(r_["disciplina"], str) else ""
        nom = str(r_["estudio"])
        if dis.lower() in ("yoga", "hot yoga") and not re.search("pilates|reformer", nom, re.I):
            continue
        if re.search("hot yoga|bikram|yoga", nom, re.I) and not re.search("pilates|reformer", nom, re.I):
            continue
        if disc == "Reformer" and (dis.lower() in ("pilates reformer", "reformer", "pilates") or re.search("pilates|reformer", nom, re.I)):
            out.append(nom)
        if disc == "Lagree" and (dis.lower() == "lagree" or re.search("lagree", nom, re.I)):
            out.append(nom)
    return out


MOTIVO = {"TIMP": "Agenda con login: no se puede leer", "Wix": "No se ha localizado una agenda pública", "Virtuagym": "No se ha localizado una agenda pública",
          "No identificada": "No se ha localizado una agenda pública", "bsport": "Solo dice si la clase está llena: no hay reservas",
          "App propia": "Solo en su app", "Tribu": "No se ha localizado una agenda pública", "AimHarder": "No publica sus reservas"}

AZUL = PatternFill("solid", fgColor="1F4E78")
GRIS = PatternFill("solid", fgColor="E7E6E6")
VERDE = PatternFill("solid", fgColor="E2EFDA")
NEG = Font(bold=True)
BLANCO = Font(bold=True, color="FFFFFF")
COLS = ["Centro", "Clases dadas", "Reservas", "Media de gente por clase", "Plazas por clase", "Ocupación",
        "% de las reservas de la disciplina en la zona", "% de las reservas de las dos disciplinas en la zona",
        "Distancia a BeatCore (m)", "Nota"]


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


def fila(ws, r, nombre, x, base_disc, base_zona, dist=None, nota=None, negrita=False, relleno=None):
    me, pl, oc = calc(x)
    vals = [nombre, x[0] or None, x[2] if x[1] else None, me, pl, oc,
            (x[2] / base_disc) if (base_disc and x[1]) else None, (x[2] / base_zona) if (base_zona and x[1]) else None, dist, nota]
    for i, v in enumerate(vals, 1):
        c = ws.cell(r, i, v)
        if negrita:
            c.font = NEG
        if relleno:
            c.fill = relleno
    for col, fmt in ((4, "0.0"), (5, "0.0"), (6, "0%"), (7, "0.0%"), (8, "0.0%"), (9, "#,##0")):
        ws.cell(r, col).number_format = fmt


wb = Workbook()
wb.remove(wb.active)
for hoja, zona in CIUDADES:
    ws = wb.create_sheet(hoja)
    ct = sumar([v for k, v in acc.items() if k[0] == zona])
    ws["A1"] = f"{hoja}: Lagree y Pilates Reformer"
    ws["A1"].font = Font(bold=True, size=14)
    ws["A2"] = (f"Periodo: del {DESDE} al {HASTA}. Zona BeatCore de {hoja} (estudios a 1 km o menos de un BeatCore). Datos de la web (clases ya dadas). "
                "BeatCore está dentro de Lagree. Reservas = gente apuntada a clases ya dadas, no asistencia. Yoga y hot yoga quedan fuera.")
    ws["A3"] = ("Media por clase, plazas por clase y ocupación se calculan sobre las clases con reservas conocidas. Los estudios sin datos salen en blanco, "
                "con su distancia y el motivo en la columna Nota.")
    listas = {}
    for d, nom in DISCS:
        con = {k[2]: (k[3], v) for k, v in acc.items() if k[0] == zona and k[1] == d}
        nombres_con = {n.lower() for n in con}
        sin, vistos = [], set()
        for n in candidatos(zona, d):
            if n.lower() in nombres_con or n.lower() in vistos:
                continue
            vistos.add(n.lower())
            tc, tr = todo.get((zona, n), [0, 0.0])
            plat = plat_cat.get((zona, n.lower()), "")
            if tc > 0:
                nota = f"Hay agenda ({tc} clases dadas, {tr:.0f} reservas), pero sus clases no son de esta disciplina (p. ej. Hot Pilates)"
            else:
                nota = MOTIVO.get(plat, "No hay datos de reservas")
            dd = distancia(zona, n)
            sin.append((dd if dd is not None else 10 ** 9, n, nota))
        sin.sort(key=lambda t: t[0])
        listas[d] = (sorted(con.items(), key=lambda t: -t[1][1][2]), sin)
    r = 5
    ws.cell(r, 1, f"Total de {hoja}").font = NEG
    r += 1
    cab(ws, r, ["Disciplina", "Clases dadas", "Reservas", "Media de gente por clase", "Plazas por clase", "Ocupación",
                "% de las reservas de las dos disciplinas", "Centros con reservas conocidas / centros en la zona"])
    for d, nom in DISCS:
        r += 1
        x = sumar([v for k, v in acc.items() if k[0] == zona and k[1] == d])
        me, pl, oc = calc(x)
        con, sin = listas[d]
        n_ok = sum(1 for _, (p, v) in con if v[1] > 0)
        for i, v in enumerate([nom, x[0], x[2] if x[1] else None, me, pl, oc, x[2] / ct[2] if ct[2] and x[1] else None,
                               f"{n_ok} / {len(con) + len(sin)}"], 1):
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
        con, sin = listas[d]
        dt = sumar([v for _, (_, v) in con])
        ws.cell(r, 1, f"{nom} en {hoja}: todos los estudios de la zona (con reservas primero; después, sin datos por distancia)").font = Font(bold=True, size=12)
        r += 1
        cab(ws, r, COLS)
        for n, (nombre, (propio, v)) in enumerate(con):
            r += 1
            nota = None if v[1] else "Hay clases dadas pero no publica reservas"
            fila(ws, r, nombre + (" (BeatCore)" if propio else ""), v, dt[2], ct[2], distancia(zona, nombre), nota,
                 relleno=VERDE if n < 5 and v[1] else None)
        for dist_, nombre, nota in sin:
            r += 1
            fila(ws, r, nombre, [0, 0, 0.0, 0.0], dt[2], ct[2], None if dist_ == 10 ** 9 else dist_, nota)
        r += 1
        fila(ws, r, f"Total {nom}", dt, dt[2], ct[2], negrita=True, relleno=GRIS)
        r += 2
    ws.cell(r, 1, "Verde = los 5 centros con más reservas de esa disciplina en la zona. Distancia = metros en línea recta al BeatCore más cercano.")
    for i, a in enumerate([46, 14, 12, 16, 14, 12, 22, 24, 16, 66], 1):
        ws.column_dimensions[get_column_letter(i)].width = a

os.makedirs("informes", exist_ok=True)
nombre_zonas = "_".join(h.lower() for h, _ in CIUDADES).replace("í", "i").replace("é", "e").replace("á", "a")
ruta = os.path.join("informes", f"lagree_reformer_{nombre_zonas}_{DESDE}_{HASTA}.xlsx")
try:
    wb.save(ruta)
except PermissionError:          # el Excel está abierto: se guarda con otro nombre
    ruta = ruta.replace(".xlsx", "_v2.xlsx")
    wb.save(ruta)
print(ruta)
