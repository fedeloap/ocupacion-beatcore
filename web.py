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
    return s[KEY + ["clase", "inicio_local", "captured_at", "capacidad", "ocupadas", "libres", "llena",
                    "centro_beatcore", "cancelada", "duracion_min"]]


def clases_unicas(snap):
    """Una fila por clase (última foto): plazas, reservas y fecha. Incluye clases programadas y ya dadas."""
    s = snap.copy()
    s["kid"] = clave_clase(s)
    s["libres_n"] = pd.to_numeric(s["libres"], errors="coerce")
    g = ["plataforma", "estudio", "sede", "kid"]
    ml = s.groupby(g)["libres_n"].max().rename("max_libres")
    s = s.sort_values("captured_at").groupby(g, as_index=False).tail(1)
    s = s.merge(ml, left_on=g, right_index=True, how="left")
    s = s[s["cancelada"].astype(str).str.lower() != "true"].copy()
    cap = pd.to_numeric(s["capacidad"], errors="coerce")
    est = (s["plataforma"] == "mindbody") & ~(cap > 0) & (s["max_libres"] > 0) & (s["max_libres"] <= analisis.AFORO_MAX_PLAUSIBLE)
    s["plazas"] = cap.where(cap > 0, s["max_libres"].where(est))
    occ = pd.to_numeric(s["ocupadas"], errors="coerce")
    occ = occ.where(occ.notna(), s["plazas"] - s["libres_n"])
    r = occ.where(s["plataforma"] != "bsport").clip(lower=0)
    s["reservas"] = r.where(s["plazas"].isna(), r.clip(upper=s["plazas"]))
    s["zona"] = s["centro_beatcore"].fillna("").replace("", "Nacional")
    s["fecha"] = s["inicio_local"].dt.normalize()
    return s.reset_index(drop=True)


def _agrega(d, ahora):
    """Clases, plazas y ocupación (reservas/plazas) por día de la semana, semana y mes."""
    if d.empty:
        return None
    ya = d[(d["inicio_local"] <= ahora) & d["reservas"].notna() & (d["plazas"] > 0)]

    def ocup(g):
        p = g["plazas"].sum()
        return round(float(g["reservas"].sum() / p), 3) if p > 0 else None

    por_fecha = d.groupby("fecha").agg(clases=("kid", "size"), plazas=("plazas", "sum"))
    med_fecha = ya.groupby("fecha").agg(reservas=("reservas", "sum"), plazas_med=("plazas", "sum"))
    dias = []
    for w in range(7):
        pf = por_fecha[por_fecha.index.dayofweek == w]
        yy = ya[ya["fecha"].dt.dayofweek == w]
        mf = med_fecha[med_fecha.index.dayofweek == w]
        dias.append({"d": w, "fechas": int(len(pf)), "clases": round(float(pf["clases"].mean()), 1) if len(pf) else None,
                     "plazas": round(float(pf["plazas"].mean()), 1) if len(pf) else None,
                     "reservas": round(float(mf["reservas"].mean()), 1) if len(mf) else None,
                     "ocup": ocup(yy) if len(yy) else None, "medidas": int(len(yy))})

    d = d.copy()
    ya = ya.copy()
    for t in (d, ya):
        t["semana"] = t["fecha"].dt.strftime("%G-W%V")
        t["mes"] = t["fecha"].dt.strftime("%Y-%m")
    semanas, meses = [], []
    for col, lista_ in (("semana", semanas), ("mes", meses)):
        for k, g in d.groupby(col):
            yy = ya[ya[col] == k]
            lista_.append({"p": k, "dias": int(g["fecha"].nunique()), "clases": int(len(g)), "plazas": int(g["plazas"].sum()),
                           "reservas": int(yy["reservas"].sum()) if len(yy) else None,
                           "ocup": ocup(yy) if len(yy) else None})
    return {"dias": dias, "semanas": semanas[-14:], "meses": meses[-6:], "ocup": ocup(ya) if len(ya) else None,
            "reservas": int(ya["reservas"].sum()) if len(ya) else None, "plazas_med": int(ya["plazas"].sum()) if len(ya) else None,
            "n_clases": int(len(d)), "n_dias": int(d["fecha"].nunique()), "sin_aforo": int(d["plazas"].isna().sum())}


def oferta_datos(snap, mapa, propios, lista_cadenas):
    """Oferta (clases y plazas) y ocupación por estudio y por cadena: por día de la semana, semana y mes."""
    u = clases_unicas(snap)
    ahora = snap["captured_at"].max()
    # a partir de cuándo está completa la agenda de cada estudio: primer día tras su primera planificación
    plan = analisis.leer("data/plan/*.csv")
    desde_plan = {}
    if len(plan):
        plan["captured_at"] = pd.to_datetime(plan["captured_at"])
        desde_plan = (plan.groupby("estudio")["captured_at"].min().dt.normalize() + pd.Timedelta(days=1)).to_dict()
    filas, _, _ = fichas(u.assign(centro_beatcore=u["zona"].where(u["zona"] != "Nacional", "")), mapa, propios)
    u["marca_n"] = [_norm(f[2]) for f in filas]
    u["nombre_n"] = [_norm(f[1]) for f in filas]
    u["propio"] = [int(f[3]) for f in filas]
    u["nombre"] = [f[1] for f in filas]
    # días válidos por estudio
    u["desde"] = u["estudio"].map(desde_plan)
    primera = u.groupby("estudio")["inicio_local"].transform("min").dt.normalize() + pd.Timedelta(days=1)
    u["parcial"] = u["desde"].isna()
    u["desde"] = u["desde"].fillna(primera)
    u = u[u["fecha"] >= u["desde"]]
    # el último día solo está completo si la última planificación (7 días) lo cubre entero: se descartan los días del borde
    if len(plan):
        hasta = plan["captured_at"].max().normalize() + pd.Timedelta(days=6)
        u = u[u["fecha"] <= hasta]
    unidades, cadenas = [], []
    nlista = [(c_, _norm(c_)) for c_ in lista_cadenas if _norm(c_)]
    for (est, zona), g in u.groupby(["estudio", "zona"]):
        a = _agrega(g, ahora)
        if a:
            mn, nn = g["marca_n"].iloc[0], g["nombre_n"].iloc[0]
            pert = [c_ for c_, n_ in nlista if _coincide(n_, mn, nn)]
            unidades.append({"estudio": g["nombre"].iloc[0], "estudio_captura": est, "zona": zona, "propio": int(g["propio"].iloc[0]),
                             "plat": g["plataforma"].iloc[0], "cadenas": pert, "parcial": bool(g["parcial"].all()), **a})
    for cad in lista_cadenas:
        n = _norm(cad)
        if not n:
            continue
        m = u[[_coincide(n, x, y) for x, y in zip(u["marca_n"], u["nombre_n"])]]
        a = _agrega(m, ahora)
        if a:
            cadenas.append({"cadena": cad, "estudios": int(m["estudio"].nunique()), "zonas": sorted(set(m["zona"])),
                            "parcial": bool(m["parcial"].all()), **a})
    return {"ahora": ahora.strftime("%Y-%m-%d %H:%M"), "unidades": unidades, "cadenas": cadenas}


def clave_clase(d):
    """Identificador de la clase estable entre capturas.

    En Mindbody el clase_id cambia de una captura a otra (los ids de la planificación no
    coinciden con los de la captura final), así que se usa estudio, sede, hora y nombre.
    En el resto de plataformas vale clase_id."""
    alt = (d["estudio"].astype(str) + "|" + d["sede"].astype(str) + "|"
           + d["inicio_local"].dt.strftime("%Y-%m-%d %H:%M") + "|" + d["clase"].astype(str))
    return alt.where(d["plataforma"] == "mindbody", d["clase_id"].astype(str))


def fichas(c, mapa, propios):
    """Por cada fila de c: (id catálogo, nombre, marca, propio, disciplina catálogo, centro), la tabla de
    estudios únicos y el índice de cada fila en esa tabla."""
    filas = []
    for e, z in zip(c["estudio"], c["centro_beatcore"]):
        r = mapa.get(f"{e}|{z}")
        filas.append((int(r["id"]) if r is not None else -1,
                      r["estudio"] if r is not None else e,
                      r["marca"] if r is not None else e,
                      bool(r["propio"]) if r is not None else e in propios,
                      r["disciplina"] if r is not None else "",
                      z))
    est_tab, est_idx, e_idx = [], {}, []
    for f in filas:
        k = f[:2] + (f[5],)
        if k not in est_idx:
            est_idx[k] = len(est_tab)
            est_tab.append({"id": f[0], "n": f[1], "m": f[2], "p": int(f[3]), "z": f[5]})
        e_idx.append(est_idx[k])
    return filas, est_tab, e_idx


def proximas(snap, mapa, propios, festivos):
    """Clases que aún no han empezado, con su última foto de reservas (planificación a 7 días)."""
    vacio = {"n": 0, "ahora": "", "dic": {}, "estudios": []}
    if snap.empty:
        return vacio
    ahora = snap["captured_at"].max()
    s = snap[snap["inicio_local"] > ahora].copy()
    s = s[s["centro_beatcore"].notna() & (s["centro_beatcore"].astype(str) != "")]
    if s.empty:
        return vacio
    s["kid"] = clave_clase(s)
    s["libres_n"] = pd.to_numeric(s["libres"], errors="coerce")
    maxlib = s.groupby(["plataforma", "estudio", "sede", "kid"])["libres_n"].max().rename("max_libres")
    s = s.sort_values("captured_at").groupby(["plataforma", "estudio", "sede", "kid"], as_index=False).tail(1)
    s = s.merge(maxlib, left_on=["plataforma", "estudio", "sede", "kid"], right_index=True, how="left")
    s = s[s["cancelada"].astype(str).str.lower() != "true"]
    s = s.sort_values(["inicio_local", "estudio"]).reset_index(drop=True)
    cap = pd.to_numeric(s["capacidad"], errors="coerce")
    occ = pd.to_numeric(s["ocupadas"], errors="coerce")
    lib = pd.to_numeric(s["libres"], errors="coerce")
    est = (s["plataforma"] == "mindbody") & ~(cap > 0) & (s["max_libres"] > 0) & (s["max_libres"] <= analisis.AFORO_MAX_PLAUSIBLE)
    fuente = pd.Series(np.where(cap > 0, 0, np.where(est, 1, np.nan)))
    cap = cap.where(cap > 0, s["max_libres"].where(est))
    occ = occ.where(occ.notna(), cap - lib)
    res = occ.where(s["plataforma"] != "bsport").clip(lower=0)
    res = res.where(cap.isna(), res.clip(upper=cap))
    lleno = s["llena"].astype(str).str.lower().map({"true": True, "false": False})
    lleno = lleno.where(lleno.notna(), (res / cap) >= 0.999).map({True: 1, False: 0})
    filas, est_tab, e_idx = fichas(s, mapa, propios)
    disc = [disciplina(k, f[4]) for k, f in zip(s["clase"], filas)]
    fecha = s["inicio_local"].dt.strftime("%Y-%m-%d")
    fest = [int(bool(f) and (f["zonas"] == "todas" or z in f["zonas"]))
            for f, z in zip((festivos.get(d) for d in fecha), s["centro_beatcore"])]
    d_centro, i_centro = indexar(s["centro_beatcore"])
    d_plat, i_plat = indexar(s["plataforma"])
    d_clase, i_clase = indexar(s["clase"])
    d_fecha, i_fecha = indexar(fecha)
    d_disc, i_disc = indexar(disc)
    d_ts, i_ts = indexar(s["captured_at"].dt.strftime("%d/%m %H:%M"))
    minutos = s["inicio_local"].dt.hour * 60 + s["inicio_local"].dt.minute
    return {
        "n": len(s), "ahora": ahora.strftime("%Y-%m-%d %H:%M"),
        "dic": {"centro": d_centro, "plat": d_plat, "clase": d_clase, "fecha": d_fecha, "disc": d_disc, "ts": d_ts},
        "estudios": est_tab,
        "e": e_idx, "c": i_centro, "p": i_plat, "k": i_clase, "f": i_fecha, "d": i_disc, "t": i_ts,
        "w": lista(s["inicio_local"].dt.weekday), "h": lista(minutos),
        "a": lista(cap), "r": lista(res), "l": lista(lleno),
        "af": lista(fuente), "fe": lista(pd.Series(fest)),
    }


def _norm(s):
    s = unicodedata.normalize("NFD", str(s)).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"\(.*?\)", " ", s)
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", s)).strip()


def _coincide(n, *textos):
    """La cadena n (normalizada) aparece como palabra en alguno de los textos. Las muy cortas, solo si es igual."""
    for t in textos:
        if not t:
            continue
        if t == n:
            return True
        if len(n) > 3 and re.search(r"\b" + re.escape(n) + r"\b", t):
            return True
    return False


def cadenas_datos(c, filas, cat_out):
    """Una fila por cadena de web/cadenas_lista.txt: inventario web + catálogo (zonas BeatCore) + ocupación medida."""
    if not os.path.exists("web/cadenas_lista.txt"):
        return {"filas": []}
    lista = [l.strip() for l in open("web/cadenas_lista.txt", encoding="utf-8") if l.strip()]
    inv = {}
    if os.path.exists("web/cadenas_inventario.json"):
        for f in json.load(open("web/cadenas_inventario.json", encoding="utf-8")).get("filas", []):
            inv[f["cadena"]] = f
    marca = [_norm(f[2]) for f in filas]
    nombre = [_norm(f[1]) for f in filas]
    cat_m = [_norm(x) for x in cat_out["marca"]]
    cat_e = [_norm(x) for x in cat_out["estudio"]]
    cdf = c[["estudio", "clase", "ocupacion", "llena_b", "aforo", "plataforma", "centro_beatcore"]].copy()
    cdf["marca"], cdf["nombre"] = marca, nombre

    def med(s):
        s = pd.to_numeric(s, errors="coerce").dropna()
        return round(float(s.median()), 2) if len(s) else None

    out = []
    for cad in lista:
        n = _norm(cad)
        if not n:
            continue
        i = inv.get(cad, {})
        # catálogo: estudios de la cadena a 1 km de algún BeatCore
        idx = [k for k in range(len(cat_out)) if _coincide(n, cat_m[k], cat_e[k])]
        sub = cat_out.iloc[idx]
        precio = {k: med(sub[k]) for k in ("clase_suelta", "cuatro_mes", "ocho_mes", "doce_mes", "ilimitada")}
        # si el catálogo no tiene el precio, se usa el que se lee en su web (etiquetado), indicando la fuente
        tip = i.get("precios_tipados", {}) or {}
        fuente_p = {}
        for k in precio:
            if precio[k] is not None:
                fuente_p[k] = "catálogo"
            elif tip.get(k) is not None:
                precio[k], fuente_p[k] = tip[k], "web"
        sw_cat = sorted({p for p in sub["plataforma"].dropna() if p and p != "No identificada"})
        # ocupación medida
        m = cdf[[_coincide(n, a, b) for a, b in zip(cdf["marca"], cdf["nombre"])]]
        mo = m[m["ocupacion"].notna()]
        centros = []
        for (est, zona, plat), g in m.groupby(["estudio", "centro_beatcore", "plataforma"]):
            go = g[g["ocupacion"].notna()]
            centros.append({"estudio": est, "zona": zona, "plat": plat, "clases": int(len(g)),
                            "ocup": round(float(go["ocupacion"].mean()), 3) if len(go) else None,
                            "llenas": round(float(g["llena_b"].mean()), 3) if g["llena_b"].notna().any() else None})
        tops = []
        for cl_, g in m.groupby("clase"):
            go = g[g["ocupacion"].notna()]
            tops.append({"clase": cl_, "n": int(len(g)),
                         "ocup": round(float(go["ocupacion"].mean()), 3) if len(go) else None})
        tops.sort(key=lambda x: -x["n"])
        out.append({
            "cadena": cad, "web": i.get("web", ""), "titulo": i.get("titulo", ""), "estado": i.get("estado", "sin web"),
            "software": i.get("software", []), "software_cat": sw_cat, "capturable": i.get("capturable", ""),
            "centros_web": i.get("centros_n"), "centros_ejemplos": i.get("centros_ejemplos", []),
            "precios_url": i.get("precios_url", ""), "precios_web": i.get("precios", []),
            "cat_estudios": int(len(sub)), "cat_zonas": sorted(set(sub["zona"])),
            "cat_con_ocup": int((sub["ocupacion_medida"] == "Sí").sum()) if len(sub) else 0,
            "precio": precio, "precio_fuente": fuente_p,
            "precios_items": [{"e": x["etiqueta"], "i": x["importe"], "t": x.get("tipo") or ""} for x in i.get("precios_items", [])][:30],
            "oferta_web": tip.get("oferta"), "matricula_web": tip.get("matricula"),
            "ocup": {"estudios": len(centros), "clases": int(len(m)),
                     "ocup": round(float(mo["ocupacion"].mean()), 3) if len(mo) else None,
                     "llenas": round(float(m["llena_b"].mean()), 3) if m["llena_b"].notna().any() else None,
                     "plazas": med(m["aforo"])},
            "centros": sorted(centros, key=lambda x: -x["clases"])[:40],
            "clases_top": tops[:15],
        })
    return {"filas": out}


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
    raw = analisis.cargar()
    # cadenas nacionales (fuera del radio de BeatCore): sin centro; solo se usan en la pestaña Cadenas
    sin_centro = raw["centro_beatcore"].isna() | (raw["centro_beatcore"].astype(str) == "")
    nac = raw[sin_centro].copy()
    nac["centro_beatcore"] = "Nacional"
    c_nac = analisis.preparar(nac, {}).reset_index(drop=True) if len(nac) else None
    c = analisis.preparar(raw[~sin_centro], {}).reset_index(drop=True)
    c["es_festivo"] = [
        int(bool(f) and (f["zonas"] == "todas" or z in f["zonas"]))
        for f, z in zip((festivos.get(d) for d in c["fecha"]), c["centro_beatcore"])
    ]
    if len(c):
        c = c[c["inicio_local"] >= c["inicio_local"].max().normalize() - pd.Timedelta(days=DIAS_MAX)]
    c = c.sort_values(["inicio_local", "estudio", "clase_id"]).reset_index(drop=True)

    cat, mapa = cargar_catalogo()
    filas, est_tab, e_idx = fichas(c, mapa, propios)

    disc = [disciplina(k, f[4]) for k, f in zip(c["clase"], filas)]
    snap = cargar_snapshots()
    cr, cl, hf, hf0 = curvas(c, snap)
    prox = proximas(snap, mapa, propios, festivos)

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
    # precios de BeatCore (web/precios_beatcore.json, dato aportado a mano por Fede)
    cat_out["doce_mes"] = np.nan
    if os.path.exists("web/precios_beatcore.json"):
        pb = json.load(open("web/precios_beatcore.json", encoding="utf-8"))
        for zona, pr in pb.items():
            if zona.startswith("_"):
                continue
            m = (cat_out["propio"] == 1) & (cat_out["zona"] == zona)
            for col in ("clase_suelta", "cuatro_mes", "ocho_mes", "doce_mes", "ilimitada"):
                if pr.get(col) is not None:
                    cat_out.loc[m, col] = float(pr[col])
            if m.any():
                cat_out.loc[m, "precios_publicados"] = "Sí"
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

    meta["proximas"] = prox["n"]
    if c_nac is not None and len(c_nac):
        filas_nac = [(-1, e, e, False, "", "Nacional") for e in c_nac["estudio"]]
        c_cad, filas_cad = pd.concat([c, c_nac], ignore_index=True), filas + filas_nac
    else:
        c_cad, filas_cad = c, filas
    cadenas = cadenas_datos(c_cad, filas_cad, cat_out)
    nombres_cadenas = [l.strip() for l in open("web/cadenas_lista.txt", encoding="utf-8") if l.strip()] \
        if os.path.exists("web/cadenas_lista.txt") else []
    oferta = oferta_datos(snap, mapa, propios, nombres_cadenas)
    tam = {n: escribir(n, o) for n, o in (("clases.json", clases), ("estudios.json", estudios), ("meta.json", meta),
                                          ("proximas.json", prox), ("cadenas.json", cadenas), ("oferta.json", oferta))}
    for f in ("index.html", "robots.txt"):
        if os.path.exists(os.path.join("web", f)):
            shutil.copy(os.path.join("web", f), os.path.join(OUT, f))
    print(f"{len(c)} clases; " + ", ".join(f"{n} {t / 1024:.0f} KB" for n, t in tam.items()))


if __name__ == "__main__":
    main()
