// Vercel Routing Middleware: pantalla de acceso con contraseña (sin usuario) para TODAS las rutas,
// incluido data/*.json. La contraseña viene de DASHBOARD_PASSWORD (se define en Vercel, nunca en el repo).
// Tras acertar se guarda una cookie firmada (HMAC) de 30 días. Si cambia la contraseña, las cookies caducan solas.

export const config = {
  matcher: "/:path*",
};

const COOKIE = "beatcore_auth";
const DIAS = 30;
const encoder = new TextEncoder();

function iguales(a, b) {
  // Comparación en tiempo constante (sobre la longitud del mayor de los dos).
  const n = Math.max(a.length, b.length);
  let diff = a.length ^ b.length;
  for (let i = 0; i < n; i++) {
    diff |= (a.charCodeAt(i) || 0) ^ (b.charCodeAt(i) || 0);
  }
  return diff === 0;
}

async function firma(pass) {
  const key = await crypto.subtle.importKey("raw", encoder.encode(pass), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  const sig = await crypto.subtle.sign("HMAC", key, encoder.encode("beatcore-dashboard-v1"));
  return [...new Uint8Array(sig)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

function leerCookie(request, nombre) {
  const c = request.headers.get("cookie") || "";
  for (const parte of c.split(";")) {
    const i = parte.indexOf("=");
    if (i > 0 && parte.slice(0, i).trim() === nombre) return parte.slice(i + 1).trim();
  }
  return "";
}

const CABECERAS = {
  "Content-Type": "text/html; charset=utf-8",
  "X-Robots-Tag": "noindex, nofollow",
  "Cache-Control": "no-store",
};

function pagina(error) {
  const html = `<!doctype html>
<html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow"><title>Acceso · Competencia BeatCore</title>
<style>
:root{--bg:#f6f7f5;--surface:#fff;--fg:#1d2724;--muted:#5d6b66;--line:#dde3e0;--accent:#0f6b5c}
@media (prefers-color-scheme:dark){:root{--bg:#121816;--surface:#19211e;--fg:#e5ece9;--muted:#9aaba5;--line:#2b3632;--accent:#5fc4b0;color-scheme:dark}}
*{box-sizing:border-box}body{margin:0;min-height:100vh;display:grid;place-items:center;padding:16px;background:var(--bg);color:var(--fg);font:16px/1.5 system-ui,"Segoe UI",sans-serif}
form{width:100%;max-width:340px;background:var(--surface);border:1px solid var(--line);border-radius:8px;padding:24px;display:grid;gap:12px}
.e{margin:0;font-size:12px;letter-spacing:.08em;text-transform:uppercase;color:var(--accent);font-weight:600}
h1{margin:0;font-size:22px;line-height:1.2}
input{font:inherit;color:var(--fg);background:var(--bg);border:1px solid var(--line);border-radius:6px;padding:10px;min-height:44px;width:100%}
button{font:inherit;font-weight:600;color:#fff;background:var(--accent);border:0;border-radius:6px;padding:10px;min-height:44px;cursor:pointer}
@media (prefers-color-scheme:dark){button{color:#0b1210}}
.err{margin:0;color:#b42318;font-size:14px}
</style></head><body>
<form method="post" autocomplete="off">
<p class="e">The Boutique Tribe</p><h1>Competencia BeatCore</h1>
<label for="p" style="font-size:14px;color:var(--muted)">Contraseña</label>
<input id="p" name="password" type="password" required autofocus autocomplete="current-password">
${error ? '<p class="err">Contraseña incorrecta</p>' : ""}
<button type="submit">Entrar</button>
</form></body></html>`;
  return new Response(html, { status: 401, headers: CABECERAS });
}

export default async function middleware(request) {
  const pass = process.env.DASHBOARD_PASSWORD;
  // Sin contraseña configurada: cerrado (nunca abrir por error).
  if (!pass) return new Response("Acceso restringido", { status: 401, headers: CABECERAS });

  const esperado = await firma(pass);
  if (iguales(leerCookie(request, COOKIE), esperado)) return; // autorizado: sigue al contenido estático

  if (request.method === "POST") {
    let clave = "";
    try {
      clave = String((await request.formData()).get("password") || "");
    } catch {
      return pagina(true);
    }
    if (iguales(clave, pass)) {
      return new Response(null, {
        status: 303,
        headers: {
          Location: new URL(request.url).pathname,
          "Set-Cookie": `${COOKIE}=${esperado}; Max-Age=${DIAS * 86400}; Path=/; HttpOnly; Secure; SameSite=Lax`,
          "Cache-Control": "no-store",
        },
      });
    }
    return pagina(true);
  }

  // Peticiones de datos sin sesión: 401 seco. Navegador: pantalla de acceso.
  const acepta = request.headers.get("accept") || "";
  if (!acepta.includes("text/html")) {
    return new Response("Acceso restringido", { status: 401, headers: { ...CABECERAS, "Content-Type": "text/plain; charset=utf-8" } });
  }
  return pagina(false);
}
