# Ocupación de la competencia BeatCore

Captura automática, cada 30 minutos, de plazas totales y ocupadas de las clases de estudios boutique cercanos a los centros BeatCore. Corre en GitHub Actions y guarda los datos en `data/AAAA-MM-DD.csv`.

## Qué se mide

| Plataforma | Dato | Cobertura |
|---|---|---|
| Momence | Exacto: capacidad y plazas vendidas | AMA, Mooves, Olimpia, Prana House, Casa Kavi, DAN'S, B3B Ayala, B3B Retiro, Casa Barré Ayala, Yogalates House, Boutique Barre, TRIB3 (Madrid); Senda, MOODBODY, PILAT3S Gràcia, Human Pilates, Dharma, Corehaus (Diagonal); Studio 130 (Valencia) |
| Mindbody | Plazas libres por clase; capacidad cuando el estudio la publica | 44 estudios a 1 km de los 4 BeatCore (buscador público de Mindbody) |
| Glofox | Exacto: capacidad y plazas ocupadas | Club Pilates Chamberí, Goya y Eixample; Pomona Club |
| bsport | Capacidad y si la clase está llena | Victoria, Batelier, Dark Studio, Enjoy Gravity, KMT (Madrid); VERDE, SHE Barre Gràcia, Rohi, Core Studio, Form Studio (Diagonal); The Sanctuary, Musa House, Soma Club Ruzafa, Aero Studio Seijaku (Valencia) |

No medibles sin login: TIMP (N7, PilatesLab), AimHarder (crossfit: oculta la ocupación), Eversports (FLO) y apps propias (eskul, Laghum).

## Dos capturas

- **Ocupación final** (`data/AAAA-MM-DD.csv`), cada 30 min: clases que empiezan entre 20 min antes y 45 min después. En el análisis se usa la última captura antes del inicio de cada clase.
- **Planificación** (`data/plan/AAAA-MM-DD.csv`), una vez al día desde las 6:00: todas las clases de los 7 días siguientes. Permite ver la curva de reservas y estimar la capacidad en Mindbody cuando no se publica.

"Ocupadas" son reservas, no asistencia (no se ven los no-shows). Solo se usan endpoints públicos del horario web de cada estudio; no se crean cuentas ni se hacen reservas.

## Columnas

`captured_at, plataforma, estudio, centro_beatcore, sede, clase_id, clase, inicio_local, duracion_min, capacidad, ocupadas, libres, libres_web, llena, cancelada, lista_espera`

## Añadir estudios

Editar `studios.json` (sección de la plataforma correspondiente). No hace falta tocar el código.

## Ejecución manual

Pestaña **Actions** > **Captura de ocupación** > **Run workflow**.

## Análisis

`python analisis.py` genera `reports/clases.csv` (una fila por clase) y `reports/informe.html`. Festivos excluidos en `festivos.json`. En Mindbody sin aforo publicado se estima con el máximo de plazas libres visto (cota inferior).
