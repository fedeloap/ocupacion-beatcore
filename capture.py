"""
Capturador de ocupación de estudios boutique (competencia BeatCore).

Dos tipos de captura, ambas solo con endpoints públicos (sin login ni reservas):

1. Ocupación final (cada ejecución, cada 30 min):
   clases que empiezan en [ahora - 20 min, ahora + 45 min].
   En el análisis se usa la última captura antes del inicio de cada clase.
   Salida: data/AAAA-MM-DD.csv

2. Planificación (una vez al día, primera ejecución a partir de las 6:00 de Madrid):
   todas las clases de los próximos 7 días. Sirve para ver la curva de reservas
   (cómo se llenan las clases con antelación) y para estimar la capacidad en
   plataformas que no la publican (Mindbody).
   Salida: data/plan/AAAA-MM-DD.csv
"""

import csv
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import requests

MADRID = ZoneInfo("Europe/Madrid")
BEFORE_MIN = 20
AFTER_MIN = 45
PLAN_DAYS = 7
UA = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "es-ES,es;q=0.9",
}

FIELDS = [
    "captured_at", "plataforma", "estudio", "centro_beatcore", "sede", "clase_id",
    "clase", "inicio_local", "duracion_min", "capacidad", "ocupadas", "libres",
    "libres_web", "llena", "cancelada", "lista_espera",
]


def now_utc():
    # REF_TIME (ISO, p.ej. 2026-10-12T09:00:00+02:00) permite probar con otra hora
    ref = os.environ.get("REF_TIME")
    return datetime.fromisoformat(ref).astimezone(timezone.utc) if ref else datetime.now(timezone.utc)


def iso_z(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def to_local(dt_utc):
    return dt_utc.astimezone(MADRID).strftime("%Y-%m-%d %H:%M")


def between(dt, a, b):
    return a <= dt <= b


# ---------------- Momence (dato exacto: capacidad y vendidas) ----------------
def momence(cfg, a, b):
    rows = []
    for s in cfg:
        page, sessions = 0, []
        try:
            while page < 20:
                url = (f"https://readonly-api.momence.com/host-plugins/host/{s['host_id']}"
                       f"/host-schedule/sessions?fromDate={iso_z(a - timedelta(hours=1))}"
                       f"&toDate={iso_z(b + timedelta(hours=1))}&pageSize=200&page={page}")
                r = requests.get(url, headers=UA, timeout=30)
                r.raise_for_status()
                batch = r.json().get("payload", [])
                sessions += batch
                if len(batch) < 200:
                    break
                page += 1
        except Exception as e:
            print(f"[momence] {s['estudio']}: error {e}", file=sys.stderr)
        for x in sessions:
            start = datetime.fromisoformat(x["startsAt"].replace("Z", "+00:00"))
            if not between(start, a, b):
                continue
            sede = x.get("location") or ""
            # solo_sedes: descarta sedes del mismo host fuera del radio de 1 km
            if s.get("solo_sedes") and sede not in s.get("sedes", {}):
                continue
            centro = s.get("sedes", {}).get(sede, s.get("centro_beatcore", ""))
            for pref, c in s.get("sedes_prefijo", {}).items():
                if sede.startswith(pref):
                    centro = c
            cap, sold = x.get("capacity"), x.get("ticketsSold")
            rem = (x.get("remainingSpots") or {}).get("remaining")
            if rem is None and isinstance(cap, int) and isinstance(sold, int):
                rem = cap - sold
            rows.append({
                "plataforma": "momence", "estudio": s["estudio"], "centro_beatcore": centro,
                "sede": sede, "clase_id": x["id"], "clase": x.get("sessionName", ""),
                "inicio_local": to_local(start), "duracion_min": x.get("durationMinutes"),
                "capacidad": cap, "ocupadas": sold, "libres": rem, "libres_web": "",
                "llena": (rem <= 0) if isinstance(rem, int) else "",
                "cancelada": x.get("isCancelled", False), "lista_espera": x.get("waitlistFull", ""),
            })
        time.sleep(1)
    return rows


# ---------------- Mindbody (plazas libres; capacidad no siempre publicada) ----------------
MB_URL = "https://prod-mkt-gateway.mindbody.io/v1/location/schedules"
MB_HEADERS = {**UA, "Content-Type": "application/json",
              "Origin": "https://www.mindbodyonline.com", "Referer": "https://www.mindbodyonline.com/"}


def mindbody(cfg, a, b):
    rows = []
    for s in cfg:
        # el endpoint trabaja bien por tramos de hasta 3 días
        cur, data = a, []
        try:
            while cur < b:
                end = min(cur + timedelta(days=3), b)
                body = {"location_ref_json": s["ref"], "start_time_from": iso_z(cur),
                        "start_time_to": iso_z(end), "location_timezone": "Europe/Madrid"}
                r = requests.post(MB_URL, json=body, headers=MB_HEADERS, timeout=30)
                r.raise_for_status()
                data += r.json().get("data", [])
                cur = end
                time.sleep(0.5)
        except Exception as e:
            print(f"[mindbody] {s['estudio']}: error {e}", file=sys.stderr)
        for d in data:
            at = d.get("attributes", {})
            if at.get("subType") != "class_time":
                continue
            x = at.get("attributes", {})
            start = datetime.fromisoformat(x["startTime"].replace("Z", "+00:00"))
            if not between(start, a, b):
                continue
            cap = x.get("capacity") or ""
            op, web = x.get("openings"), x.get("webOpenings")
            rows.append({
                "plataforma": "mindbody", "estudio": s["estudio"], "centro_beatcore": s.get("centro_beatcore", ""),
                "sede": s["estudio"], "clase_id": d.get("id"), "clase": (x.get("course") or {}).get("name", ""),
                "inicio_local": to_local(start), "duracion_min": x.get("duration"),
                "capacidad": cap,
                "ocupadas": (cap - op) if isinstance(cap, int) and isinstance(op, int) else "",
                "libres": op if op is not None else "", "libres_web": web if web is not None else "",
                "llena": (op <= 0) if isinstance(op, int) else "",
                "cancelada": x.get("isCancelled", ""), "lista_espera": "",
            })
        time.sleep(0.5)
    return rows


# ---------------- bsport (capacidad y si está llena) ----------------
def bsport(cfg, a, b):
    rows = []
    d1 = a.astimezone(MADRID).strftime("%Y-%m-%d")
    d2 = b.astimezone(MADRID).strftime("%Y-%m-%d")
    for s in cfg:
        offers, url = [], (f"https://api.production.bsport.io/book/v1/offer/?company={s['company_id']}"
                           f"&min_date={d1}&max_date={d2}&page_size=100")
        try:
            while url:
                r = requests.get(url, headers=UA, timeout=30)
                r.raise_for_status()
                j = r.json()
                offers += j.get("results", [])
                url = j.get("next") or (j.get("links") or {}).get("next")
                time.sleep(0.5)
        except Exception as e:
            print(f"[bsport] {s['estudio']}: error {e}", file=sys.stderr)
        for x in offers:
            start = datetime.fromisoformat(x["date_start"]).astimezone(timezone.utc)
            if not between(start, a, b):
                continue
            est = str(x.get("establishment"))
            # solo_establecimientos: descarta sedes lejanas (p.ej. SHE Barre en Alella o Mataró)
            if s.get("solo_establecimientos") and est not in s.get("establecimientos", {}):
                continue
            rows.append({
                "plataforma": "bsport", "estudio": s["estudio"],
                "centro_beatcore": s.get("establecimientos", {}).get(est, s.get("centro_beatcore", "")),
                "sede": est, "clase_id": x["id"], "clase": x.get("activity_name", ""),
                "inicio_local": to_local(start), "duracion_min": x.get("duration_minute"),
                # bsport no expone el número exacto de reservas válidas: solo capacidad y si está llena
                "capacidad": x.get("effectif"), "ocupadas": "", "libres": "", "libres_web": "",
                "llena": bool(x.get("full")), "cancelada": "", "lista_espera": x.get("is_waiting_list_full", ""),
            })
        time.sleep(1)
    return rows


# ---------------- Glofox (dato exacto; requiere token de invitado del portal) ----------------
def glofox(cfg, a, b):
    if not cfg:
        return []
    rows = []
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("[glofox] playwright no instalado", file=sys.stderr)
        return rows
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for s in cfg:
            # contexto nuevo por estudio: el token de invitado se guarda en localStorage
            # y es propio de cada branch; reutilizarlo devolvería las clases del primer estudio
            ctx = browser.new_context()
            page = ctx.new_page()
            try:
                page.goto(f"https://app.glofox.com/portal/#/branch/{s['branch_id']}/classes-day-view",
                          wait_until="networkidle", timeout=60000)
                token = page.evaluate(
                    "() => { try { return JSON.parse(localStorage.getItem('ngStorage-tokens'))[0].webPortalToken } catch(e) { return null } }")
                if not token:
                    print(f"[glofox] {s['estudio']}: sin token", file=sys.stderr)
                    continue
                data, pg = [], 1
                while pg <= 20:
                    url = (f"https://api.glofox.com/2.0/events?start={int(a.timestamp())}&end={int(b.timestamp())}"
                           f"&page={pg}&private=false&sort_by=time_start")
                    r = requests.get(url, headers={**UA, "Authorization": f"Bearer {token}"}, timeout=30)
                    j = r.json()
                    data += j.get("data", [])
                    if not j.get("has_more"):
                        break
                    pg += 1
                for x in data:
                    st = datetime.fromtimestamp(int(x["time_start"]), timezone.utc)
                    if not between(st, a, b):
                        continue
                    size, booked = x.get("size"), x.get("booked")
                    ok = isinstance(size, int) and isinstance(booked, int)
                    rows.append({
                        "plataforma": "glofox", "estudio": s["estudio"], "centro_beatcore": s.get("centro_beatcore", ""),
                        "sede": s["estudio"], "clase_id": x.get("_id"), "clase": x.get("name", ""),
                        "inicio_local": to_local(st), "duracion_min": x.get("duration"),
                        "capacidad": size, "ocupadas": booked, "libres": (size - booked) if ok else "",
                        "libres_web": "", "llena": (booked >= size) if ok else "",
                        "cancelada": "", "lista_espera": x.get("waiting", ""),
                    })
            except Exception as e:
                print(f"[glofox] {s['estudio']}: error {e}", file=sys.stderr)
            ctx.close()
        browser.close()
    return rows


def capture(cfg, a, b):
    import timp
    return (momence(cfg.get("momence", []), a, b) + mindbody(cfg.get("mindbody", []), a, b)
            + bsport(cfg.get("bsport", []), a, b) + glofox(cfg.get("glofox", []), a, b)
            + timp.capture(cfg.get("timp", []), a, b))


def write(rows, path, stamp):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            header = f.readline().strip().split(",")
        if header != FIELDS:  # cambio de formato: se conserva el fichero antiguo aparte
            os.replace(path, path.replace(".csv", "_v1.csv"))
    new = not os.path.exists(path)
    with open(path, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        if new:
            w.writeheader()
        for r in rows:
            r["captured_at"] = stamp
            w.writerow(r)


def main():
    cfg = json.load(open(os.path.join(os.path.dirname(__file__), "studios.json"), encoding="utf-8"))
    ref = now_utc()
    local = ref.astimezone(MADRID)
    stamp = local.strftime("%Y-%m-%d %H:%M:%S")
    day = local.strftime("%Y-%m-%d")

    rows = capture(cfg, ref - timedelta(minutes=BEFORE_MIN), ref + timedelta(minutes=AFTER_MIN))
    write(rows, os.path.join("data", f"{day}.csv"), stamp)
    print(f"{stamp}: {len(rows)} clases (ocupación final)")

    plan_path = os.path.join("data", "plan", f"{day}.csv")
    if (local.hour >= 6 and not os.path.exists(plan_path)) or os.environ.get("FORCE_PLAN"):
        plan = capture(cfg, ref, ref + timedelta(days=PLAN_DAYS))
        write(plan, plan_path, stamp)
        print(f"{stamp}: {len(plan)} clases (planificación 7 días)")


if __name__ == "__main__":
    main()
