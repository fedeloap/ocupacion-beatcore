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

import glob
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
    # correcciones de precio dictadas por Fede (web/precios_ajustes.json): pisan lo leído en el catálogo
    if os.path.exists("web/precios_ajustes.json"):
        aj = json.load(open("web/precios_ajustes.json", encoding="utf-8"))
        for k, v in aj.items():
            if k.startswith("_"):
                continue
            for col, val in v.items():
                if col.startswith("_"):
                    continue
                cat.loc[cat["id"] == int(k), col] = np.nan if val is None else val
    mapa = {}
    for _, r in cat.iterrows():
        if isinstance(r["captura"], str):
            for k in r["captura"].split(";"):
                mapa.setdefault(k.strip(), r)
    return cat, mapa


def excluidos():
    """Estudios que no se quieren en el dashboard (web/excluidos.json)."""
    try:
        return set(json.load(open("web/excluidos.json", encoding="utf-8")).get("estudios", []))
    except Exception:
        return set()


EXTRAS = []       # sesiones de servicios que no son clases (recovery, sauna, open gym): se miden aparte


def fuera_de_espana(df):
    """Centros (o sedes) fuera de España: no interesan y no entran en ningún dato de la web (web/ubicaciones.json)."""
    _ubicacion("", "Nacional")
    ub = _UBIC or {}
    m = df["estudio"].isin({e for e, v in ub.items() if e != "_sedes" and v.get("provincia") == "Fuera de España"})
    if "sede" in df.columns:
        sd = df["sede"].astype(str)
        for e, mp in ub.get("_sedes", {}).items():
            fuera = {k for k, v in mp.items() if v.get("provincia") == "Fuera de España"}
            if fuera:
                m = m | ((df["estudio"] == e) & sd.isin(fuera))
    return m


def es_extra(df):
    """Sesiones que no cuentan como clase en medias, totales ni facturación (web/servicios_extra.json)."""
    try:
        cfg = json.load(open("web/servicios_extra.json", encoding="utf-8"))
    except Exception:
        return pd.Series(False, index=df.index)
    est = df["estudio"].astype(str).str.lower()
    de_estudio = pd.Series(False, index=df.index)
    for t in cfg.get("estudios_contienen", []):
        de_estudio |= est.str.contains(t.lower(), regex=False)
    return de_estudio & df["clase"].astype(str).str.contains(cfg.get("patron", "$^"), case=False, regex=True)


def cargar_snapshots():
    partes = [analisis.leer(p) for p in ("data/*.csv", "data/curva/*.csv", "data/plan/*.csv")]
    s = pd.concat([p for p in partes if len(p)], ignore_index=True)
    s = s[~s["estudio"].isin(excluidos())]
    s["captured_at"] = pd.to_datetime(s["captured_at"])
    s["sede"] = s["sede"].fillna("").astype(str)
    s["clase_id"] = s["clase_id"].astype(str)
    s = s.drop_duplicates(KEY + ["captured_at"])
    s["inicio_local"] = pd.to_datetime(s["inicio_local"])
    s = s[~fuera_de_espana(s)]
    m = es_extra(s)
    EXTRAS.clear()
    EXTRAS.append(s[m])
    s = s[~m]
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


def _agrega(d, ahora, d_all=None):
    """Clases, plazas y ocupación (reservas/plazas) por día de la semana, semana y mes."""
    if d.empty:
        return None
    # clases/plazas se cuentan en días completos (d); % reservado y reservas, en todas las clases ya dadas (d_all)
    src = d_all if d_all is not None and len(d_all) else d
    ya = src[(src["inicio_local"] <= ahora) & src["reservas"].notna() & (src["plazas"] > 0)]

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

    # para la facturación: clases en una semana tipo y reservas medias por clase ya dada (bsport no publica reservas)
    ds_c = [x["clases"] for x in dias if x["clases"] is not None]
    n_fechas = int(d["fecha"].nunique())
    clases_sem = sum(ds_c) if n_fechas >= 7 else len(d) / n_fechas * 7
    yr = src[(src["inicio_local"] <= ahora) & src["reservas"].notna()]
    res_clase = round(float(yr["reservas"].mean()), 2) if len(yr) else None

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
    # celdas día de la semana x hora: permiten filtrar por días y franja horaria en el navegador
    d["dow"], d["hora"] = d["fecha"].dt.dayofweek, d["inicio_local"].dt.hour
    ya["dow"], ya["hora"] = ya["fecha"].dt.dayofweek, ya["inicio_local"].dt.hour
    cel = d.groupby(["dow", "hora"]).agg(c=("kid", "size"), p=("plazas", "sum"))
    cel = cel.join(ya.groupby(["dow", "hora"]).agg(r=("reservas", "sum"), pm=("plazas", "sum")), how="left").fillna(0)
    celdas = [{"d": int(i[0]), "h": int(i[1]), "c": int(r["c"]), "p": int(r["p"]), "r": int(r["r"]), "pm": int(r["pm"])}
              for i, r in cel.iterrows()]
    top = []
    for nombre, g in d.groupby("clase"):
        yy = ya[ya["clase"] == nombre]
        top.append({"clase": nombre, "c": int(len(g)), "p": int(g["plazas"].sum()), "o": ocup(yy) if len(yy) else None})
    top.sort(key=lambda x: -x["c"])
    return {"dias": dias, "semanas": semanas[-14:], "meses": meses[-6:], "celdas": celdas, "top": top[:15],
            "ocup": ocup(ya) if len(ya) else None,
            "reservas": int(ya["reservas"].sum()) if len(ya) else None, "plazas_med": int(ya["plazas"].sum()) if len(ya) else None,
            "n_clases": int(len(d)), "n_dias": int(d["fecha"].nunique()), "sin_aforo": int(d["plazas"].isna().sum()),
            "clases_sem": round(float(clases_sem), 1), "res_clase": res_clase, "n_res": int(len(yr))}


DESCUENTO_CUOTA = 0.10     # cuotas limitadas o más altas que no pagan por sesión (decisión de Fede, 13/10/2026)
SEMANAS_MES = 52 / 12


def _num(v):
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    return None if np.isnan(v) or v <= 0 else v


SESIONES_ILIMITADA = 10        # sesiones al mes que se suponen a una cuota ilimitada (decisión de Fede, 14/10/2026)
DESCUENTO_SUELTA = 0.25        # la clase suelta se rebaja un 25 % (decisión de Fede, 14/10/2026)


def facturacion(a, tarifas, origen):
    """Facturación mensual estimada de un centro: € por sesión x reservas al mes
    (clases de una semana tipo x 52/12 x reservas medias por clase).
    € por sesión, por orden: cuota de 8/mes menos un 10 %, entre 8; cuota de 4/mes menos un 10 %, entre 4;
    clase suelta menos un 25 %; ilimitada entre 10. Sin reservas conocidas (bsport) no hay estimación."""
    ocho, cuatro, ilim, suelta = [_num(x) for x in tarifas]
    if ocho:
        ps, base, cuota = ocho * (1 - DESCUENTO_CUOTA) / 8, "8/mes", ocho
    elif cuatro:
        ps, base, cuota = cuatro * (1 - DESCUENTO_CUOTA) / 4, "4/mes", cuatro
    elif suelta:
        ps, base, cuota = suelta * (1 - DESCUENTO_SUELTA), "suelta", None
    elif ilim:
        ps, base, cuota = ilim / SESIONES_ILIMITADA, "ilimitada", None
    else:
        ps, base, cuota = None, "", None
    cl_mes = a["clases_sem"] * SEMANAS_MES
    res_mes = cl_mes * a["res_clase"] if a["res_clase"] is not None else None
    return {"cuota": cuota, "base": base, "origen": origen if ps else "", "precio_ses": round(ps, 2) if ps else None,
            "clases_mes": round(cl_mes), "res_clase": a["res_clase"],
            "res_mes": round(res_mes) if res_mes is not None else None,
            "fact_mes": round(ps * res_mes) if ps and res_mes is not None else None}


_ZONA_UBIC = {"Chamberí": ("Madrid", "Madrid"), "Salamanca": ("Madrid", "Madrid"), "Diagonal": ("Barcelona", "Barcelona"),
              "Valencia": ("Valencia", "Valencia")}
_UBIC = None


def _ubic_sedes():
    _ubicacion("", "Nacional")
    return (_UBIC or {}).get("_sedes", {})


def _ubicacion(estudio, zona):
    """(ciudad, provincia) de un centro: por su zona BeatCore o por web/ubicaciones.json (python ubicaciones.py)."""
    global _UBIC
    if zona in _ZONA_UBIC:
        return _ZONA_UBIC[zona]
    if _UBIC is None:
        try:
            _UBIC = json.load(open("web/ubicaciones.json", encoding="utf-8"))
        except Exception:
            _UBIC = {}
    u = _UBIC.get(estudio) or {}
    return (u.get("ciudad", ""), u.get("provincia", ""))


def datos_fecha(g, g_all, ahora, idx, meses, ukey):
    """Datos de un centro en columnas para calcular cualquier rango de fechas en el navegador.
    Diarios (dd, dc, dp, dr, dm, dx), de TODO el histórico, en oferta.json: clases y plazas de los días completos (g);
    reservas y plazas medidas de todas las clases ya dadas (g_all). Por hora y por clase, agrupados por mes, en
    meses[mes][ukey] (oferta_h_AAAA-MM.json). 'idx': fecha -> posición en oferta.json."""
    vacio = {k: [] for k in ("dd", "dc", "dp", "dr", "dm", "dx")}
    d = (g_all if g_all is not None and len(g_all) else g).copy()
    if d.empty:
        return vacio
    dentro = d["kid"].isin(set(g["kid"])).astype(int)
    dada = d["inicio_local"] <= ahora
    ok = dada & d["reservas"].notna() & (d["plazas"] > 0)
    d["_c"] = dentro
    d["_p"] = d["plazas"].fillna(0) * dentro
    d["_r"], d["_m"] = d["reservas"].where(ok, 0), d["plazas"].where(ok, 0)
    d["_x"] = d["reservas"].where(dada & d["reservas"].notna(), 0)
    agg = dict(c=("_c", "sum"), p=("_p", "sum"), r=("_r", "sum"), m=("_m", "sum"), x=("_x", "sum"))

    def util(t):
        return t[(t["c"] > 0) | (t["r"] > 0) | (t["x"] > 0)]

    dia = util(d.groupby("fecha").agg(**agg).reset_index())
    out = {"dd": [idx.setdefault(f.strftime("%Y-%m-%d"), len(idx)) for f in dia["fecha"]],
           "dc": [int(v) for v in dia["c"]], "dp": [int(round(v)) for v in dia["p"]], "dr": [int(round(v)) for v in dia["r"]],
           "dm": [int(round(v)) for v in dia["m"]], "dx": [int(round(v)) for v in dia["x"]]}
    # por hora y por clase, en el fichero de cada mes
    d["hora"] = d["inicio_local"].dt.hour
    d["mes"] = d["fecha"].dt.strftime("%Y-%m")
    for mes, dm_ in d.groupby("mes"):
        ent = meses.setdefault(mes, {"fechas": {}, "nombres": {}, "u": {}})
        fi, ni = ent["fechas"], ent["nombres"]
        h = util(dm_.groupby(["fecha", "hora"]).agg(**agg).reset_index())
        k = util(dm_.groupby(["fecha", "clase"]).agg(**agg).reset_index())
        ent["u"][ukey] = {
            "hd": [fi.setdefault(f.strftime("%Y-%m-%d"), len(fi)) for f in h["fecha"]], "hh": [int(v) for v in h["hora"]],
            "hc": [int(v) for v in h["c"]], "hp": [int(round(v)) for v in h["p"]], "hr": [int(round(v)) for v in h["r"]],
            "hm": [int(round(v)) for v in h["m"]], "hx": [int(round(v)) for v in h["x"]],
            "kd": [fi.setdefault(f.strftime("%Y-%m-%d"), len(fi)) for f in k["fecha"]],
            "kn": [ni.setdefault(str(n), len(ni)) for n in k["clase"]], "kc": [int(v) for v in k["c"]],
            "kp": [int(round(v)) for v in k["p"]], "kr": [int(round(v)) for v in k["r"]], "km": [int(round(v)) for v in k["m"]]}
    return out


def facturacion_meses(g, a, ahora, ps, g_all=None):
    """Reservas y facturación por mes natural de un centro.

    'obs': lo ya capturado (clases dadas con reservas conocidas; el mes empieza a contar el día que se empezó a capturar).
    'est': mes completo estimado. Cada día cuenta con lo observado si ya pasó; si no, con las clases programadas (o, sin
    planificación, las de su día de la semana en una semana tipo) x reservas medias por clase. Va afinándose cada día."""
    rc = a["res_clase"]
    if rc is None:
        return []
    hoy = ahora.normalize()
    src = g_all if g_all is not None and len(g_all) else g
    dadas = src[(src["inicio_local"] <= ahora) & src["reservas"].notna()]
    obs_f = dadas.groupby("fecha")["reservas"].sum()
    n_f = g.groupby("fecha").size()
    cl_dow = {x["d"]: (x["clases"] or 0) for x in a["dias"]}
    out = []
    meses = sorted({f.strftime("%Y-%m") for f in g["fecha"].unique()})
    for ym in meses:
        ini = pd.Timestamp(ym + "-01")
        fin = ini + pd.offsets.MonthEnd(0)
        res_obs, res_est, dias_obs = 0.0, 0.0, 0
        desde = None
        for d in pd.date_range(ini, fin):
            previstas = n_f.get(d, cl_dow.get(d.dayofweek, 0)) * rc
            if d in obs_f.index and d < hoy:
                v = float(obs_f[d])
                res_obs += v
                res_est += v
                dias_obs += 1
                desde = desde or d
            elif d == hoy:
                v = float(obs_f.get(d, 0.0))
                res_obs += v
                res_est += max(v, previstas)
                if v > 0:
                    dias_obs += 1
                    desde = desde or d
            else:
                res_est += previstas
        out.append({"p": ym, "dias_obs": dias_obs, "dias_mes": int(fin.day),
                    "desde": desde.strftime("%Y-%m-%d") if desde is not None else None,
                    "res_obs": round(res_obs), "res_est": round(res_est),
                    "fact_obs": round(res_obs * ps) if ps else None, "fact_est": round(res_est * ps) if ps else None})
    return out


def oferta_datos(snap, mapa, propios, lista_cadenas, precio_cad=None, pb=None):
    """Oferta (clases y plazas), ocupación y facturación estimada por estudio y por cadena."""
    precio_cad, pb = precio_cad or {}, pb or {}
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
    u["marca"] = [f[2] for f in filas]
    u_all = u.copy()          # todas las clases (también de días no completos): para % reservado y reservas
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
    # servicios que no son clase (recovery, sauna, open gym): sesiones, plazas y ocupación, fuera de totales y medias
    extras_u = {}
    if EXTRAS and len(EXTRAS[0]):
        ue = clases_unicas(EXTRAS[0])
        ue["desde"] = ue["estudio"].map(desde_plan)
        ue["desde"] = ue["desde"].fillna(ue.groupby("estudio")["inicio_local"].transform("min").dt.normalize() + pd.Timedelta(days=1))
        ue = ue[ue["fecha"] >= ue["desde"]]
        if len(plan):
            ue = ue[ue["fecha"] <= plan["captured_at"].max().normalize() + pd.Timedelta(days=6)]
        for (est_e, zona_e), ge in ue.groupby(["estudio", "zona"]):
            n_d = max(1, int(ge["fecha"].nunique()))
            lista_s = []
            for nom, gs in ge.groupby("clase"):
                ya_s = gs[(gs["inicio_local"] <= ahora) & gs["reservas"].notna() & (gs["plazas"] > 0)]
                lista_s.append({"s": nom, "n": int(len(gs)), "sem": round(len(gs) / n_d * 7, 1),
                                "pl": round(float(gs["plazas"].sum()) / n_d * 7), "pp": float(gs["plazas"].mean()) if gs["plazas"].notna().any() else None,
                                "o": round(float(ya_s["reservas"].sum() / ya_s["plazas"].sum()), 3) if len(ya_s) else None,
                                "m": int(len(ya_s))})
            lista_s.sort(key=lambda x: -x["n"])
            extras_u[(est_e, zona_e)] = lista_s
    unidades, cadenas = [], []
    nlista = [(c_, _norm(c_)) for c_ in lista_cadenas if _norm(c_)]
    # estudios cuya agenda mezcla ciudades: un centro por ciudad (web/ubicaciones.json -> _sedes)
    fechas_idx, nombres_idx, clases_out = {}, {}, {}
    sedes_ub = _ubic_sedes()
    def _asigna_pv(df):
        df["pv"] = ""
        if sedes_ub:
            for est_s, mp in sedes_ub.items():
                m_ = df["estudio"] == est_s
                if m_.any():
                    base = _ubicacion(est_s, "Nacional")
                    df.loc[m_, "pv"] = [
                        "|".join((mp.get(str(sd)) or {}).get("ciudad", base[0]) and
                                 [(mp.get(str(sd)) or {}).get("ciudad", base[0]), (mp.get(str(sd)) or {}).get("provincia", base[1])]
                                 or [base[0], base[1]])
                        for sd in df.loc[m_, "sede"]]
    _asigna_pv(u)
    _asigna_pv(u_all)
    ga = {k: v for k, v in u_all.groupby(["estudio", "zona", "pv"])}
    meses_h = {}
    n_pv = u.groupby("estudio")["pv"].nunique()
    for (est, zona, pv), g in u.groupby(["estudio", "zona", "pv"]):
        g_all = ga.get((est, zona, pv), g)
        a = _agrega(g, ahora, g_all)
        if a:
            mn, nn = g["marca_n"].iloc[0], g["nombre_n"].iloc[0]
            pert = [c_ for c_, n_ in nlista if _coincide(n_, mn, nn)]
            r = mapa.get(f"{est}|{'' if zona == 'Nacional' else zona}")
            propio_u = int(g["propio"].iloc[0])
            tar = (None, None, None, None)
            origen = ""
            if propio_u and zona in pb:
                tar = tuple(pb[zona].get(k) for k in ("ocho_mes", "cuatro_mes", "ilimitada", "clase_suelta"))
                origen = "precio publicado"
            elif r is not None and any(_num(r[k]) for k in ("ocho_mes", "cuatro_mes", "ilimitada", "clase_suelta")):
                tar = tuple(r[k] for k in ("ocho_mes", "cuatro_mes", "ilimitada", "clase_suelta"))
                origen = "precio del estudio"
            else:
                for c_ in pert:
                    if c_ in precio_cad and any(_num(x) for x in precio_cad[c_]):
                        tar = precio_cad[c_]
                        origen = "mediana de la cadena " + c_
                        break
            fact = facturacion(a, tar, origen)
            ub = tuple(pv.split("|")) if pv else _ubicacion(est, zona)
            nombre_u = g["nombre"].iloc[0]
            if pv and n_pv.get(est, 1) > 1:
                nombre_u += f" ({ub[0] or 'sin ubicar'})"
            ukey = f"{est}|{zona}|{pv}"
            a_u = {k: v for k, v in a.items() if k not in ("celdas", "top")}
            unidades.append({**datos_fecha(g, g_all, ahora, fechas_idx, meses_h, ukey), "ukey": ukey, "prov": ub[1], "ciu": ub[0], "fact": fact, "marca": g["marca"].iloc[0], "extras": extras_u.get((est, zona), []),
                             "fmeses": facturacion_meses(g, a, ahora, fact["precio_ses"], g_all), "estudio": nombre_u, "estudio_captura": est, "zona": zona, "propio": int(g["propio"].iloc[0]),
                             "plat": g["plataforma"].iloc[0], "cadenas": pert, "parcial": bool(g["parcial"].all()), **a_u})
    for cad in lista_cadenas:
        n = _norm(cad)
        if not n:
            continue
        m = u[[_coincide(n, x, y) for x, y in zip(u["marca_n"], u["nombre_n"])]]
        m_all = u_all[[_coincide(n, x, y) for x, y in zip(u_all["marca_n"], u_all["nombre_n"])]]
        a = _agrega(m, ahora, m_all)
        if a:
            a = {k: v for k, v in a.items() if k not in ("celdas", "top")}
            fu = [u["fact"] for u in unidades if cad in u["cadenas"]]
            con = [f for f in fu if f["fact_mes"] is not None]
            fact = {"centros": len(fu), "con_fact": len(con),
                    "fact_mes": sum(f["fact_mes"] for f in con) if con else None,
                    "res_mes": sum(f["res_mes"] for f in con) if con else None,
                    "precio_ses": round(float(np.mean([f["precio_ses"] for f in con])), 2) if con else None}
            cadenas.append({"cadena": cad, "estudios": int(m["estudio"].nunique()), "zonas": sorted(set(m["zona"])),
                            "parcial": bool(m["parcial"].all()), "fact": fact, **a})
    fechas = [f for f, _ in sorted(fechas_idx.items(), key=lambda kv: kv[1])]
    ficheros = {}
    for mes, ent in meses_h.items():
        ficheros[f"oferta_h_{mes}.json"] = {
            "mes": mes, "fechas": [f for f, _ in sorted(ent["fechas"].items(), key=lambda kv: kv[1])],
            "nombres": [n for n, _ in sorted(ent["nombres"].items(), key=lambda kv: kv[1])], "u": ent["u"]}
    return {"ahora": ahora.strftime("%Y-%m-%d %H:%M"), "fechas": fechas, "meses_h": sorted(meses_h), "unidades": unidades,
            "cadenas": cadenas, "_ficheros": ficheros}


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
    raw = raw[~raw["estudio"].isin(excluidos())]
    raw = raw[~es_extra(raw)]
    raw = raw[~fuera_de_espana(raw)]
    # cadenas nacionales (fuera del radio de BeatCore): sin centro; solo se usan en la pestaña Cadenas
    sin_centro = raw["centro_beatcore"].isna() | (raw["centro_beatcore"].astype(str) == "")
    nac = raw[sin_centro].copy()
    nac["centro_beatcore"] = "Nacional"
    c_nac = analisis.preparar(nac, {}).reset_index(drop=True) if len(nac) else None
    c = analisis.preparar(raw[~sin_centro], {}).reset_index(drop=True)

    def marca_festivo(df):
        df["es_festivo"] = [int(bool(f) and (f["zonas"] == "todas" or z in f["zonas"]))
                            for f, z in zip((festivos.get(d) for d in df["fecha"]), df["centro_beatcore"])]
        return df
    c = marca_festivo(c)
    if c_nac is not None and len(c_nac):
        c_nac = marca_festivo(c_nac)
    c_zona = c                       # solo zonas BeatCore: es la base de la pestaña Cadenas
    # toda la historia, y también las cadenas nacionales (centro "Nacional": solo salen al elegir ese centro)
    c = pd.concat([c_zona, c_nac], ignore_index=True) if c_nac is not None and len(c_nac) else c_zona
    c = c.sort_values(["inicio_local", "estudio", "clase_id"]).reset_index(drop=True)

    cat, mapa = cargar_catalogo()
    filas, est_tab, e_idx = fichas(c, mapa, propios)
    filas_zona = fichas(c_zona, mapa, propios)[0]

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

    arr = {
        "e": e_idx, "c": i_centro, "p": i_plat, "k": i_clase, "f": i_fecha, "d": i_disc,
        "w": lista(c["inicio_local"].dt.weekday),
        "h": lista(minutos),
        "du": lista(c["duracion_min"]),
        "a": lista(c["aforo"]),
        "r": lista(c["reservas"]),
        "l": lista(llena),
        "af": lista(fuente),
        "fe": lista(c["es_festivo"]),
        "hf": lista(hf, 1), "hf0": lista(hf0),
    }
    # un fichero por mes (clases_AAAA-MM.json); clases.json solo lleva los diccionarios y el índice de meses
    mes_c = c["fecha"].astype(str).str.slice(0, 7).values
    ficheros_c, meses_idx = {}, []
    for mes in sorted(set(mes_c)):
        ix = [i for i in range(len(c)) if mes_c[i] == mes]
        f = {k: [v[i] for i in ix] for k, v in arr.items()}
        f["cr"] = [[x[i] for i in ix] for x in cr]
        f["cl"] = [[x[i] for i in ix] for x in cl]
        f["mes"], f["n"] = mes, len(ix)
        ficheros_c[f"clases_{mes}.json"] = f
        fch = c["fecha"].iloc[ix]
        meses_idx.append({"mes": mes, "n": len(ix), "desde": str(fch.min()), "hasta": str(fch.max())})
    clases = {
        "n": len(c), "checkpoints": CHECKPOINTS,
        "dic": {"centro": d_centro, "plat": d_plat, "clase": d_clase, "fecha": d_fecha, "disc": d_disc},
        "estudios": est_tab, "meses": meses_idx,
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
        c_cad, filas_cad = pd.concat([c_zona, c_nac], ignore_index=True), filas_zona + filas_nac
    else:
        c_cad, filas_cad = c_zona, filas_zona
    cadenas = cadenas_datos(c_cad, filas_cad, cat_out)
    nombres_cadenas = [l.strip() for l in open("web/cadenas_lista.txt", encoding="utf-8") if l.strip()] \
        if os.path.exists("web/cadenas_lista.txt") else []
    precio_cad = {f["cadena"]: tuple(f["precio"].get(k) for k in ("ocho_mes", "cuatro_mes", "ilimitada", "clase_suelta"))
                  for f in cadenas["filas"]}
    pb = {k: v for k, v in json.load(open("web/precios_beatcore.json", encoding="utf-8")).items() if not k.startswith("_")}         if os.path.exists("web/precios_beatcore.json") else {}
    oferta = oferta_datos(snap, mapa, propios, nombres_cadenas, precio_cad, pb)
    ficheros_h = oferta.pop("_ficheros")
    for viejo in (glob.glob(os.path.join(OUT, "data", "oferta_h_*.json")) + glob.glob(os.path.join(OUT, "data", "oferta_clases.json"))
                  + glob.glob(os.path.join(OUT, "data", "clases_2*.json"))):
        os.remove(viejo)
    tam = {n: escribir(n, o) for n, o in (("clases.json", clases), ("estudios.json", estudios), ("meta.json", meta),
                                          ("proximas.json", prox), ("cadenas.json", cadenas), ("oferta.json", oferta))}
    tam.update({n: escribir(n, o) for n, o in ficheros_h.items()})
    tam.update({n: escribir(n, o) for n, o in ficheros_c.items()})
    for f in ("index.html", "robots.txt"):
        if os.path.exists(os.path.join("web", f)):
            shutil.copy(os.path.join("web", f), os.path.join(OUT, f))
    print(f"{len(c)} clases; " + ", ".join(f"{n} {t / 1024:.0f} KB" for n, t in tam.items()))


if __name__ == "__main__":
    main()
