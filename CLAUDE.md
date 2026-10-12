# CLAUDE.md · Ocupación y competencia BeatCore

Contexto para Claude Code. Responde siempre en español, directo y conciso, sin guiones largos.
Usuario: Fede (The Boutique Tribe / WEC). Analiza la competencia de **BeatCore**, cadena de reformer con 4 centros:
Chamberí (Madrid), Salamanca (Madrid), Diagonal (Barcelona) y Ruzafa (Valencia, zona "Valencia" en los datos).
Ojo: el dictado por voz escribe "Bitcoin" o "Beatcore" cuando quiere decir BeatCore.

## Objetivo inmediato

Construir un **dashboard web** para compartir con gente externa (que no usa Claude), publicado en **Vercel**
con **contraseña**, y regenerado automáticamente a partir de los datos que captura GitHub Actions.
Decisión de Fede (12/10/2026): **el repo sigue público**. La contraseña protege la web, no los CSV del repo; lo sabe y lo acepta.

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
  (columnares, strings con diccionario) en `public/data/`. Limitar a los últimos 90 días si pesa.
- `web/index.html`: HTML + JS estático (Chart.js desde cdnjs con versión fija o SVG propio). Debe verse bien en móvil.
- Todas las rutas de datos son relativas (`data/...`) para que la web funcione igual en local y en Vercel.

## Despliegue en Vercel (decidido)

**Generación del sitio**
- El JSON lo genera `web.py` dentro de GitHub Actions (Python ya está instalado ahí), no en el build de Vercel.
- Salida en `public/` (index.html + `public/data/*.json`), commiteada al repo. Vercel solo sirve estáticos:
  sin framework, sin build command, output directory `public`.
- Regenerar `public/` unas 3 veces al día (p. ej. tras la captura de las 7:38, 14:38 y 22:38 hora Madrid) o en cada captura,
  pero **sin desplegar 38 veces al día**.

**Estado (12/10/2026): construido, pendiente de que Fede lo conecte en Vercel.**
- `web.py` genera `public/` (lee `web/index.html`, `web/robots.txt`, `web/config.json`). En local: `python web.py` y
  `python -m http.server 8765 --directory public`. El interruptor/ficheros fuente se editan en `web/`, nunca en `public/`.
- Opción elegida: **1 (`ignoreCommand` + `[deploy]`)**, en `vercel.json`. El workflow regenera `public/` en las capturas
  de 05:38, 12:38 y 20:38 UTC (7:38, 14:38 y 22:38 en horario de verano; una hora menos en invierno) o a mano
  (Actions → Run workflow → regenerar = 1), y ese commit lleva `[deploy]`.
- Contraseña: `middleware.js` (pantalla de acceso solo con contraseña, sin usuario, cookie firmada de 30 días, cubre todas las rutas
  incluido `data/*.json`). Si `DASHBOARD_PASSWORD` no existe, la web queda cerrada. `DASHBOARD_USER` ya no se usa.
  Cambiar la contraseña invalida las sesiones abiertas.
- Enlace del My Maps: `web/config.json` → `mapa_url`. **Falta que Fede lo dé.**
- Disciplina de clase: regex sobre el nombre en `web.py` (`REGLAS`); si no dice nada, la del estudio en el catálogo.
  Pilates sin la palabra "reformer" cae en la disciplina del estudio (puede ser mat).
- Ficheros JSON: `public/data/clases.json` (columnar), `estudios.json`, `meta.json`. 90 días máximo.

**Evitar un despliegue por cada commit de captura** (elige una y documéntala aquí):
1. `vercel.json` con `ignoreCommand` que solo deje construir si el último commit lleva `[deploy]` en el mensaje
   (recordar: en Vercel, salida 0 = se salta el build, salida 1 = construye). El paso de regeneración del Action commitea con `[deploy]`.
2. O desactivar el despliegue automático por git (`"git": {"deploymentEnabled": false}`) y lanzar un **Deploy Hook**
   desde el Action con `curl -X POST "$VERCEL_DEPLOY_HOOK"`. El hook va como secreto de GitHub `VERCEL_DEPLOY_HOOK`.
   No verificado si los Deploy Hooks funcionan con `deploymentEnabled: false`: comprobarlo antes de dar por buena esta opción.

**Contraseña**
- No usar la "Password Protection" nativa de Vercel (es un extra de pago).
- Usar **Vercel Routing Middleware** (`middleware.js` en la raíz, sirve para proyectos estáticos sin Next.js) con HTTP Basic Auth,
  o una pantalla de login simple que ponga una cookie firmada.
- El middleware debe cubrir **todas** las rutas, incluidos `data/*.json`, no solo `index.html`.
- La contraseña va en la variable de entorno de Vercel `DASHBOARD_PASSWORD` (y usuario en `DASHBOARD_USER` si es Basic Auth).
  **La define Fede en el panel de Vercel**. Nunca en el repo ni en el chat.
- Comparar la contraseña en tiempo constante y devolver 401 con `WWW-Authenticate` si falla.
- Añadir `X-Robots-Tag: noindex` y un `robots.txt` que bloquee todo.

**Pasos que hace Fede (Claude Code no puede ni debe hacerlos por él)**
1. En vercel.com: Add New → Project → importar `fedeloap/ocupacion-beatcore`. Framework "Other", output directory `public`.
2. Settings → Environment Variables: `DASHBOARD_PASSWORD` (y `DASHBOARD_USER`). Redesplegar.
3. Si se usa la opción 2: crear el Deploy Hook en Settings → Git y guardarlo como secreto `VERCEL_DEPLOY_HOOK` en GitHub.
4. Opcional: dominio propio (p. ej. `competencia.theboutiquetribe.com`) en Settings → Domains.

**Avisos**
- El plan Hobby de Vercel es para uso no comercial según sus condiciones. Este uso es comercial: en rigor corresponde Pro. Lo decide Fede.
- No pasar el repo a privado sin avisar: GitHub Actions gratis en privado da 2.000 min/mes y la captura consume unos 3.400.

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
- Precios de BeatCore: HECHO a mano (12/10/2026, capturas de Fede) en `web/precios_beatcore.json`; `web.py` los une al catálogo.
  Pendiente: automatizarlos desde beatcore.co/comprar-beatcore y confirmar si son membresías mensuales o bonos. Falta el
  ilimitado de Chamberí y la clase suelta (pestaña "Drop in").
- Borrar `timp.py`, los secretos TIMP y su paso en el workflow.

## Reglas que no se negocian

- Solo datos públicos sin login. No usar credenciales de Fede (ClassPass, TIMP, etc.); si hace falta login, lo hace él.
- No saltarse Cloudflare, captchas ni protecciones anti bot. Eversports, AimHarder, Harbiz, Wodbuster, Trainingym y TIMP quedan fuera.
- No pegar tokens ni API keys en el chat ni en el repo. El PAT de cron-job.org caduca el 2027-01-09.
- Nada de introducir datos a mano: todo automático.
- Antes de inventar, preguntar. Marcar explícitamente lo que no se sabe.
