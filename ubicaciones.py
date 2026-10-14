"""Provincia y ciudad de cada centro capturado (studios.json y studios_cadenas.json) -> web/ubicaciones.json.

Fuentes, de más a menos fiable:
  1. glofox: la ficha pública de la sede (dirección y código postal) con la sesión de invitado del propio portal.
  2. zona BeatCore del estudio (Chamberí y Salamanca = Madrid, Diagonal = Barcelona, Valencia = Valencia).
  3. palabras del nombre del centro (ciudad, barrio o municipio conocidos).
Lo que no se puede ubicar queda sin provincia: no se inventa. Se ejecuta a mano:  python ubicaciones.py
"""
import json
import re
import sys
import unicodedata

import requests

UA = {"User-Agent": "Mozilla/5.0"}

PROVINCIAS = {
    "01": "Álava", "02": "Albacete", "03": "Alicante", "04": "Almería", "05": "Ávila", "06": "Badajoz", "07": "Illes Balears",
    "08": "Barcelona", "09": "Burgos", "10": "Cáceres", "11": "Cádiz", "12": "Castellón", "13": "Ciudad Real", "14": "Córdoba",
    "15": "A Coruña", "16": "Cuenca", "17": "Girona", "18": "Granada", "19": "Guadalajara", "20": "Gipuzkoa", "21": "Huelva",
    "22": "Huesca", "23": "Jaén", "24": "León", "25": "Lleida", "26": "La Rioja", "27": "Lugo", "28": "Madrid", "29": "Málaga",
    "30": "Murcia", "31": "Navarra", "32": "Ourense", "33": "Asturias", "34": "Palencia", "35": "Las Palmas", "36": "Pontevedra",
    "37": "Salamanca", "38": "Santa Cruz de Tenerife", "39": "Cantabria", "40": "Segovia", "41": "Sevilla", "42": "Soria",
    "43": "Tarragona", "44": "Teruel", "45": "Toledo", "46": "Valencia", "47": "Valladolid", "48": "Bizkaia", "49": "Zamora",
    "50": "Zaragoza", "51": "Ceuta", "52": "Melilla"}

ZONAS = {"Chamberí": ("Madrid", "Madrid"), "Salamanca": ("Madrid", "Madrid"), "Diagonal": ("Barcelona", "Barcelona"),
         "Valencia": ("Valencia", "Valencia")}

# palabra del nombre -> (ciudad, provincia). Solo términos que no son ambiguos.
LUGARES = {
    "madrid": ("Madrid", "Madrid"), "barcelona": ("Barcelona", "Barcelona"), "valencia": ("Valencia", "Valencia"),
    "russafa": ("Valencia", "Valencia"), "ruzafa": ("Valencia", "Valencia"),
    "vigo": ("Vigo", "Pontevedra"), "pontevedra": ("Pontevedra", "Pontevedra"), "bilbao": ("Bilbao", "Bizkaia"),
    "santander": ("Santander", "Cantabria"), "malaga": ("Málaga", "Málaga"), "sevilla": ("Sevilla", "Sevilla"),
    "zaragoza": ("Zaragoza", "Zaragoza"), "alicante": ("Alicante", "Alicante"), "murcia": ("Murcia", "Murcia"),
    "granada": ("Granada", "Granada"), "valladolid": ("Valladolid", "Valladolid"), "zamora": ("Zamora", "Zamora"),
    "palma": ("Palma", "Illes Balears"), "ibiza": ("Ibiza", "Illes Balears"), "las palmas": ("Las Palmas", "Las Palmas"),
    "tenerife": ("Santa Cruz de Tenerife", "Santa Cruz de Tenerife"), "gijon": ("Gijón", "Asturias"), "oviedo": ("Oviedo", "Asturias"),
    "san sebastian": ("San Sebastián", "Gipuzkoa"), "donostia": ("San Sebastián", "Gipuzkoa"), "pamplona": ("Pamplona", "Navarra"),
    "vitoria": ("Vitoria", "Álava"), "logrono": ("Logroño", "La Rioja"), "burgos": ("Burgos", "Burgos"), "leon": ("León", "León"),
    "cordoba": ("Córdoba", "Córdoba"), "toledo": ("Toledo", "Toledo"), "salamanca ciudad": ("Salamanca", "Salamanca"),
    "sabadell": ("Sabadell", "Barcelona"), "badalona": ("Badalona", "Barcelona"), "hospitalet": ("L'Hospitalet", "Barcelona"),
    "castelldefels": ("Castelldefels", "Barcelona"), "sitges": ("Sitges", "Barcelona"), "girona": ("Girona", "Girona"),
    "tarragona": ("Tarragona", "Tarragona"), "lleida": ("Lleida", "Lleida"), "reus": ("Reus", "Tarragona"),
    "pozuelo": ("Pozuelo de Alarcón", "Madrid"), "las rozas": ("Las Rozas", "Madrid"), "majadahonda": ("Majadahonda", "Madrid"),
    "alcobendas": ("Alcobendas", "Madrid"), "alcorcon": ("Alcorcón", "Madrid"), "getafe": ("Getafe", "Madrid"),
    "boadilla": ("Boadilla del Monte", "Madrid"), "sanse": ("San Sebastián de los Reyes", "Madrid"),
    "tres cantos": ("Tres Cantos", "Madrid"), "alcala de henares": ("Alcalá de Henares", "Madrid"),
    "rivas": ("Rivas-Vaciamadrid", "Madrid"), "torrejon": ("Torrejón de Ardoz", "Madrid"), "leganes": ("Leganés", "Madrid"),
    "las tablas": ("Madrid", "Madrid"), "sanchinarro": ("Madrid", "Madrid"),
    # barrios de Madrid que solo existen allí
    "chamberi": ("Madrid", "Madrid"), "conde duque": ("Madrid", "Madrid"), "bernabeu": ("Madrid", "Madrid"),
    "castellana": ("Madrid", "Madrid"), "lopez de hoyos": ("Madrid", "Madrid"), "clara del rey": ("Madrid", "Madrid"),
    "conde orgaz": ("Madrid", "Madrid"), "julian camarillo": ("Madrid", "Madrid"), "arturo soria": ("Madrid", "Madrid"),
    "embajadores": ("Madrid", "Madrid"), "lavapies": ("Madrid", "Madrid"), "moncloa": ("Madrid", "Madrid"),
    "plaza castilla": ("Madrid", "Madrid"), "montecarmelo": ("Madrid", "Madrid"), "casa de campo": ("Madrid", "Madrid"),
    "conde casal": ("Madrid", "Madrid"), "delicias": ("Madrid", "Madrid"), "azca": ("Madrid", "Madrid"),
    "barrio de salamanca": ("Madrid", "Madrid"), "serrano": ("Madrid", "Madrid"), "o'donnell": ("Madrid", "Madrid"),
    "retiro": ("Madrid", "Madrid"), "monumental": ("Madrid", "Madrid"), "pacifico": ("Madrid", "Madrid"),
    "almagro": ("Madrid", "Madrid"), "ventas": ("Madrid", "Madrid"), "goya": ("Madrid", "Madrid"),
    "juan carlos i": ("Madrid", "Madrid"), "juan de borbon": ("Madrid", "Madrid"), "ronda sur": ("Madrid", "Madrid"),
    "nuevos ministerios": ("Madrid", "Madrid"), "legazpi": ("Madrid", "Madrid"), "moratalaz": ("Madrid", "Madrid"),
    "tetuan": ("Madrid", "Madrid"), "argüelles": ("Madrid", "Madrid"), "arguelles": ("Madrid", "Madrid"),
    # barrios de Barcelona
    "eixample": ("Barcelona", "Barcelona"), "gracia": ("Barcelona", "Barcelona"), "poblenou": ("Barcelona", "Barcelona"),
    "sagrada familia": ("Barcelona", "Barcelona"), "sant joan": ("Barcelona", "Barcelona"), "sant gervasi": ("Barcelona", "Barcelona"),
    "sarria": ("Barcelona", "Barcelona"), "born": ("Barcelona", "Barcelona"), "universitat": ("Barcelona", "Barcelona"),
    "aribau": ("Barcelona", "Barcelona"), "nou barris": ("Barcelona", "Barcelona"), "pedralbes": ("Barcelona", "Barcelona"),
    "bonanova": ("Barcelona", "Barcelona"), "diagonal": ("Barcelona", "Barcelona"), "provenza": ("Barcelona", "Barcelona"),
    "bcn": ("Barcelona", "Barcelona"), "clot": ("Barcelona", "Barcelona"), "santgervasi": ("Barcelona", "Barcelona"),
    "mallorca": ("Barcelona", "Barcelona"),   # calle Mallorca (Fabrik): en Barcelona
    "masnou": ("El Masnou", "Barcelona"), "mataro": ("Mataró", "Barcelona"), "mollet": ("Mollet del Vallès", "Barcelona"),
    "paret": ("Paret del Vallès", "Barcelona"), "premia": ("Premià de Mar", "Barcelona"),
    "marbella": ("Marbella", "Málaga"), "palmaracketclub": ("Palma", "Illes Balears"), "zaragoza": ("Zaragoza", "Zaragoza"),
    "lasrozas": ("Las Rozas", "Madrid"), "sanbernardo": ("Madrid", "Madrid"), "avenidadefrancia": ("Valencia", "Valencia"),
    "benimaclet": ("Valencia", "Valencia"), "patacona": ("Alboraya", "Valencia"), "eliana": ("L'Eliana", "Valencia"),
    "fernando vi": ("Madrid", "Madrid"), "paseo de la habana": ("Madrid", "Madrid"), "ortega y gasset": ("Madrid", "Madrid"),
    "alcala": ("Madrid", "Madrid"), "gines": ("Gines", "Sevilla"), "losremedios": ("Sevilla", "Sevilla"), "caceres": ("Cáceres", "Cáceres"),
    "rosalia": ("Vigo", "Pontevedra"), "plaza america": ("Vigo", "Pontevedra"),
}


def norm(s):
    s = unicodedata.normalize("NFD", str(s)).encode("ascii", "ignore").decode().lower()
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9' ]+", " ", s)).strip()


def por_nombre(nombre):
    n = " " + norm(nombre) + " "
    compacto = re.sub(r"[^a-z0-9]", "", norm(nombre))
    mejor = None
    for k, v in LUGARES.items():
        if (f" {k} " in n or (len(k) >= 6 and " " not in k and k in compacto)) and (mejor is None or len(k) > len(mejor[0])):
            mejor = (k, v)
    return mejor[1] if mejor else None


def glofox_dir(branch_id):
    try:
        r = requests.post("https://api.glofox.com/2.0/login", headers={**UA, "Content-Type": "application/json"},
                          json={"branch_id": branch_id, "login": "GUEST", "password": "GUEST"}, timeout=25)
        tok = r.json().get("token")
        b = requests.get(f"https://api.glofox.com/2.0/branches/{branch_id}", headers={**UA, "Authorization": f"Bearer {tok}"}, timeout=25).json()
        a = b.get("address") or {}
        return a.get("city") or "", str(a.get("postal_code") or "")
    except Exception:
        return "", ""


# Estudios cuya agenda mezcla centros de distintas ciudades: la ubicación se decide por sede.
# (regex del nombre del estudio, [(regex de la sede, ciudad, provincia)])
REGLAS_SEDE = [
    (r"^ARDE BARRE", [(r"moraleja", "Alcobendas", "Madrid")]),
    (r"^PILAT3S$", [
        (r"braga|douro|foz|estoril|oeiras|infante santo|avenidas novas|sottomayor|quinta da fonte", "Portugal", "Fuera de España"),
        (r"sheffield", "Sheffield", "Fuera de España"),
        (r"sagrada familia", "Barcelona", "Barcelona")]),
    (r"^B3B WOMAN$", [(r"chamartin|gmc", "Madrid", "Madrid")]),
]


def bsport_dir(eid):
    try:
        j = requests.get(f"https://api.production.bsport.io/api/v1/establishment/{eid}/", headers=UA, timeout=20).json()
        loc = j.get("location") or {}
        cp = str(loc.get("zipcode") or "")
        m = re.match(r"^(\d{2})\d{3}$", cp)
        prov = PROVINCIAS.get(m.group(1), "") if m and (loc.get("country") or "").lower()[:3] in ("spa", "esp") else ""
        return (loc.get("city") or "", prov, j.get("title") or "")
    except Exception:
        return "", "", ""


def sedes_capturadas():
    """Pares (estudio, sede) de las capturas más recientes."""
    import glob
    import pandas as pd
    fs = sorted(glob.glob("data/plan/*.csv"))[-4:] + sorted(glob.glob("data/*.csv"))[-2:]
    pares = set()
    for f in fs:
        try:
            d = pd.read_csv(f, usecols=["plataforma", "estudio", "sede"], low_memory=False)
        except Exception:
            continue
        for pl, e, sd in d.drop_duplicates().itertuples(index=False):
            pares.add((str(pl), str(e), str(sd)))
    return pares


def main():
    entradas = []
    for fn in ("studios.json", "studios_cadenas.json"):
        d = json.load(open(fn, encoding="utf-8"))
        for plat, lst in d.items():
            if isinstance(lst, list):
                for e in lst:
                    entradas.append((plat, e))
    out, cuenta = {}, {"glofox": 0, "zona": 0, "nombre": 0, "sin ubicar": 0}
    for plat, e in entradas:
        est = e["estudio"]
        ciudad = prov = cp = ""
        fuente = ""
        if plat == "glofox" and e.get("branch_id"):
            c, cp_ = glofox_dir(e["branch_id"])
            m = re.match(r"^(\d{2})\d{3}$", cp_ or "")
            if m and m.group(1) in PROVINCIAS:
                prov, cp, ciudad, fuente = PROVINCIAS[m.group(1)], cp_, c, "glofox"
        if not prov:
            v = ZONAS.get(e.get("centro_beatcore") or "")
            if v:
                ciudad, prov, fuente = v[0], v[1], "zona"
        if not prov:
            v = por_nombre(est)
            if v:
                ciudad, prov, fuente = v[0], v[1], "nombre"
        cuenta[fuente or "sin ubicar"] += 1
        out[est] = {"ciudad": ciudad, "provincia": prov, "cp": cp, "fuente": fuente}
    try:
        for k, v in json.load(open("web/ubicaciones_manual.json", encoding="utf-8")).items():
            if not k.startswith("_"):
                out[k] = {"ciudad": v.get("ciudad", ""), "provincia": v.get("provincia", ""), "cp": "", "fuente": v.get("fuente", "manual")}
    except FileNotFoundError:
        pass
    # ubicación por sede, solo para estudios cuya agenda mezcla ciudades
    sedes = {}
    cache_bs = {}
    for pl, est, sd in sedes_capturadas():
        r = None
        if pl == "bsport" and sd.isdigit():
            if sd not in cache_bs:
                cache_bs[sd] = bsport_dir(sd)
            c, pv, _t = cache_bs[sd]
            if pv:
                r = {"ciudad": c, "provincia": pv, "fuente": "bsport"}
        for pat_e, reglas in REGLAS_SEDE:
            if re.search(pat_e, est):
                for pat_s, c, pv in reglas:
                    if re.search(pat_s, norm(sd)):
                        r = {"ciudad": c, "provincia": pv, "fuente": "nombre de la sede"}
                        break
        if r:
            sedes.setdefault(est, {})[sd] = r
    out["_sedes"] = sedes
    json.dump(out, open("web/ubicaciones.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(cuenta, "de", len(out) - 1, "| estudios con ubicación por sede:", len(sedes))
    zonas_ = {e["estudio"] for _, e in entradas if e.get("centro_beatcore")}
    sin = [k for k, v in out.items() if k != "_sedes" and not v["provincia"] and k not in zonas_]
    print("SIN UBICAR:", len(sin))
    for k in sin:
        print("  ", k)


if __name__ == "__main__":
    main()
