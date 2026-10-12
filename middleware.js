// Vercel Routing Middleware: HTTP Basic Auth para TODAS las rutas (incluido data/*.json).
// Usuario y contraseña vienen de las variables de entorno DASHBOARD_USER y DASHBOARD_PASSWORD
// (se definen en el panel de Vercel, nunca en el repo).

export const config = {
  matcher: "/:path*",
};

function iguales(a, b) {
  // Comparación en tiempo constante (sobre la longitud del mayor de los dos).
  const n = Math.max(a.length, b.length);
  let diff = a.length ^ b.length;
  for (let i = 0; i < n; i++) {
    diff |= (a.charCodeAt(i) || 0) ^ (b.charCodeAt(i) || 0);
  }
  return diff === 0;
}

function noAutorizado() {
  return new Response("Acceso restringido", {
    status: 401,
    headers: {
      "WWW-Authenticate": 'Basic realm="Competencia BeatCore", charset="UTF-8"',
      "X-Robots-Tag": "noindex, nofollow",
      "Cache-Control": "no-store",
    },
  });
}

export default function middleware(request) {
  const pass = process.env.DASHBOARD_PASSWORD;
  const user = process.env.DASHBOARD_USER || "";
  // Sin contraseña configurada: cerrado (nunca abrir por error).
  if (!pass) return noAutorizado();

  const cabecera = request.headers.get("authorization") || "";
  if (!cabecera.startsWith("Basic ")) return noAutorizado();

  let usuario = "";
  let clave = "";
  try {
    const bytes = Uint8Array.from(atob(cabecera.slice(6).trim()), (c) => c.charCodeAt(0));
    const decodificado = new TextDecoder("utf-8").decode(bytes);
    const i = decodificado.indexOf(":");
    if (i < 0) return noAutorizado();
    usuario = decodificado.slice(0, i);
    clave = decodificado.slice(i + 1);
  } catch {
    return noAutorizado();
  }

  const okClave = iguales(clave, pass);
  const okUsuario = user ? iguales(usuario, user) : true;
  if (!(okClave && okUsuario)) return noAutorizado();

  // undefined: deja pasar la petición al contenido estático.
}
