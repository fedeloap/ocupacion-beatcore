"""
Capturador de ocupación de estudios boutique (competencia BeatCore).

Cada ejecución guarda, para las clases que empiezan en la ventana
[ahora - 20 min, ahora + 45 min], las plazas totales y ocupadas.
Ejecutado cada 30 min, cada clase queda capturada 1 o 2 veces cerca de su inicio;
en el análisis se usa la última captura antes de empezar.

Salida: data/AAAA-MM-DD.csv (una fila por clase y captura).
Solo usa endpoints públicos (sin login ni reservas).
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
UA = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "es-ES,es;q=0.9",
}

FIELDS = [
    "captured_at", "plataforma", "estudio", "centro_beatcore", "sede", "clase_id",
    "clase", "inicio_local", "duracion_min", "capacidad", "ocupadas", "libres",
    "llena", "cancelada", "lista_espera",
]


def now_utc():
    # REF_TIME (ISO, p.ej. 2026-10-12T09:00:00+02:00) permite probar con otra hora
    ref = os.environ.get("REF_TIME")
    return datetime.fromisoformat(ref).astimezone(timezone.utc) if ref else datetime.now(timezone.utc)


def in_window(start_utc, ref):
    return ref - timedelta(minutes=BEFORE_MIN) <= start_utc <= ref + timedelta(minutes=AFTER_MIN)


def to_local(dt_utc):
    return dt_utc.astimezone(MADRID).strftime("%Y-%m-%d %H:%M")


# ---------------- Momence (dato exacto: capacidad y vendidas) ----------------
def momence(cfg, ref):
    rows = []
    frm = (ref - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    to = (ref + timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    for s in cfg:
        url = (f"https://readonly-api.momence.com/host-plugins/host/{s['host_id']}"
               f"/host-schedule/sessions?fromDate={frm}&toDate={to}&pageSize=200&page=0")
        try:
            r = requests.get(url, headers=UA, timeout=30)
            r.raise_for_status()
            sessions = r.json().get("payload", [])
        except Exception as e:
            print(f"[momence] {s['estudio']}: error {e}", file=sys.stderr)
            continue
        for x in sessions:
            start = datetime.fromisoformat(x["startsAt"].replace("Z", "+00:00"))
            if not in_window(start, ref):
                continue
            sede = x.get("location") or ""
            centro = s.get("sedes", {}).get(sede, "")
            for pref, c in s.get("sedes_prefijo", {}).items():
                if sede.startswith(pref):
                    centro = c
            cap, sold = x.get("capacity"), x.get("ticketsSold")
            rem = (x.get("remainingSpots") or {}).get("remaining")
            rows.append({
                "plataforma": "momence", "estudio": s["estudio"], "centro_beatcore": centro,
                "sede": sede, "clase_id": x["id"], "clase": x.get("sessionName", ""),
                "inicio_local": to_local(start), "duracion_min": x.get("durationMinutes"),
                "capacidad": cap, "ocupadas": sold, "libres": rem,
                "llena": (rem == 0) if rem is not None else "",
                "cancelada": x.get("isCancelled", False), "lista_espera": x.get("waitlistFull", ""),
            })
        time.sleep(1)
    return rows


# ---------------- bsport (capacidad y si está llena) ----------------
def bsport(cfg, ref):
    rows = []
    day = ref.astimezone(MADRID).strftime("%Y-%m-%d")
    for s in cfg:
        url = (f"https://api.production.bsport.io/book/v1/offer/?company={s['company_id']}"
               f"&min_date={day}&max_date={day}")
        try:
            r = requests.get(url, headers=UA, timeout=30)
            r.raise_for_status()
            offers = r.json().get("results", [])
        except Exception as e:
            print(f"[bsport] {s['estudio']}: error {e}", file=sys.stderr)
            continue
        for x in offers:
            start = datetime.fromisoformat(x["date_start"]).astimezone(timezone.utc)
            if not in_window(start, ref):
                continue
            est = str(x.get("establishment"))
            rows.append({
                "plataforma": "bsport", "estudio": s["estudio"],
                "centro_beatcore": s.get("establecimientos", {}).get(est, ""),
                "sede": est, "clase_id": x["id"], "clase": x.get("activity_name", ""),
                "inicio_local": to_local(start), "duracion_min": x.get("duration_minute"),
                # bsport no expone el número exacto de reservas válidas: solo capacidad y si está llena
                "capacidad": x.get("effectif"), "ocupadas": "", "libres": "",
                "llena": bool(x.get("full")), "cancelada": "", "lista_espera": x.get("is_waiting_list_full", ""),
            })
        time.sleep(1)
    return rows


# ---------------- Glofox (dato exacto; requiere token de invitado del portal) ----------------
def glofox(cfg, ref):
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
        page = browser.new_page()
        for s in cfg:
            try:
                page.goto(f"https://app.glofox.com/portal/#/branch/{s['branch_id']}/classes-day-view",
                          wait_until="networkidle", timeout=60000)
                token = page.evaluate(
                    "() => { try { return JSON.parse(localStorage.getItem('ngStorage-tokens'))[0].webPortalToken } catch(e) { return null } }")
                if not token:
                    print(f"[glofox] {s['estudio']}: sin token", file=sys.stderr)
                    continue
                start = int((ref - timedelta(minutes=BEFORE_MIN)).timestamp())
                end = int((ref + timedelta(minutes=AFTER_MIN)).timestamp())
                url = (f"https://api.glofox.com/2.0/events?start={start}&end={end}"
                       f"&page=1&private=false&sort_by=time_start")
                r = requests.get(url, headers={**UA, "Authorization": f"Bearer {token}"}, timeout=30)
                data = r.json().get("data", [])
                for x in data:
                    st = datetime.fromtimestamp(int(x["time_start"]), timezone.utc)
                    if not in_window(st, ref):
                        continue
                    size, booked = x.get("size"), x.get("booked")
                    rows.append({
                        "plataforma": "glofox", "estudio": s["estudio"], "centro_beatcore": s.get("centro_beatcore", ""),
                        "sede": s["estudio"], "clase_id": x.get("_id"), "clase": x.get("name", ""),
                        "inicio_local": to_local(st), "duracion_min": x.get("duration"),
                        "capacidad": size, "ocupadas": booked,
                        "libres": (size - booked) if isinstance(size, int) and isinstance(booked, int) else "",
                        "llena": (booked >= size) if isinstance(size, int) and isinstance(booked, int) else "",
                        "cancelada": "", "lista_espera": x.get("waiting", ""),
                    })
            except Exception as e:
                print(f"[glofox] {s['estudio']}: error {e}", file=sys.stderr)
        browser.close()
    return rows


def main():
    cfg = json.load(open(os.path.join(os.path.dirname(__file__), "studios.json"), encoding="utf-8"))
    ref = now_utc()
    rows = momence(cfg.get("momence", []), ref) + bsport(cfg.get("bsport", []), ref) + glofox(cfg.get("glofox", []), ref)
    stamp = ref.astimezone(MADRID).strftime("%Y-%m-%d %H:%M:%S")
    os.makedirs("data", exist_ok=True)
    path = os.path.join("data", ref.astimezone(MADRID).strftime("%Y-%m-%d") + ".csv")
    new = not os.path.exists(path)
    with open(path, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        if new:
            w.writeheader()
        for r in rows:
            r["captured_at"] = stamp
            w.writerow(r)
    print(f"{stamp}: {len(rows)} clases capturadas -> {path}")


if __name__ == "__main__":
    main()
