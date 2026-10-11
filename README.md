# Ocupación de la competencia BeatCore

Captura automática, cada 30 minutos, de plazas totales y ocupadas de las clases de estudios boutique cercanos a los centros BeatCore. Corre en GitHub Actions y guarda los datos en `data/AAAA-MM-DD.csv`.

## Qué se mide

| Plataforma | Dato | Estudios (piloto) |
|---|---|---|
| Momence | Exacto: capacidad y plazas vendidas | AMA (Chamberí y Lagasca), Mooves, Olimpia, Prana House, Casa Kavi, DAN'S (Barceló y Salamanca), B3B Ayala |
| Glofox | Exacto: capacidad y plazas ocupadas | Club Pilates Chamberí |
| bsport | Capacidad y si la clase está llena (sin recuento exacto) | Victoria Studio (Almagro y Goya), Batelier |

No medibles sin login (por ahora): estudios en TIMP (N7, PilatesLab), Mindbody (Solid, esBarré, Inhala…), Eversports (FLO) y apps propias (eskul, Laghum, FS8).

## Cómo funciona

- Cada ejecución guarda las clases que empiezan entre 20 minutos antes y 45 minutos después del momento de captura.
- Para el análisis se usa la última captura de cada clase antes de su inicio.
- "Ocupadas" son reservas, no asistencia real (no se ven los no-shows).
- Solo se usan endpoints públicos que los propios estudios exponen en su horario web; no se crean cuentas ni se hacen reservas.

## Columnas

`captured_at, plataforma, estudio, centro_beatcore, sede, clase_id, clase, inicio_local, duracion_min, capacidad, ocupadas, libres, llena, cancelada, lista_espera`

## Añadir estudios

Editar `studios.json` (sección de la plataforma correspondiente). No hace falta tocar el código.

## Ejecución manual

En GitHub: pestaña **Actions** > **Captura de ocupación** > **Run workflow**.
