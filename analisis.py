"""
Análisis de ocupación de la competencia BeatCore.

Lee data/*.csv (ocupación final) y data/plan/*.csv (planificación) y genera:
  reports/clases.csv     una fila por clase con su ocupación final
  reports/estudios.csv   resumen por estudio
  reports/informe.html   informe para publicar como artifact

Reglas:
  - Para cada clase se usa la última captura hecha antes de su inicio (+5 min de margen).
  - Se excluyen clases canceladas, estudios sin centro asignado y los festivos de festivos.json.
  - Aforo: el publicado; en Mindbody, si no se publica, se estima como el máximo de plazas
    libres visto para esa clase en cualquier captura (cota inferior del aforo real).
  - bsport solo dice si la clase se llenó: entra en "% clases llenas", no en "% ocupación".
"""

import glob
import html
import json
import os
from datetime import datetime

import pandas as pd

MARGEN_MIN = 5
AFORO_MAX_PLAUSIBLE = 60
DIAS = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
FRANJAS = [(6, 10, "6 a 10 h"), (10, 14, "10 a 14 h"), (14, 17, "14 a 17 h"), (17, 21, "17 a 21 h"), (21, 25, "21 h o más")]
ZONAS = ["Chamberí", "Salamanca", "Diagonal", "Valencia"]


def corregir_aimharder(d):
    """AimHarder: los boxes que no publican las reservas devolvían ocupation=0 en todas las clases y se guardaban como
    0 reservas. Si un estudio de AimHarder nunca ha tenido reservas > 0 en lo capturado, sus reservas son desconocidas."""
    if d.empty or "plataforma" not in d.columns:
        return d
    am = d["plataforma"] == "aimharder"
    if not am.any():
        return d
    occ = pd.to_numeric(d["ocupadas"], errors="coerce")
    maxocc = occ.where(am).groupby(d["estudio"]).transform("max")
    mala = am & (maxocc.fillna(0) <= 0)
    for col in ("ocupadas", "libres", "llena"):
        if col in d.columns:
            d[col] = d[col].astype("object")
            d.loc[mala, col] = float("nan") if col != "llena" else ""
    return d


def leer(patron):
    fs = [f for f in sorted(glob.glob(patron)) if os.path.getsize(f) > 0]
    if not fs:
        return pd.DataFrame()
    d = pd.concat([pd.read_csv(f) for f in fs], ignore_index=True)
    d = corregir_aimharder(d)
    # estudios renombrados: el histórico conserva el nombre antiguo (web/alias_estudios.json)
    if os.path.exists("web/alias_estudios.json"):
        import json
        alias = {k: v for k, v in json.load(open("web/alias_estudios.json", encoding="utf-8")).items() if not k.startswith("_")}
        for col in ("estudio", "sede"):
            if col in d.columns:
                d[col] = d[col].replace(alias)
    return d


def franja(h):
    for a, b, n in FRANJAS:
        if a <= h < b:
            return n
    return FRANJAS[0][2]


def cargar():
    fin = leer("data/*.csv")
    plan = leer("data/plan/*.csv")
    curva = leer("data/curva/*.csv")
    todo = pd.concat([fin, plan, curva], ignore_index=True)
    for d in (fin, todo):
        d["captured_at"] = pd.to_datetime(d["captured_at"])
        d["inicio_local"] = pd.to_datetime(d["inicio_local"])
    key = ["plataforma", "estudio", "sede", "clase_id"]
    for d in (fin, todo):
        d["sede"] = d["sede"].fillna("").astype(str)
        d["clase_id"] = d["clase_id"].astype(str)

    # aforo estimado (Mindbody): máximo de plazas libres visto en cualquier captura
    libres = pd.to_numeric(todo["libres"], errors="coerce")
    todo["libres_n"] = libres
    # En Mindbody el clase_id cambia entre capturas (planificación, curva y final): la clase se identifica por
    # estudio, sede, hora y nombre. Así el máximo de plazas libres (aforo estimado) sale de todas sus fotos y no solo de la final.
    for d in (fin, todo):
        alt = (d["estudio"].astype(str) + "|" + d["sede"].astype(str) + "|"
               + d["inicio_local"].dt.strftime("%Y-%m-%d %H:%M") + "|" + d["clase"].astype(str))
        d["_k"] = alt.where(d["plataforma"] == "mindbody", d["clase_id"])
    key_est = ["plataforma", "estudio", "sede", "_k"]
    max_libres = todo.groupby(key_est)["libres_n"].max().rename("max_libres")

    fin = fin[fin["captured_at"] <= fin["inicio_local"] + pd.Timedelta(minutes=MARGEN_MIN)]
    fin = fin.sort_values("captured_at").groupby(key_est, as_index=False).tail(1)     # una fila por clase (en Mindbody, aunque cambie su id)
    fin = fin.merge(max_libres, left_on=key_est, right_index=True, how="left")
    # Clases ya dadas cuya foto final falló (la ventana de captura no las cogió): se usa su última foto de las
    # 8 h previas a empezar (la curva guarda las próximas 6 h). Así el recuento coincide con la pestaña Oferta.
    if len(curva):
        ahora = todo["captured_at"].max()
        c2 = todo[(todo["captured_at"] <= todo["inicio_local"] + pd.Timedelta(minutes=MARGEN_MIN))
                  & (todo["captured_at"] >= todo["inicio_local"] - pd.Timedelta(hours=8))
                  & (todo["inicio_local"] <= ahora)]
        c2 = c2.sort_values("captured_at").groupby(key_est, as_index=False).tail(1)
        c2 = c2[~c2.set_index(key_est).index.isin(fin.set_index(key_est).index)]
        c2 = c2.drop(columns=["libres_n"], errors="ignore").merge(max_libres, left_on=key_est, right_index=True, how="left")
        fin = pd.concat([fin, c2[fin.columns.intersection(c2.columns)]], ignore_index=True)
        # Clases ya pasadas que dejaron de salir en la agenda estando a 0 reservas (la plataforma oculta las vacías): se dieron
        # sin nadie apuntado (Fede, 17/10/2026). Si tenían reservas al desaparecer, se tratan como canceladas y no cuentan.
        c3 = todo[(todo["inicio_local"] <= ahora) & (todo["captured_at"] < todo["inicio_local"])]
        c3 = c3.sort_values("captured_at").groupby(key_est, as_index=False).tail(1)
        c3 = c3[(pd.to_numeric(c3["ocupadas"], errors="coerce") == 0) & (c3["cancelada"].astype(str).str.lower() != "true")]
        c3 = c3[~c3.set_index(key_est).index.isin(fin.set_index(key_est).index)]
        c3 = c3.drop(columns=["libres_n"], errors="ignore").merge(max_libres, left_on=key_est, right_index=True, how="left")
        fin = pd.concat([fin, c3[fin.columns.intersection(c3.columns)]], ignore_index=True)
    return fin.drop(columns=["_k"])


def preparar(c, festivos):
    c = c[c["centro_beatcore"].notna() & (c["centro_beatcore"].astype(str) != "")].copy()
    c = c[c["cancelada"].astype(str).str.lower() != "true"]
    c["fecha"] = c["inicio_local"].dt.strftime("%Y-%m-%d")

    def es_festivo(r):
        f = festivos.get(r["fecha"])
        return bool(f) and (f["zonas"] == "todas" or r["centro_beatcore"] in f["zonas"])

    c["festivo"] = c.apply(es_festivo, axis=1)
    c = c[~c["festivo"]]
    cap = pd.to_numeric(c["capacidad"], errors="coerce")
    occ = pd.to_numeric(c["ocupadas"], errors="coerce")
    lib = pd.to_numeric(c["libres"], errors="coerce")
    c["aforo_fuente"] = ""
    c.loc[cap > 0, "aforo_fuente"] = "publicado"
    est = (c["plataforma"] == "mindbody") & ~(cap > 0) & (c["max_libres"] > 0) & (c["max_libres"] <= AFORO_MAX_PLAUSIBLE)
    cap = cap.where(cap > 0, c["max_libres"].where(est))
    # el aforo estimado de cada clase es un mínimo (solo vemos las plazas libres que había en sus fotos): una misma clase
    # de un mismo estudio y sede comparte sala, así que se toma el máximo visto en todas sus sesiones
    cap_g = cap.groupby([c["estudio"], c["sede"], c["clase"]]).transform("max")
    cap = cap.where(~est, cap_g.where(cap_g > cap.fillna(0), cap))
    c.loc[est, "aforo_fuente"] = "estimado"
    occ = occ.where(occ.notna(), cap - lib)
    c["aforo"] = cap
    c["reservas"] = occ.where(c["plataforma"] != "bsport")
    c["ocupacion"] = (c["reservas"] / c["aforo"]).clip(0, 1)
    llena = c["llena"].astype(str).str.lower().map({"true": True, "false": False})
    c["llena_b"] = llena.where(llena.notna(), c["ocupacion"] >= 0.999)
    c["dia"] = c["inicio_local"].dt.weekday.map(lambda i: DIAS[i])
    c["franja"] = c["inicio_local"].dt.hour.map(franja)
    c["hora"] = c["inicio_local"].dt.strftime("%H:%M")
    return c


def pct(x):
    return "" if pd.isna(x) else f"{x * 100:.0f}%"


def tabla(df, cols, clases=None):
    h = "<table><thead><tr>" + "".join(f"<th>{html.escape(c)}</th>" for c in cols) + "</tr></thead><tbody>"
    for _, r in df.iterrows():
        h += "<tr>" + "".join(
            f'<td class="{(clases or {}).get(c, "")}">{html.escape(str(r[c])) if pd.notna(r[c]) else ""}</td>' for c in cols) + "</tr>"
    return h + "</tbody></table>"


def heat(c):
    out = ""
    for z in ZONAS:
        d = c[(c["centro_beatcore"] == z) & c["ocupacion"].notna()]
        if d.empty:
            continue
        p = d.pivot_table(index="franja", columns="dia", values="ocupacion", aggfunc="mean")
        n = d.pivot_table(index="franja", columns="dia", values="ocupacion", aggfunc="count")
        dias = [x for x in DIAS if x in p.columns]
        fr = [f[2] for f in FRANJAS if f[2] in p.index]
        h = f"<h3>{z}</h3><div class='scroll'><table class='heat'><thead><tr><th></th>" + "".join(f"<th>{x[:3]}</th>" for x in dias) + "</tr></thead><tbody>"
        for f in fr:
            h += f"<tr><th>{f}</th>"
            for x in dias:
                v = p.at[f, x] if x in p.columns else None
                k = n.at[f, x] if x in n.columns else 0
                if pd.isna(v):
                    h += "<td class='vacio'></td>"
                else:
                    h += f"<td style='--o:{v:.2f}' title='{int(k)} clases'>{v * 100:.0f}%</td>"
            h += "</tr>"
        out += h + "</tbody></table></div>"
    return out


def informe(c, festivos):
    hoy = datetime.now().strftime("%d/%m/%Y %H:%M")
    if c.empty:
        rango = "sin datos"
    else:
        rango = f"{c['inicio_local'].min():%d/%m/%Y} a {c['inicio_local'].max():%d/%m/%Y}"
    dias_n = c["fecha"].nunique()
    con_occ = c[c["ocupacion"].notna()]

    zon = []
    for z in ZONAS:
        d = c[c["centro_beatcore"] == z]
        o = d[d["ocupacion"].notna()]
        zon.append({"Zona": z, "Estudios": d["estudio"].nunique(), "Clases": len(d),
                    "Ocupación media": pct(o["ocupacion"].mean()), "Clases llenas": pct(d["llena_b"].mean()),
                    "Reservas por clase": f"{o['reservas'].mean():.1f}" if len(o) else "",
                    "Aforo medio": f"{o['aforo'].mean():.1f}" if len(o) else ""})
    zon = pd.DataFrame(zon)

    g = c.groupby(["centro_beatcore", "estudio", "plataforma"])
    est = g.agg(clases=("clase_id", "count"), ocup=("ocupacion", "mean"), llenas=("llena_b", "mean"),
                aforo=("aforo", "mean"), reservas=("reservas", "mean"),
                estimado=("aforo_fuente", lambda s: (s == "estimado").mean())).reset_index()
    est = est.sort_values(["centro_beatcore", "ocup"], ascending=[True, False])
    est_v = pd.DataFrame({
        "Zona": est["centro_beatcore"], "Estudio": est["estudio"], "Plataforma": est["plataforma"],
        "Clases": est["clases"], "Aforo medio": est["aforo"].map(lambda x: "" if pd.isna(x) else f"{x:.0f}"),
        "Reservas/clase": est["reservas"].map(lambda x: "" if pd.isna(x) else f"{x:.1f}"),
        "Ocupación": est["ocup"].map(pct), "Llenas": est["llenas"].map(pct),
        "Aforo": est["estimado"].map(lambda x: "estimado" if x > 0.5 else "publicado")})

    top = con_occ.groupby(["centro_beatcore", "estudio", "clase", "dia", "hora"]).agg(
        veces=("clase_id", "count"), ocup=("ocupacion", "mean"), aforo=("aforo", "mean")).reset_index()
    top = top[top["veces"] >= (2 if dias_n >= 14 else 1)].sort_values(["ocup", "aforo"], ascending=False).head(25)
    top_v = pd.DataFrame({"Zona": top["centro_beatcore"], "Estudio": top["estudio"], "Clase": top["clase"],
                          "Día": top["dia"], "Hora": top["hora"], "Ocupación": top["ocup"].map(pct),
                          "Aforo": top["aforo"].map(lambda x: f"{x:.0f}"), "Semanas": top["veces"]})

    fest_txt = "; ".join(f"{k} ({v['nombre']}, {v['zonas'] if isinstance(v['zonas'], str) else ', '.join(v['zonas'])})"
                         for k, v in sorted(festivos.items()))
    num = {"Clases": "n", "Ocupación media": "n", "Clases llenas": "n", "Reservas por clase": "n", "Aforo medio": "n",
           "Estudios": "n", "Aforo medio ": "n", "Reservas/clase": "n", "Ocupación": "n", "Llenas": "n", "Semanas": "n", "Aforo": "n"}

    css = open(os.path.join(os.path.dirname(__file__), "informe.css"), encoding="utf-8").read()
    return f"""<title>Ocupación competencia BeatCore</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Archivo:wght@500;700;800&family=Source+Sans+3:wght@400;600&display=swap">
<style>{css}</style>
<main>
<header>
<p class="eyebrow">The Boutique Tribe · análisis de competencia</p>
<h1>Ocupación de la competencia BeatCore</h1>
<p class="meta">Clases del {rango} · {dias_n} días con datos · {len(c)} clases · actualizado {hoy}</p>
</header>

<section>
<h2>Resumen por zona</h2>
<div class="scroll">{tabla(zon, list(zon.columns), num)}</div>
<p class="nota">Ocupación media sobre clases con aforo conocido o estimado (Momence, Glofox y Mindbody). "Clases llenas" incluye también bsport, que solo indica si la clase se llenó.</p>
</section>

<section>
<h2>Ocupación por día y franja</h2>
<p class="nota">Media de ocupación de las clases en cada hueco. Más oscuro, más lleno. Pasa el ratón para ver cuántas clases hay detrás.</p>
<div class="heats">{heat(c)}</div>
</section>

<section>
<h2>Clases más llenas</h2>
<div class="scroll">{tabla(top_v, list(top_v.columns), num)}</div>
</section>

<section>
<h2>Detalle por estudio</h2>
<div class="scroll">{tabla(est_v, list(est_v.columns), num)}</div>
</section>

<section class="metodo">
<h2>Cómo se calcula</h2>
<ul>
<li>Cada clase se mide con la última captura hecha antes de empezar. Las capturas se hacen cada 30 minutos de 6:00 a 0:38.</li>
<li>Las reservas no son asistencia: no se ven las ausencias.</li>
<li>Mindbody no siempre publica el aforo. En ese caso se estima con el máximo de plazas libres visto para esa clase, que es una cota inferior del aforo real: la ocupación de esos estudios puede estar algo subestimada.</li>
<li>Se excluyen clases canceladas y festivos: {html.escape(fest_txt) or "ninguno"}.</li>
<li>Solo se usan datos públicos del horario web de cada estudio.</li>
</ul>
</section>
</main>"""


def exportar_dashboard(c):
    """Agregados para el dashboard de socios (ficheros pequeños, uno por vista)."""
    desde = c["inicio_local"].min().strftime("%Y-%m-%d") if len(c) else ""
    hasta = c["inicio_local"].max().strftime("%Y-%m-%d") if len(c) else ""
    o = c[c["ocupacion"].notna()]
    fr = o.groupby(["centro_beatcore", "dia", "franja"]).agg(
        ocupacion=("ocupacion", "mean"), clases=("clase_id", "count")).reset_index()
    fr = fr.rename(columns={"centro_beatcore": "zona"})
    fr["ocupacion"] = fr["ocupacion"].round(3)
    fr.to_csv("reports/ocup_franja.csv", index=False)
    g = c.groupby(["centro_beatcore", "estudio", "plataforma"])
    es = g.agg(clases=("clase_id", "count"), ocupacion=("ocupacion", "mean"), llenas=("llena_b", "mean"),
               aforo=("aforo", "mean"), reservas=("reservas", "mean"),
               estimado=("aforo_fuente", lambda s: (s == "estimado").mean())).reset_index()
    es = es.rename(columns={"centro_beatcore": "zona"})
    es["aforo_tipo"] = es["estimado"].map(lambda x: "estimado" if x > 0.5 else "publicado")
    es = es.drop(columns="estimado")
    for k in ("ocupacion", "llenas"):
        es[k] = es[k].round(3)
    for k in ("aforo", "reservas"):
        es[k] = es[k].round(1)
    es["desde"], es["hasta"] = desde, hasta
    es.to_csv("reports/ocup_estudios.csv", index=False)


def main():
    os.makedirs("reports", exist_ok=True)
    festivos = json.load(open("festivos.json", encoding="utf-8"))
    c = preparar(cargar(), festivos)
    cols = ["fecha", "dia", "hora", "franja", "centro_beatcore", "plataforma", "estudio", "sede", "clase", "aforo",
            "aforo_fuente", "reservas", "ocupacion", "llena_b", "captured_at"]
    c[cols].sort_values(["fecha", "hora", "estudio"]).to_csv("reports/clases.csv", index=False)
    open("reports/informe.html", "w", encoding="utf-8").write(informe(c, festivos))
    exportar_dashboard(c)
    print(f"{len(c)} clases analizadas; {c['ocupacion'].notna().sum()} con ocupación; informe en reports/informe.html")


if __name__ == "__main__":
    main()
