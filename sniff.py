"""
Segunda pasada de descubrimiento: abre cada web en un navegador (Playwright), carga la home y sus páginas de
horarios/reservas y anota las peticiones de red a plataformas de reservas. Sirve para sacar los identificadores
(host de Momence, company de bsport, branch de Glofox, tenant de Mariana Tek, box de AimHarder, site de Mindbody)
que no aparecen en el HTML estático porque el widget se monta con JavaScript.

Solo carga páginas públicas (como cualquier visitante). No hace login ni salta protecciones: si una web
muestra un desafío anti-bot, se anota y se deja.
Salida: web/cadenas_red.json
"""

import asyncio
import json
import os
import re
import sys
from urllib.parse import urljoin, urlparse

from playwright.async_api import async_playwright

PLAT = re.compile(r"momence\.com|bsport\.io|bsport\.fr|mindbody|healcode|glofox\.com|marianatek\.com|aimharder\.com|"
                  r"wodbuster|harbiz|trainingym|timp\.pro|eversports|virtuagym|bookeo|fitogram|momoyoga", re.I)
CLAVE = re.compile(r"horario|reserv|schedul|clase|book|calend|agenda|class|timetable|sesion|actividad", re.I)
MAX_LINKS = 4


def extraer(urls, cuerpos):
    t = "\n".join(urls + cuerpos)
    out = {}
    out["momence"] = sorted(set(re.findall(r"momence\.com/[^\s\"']*?host(?:-plugins/host)?/(\d{3,8})", t)) |
                            set(re.findall(r"host[_-]?id[=\":\s]+(\d{3,8})", t, re.I)))
    out["bsport"] = sorted(set(re.findall(r"bsport\.io/[^\s\"']*?company[=/](\d{2,7})", t)) |
                           set(re.findall(r"[?&]company=(\d{2,7})", t)))
    out["glofox"] = sorted(set(re.findall(r"glofox\.com/[^\s\"']*?branch/([0-9a-f]{24})", t)) |
                           set(re.findall(r"/branch/([0-9a-f]{24})", t)))
    out["marianatek"] = sorted(set(re.findall(r"https?://([a-z0-9\-]+)\.marianatek\.com", t)) - {"www", "api"})
    out["aimharder"] = sorted(set(re.findall(r"https?://([a-z0-9\-]+)\.aimharder\.com", t)) - {"www", "app", "api"})
    out["mindbody"] = sorted(set(re.findall(r"mb_site_id\\?\"?[:=]\s*\\?\"?(\d{4,8})", t)) |
                             set(re.findall(r"(?:studioid|siteId|siteID)=(\d{4,8})", t)))
    return {k: v for k, v in out.items() if v}


async def sniff(ctx, cadena, web, sem):
    async with sem:
        urls, cuerpos, estado = [], [], "ok"
        page = await ctx.new_page()

        def on_req(req):
            if PLAT.search(req.url):
                urls.append(req.url)
                try:
                    pd = req.post_data
                    if pd and PLAT.search(req.url):
                        cuerpos.append(pd)
                except Exception:
                    pass

        page.on("request", on_req)
        try:
            # "load" + espera corta: varias webs nunca llegan a networkidle (analítica, mapas, vídeos)
            await page.goto(web, wait_until="load", timeout=60000)
            await page.wait_for_timeout(6000)
            html = await page.content()
            titulo = (re.search(r"<title[^>]*>(.*?)</title>", html, re.S | re.I) or [None, ""])[1]
            # desafío real de Cloudflare u otro: título característico o marcas del desafío (no basta la palabra "captcha",
            # que sale en casi todos los formularios de contacto)
            if re.search(r"just a moment|attention required|un momento|verifying you are human|cf-chl|challenge-platform/h/b", titulo + html[:6000], re.I):
                estado = "desafio anti-bot"
            else:
                cuerpos.append(html)
                enlaces = []
                for href in await page.eval_on_selector_all("a[href]", "els => els.map(e => e.href)"):
                    if urlparse(href).netloc.replace("www.", "") == urlparse(page.url).netloc.replace("www.", "") and CLAVE.search(href):
                        if href not in enlaces and href != page.url:
                            enlaces.append(href)
                for u in enlaces[:MAX_LINKS]:
                    try:
                        await page.goto(u, wait_until="load", timeout=45000)
                        await page.wait_for_timeout(4000)
                        cuerpos.append(await page.content())
                    except Exception:
                        continue
                for fr in page.frames:
                    if PLAT.search(fr.url):
                        urls.append(fr.url)
        except Exception as e:
            estado = f"error {type(e).__name__}"
        finally:
            await page.close()
        return {"cadena": cadena, "web": web, "estado": estado, "peticiones": len(urls), "ids": extraer(urls, cuerpos),
                "dominios": sorted({urlparse(u).netloc for u in urls})[:12]}


async def main(salida="web/cadenas_red.json"):
    inv = json.load(open("web/cadenas_inventario.json", encoding="utf-8"))["filas"]
    tareas = [(f["cadena"], f["web"]) for f in inv if f.get("web") and f.get("estado") == "ok"]
    previo = {}
    if os.path.exists(salida):
        previo = {r["cadena"]: r for r in json.load(open(salida, encoding="utf-8"))["cadenas"]}
    if os.environ.get("SNIFF_SOLO") == "pendientes":
        # solo las nuevas y las que dieron error o tiempo agotado (los desafíos anti-bot no se reintentan)
        # (los "desafío anti-bot" de la primera pasada se repiten: el detector anterior daba falsos positivos)
        tareas = [(c, w) for c, w in tareas if c not in previo or previo[c]["estado"].startswith("error")
                  or previo[c]["estado"] == "desafio anti-bot"]
        print(len(tareas), "webs pendientes")
    sem = asyncio.Semaphore(4)
    async with async_playwright() as p:
        import glob
        # en Windows puede haber solo el Chromium completo (sin "headless shell"): se usa si existe
        exe = (glob.glob(os.path.expandvars(r"%LOCALAPPDATA%\ms-playwright\chromium-*\chrome-win64\chrome.exe")) or [None])[-1]
        browser = None
        for opts in ({"executable_path": exe} if exe else None, {"channel": "msedge"}, {"channel": "chrome"}, {}):
            if opts is None:
                continue
            try:
                browser = await p.chromium.launch(**opts)
                break
            except Exception as e:
                print("no arranca con", opts, type(e).__name__, file=sys.stderr)
        if browser is None:
            raise SystemExit("No hay navegador disponible para Playwright")
        ctx = await browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                                                   "(KHTML, like Gecko) Chrome/130.0 Safari/537.36", locale="es-ES")
        res = await asyncio.gather(*[sniff(ctx, c, w, sem) for c, w in tareas])
        await browser.close()
    previo.update({r["cadena"]: r for r in res})
    res = list(previo.values())
    json.dump({"cadenas": res}, open(salida, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    con = [r for r in res if r["ids"]]
    print(f"{len(res)} webs; con identificadores: {len(con)}")
    cnt = {}
    for r in con:
        for k in r["ids"]:
            cnt[k] = cnt.get(k, 0) + 1
    print(cnt)


if __name__ == "__main__":
    asyncio.run(main(*(sys.argv[1:2])))
