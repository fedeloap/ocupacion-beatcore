"""
Genera el sitio estático del dashboard en public/.

  public/index.html           copia de web/index.html
  public/robots.txt           copia de web/robots.txt
  public/data/clases.json     una fila por clase (columnar, strings con diccionario) + curvas
  public/data/estudios.json   catálogo web/estudios.csv
  public/data/meta.json       fecha de generación, rango, enlace del mapa

Reutiliza analisis.cargar() y analisis.preparar(). Las curvas usan todas las capturas
(data/*.csv, data/curva, data/plan) de las clases que ya han empezado.
"""

import json
import os
import re
import shutil
import unicodedata
from datetime import datetime, timezone

import numpy as np
import pandas as pd

import analisis

OUT = "public"
DIAS_MAX = 90
CHECKPOINTS = [168, 96, 72, 48, 24, 12, 6, 3, 1, 0]
KEY = ["plataforma", "estudio", "sede", "clase_id"]
MARGEN_H = analisis.MARGEN_MIN / 60

DISCIPLINAS = ["Reformer", "Lagree", "Barre", "Yoga", "HIIT/Funcional", "Ciclo", "Boxeo", "Otros"]

# Orden importa: la primera que encaja gana.
REGLAS = [
    ("Otros", r"sauna|recovery|recuperaci|estiramiento|face workout|facial|relax|infrared|cold plunge|masaje"),
    ("Lagree", r"lagree|microformer|megaformer"),
    ("Reformer", r"reformer|jumpboard|cadillac"),
    ("Barre", r"barre|barra"),
    ("Yoga", r"yoga|vinyasa|hatha|ashtanga|yin\b|kundalini"),
    ("Ciclo", r"cycl|cicl|spinning|\bspin\b|\brpm\b|\bride\b|indoor"),
    ("Boxeo", r"box|kick|muay|\bmma\b"),
    ("HIIT/Funcional", r"hiit|funcional|functional|crossfit|calistenia|circuito|tabata|boot ?camp|\bwod\b|hyrox|cross ?training"),
]
# Si el nombre de la clase no dice nada, se usa la disciplina del estudio en el catálogo.
DISC_CATALOGO = {
    "Pilates reformer": "Reformer", "Reformer": "Reformer", "Lagree": "Lagree", "Barre": "Barre",
    "Yoga": "Yoga", "Hot yoga": "Yoga", "Funcional": "HIIT/Funcional", "HIIT": "HIIT/Funcional",
    "Crossfit": "HIIT/Funcional", "Indoor cycling": "Ciclo", "Boxeo": "Boxeo",
}


def sin_acentos(s):
    return "".join(ch for ch in unicodedata.normalize("NFD", str(s)) if unicodedata.category(ch) != "Mn")


def disciplina(clase, disc_catalogo):
    t = sin_acentos(clase).lower()
    for nombre, rx in REGLAS:
        if re.search(rx, t):
            return nombre
    return DISC_CATALOGO.get(disc_catalogo, "Otros")


def lista(s, nd=None):
    """Serie a lista JSON: NaN a None, enteros como int."""
    s = pd.to_numeric(s, errors="coerce")
    if nd is not None:
        s = s.round(nd)
    vals = s.to_numpy(dtype="float64")
    ok = ~np.isnan(vals)
    if nd == 0 or (nd is None and ok.any() and np.all(vals[ok] == np.floor(vals[ok]))):
        return [int(v) if o else None for v, o in zip(vals, ok)]
    return [float(v) if o else None for v, o in zip(vals, ok)]


def indexar(valores):
    """Devuelve (diccionario ordenado, índices)."""
    dic = sorted({str(v) for v in valores})
    pos = {v: i for i, v in enumerate(dic)}
    return dic, [pos[str(v)] for v in valores]


def escribir(nombre, obj):
    ruta = os.path.join(OUT, "data", nombre)
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))
    return os.path.getsize(ruta)


def cargar_catalogo():
    cat = pd.read_csv("web/estudios.csv")
    mapa = {}
    for _, r in cat.iterrows():
        if isinstance(r["captura"], str):
            for k in r["captura"].split(";"):
                mapa.setdefault(k.strip(), r)
    return cat, mapa


def cargar_snapshots():
    partes = [analisis.leer(p) for p in ("data/*.csv", "data/curva/*.csv", "data/plan/*.csv")]
    s = pd.concat([p for p in partes if len(p)], ignore_index=True)
    s["captured_at"] = pd.to_datetime(s["captured_at"])
    s["sede"] = s["sede"].fillna("").astype(str)
    s["clase_id"] = s["clase_id"].astype(str)
    s = s.drop_duplicates(KEY + ["captured_at"])
    s["inicio_local"] = pd.to_datetime(s["inicio_local"])
    return s[KEY + ["clase", "inicio_local", "captured_at", "ocupadas", "libres", "llena"]]


def clave_clase(d):
    """Identificador de la clase estable entre capturas.

    En Mindbody el clase_id cambia de una captura a otra (los ids de la planificación no
    coinciden con los de la captura final), así que se usa estudio, sede, hora y nombre.
    En el resto de plataformas vale clase_id."""
    alt = (d["estudio"].astype(str) + "|" + d["sede"].astype(str) + "|"
           + d["inicio_local"].dt.strftime("%Y-%m-%d %H:%M") + "|" + d["clase"].astype(str))
    return alt.where(d["plataforma"] == "mindbody", d["clase_id"].astype(str))


def curvas(c, snap):
    """Reservas y 'llena' en cada checkpoint, y horas antes de llenarse, por clase (índice de c)."""
    base = c[KEY + ["clase", "inicio_local", "aforo"]].copy()
    base["i"] = np.arange(len(base))
    base["kid"] = clave_clase(base)
    snap = snap.assign(kid=clave_clase(snap)).drop(columns=["clase_id", "clase", "inicio_local"])
    m = snap.merge(base.drop(columns=["clase_id", "clase"]), on=["plataforma", "estudio", "sede", "kid"], how="inner")
    m["hb"] = (m["inicio_local"] - m["captured_at"]).dt.total_seconds() / 3600
    m = m[m["hb"] >= -MARGEN_H].copy()
    aforo = m["aforo"]
    ocup = pd.to_numeric(m["ocupadas"], errors="coerce")
    lib = pd.to_numeric(m["libres"], errors="coerce")
    res = ocup.where(ocup.notna(), aforo - lib)
    m["res"] = res.clip(lower=0).where(aforo.isna(), res.clip(lower=0, upper=aforo))
    lleno = m["llena"].astype(str).str.lower().map({"true": True, "false": False})
    m["lleno"] = lleno.where(lleno.notna(), (m["res"] >= aforo) & aforo.notna())
    m = m.sort_values(["i", "hb"])

    n = len(c)
    cr, cl = [], []
    for cp in CHECKPOINTS:
        lo = cp if cp > 0 else -MARGEN_H
        hi = cp + max(1.0, 0.5 * cp)
        s = m[(m["hb"] >= lo) & (m["hb"] <= hi)].groupby("i").first()
        r = pd.Series(np.nan, index=range(n))
        r.loc[s.index] = s["res"]
        l = pd.Series(np.nan, index=range(n))
        l.loc[s.index] = s["lleno"].astype(float)
        cr.append(lista(r))
        cl.append(lista(l))

    # primera foto en la que la clase aparece llena (cota superior de cuándo se llenó)
    llenas = m[m["lleno"] == True]  # noqa: E712
    primera_llena = llenas.sort_values(["i", "hb"], ascending=[True, False]).groupby("i").first()["hb"]
    primera_foto = m.groupby("i")["hb"].max()
    hf = pd.Series(np.nan, index=range(n))
    hf.loc[primera_llena.index] = primera_llena.clip(lower=0)
    hf0 = pd.Series(np.nan, index=range(n))
    hf0.loc[primera_llena.index] = (primera_llena >= primera_foto.loc[primera_llena.index] - 1e-9).astype(float)
    return cr, cl, hf, hf0


def main():
    os.makedirs(os.path.join(OUT, "data"), exist_ok=True)
    festivos = json.load(open("festivos.json", encoding="utf-8"))
    studios = json.load(open("studios.json", encoding="utf-8"))
    propios = set()
    for plat, lst in studios.items():
        if isinstance(lst, list):
            propios |= {e["estudio"] for e in lst if e.get("propio")}

    # Los festivos NO se excluyen en la web (hay clases ese día); se marcan para poder filtrarlos.
    c = analisis.preparar(analisis.cargar(), {}).reset_index(drop=True)
    c["es_festivo"] = [
        int(bool(f) and (f["zonas"] == "todas" or z in f["zonas"]))
        for f, z in zip((festivos.get(d) for d in c["fecha"]), c["centro_beatcore"])
    ]
    if len(c):
        c = c[c["inicio_local"] >= c["inicio_local"].max().normalize() - pd.Timedelta(days=DIAS_MAX)]
    c = c.sort_values(["inicio_local", "estudio", "clase_id"]).reset_index(drop=True)

    cat, mapa = cargar_catalogo()
    filas = []
    for e, z in zip(c["estudio"], c["centro_beatcore"]):
        r = mapa.get(f"{e}|{z}")
        filas.append((int(r["id"]) if r is not None else -1,
                      r["estudio"] if r is not None else e,
                      r["marca"] if r is not None else e,
                      bool(r["propio"]) if r is not None else e in propios,
                      r["disciplina"] if r is not None else "",
                      z))
    est_tab, est_idx = [], {}
    e_idx = []
    for f in filas:
        if f[:2] + (f[5],) not in est_idx:
            est_idx[f[:2] + (f[5],)] = len(est_tab)
            est_tab.append({"id": f[0], "n": f[1], "m": f[2], "p": int(f[3]), "z": f[5]})
        e_idx.append(est_idx[f[:2] + (f[5],)])

    disc = [disciplina(k, f[4]) for k, f in zip(c["clase"], filas)]
    cr, cl, hf, hf0 = curvas(c, cargar_snapshots())

    d_centro, i_centro = indexar(c["centro_beatcore"])
    d_plat, i_plat = indexar(c["plataforma"])
    d_clase, i_clase = indexar(c["clase"])
    d_fecha, i_fecha = indexar(c["fecha"])
    d_disc, i_disc = indexar(disc)
    minutos = c["inicio_local"].dt.hour * 60 + c["inicio_local"].dt.minute
    llena = c["llena_b"].map({True: 1, False: 0})
    fuente = c["aforo_fuente"].map({"publicado": 0, "estimado": 1})

    clases = {
        "n": len(c), "checkpoints": CHECKPOINTS,
        "dic": {"centro": d_centro, "plat": d_plat, "clase": d_clase, "fecha": d_fecha, "disc": d_disc},
        "estudios": est_tab,
        "e": e_idx, "c": i_centro, "p": i_plat, "k": i_clase, "f": i_fecha, "d": i_disc,
        "w": lista(c["inicio_local"].dt.weekday),
        "h": lista(minutos),
        "du": lista(c["duracion_min"]),
        "a": lista(c["aforo"]),
        "r": lista(c["reservas"]),
        "l": lista(llena),
        "af": lista(fuente),
        "fe": lista(c["es_festivo"]),
        "cr": cr, "cl": cl,
        "hf": lista(hf, 1), "hf0": lista(hf0),
    }

    cat_out = cat.copy()
    cat_out["propio"] = cat_out["propio"].astype(int)
    cat_cols = list(cat_out.columns)
    estudios = {"cols": cat_cols,
                "rows": [[None if (isinstance(v, float) and np.isnan(v)) else (v.item() if hasattr(v, "item") else v)
                          for v in row] for row in cat_out.itertuples(index=False, name=None)]}

    cfg = {}
    if os.path.exists("web/config.json"):
        cfg = json.load(open("web/config.json", encoding="utf-8"))
    meta = {
        "generado": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ"),
        "desde": c["fecha"].min() if len(c) else "",
        "hasta": c["fecha"].max() if len(c) else "",
        "clases": len(c),
        "mapa_url": cfg.get("mapa_url", ""),
        "festivos": {k: v["nombre"] for k, v in festivos.items()},
    }

    tam = {n: escribir(n, o) for n, o in (("clases.json", clases), ("estudios.json", estudios), ("meta.json", meta))}
    for f in ("index.html", "robots.txt"):
        if os.path.exists(os.path.join("web", f)):
            shutil.copy(os.path.join("web", f), os.path.join(OUT, f))
    print(f"{len(c)} clases; " + ", ".join(f"{n} {t / 1024:.0f} KB" for n, t in tam.items()))


if __name__ == "__main__":
    main()
