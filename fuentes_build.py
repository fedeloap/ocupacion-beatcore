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
    for ruta in ("web/cadenas_fuentes.json", "web/cadenas_red.json"):
        try:
            datos = json.load(open(ruta, encoding="utf-8"))["cadenas"]
        except Exception:
            continue
        for r in datos:
            d = c.setdefault(r["cadena"], {})
            for f in r.get("fuentes", []):
                k = f["plataforma"]
                v = f.get("host_id") or f.get("company_id") or f.get("tenant") or f.get("subdominio") or f.get("site_id") or f.get("branch_id")
                if v is not None:
                    d.setdefault(k, set()).add(str(v))
            for k, vals in (r.get("ids") or {}).items():
                for v in vals:
                    d.setdefault(k, set()).add(str(v))
    return c


def main():
    ya = ya_capturados()
    cand = candidatos()
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
        for br in sorted(plats.get("glofox", [])):
            if br in ya["glofox"]:
                continue
            out["glofox"].append({"estudio": cadena, "branch_id": br, "centro_beatcore": ""})
            resumen.append((cadena, "glofox", br, "sin verificar"))
    json.dump(out, open("studios_cadenas.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    for r in resumen:
        print(r)
    print({k: len(v) for k, v in out.items() if isinstance(v, list)})


if __name__ == "__main__":
    main()
