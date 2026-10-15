"""Recupera las clases de los 4 centros BeatCore (Momence) anteriores a que empezáramos a capturarlos
(12/10/2026 a las 11:08 hora de Madrid). Momence sigue devolviendo las sesiones pasadas con sus plazas y
vendidas finales; se guardan como si fueran la foto final de la clase (captured_at = hora de inicio).
Solo añade las clases que no estén ya en data/. Se ejecuta una vez a mano:  python backfill_beatcore.py
"""
import csv
import glob
import json
import os
from datetime import datetime, timezone

import capture

DESDE = datetime(2026, 10, 10, 22, 0, tzinfo=timezone.utc)     # 11/10 00:00 Madrid
HASTA = datetime(2026, 10, 12, 9, 30, tzinfo=timezone.utc)     # antes de la primera clase ya capturada (12:00 Madrid)


def main():
    st = json.load(open("studios.json", encoding="utf-8"))
    cfg = [e for e in st.get("momence", []) if e.get("propio")]
    rows = capture.momence(cfg, DESDE, HASTA)
    existentes = set()
    for f in glob.glob("data/*.csv") + glob.glob("data/curva/*.csv"):
        with open(f, encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                existentes.add((r["estudio"], r["clase_id"]))
    por_dia = {}
    for r in rows:
        if (r["estudio"], str(r["clase_id"])) in existentes:
            continue
        r["captured_at"] = r["inicio_local"] + ":00"
        por_dia.setdefault(r["inicio_local"][:10], []).append(r)
    n = 0
    for dia, rs in sorted(por_dia.items()):
        path = os.path.join("data", f"{dia}.csv")
        nuevo = not os.path.exists(path)
        with open(path, "a", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=capture.FIELDS)
            if nuevo:
                w.writeheader()
            for r in rs:
                w.writerow({k: r.get(k, "") for k in capture.FIELDS})
                n += 1
        print(dia, len(rs), "clases añadidas")
    print("total", n)


if __name__ == "__main__":
    main()
