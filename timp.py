"""
TIMP (web.timp.pro): necesita una cuenta de usuario normal (sin alta en cada centro).
Credenciales en los secretos de GitHub TIMP_EMAIL y TIMP_PASSWORD; nunca se imprimen.

Cada clase trae capacity "9 / 12" o "12 / 12 + 4" (lista de espera) cuando el centro
muestra plazas (show_tickets_count true); si no, solo status: available o queue_available.
"""
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import requests

API = "https://panel.timp.pro/api/user_app/v2"
KEY = "sDyGM00j1uF5nwTC"  # clave pública de la app web (está en su JavaScript)
MADRID = ZoneInfo("Europe/Madrid")
_token = None
_login_error = None


def _headers(token=None):
    h = {"Accept": "application/timp.user-app-v2", "Api-Access-Key": KEY, "App-Version": "9.3.0",
         "App-Platform": "web", "Time-Zone": "Europe/Madrid", "Accept-Language": "es",
         "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/130.0 Safari/537.36"}
    if token:
        h["Api-Access-Token"] = token
    return h


def _find_token(obj):
    if isinstance(obj, dict):
        for k, v in obj.items():
            if "token" in k.lower() and isinstance(v, str) and len(v) >= 10:
                return v
        for v in obj.values():
            t = _find_token(v)
            if t:
                return t
    if isinstance(obj, list):
        for v in obj:
            t = _find_token(v)
            if t:
                return t
    return None


def login():
    global _token, _login_error
    if _token:
        return _token
    if _login_error:  # un solo intento por ejecución, para no bloquear la cuenta
        raise RuntimeError(_login_error)
    email, pwd = os.environ.get("TIMP_EMAIL"), os.environ.get("TIMP_PASSWORD")
    if not email or not pwd:
        raise RuntimeError("faltan los secretos TIMP_EMAIL / TIMP_PASSWORD")
    r = requests.post(API + "/sessions", data={"email": email, "password": pwd}, headers=_headers(), timeout=30)
    if r.status_code >= 400:
        # el cuerpo trae solo el código de error (p. ej. login_bad_password), sin datos de la cuenta
        try:
            det = r.json()
            det = {k: (v if isinstance(v, (int, float, bool)) or (isinstance(v, str) and "@" not in v and len(v) < 80) else type(v).__name__)
                   for k, v in det.items()} if isinstance(det, dict) else str(det)[:120]
        except Exception:
            det = r.text[:120]
        _login_error = f"login TIMP {r.status_code}: {det}"
        raise RuntimeError(_login_error)
    _token = _find_token(r.json())
    if not _token:
        raise RuntimeError("login TIMP sin token en la respuesta; claves: " + ",".join(r.json().keys()))
    return _token


def get(path, **params):
    r = requests.get(API + path, params=params or None, headers=_headers(login()), timeout=30)
    r.raise_for_status()
    return r.json()


def _items(j):
    if isinstance(j, list):
        return j
    if isinstance(j, dict):
        for k in ("data", "items", "results", "activities", "activities_groups", "branch_buildings"):
            if isinstance(j.get(k), list):
                return j[k]
    return []


def actividades(branch_id):
    """Ids y nombres de las actividades reservables de un centro."""
    out = []
    for g in _items(get(f"/branch_buildings/{branch_id}/activities_groups")):
        gid = g.get("id")
        try:
            det = get(f"/activities_groups/{gid}")
        except Exception:
            continue
        for a in _items(det) or _items(det.get("activities") if isinstance(det, dict) else []):
            out.append({"id": a.get("id"), "name": a.get("name"), "grupo": g.get("name")})
    try:
        for a in _items(get(f"/branch_buildings/{branch_id}/activities/orphan_index")):
            out.append({"id": a.get("id"), "name": a.get("name"), "grupo": ""})
    except Exception:
        pass
    return [a for a in out if a["id"]]


def _cap(s):
    m = re.match(r"\s*(\d+)\s*/\s*(\d+)(?:\s*\+\s*(\d+))?", s or "")
    return (int(m.group(1)), int(m.group(2)), int(m.group(3) or 0)) if m else (None, None, None)


def capture(cfg, a, b):
    """Filas en el formato de capture.py para las clases de los centros TIMP entre a y b (UTC)."""
    if not cfg:
        return []
    rows = []
    try:
        login()
    except Exception as e:
        print(f"[timp] {e}", file=sys.stderr)
        return rows
    dias = sorted({(a + timedelta(days=i)).astimezone(MADRID).date() for i in range(0, (b - a).days + 2)})
    dias = [d for d in dias if datetime.combine(d, datetime.min.time(), MADRID) <= b.astimezone(MADRID) + timedelta(days=1)]
    for s in cfg:
        acts = s.get("actividades") or []
        for act in acts:
            for d in dias:
                try:
                    lst = _items(get(f"/activities/{act['id']}/admissions", date=d.isoformat()))
                except Exception as e:
                    print(f"[timp] {s['estudio']} {act.get('name')}: {e}", file=sys.stderr)
                    continue
                for x in lst:
                    h0 = (x.get("hours") or "").split("-")[0].strip()
                    try:
                        start = datetime.combine(d, datetime.strptime(h0, "%H:%M").time(), MADRID)
                    except ValueError:
                        continue
                    if not (a <= start.astimezone(timezone.utc) <= b):
                        continue
                    occ, cap, wait = _cap(x.get("capacity"))
                    st = x.get("status") or ""
                    llena = (occ >= cap) if cap else (st != "available")
                    rows.append({
                        "plataforma": "timp", "estudio": s["estudio"], "centro_beatcore": s.get("centro_beatcore", ""),
                        "sede": s.get("sede", s["estudio"]), "clase_id": x.get("id"), "clase": x.get("activity_name") or act.get("name"),
                        "inicio_local": start.strftime("%Y-%m-%d %H:%M"), "duracion_min": "",
                        "capacidad": cap if cap else "", "ocupadas": occ if cap else "",
                        "libres": (cap - occ) if cap else "", "libres_web": "", "llena": llena,
                        "cancelada": st in ("cancelled", "canceled"), "lista_espera": wait if cap else (st == "queue_available"),
                    })
                time.sleep(0.4)
    return rows


def descubrir(ids):
    """Imprime centros (y sus hermanos) con actividades y un ejemplo de clase. Sin datos personales."""
    vistos = set()
    manana = (datetime.now(MADRID) + timedelta(days=1)).date().isoformat()
    for bid in ids:
        try:
            herm = _items(get(f"/branch_buildings/{bid}/branch_buildings"))
        except Exception as e:
            print(f"{bid}: hermanos error {e}")
            herm = []
        cand = [{"id": bid}] + herm
        for c in cand:
            cid = c.get("id")
            if cid in vistos:
                continue
            vistos.add(cid)
            try:
                info = get(f"/branch_buildings/{cid}")
            except Exception as e:
                print(f"{cid}: error {e}")
                continue
            info = info.get("data", info) if isinstance(info, dict) else {}
            print(f"\n## {cid} | {info.get('name')} | {info.get('address')} | {info.get('latitude')},{info.get('longitude')}")
            try:
                for a in actividades(cid):
                    ej = ""
                    try:
                        lst = _items(get(f"/activities/{a['id']}/admissions", date=manana))
                        ej = [(x.get("hours"), x.get("capacity"), x.get("status")) for x in lst[:3]]
                    except Exception as e:
                        ej = f"error {e}"
                    print(f"   act {a['id']} | {a['grupo']} > {a['name']} | {ej}")
            except Exception as e:
                print(f"   actividades error {e}")


if __name__ == "__main__":
    descubrir([int(x) for x in sys.argv[1:]])
