# CLAUDE.md · Ocupación y competencia BeatCore

Contexto para Claude Code. Responde siempre en español, directo y conciso, sin guiones largos.
Usuario: Fede (The Boutique Tribe / WEC). Analiza la competencia de **BeatCore**, cadena de reformer con 4 centros:
Chamberí (Madrid), Salamanca (Madrid), Diagonal (Barcelona) y Ruzafa (Valencia, zona "Valencia" en los datos).
Ojo: el dictado por voz escribe "Bitcoin" o "Beatcore" cuando quiere decir BeatCore.

## Objetivo inmediato

Construir un **dashboard web público** (sin login, sin Claude) para compartir con gente externa, publicado en
**GitHub Pages** desde este repo (que ya es público) y regenerado automáticamente por GitHub Actions.

## Estructura del repo

| Ruta | Qué es |
|---|---|
| `capture.py` | Captura de ocupación desde APIs públicas de reservas. La lanza el workflow cada 30 min |
| `studios.json` | Estudios que se capturan, por plataforma, con su `centro_beatcore`. BeatCore lleva `"propio": true` |
| `analisis.py` | Ocupación final por clase (`cargar()` + `preparar()`), informe HTML y CSV en `reports/` |
| `festivos.json` | Festivos que se excluyen del análisis |
| `web/estudios.csv` | **Catálogo maestro** de estudios (330 filas): precios, plataforma, marca, cobertura y enlace con la captura |
| `data/YYYY-MM-DD.csv` | Capturas "finales": clases a punto de empezar (última foto antes del inicio) |
| `data/curva/YYYY-MM-DD.csv` | Cada captura guarda también las clases de las próximas 6 h (curva de reservas fina) |
| `data/plan/YYYY-MM-DD[_m|_t].csv` | Dos veces al día: las clases de los próximos 7 días (curva de reservas larga) |
| `timp.py` | Abandonado (TIMP requiere login). No usar ni ampliar |
| `.github/workflows/capture.yml` | Captura + commit de `data/`. Lo dispara cron-job.org cada 30 min (el cron de GitHub no es fiable) |

### Columnas de las capturas (`data/**.csv`)
`captured_at, plataforma, estudio, centro_beatcore, sede, clase_id, clase, inicio_local, duracion_min, capacidad,
ocupadas, libres, libres_web, llena, cancelada, lista_espera`

Clave de clase: `(plataforma, estudio, sede, clase_id)`. Hora local de Madrid.

Particularidades por plataforma:
- **Momence, Glofox, Mariana Tek**: aforo y reservas publicados.
- **Mindbody**: a veces no publica aforo; `analisis.py` lo estima con el máximo de plazas libres visto (cota inferior).
- **bsport**: solo dice si la clase está llena. Sirve para "% clases llenas" y "cuándo se llena", no para % ocupación.

### `web/estudios.csv`
`id, zona, estudio, marca, propio, grupo, disciplina, cadena, distancia_m, tipo_servicio, precios_publicados,
clase_suelta, cuatro_mes, ocho_mes, ilimitada, oferta_entrada, matricula, plataforma, ocupacion_medida, rating,
resenas_google, en_classpass, web, captura`

- `captura`: claves `estudio|centro_beatcore` separadas por `;` que enlazan con las capturas. Vacío = sin ocupación.
- `propio = True`: los 4 centros BeatCore (ids 901 a 904). Aún sin precios en el catálogo.
- ids 1001 a 1005: estudios que salen en Mindbody/Momence pero no estaban en el listado de Google.
- `marca`: para filtrar por cadena (Solid Studio, Club Pilates, B3B, Boutique Barre, BeatCore...). `cadena` solo dice Independiente/Cadena.
- Si se añade un estudio a `studios.json`, añadir su clave a `captura` en el catálogo.

## Especificación del dashboard

**Filtros globales** (aplican a todas las pestañas):
centro BeatCore, marca/cadena, estudio, disciplina (grupo del estudio y, mejor aún, inferida del nombre de la clase:
Reformer, Lagree, Barre, Yoga, HIIT/Funcional, Ciclo, Boxeo, Otros), día de la semana, rango de horas, rango de fechas.
Interruptor "BeatCore vs resto" para comparar siempre la línea propia con la competencia filtrada.

**Pestañas**
1. **Resumen**: KPIs y tabla BeatCore vs competencia por centro (ocupación media, % clases llenas, reservas/clase, aforo medio, nº clases).
   Tabla de **cobertura por centro**: estudios, con precios, con ocupación, con ambos, sin nada.
2. **Ocupación**: mapa de calor día × hora (BeatCore y competencia lado a lado), ranking de estudios.
3. **Curvas de reserva**: % ocupación según horas antes de la clase (checkpoints 168, 96, 72, 48, 24, 12, 6, 3, 1 y 0 h),
   usando el último snapshot anterior a cada checkpoint (con tolerancia, p. ej. máx(1 h, 50 % del checkpoint)).
   Métrica "horas antes de llenarse" (primer snapshot lleno; es cota superior; marcar si ya estaba llena en la primera foto).
4. **Clases**: tabla clase a clase, ordenable, con su curva al pulsar. Fede quiere casos concretos, no solo medias.
5. **Precios**: tabla por estudio (clase suelta, 4/mes, 8/mes, ilimitada, oferta) y medianas por centro.
6. **Estudios**: catálogo con plataforma, si tiene precio y ocupación, web.
7. **Mapa**: iframe del My Maps de Fede (`https://www.google.com/maps/d/embed?mid=...`) más enlace. Pedirle el enlace si no está en la config.
   El mapa d3 esquemático anterior **no le gustó**: no repetirlo.

**Técnica recomendada**
- `web.py`: reutiliza `analisis.cargar()` y `preparar()`, une el catálogo, calcula curvas y escribe JSON compactos
  (columnares, strings con diccionario) en `_site/data/`. Limitar a los últimos 90 días si pesa.
- `web/index.html`: HTML + JS estático (Chart.js desde cdnjs con versión fija o SVG propio). Debe verse bien en móvil.
- Despliegue: añadir al workflow `actions/upload-pages-artifact` + `actions/deploy-pages`
  (permisos `pages: write`, `id-token: write`, entorno `github-pages`).
  Fede tiene que activar una vez **Settings → Pages → Source: GitHub Actions** (el GITHUB_TOKEN no puede activarlo).
- URL resultante: `https://fedeloap.github.io/ocupacion-beatcore/`. Es pública: cualquiera con el enlace la ve.
  Si quiere restringirlo, alternativa: Cloudflare Pages + Cloudflare Access, o Vercel con contraseña.

## Cobertura actual (12/10/2026)

| Centro | Estudios | Con precios | Con ocupación | Ambos | Ninguno |
|---|---|---|---|---|---|
| Chamberí | 92 | 47 | 33 | 22 | 34 |
| Salamanca | 74 | 35 | 30 | 19 | 28 |
| Diagonal | 106 | 57 | 29 | 22 | 42 |
| Valencia | 62 | 24 | 8 | 6 | 36 |

Incluye los 4 BeatCore (con ocupación, sin precios). Competencia (sin BeatCore): 330 estudios, 163 con precios, 96 con ocupación, 69 con ambos.

## Pendiente

- Probar plataformas públicas aún no cubiertas: Wix Bookings (Into Barre, Grow Yoga, ADF, HEAT, Studio Calisthenics, WO,
  Wellness Evolution, Funcional Fun, Latte Up), YogaOne (reservas.yogaone.es), Point Barre (Acuity), Ekam (momoyoga),
  Riu Endins (viday), Prado Motion (bewe), LevelOut y Tumbao (Mindbody, widget 128024).
- Precios de BeatCore (beatcore.co/comprar-beatcore) para compararlos.
- Borrar `timp.py`, los secretos TIMP y su paso en el workflow.

## Reglas que no se negocian

- Solo datos públicos sin login. No usar credenciales de Fede (ClassPass, TIMP, etc.); si hace falta login, lo hace él.
- No saltarse Cloudflare, captchas ni protecciones anti bot. Eversports, AimHarder, Harbiz, Wodbuster, Trainingym y TIMP quedan fuera.
- No pegar tokens ni API keys en el chat ni en el repo. El PAT de cron-job.org caduca el 2027-01-09.
- Nada de introducir datos a mano: todo automático.
- Antes de inventar, preguntar. Marcar explícitamente lo que no se sabe.
