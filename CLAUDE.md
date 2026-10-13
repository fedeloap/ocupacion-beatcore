# CLAUDE.md · Ocupación y competencia BeatCore

Contexto para Claude Code. Responde siempre en español, directo y conciso, sin guiones largos.
Usuario: Fede (The Boutique Tribe / WEC). Analiza la competencia de **BeatCore**, cadena de reformer con 4 centros:
Chamberí (Madrid), Salamanca (Madrid), Diagonal (Barcelona) y Ruzafa (Valencia, zona "Valencia" en los datos).
Ojo: el dictado por voz escribe "Bitcoin", "Beatcore", "Team" (= TIMP), "Einhard" (= AimHarder), "Bootbuster" (= Wodbuster), "Distrito"... Interpreta con el contexto.

Cómo le gusta trabajar a Fede (aprendido en sesión):
- Textos de ayuda en la web: viñetas cortas y claras, a todo el ancho, **sin el título "Cómo leer…"**. Si algo le marea, lo quita: simplicidad ante todo.
- Quiere casos concretos y datos por centro, no solo medias (una media de cadena puede esconder un centro que va mal).
- Quiere **todo automático**; lo que no se sabe se deja en blanco y se dice. No inventar: preguntar.
- Prefiere que yo haga el trabajo (Vercel, commits, despliegues) y le cuente el resultado. Confirma con capturas de pantalla.

## Qué hay construido

**Web con contraseña** en Vercel: **https://analisis-beatcore.vercel.app** (proyecto `analisis-beatcore`, cuenta "Fede's projects",
repo `fedeloap/ocupacion-beatcore`, rama `main`). Se regenera sola 3 veces al día desde GitHub Actions y se despliega solo
cuando el último commit lleva `[deploy]` en el mensaje (`vercel.json` → `ignoreCommand`).

**Pestañas** (`web/index.html`, un solo fichero HTML+JS, Chart.js 4.4.1 desde cdnjs):
Resumen · Ocupación · Oferta · Ritmo de reserva · Clases · Próximas clases · Precios · Estudios · Cadenas · Mapa.
Filtros globales arriba (centro, marca, estudio, disciplina, horas, fechas, días, festivos). "BeatCore siempre visible"
ignora marca/estudio/disciplina para dar perspectiva. Los datos se cargan de `public/data/*.json`.

## Estructura del repo

| Ruta | Qué es |
|---|---|
| `capture.py` | Captura desde agendas públicas (Momence, Mindbody, bsport, Glofox, Mariana Tek, AimHarder, Trainingym). La lanza el workflow cada 30 min |
| `studios.json` | Estudios de la competencia en el radio de BeatCore (con `centro_beatcore`). BeatCore lleva `"propio": true` |
| `studios_cadenas.json` | Centros de cadenas nacionales (sin `centro_beatcore`). Solo se capturan en ocupación final y plan; lo genera `fuentes_build.py` |
| `analisis.py` | `cargar()` + `preparar()` (ocupación final por clase), informe HTML y CSV en `reports/` (excluye festivos; la web NO) |
| `web.py` | Genera `public/` (index.html, robots.txt y JSON). Une catálogo, curvas, próximas clases, oferta y cadenas |
| `web/index.html` | Fuente de la web. **Se edita aquí, nunca en `public/`** |
| `web/estudios.csv` | Catálogo maestro (333 filas): precios, plataforma, marca, cobertura, enlace con la captura |
| `web/precios_beatcore.json` | Precios de BeatCore (aportados a mano por Fede el 12/10/2026; membresías mensuales) |
| `web/excluidos.json` | Estudios que Fede no quiere (no boutique). Hoy: Centro MaNá |
| `web/config.json` | `mapa_url` (My Maps embebido) |
| `web/cadenas_lista.txt` | Lista de cadenas de Fede (149). `web/cadenas_webs.csv`: su web oficial |
| `web/cadenas_inventario.json` | Salida de `cadenas.py`: software, centros estimados, importes de su web con etiqueta |
| `web/cadenas_centros.json` | Salida de `centros.py` + `centros_es.py`: centros de España de cada cadena con su id de agenda |
| `web/cadenas_fuentes*.json`, `web/cadenas_red.json` | Descubrimiento de agendas (HTML, profundo, red). Entradas de `fuentes_build.py` |
| `web/cadenas_fuentes_manual.json` | Fuentes localizadas a mano (Siclo por Mindbody, Trainingym de Action Black y Space by 9F) |
| `data/YYYY-MM-DD.csv` | Capturas "finales": clases a punto de empezar (última foto antes del inicio) |
| `data/curva/YYYY-MM-DD.csv` | Cada captura guarda las clases de las próximas 6 h (curva fina). Solo zonas BeatCore |
| `data/plan/YYYY-MM-DD[_m|_t].csv` | Dos veces al día: clases de los próximos 7 días (curva larga y oferta). Incluye cadenas nacionales |
| `.github/workflows/capture.yml` | Captura + regeneración de `public/` (05:38, 12:38 y 20:38 UTC) + commit. Lo dispara cron-job.org |
| `middleware.js`, `vercel.json` | Contraseña (pantalla de acceso sin usuario, cookie firmada 30 días) y despliegue |
| `timp.py` | Abandonado (TIMP requiere login). No usar ni ampliar |

Scripts de descubrimiento (se ejecutan a mano, en este orden):
`cadenas.py` (inventario de webs) → `fuentes.py` / `sniff.py` (navegador; usa Edge vía Playwright en Windows) /
`fuentes_profundo.py` / `centros.py` + `centros_es.py` (todos los centros de España por sitemap, filtrados por JSON-LD) →
`fuentes_build.py` (verifica y escribe `studios_cadenas.json`) → `python web.py`.

### Columnas de las capturas (`data/**.csv`)
`captured_at, plataforma, estudio, centro_beatcore, sede, clase_id, clase, inicio_local, duracion_min, capacidad,
ocupadas, libres, libres_web, llena, cancelada, lista_espera`. Hora local de Madrid.
Clave de clase: `(plataforma, estudio, sede, clase_id)`. **En Mindbody el `clase_id` cambia entre capturas**: se usa
`estudio|sede|inicio|clase` (`web.clave_clase`). Sin `centro_beatcore` = cadena nacional (zona "Nacional" en la web).

Particularidades por plataforma:
- **Momence, Glofox, Mariana Tek, AimHarder, Trainingym**: aforo y reservas publicados.
- **Mindbody**: a veces no publica aforo; se estima con el máximo de plazas libres visto (cota inferior). Muchas clases quedan sin aforo.
- **bsport**: solo dice si la clase está llena: cuenta en "% llenas" y oferta, no en % ocupación.
- **Glofox**: sesión de invitado del portal público (`POST api.glofox.com/2.0/login` con GUEST), sin navegador.
- **Trainingym**: `center.trainingym.com/api/v1/public/center/<centro>` da el token y `booking.trainingym.com/api/v2/calendar/totem/notauth` el calendario (máx. ~6 días por consulta).
- **AimHarder**: `https://<box>.aimharder.com/api/bookings?day=AAAAMMDD&familyId=&box=<id>` (`limit` y `ocupation`).

## Decisiones y definiciones de métricas

- **Festivos**: la web los incluye (el 12/10 hay clases); hay interruptor "Incluir festivos". `analisis.py` los sigue excluyendo.
- **Semana tipo** (pestaña Oferta y Cadenas): suma de la media de cada día de la semana. Solo cuentan días completos
  (de la primera planificación del estudio + 1 día hasta la última planificación + 6). Festivos sin clases no cuentan.
- **% cubierto / ocupación en oferta**: reservas / plazas de clases ya dadas con aforo y reservas conocidos (ponderada por plazas).
  Las clases sin aforo cuentan como clases, no como plazas (plazas ofertadas = mínimo).
- **Ritmo de reserva**: ocupación a 24 h, 6 h, 1 h y al empezar por estudio. Se quitó la curva agregada (mezclaba clases distintas) y el
  "% de lo final ya reservado" (confundía). "Horas antes de llenarse" sigue (cota superior).
- **Disciplina de clase**: regex sobre el nombre en `web.py` (`REGLAS`); si no dice nada, la del estudio en el catálogo.
- **Cadenas**: precio = mediana del catálogo (zonas BeatCore); si falta, el leído en su web (marcado "leído en su web").
- **Cadenas son nacionales**: Fede quiere **todos los centros de España de cada cadena** (Club Pilates ~45, Brooklyn ~200, Sano ~80...),
  no solo los cercanos a BeatCore. La pestaña Cadenas es para ver cómo van las cadenas en general (y posibles compras), no solo comparar con BeatCore.

## Estado del descubrimiento de centros (13/10/2026)

142 estudios de cadenas en `studios_cadenas.json` (Club Pilates 41, Pilat3s ~19, Nexes 13, Batard 8, F45 7, FS8 2, Flow Training 4,
180 Training Club 3, Action Black/Space by 9F 4, B3B, Arde Barre, Trib3, Edan, Siclo, Denovo, Gratia...).
Captura nacional en paralelo (`capture_par`): ~80 s la ventana de 30 min y ~140 s el plan a 7 días.

Sin agenda pública utilizable: **TIMP** (web Flutter sin datos), **Wodbuster** (solo registro de invitado), **Provis** (login),
**Virtuagym**, **Commando** (API con clave: no se usa; las claves no van al repo). Cadenas con su propia app (Brooklyn, BZ55, F45 app,
Distrito y Sano por AimHarder app...): se puede contar centros, no clases.

## Pendiente

1. **Cobertura de centros por cadena**: tabla "centros que dice su web / centros con agenda capturada" para ver dónde faltan.
   44 de las 149 webs no tienen sitemap con fichas de centro. Mostrar la lista de centros de cada cadena aunque no tenga agenda.
2. **Distrito y Sano** (AimHarder por app): Fede busca el enlace de reserva (`algo.aimharder.com`) para localizar sus boxes (Sano ~80 centros).
3. **PlayGym** (bsport; falta el `company`), **House of Balance** (Mindbody widgets), webs que no responden: Heltia corregida a `heltia.es/es`.
4. **Pilat3s**: los hosts de Momence mezclan España, Portugal, Países Bajos y Reino Unido; separar por sede.
5. Mapa de calor de oferta por cadena y por centro: ya hecho; vigilar el tamaño de `oferta.json` (453 KB) al crecer.
6. Fede intentará sacar datos de TIMP/AimHarder con otra cuenta y pasarlos: preparar un **importador de CSV** (columnas de las capturas) si llega.
7. Pedirle qué debe pedir en las negociaciones de compra (data room): ocupación real, asistencia.
8. Clase suelta de BeatCore Diagonal (27 €) y Valencia (22 €) ya están; automatizar precios de BeatCore desde beatcore.co.
9. Borrar `timp.py`, los secretos TIMP y su paso en el workflow.
10. Filtrar no boutique (natación, escuelas infantiles) en la competencia: Fede quitó Centro MaNá; ofrecerle revisar el resto.

## Vercel

- Salida `public/`, sin framework ni build. `DASHBOARD_PASSWORD` la define Fede en el panel de Vercel (**nunca en el repo ni en el chat**).
  `DASHBOARD_USER` ya no se usa. Sin contraseña configurada la web queda cerrada.
- El workflow commitea `public/` con `[deploy]` solo en las 3 regeneraciones; las capturas no despliegan.
  Si un `git pull --rebase` da conflicto en `public/data/*.json` (el Action regenera a la vez): quedarse con la propia (`git checkout --theirs`),
  continuar el rebase, volver a ejecutar `python web.py` y subir.
- Dominios: `analisis-beatcore.vercel.app` (principal) y `ocupacion-beatcore.vercel.app` (antiguo). Plan Hobby: uso comercial, en rigor Pro; lo decide Fede.
- No pasar el repo a privado sin avisar (Actions gratis en privado: 2.000 min/mes y la captura consume más).
- Repo **público**: decisión de Fede (12/10/2026). La contraseña protege la web, no los CSV.

## Cobertura del catálogo (12/10/2026)

| Centro | Estudios | Con precios | Con ocupación | Ambos | Ninguno |
|---|---|---|---|---|---|
| Chamberí | 92 | 47 | 33 | 22 | 34 |
| Salamanca | 74 | 35 | 30 | 19 | 28 |
| Diagonal | 106 | 57 | 29 | 22 | 42 |
| Valencia | 62 | 24 | 8 | 6 | 36 |

## Reglas que no se negocian

- Solo datos públicos **sin login ni credenciales de nadie**. No usar cuentas de Fede (ClassPass, TIMP, etc.); si hace falta login, lo hace él.
  Las sesiones de invitado que abre el propio portal público (Glofox) para cualquier visitante sí valen.
- **No saltarse Cloudflare, captchas, desafíos anti-bot ni claves de acceso.** Decisión de Fede (13/10/2026): no se excluye ninguna plataforma
  *por definición*; se prueba con todas, y solo se usa lo que responde público. Nada de recomendar herramientas para evadir protecciones.
- No pegar tokens ni API keys en el chat ni en el repo. El PAT de cron-job.org caduca el 2027-01-09.
- Los datos de BeatCore y de precios aportados a mano por Fede están en `web/precios_beatcore.json`; lo demás, automático.
- Antes de inventar, preguntar. Marcar explícitamente lo que no se sabe.
- Commits: terminar el mensaje con la línea de coautoría que indique la sesión; añadir `[deploy]` solo cuando haya que desplegar la web.
