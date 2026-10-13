"""
Construye studios_cadenas.json (estudios de cadenas nacionales que captura capture.py) a partir de
web/cadenas_fuentes.json (HTML) y web/cadenas_red.json (peticiones de red). Cada identificador se verifica
contra la agenda pública de su plataforma, y se descartan los que ya están en studios.json.
"""

import json
import re
import sys

import fuentes as F

FUENTES = []


def ya_capturados():
    s = json.load(open("studios.json", encoding="utf-8"))
    ya = {"momence": set(), "bsport": set(), "mindbody": set(), "glofox": set(), "marianatek": set(), "aimharder": set()}
    for e in s.get("momence", []):
        ya["momence"].add(str(e["host_id"]))
    for e in s.get("bsport", []):
        ya["bsport"].add(str(e["company_id"]))
    for e in s.get("mindbody", []):
        m = re.search(r"mb_site_id\D+(\d+)", e["ref"])
        if m:
            ya["mindbody"].add(m.group(1))
    for e in s.get("glofox", []):
        ya["glofox"].add(e["branch_id"])
    for e in s.get("marianatek", []):
        ya["marianatek"].add(f"{e['tenant']}|{e['location_id']}")
    return ya


def slug_mb(site):
    """Nombre del estudio de Mindbody (aparece en las URLs de contenido: .../studios/<slug>/...)."""
    import requests
    from datetime import datetime, timedelta, timezone
    body = {"location_ref_json": json.dumps({"mb_site_id": int(site), "mb_location_id": 1, "inventory_source": "MB"}),
            "start_time_from": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z"),
            "start_time_to": (datetime.now(timezone.utc) + timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%S.000Z"),
            "location_timezone": "Europe/Madrid"}
    try:
        r = requests.post("https://prod-mkt-gateway.mindbody.io/v1/location/schedules", json=body, timeout=20,
                          headers={"User-Agent": "Mozilla/5.0", "Content-Type": "application/json",
                                   "Origin": "https://www.mindbodyonline.com", "Referer": "https://www.mindbodyonline.com/"})
        m = re.search(r"studios/([a-z0-9\-_]+)/", r.text)
        return m.group(1) if m else str(site)
    except Exception:
        return str(site)


def candidatos():
    """cadena -> {plataforma: set(ids)} uniendo HTML estático y red."""
    c = {}
    for ruta in ("web/cadenas_fuentes.json", "web/cadenas_fuentes_prof.json", "web/cadenas_red.json"):
        try:
            datos = json.load(open(ruta, encoding="utf-8"))["cadenas"]
        except Exception:
            continue
        for r in datos:
            d = c.setdefault(r["cadena"], {})
            for f in r.get("fuentes", []):
                k = f["plataforma"]
                v = (f.get("host_id") or f.get("company_id") or f.get("tenant") or f.get("subdominio") or f.get("site_id")
                     or f.get("branch_id") or f.get("centro_code"))
                if v is not None:
                    d.setdefault(k, set()).add(str(v))
            for k, vals in (r.get("ids") or {}).items():
                for v in vals:
                    d.setdefault(k, set()).add(str(v))
    return c


CADENAS_FUERA = {"LEVELOUT"}  # sedes en el Reino Unido, no aplican


def main():
    ya = ya_capturados()
    cand = {k: v for k, v in candidatos().items() if k not in CADENAS_FUERA}
    out = {"_nota": "Estudios de cadenas nacionales (fuera del radio de BeatCore). Solo captura final. Generado por fuentes_build.py.",
           "momence": [], "bsport": [], "mindbody": [], "glofox": [], "marianatek": [], "aimharder": []}
    resumen = []
    for cadena, plats in sorted(cand.items()):
        for hid in sorted(plats.get("momence", [])):
            if hid in ya["momence"]:
                continue
            v = F.ver_momence(hid)
            if v:
                out["momence"].append({"estudio": cadena, "host_id": int(hid), "centro_beatcore": ""})
                resumen.append((cadena, "momence", hid, v.get("clases_7d")))
        for cid in sorted(plats.get("bsport", [])):
            if cid in ya["bsport"]:
                continue
            v = F.ver_bsport(cid)
            if v:
                out["bsport"].append({"estudio": cadena, "company_id": int(cid), "centro_beatcore": ""})
                resumen.append((cadena, "bsport", cid, v.get("clases_7d")))
        for sub in sorted(plats.get("aimharder", [])):
            v = F.ver_aimharder(sub)
            if v:
                nombre = v.get("nombre") or sub
                est = nombre if re.search(re.escape(cadena.split(" (")[0].lower()), nombre.lower()) else f"{cadena} {nombre}"
                out["aimharder"].append({"estudio": est, "subdominio": sub, "box": v["box"], "centro_beatcore": ""})
                resumen.append((cadena, "aimharder", sub, v.get("clases_dia")))
        for t in sorted(plats.get("marianatek", [])):
            v = F.ver_mariana(t)
            for loc in (v or {}).get("locations", []):
                if f"{t}|{loc['id']}" in ya["marianatek"]:
                    continue
                out["marianatek"].append({"estudio": f"{cadena} {loc['nombre']}", "tenant": t, "location_id": loc["id"], "centro_beatcore": ""})
                resumen.append((cadena, "marianatek", f"{t}/{loc['id']}", ""))
        for site in sorted(plats.get("mindbody", [])):
            if site in ya["mindbody"]:
                continue
            v = F.ver_mindbody(site)
            if v:
                ref = json.dumps({"mb_site_id": int(site), "mb_location_id": 1, "inventory_source": "MB"}, separators=(",", ":"))
                slug = slug_mb(site)
                if slug.endswith("uk"):  # sedes del Reino Unido: fuera del ámbito
                    continue
                nombre = cadena if len(plats.get("mindbody", [])) == 1 else f"{cadena} {slug}"
                out["mindbody"].append({"estudio": nombre, "ref": ref, "centro_beatcore": ""})
                resumen.append((cadena, "mindbody", site, v.get("clases_2d")))
        for code in sorted(plats.get("trainingym", [])):
            v = F.ver_trainingym(code)
            if v:
                out.setdefault("trainingym", []).append({"estudio": f"{cadena} {v['nombre']}", "centro_code": code, "centro_beatcore": ""})
                resumen.append((cadena, "trainingym", code, v.get("clases_3d")))
        for br in sorted(plats.get("glofox", [])):
            if br in ya["glofox"]:
                continue
            out["glofox"].append({"estudio": cadena, "branch_id": br, "centro_beatcore": ""})
            resumen.append((cadena, "glofox", br, "sin verificar"))
    # todos los centros de cada cadena (centros.py: fichas del sitemap con su identificador de agenda)
    try:
        cen = json.load(open("web/cadenas_centros.json", encoding="utf-8"))
    except Exception:
        cen = {}
    ya_est = {k: {str(e.get("host_id") or e.get("company_id") or e.get("subdominio") or e.get("branch_id") or
                    e.get("centro_code") or e.get("ref") or e.get("tenant")) for e in v}
              for k, v in out.items() if isinstance(v, list)}
    def nuevo(plat, ident):
        return not any(str(ident) in s or s == str(ident) for s in ya_est.get(plat, set()))
    for cadena, d in cen.items():
        for c in d.get("centros", []):
            plat, i, slug = c["plataforma"], str(c["id"]), c["nombre"]
            nombre = f"{cadena} {slug}"
            if plat == "glofox" and i not in ya["glofox"] and nuevo("glofox", i):
                out["glofox"].append({"estudio": nombre, "branch_id": i, "centro_beatcore": ""})
                ya_est.setdefault("glofox", set()).add(i)
                resumen.append((cadena, "glofox", slug, c.get("clases_7d")))
            elif plat == "momence" and i not in ya["momence"] and nuevo("momence", i):
                out["momence"].append({"estudio": cadena, "host_id": int(i), "centro_beatcore": ""})
                ya_est.setdefault("momence", set()).add(i)
                resumen.append((cadena, "momence", i, c.get("clases_7d")))
            elif plat == "bsport" and i not in ya["bsport"] and nuevo("bsport", i):
                out["bsport"].append({"estudio": cadena, "company_id": int(i), "centro_beatcore": ""})
                ya_est.setdefault("bsport", set()).add(i)
                resumen.append((cadena, "bsport", i, c.get("clases_7d")))
            elif plat == "mindbody" and i not in ya["mindbody"] and nuevo("mindbody", i):
                ref = json.dumps({"mb_site_id": int(i), "mb_location_id": 1, "inventory_source": "MB"}, separators=(",", ":"))
                out["mindbody"].append({"estudio": nombre, "ref": ref, "centro_beatcore": ""})
                ya_est.setdefault("mindbody", set()).add(i)
                resumen.append((cadena, "mindbody", i, c.get("clases_2d")))
            elif plat == "aimharder" and nuevo("aimharder", i) and c.get("box"):
                out["aimharder"].append({"estudio": nombre, "subdominio": i, "box": c["box"], "centro_beatcore": ""})
                ya_est.setdefault("aimharder", set()).add(i)
                resumen.append((cadena, "aimharder", i, c.get("clases_dia")))
            elif plat == "trainingym" and nuevo("trainingym", i):
                out.setdefault("trainingym", []).append({"estudio": f"{cadena} {c.get('nombre_centro') or slug}", "centro_code": i, "centro_beatcore": ""})
                ya_est.setdefault("trainingym", set()).add(i)
                resumen.append((cadena, "trainingym", i, c.get("clases_3d")))
    # fuentes localizadas a mano (web/cadenas_fuentes_manual.json), verificadas igual
    try:
        man = json.load(open("web/cadenas_fuentes_manual.json", encoding="utf-8"))
    except Exception:
        man = {}
    for e in man.get("mindbody", []):
        if str(e["site_id"]) in ya["mindbody"] or any(str(e["site_id"]) in x["ref"] for x in out["mindbody"]):
            continue
        if F.ver_mindbody(str(e["site_id"])):
            ref = json.dumps({"mb_site_id": int(e["site_id"]), "mb_location_id": 1, "inventory_source": "MB"}, separators=(",", ":"))
            out["mindbody"].append({"estudio": e["estudio"], "ref": ref, "centro_beatcore": ""})
            resumen.append((e["estudio"], "mindbody", e["site_id"], "manual"))
    for e in man.get("trainingym", []):
        if any(x["centro_code"] == e["centro_code"] for x in out.get("trainingym", [])):
            continue
        v = F.ver_trainingym(e["centro_code"])
        if v:
            out.setdefault("trainingym", []).append({"estudio": e["estudio"], "centro_code": e["centro_code"], "centro_beatcore": ""})
            resumen.append((e["estudio"], "trainingym", e["centro_code"], v.get("clases_3d")))
    json.dump(out, open("studios_cadenas.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    for r in resumen:
        print(r)
    print({k: len(v) for k, v in out.items() if isinstance(v, list)})


if __name__ == "__main__":
    main()
