"""
apify_viral.py — Buscador de contenido viral via Apify
Busca en TikTok, YouTube e Instagram los videos más virales sobre un tema.

Uso desde Telegram:
  /viral barberia tiktok
  /viral sistema pos youtube
  /viral bodega instagram
  /viral barberia        ← busca en las 3 plataformas
"""

import json
import os
import time
import urllib.request as _ur
import urllib.error

# ── Configuración ─────────────────────────────────────────────────────────────
APIFY_TOKEN = os.getenv("APIFY_TOKEN", "")

# Actores Apify (todos gratuitos con free tier)
ACTORS = {
    "tiktok":    "clockworks/tiktok-scraper",
    "youtube":   "apify/youtube-scraper",
    "instagram": "apify/instagram-hashtag-scraper",
}

BASE_URL = "https://api.apify.com/v2"
TIMEOUT_INICIO = 30   # segundos para iniciar
TIMEOUT_ESPERA = 120  # máximo 2 min esperando resultados
POLL_INTERVAL  = 5    # revisar cada 5 seg


# ── Helpers HTTP ──────────────────────────────────────────────────────────────
def _post(url: str, body: dict) -> dict:
    data = json.dumps(body).encode()
    req  = _ur.Request(url, data=data, headers={"Content-Type": "application/json"})
    with _ur.urlopen(req, timeout=TIMEOUT_INICIO) as r:
        return json.loads(r.read())


def _get(url: str) -> dict | list:
    with _ur.urlopen(url, timeout=TIMEOUT_INICIO) as r:
        return json.loads(r.read())


# ── Construir input por plataforma ─────────────────────────────────────────────
def _input_tiktok(tema: str) -> dict:
    return {
        "searchQueries": [tema],
        "maxVideos":      8,
        "resultsPerPage": 8,
        "shouldDownloadCovers": False,
        "shouldDownloadVideos": False,
        "shouldDownloadSubtitles": False,
    }


def _input_youtube(tema: str) -> dict:
    return {
        "searchKeywords": tema,
        "maxResults":      8,
        "type":           "VIDEO",
        "gl":             "VE",
        "hl":             "es",
    }


def _input_instagram(tema: str) -> dict:
    # Instagram scraper usa hashtags — convertir tema en hashtag limpio
    hashtag = tema.replace(" ", "").lower()
    return {
        "hashtags":     [hashtag, hashtag.replace("_", "")],
        "resultsLimit":  8,
    }


# ── Iniciar un run ────────────────────────────────────────────────────────────
def _iniciar_run(plataforma: str, tema: str) -> str | None:
    """Inicia el actor y devuelve el runId."""
    actor = ACTORS[plataforma]
    url   = f"{BASE_URL}/acts/{actor}/runs?token={APIFY_TOKEN}"
    body  = {
        "tiktok":    _input_tiktok,
        "youtube":   _input_youtube,
        "instagram": _input_instagram,
    }[plataforma](tema)

    try:
        resp = _post(url, body)
        return resp.get("data", {}).get("id")
    except Exception as e:
        return None


# ── Esperar completitud ───────────────────────────────────────────────────────
def _esperar_run(run_id: str) -> bool:
    """Polling hasta que el run termine. Devuelve True si SUCCEEDED."""
    url = f"{BASE_URL}/actor-runs/{run_id}?token={APIFY_TOKEN}"
    fin = time.time() + TIMEOUT_ESPERA
    while time.time() < fin:
        try:
            data = _get(url)
            status = data.get("data", {}).get("status", "")
            if status == "SUCCEEDED":
                return True
            if status in ("FAILED", "ABORTED", "TIMED-OUT"):
                return False
        except Exception:
            pass
        time.sleep(POLL_INTERVAL)
    return False


# ── Obtener items del dataset ─────────────────────────────────────────────────
def _get_items(run_id: str) -> list:
    url = f"{BASE_URL}/actor-runs/{run_id}/dataset/items?token={APIFY_TOKEN}&limit=5&clean=true"
    try:
        data = _get(url)
        return data if isinstance(data, list) else []
    except Exception:
        return []


# ── Formatear resultados por plataforma ──────────────────────────────────────
def _formatear_tiktok(items: list, tema: str) -> str:
    if not items:
        return f"No encontré TikToks virales sobre <b>{tema}</b> ahora mismo."
    lineas = [f"🎵 <b>TikTok Viral — {tema.upper()}</b>\n"]
    for i, v in enumerate(items[:5], 1):
        titulo = (v.get("text") or v.get("desc") or "Sin título")[:80]
        vistas = v.get("playCount") or v.get("stats", {}).get("playCount", 0)
        likes  = v.get("diggCount") or v.get("stats", {}).get("diggCount", 0)
        autor  = v.get("authorMeta", {}).get("name") or v.get("author", {}).get("uniqueId", "")
        url_v  = v.get("webVideoUrl") or v.get("url", "")

        vistas_fmt = f"{vistas/1e6:.1f}M" if vistas >= 1_000_000 else (f"{vistas/1e3:.0f}K" if vistas >= 1000 else str(vistas))
        likes_fmt  = f"{likes/1e6:.1f}M"  if likes  >= 1_000_000 else (f"{likes/1e3:.0f}K"  if likes  >= 1000 else str(likes))

        lineas.append(
            f"{i}. <b>{titulo}</b>\n"
            f"   👤 @{autor}  |  👁 {vistas_fmt}  |  ❤️ {likes_fmt}\n"
            f"   🔗 {url_v}\n"
        )
    return "\n".join(lineas)


def _formatear_youtube(items: list, tema: str) -> str:
    if not items:
        return f"No encontré videos de YouTube sobre <b>{tema}</b> ahora mismo."
    lineas = [f"▶️ <b>YouTube Viral — {tema.upper()}</b>\n"]
    for i, v in enumerate(items[:5], 1):
        titulo = (v.get("title") or "Sin título")[:80]
        vistas = v.get("viewCount", 0)
        likes  = v.get("likes", 0)
        canal  = v.get("channelName") or v.get("channel", {}).get("name", "")
        url_v  = v.get("url") or f"https://youtube.com/watch?v={v.get('id','')}"

        vistas_fmt = f"{vistas/1e6:.1f}M" if vistas >= 1_000_000 else (f"{vistas/1e3:.0f}K" if vistas >= 1000 else str(vistas))

        lineas.append(
            f"{i}. <b>{titulo}</b>\n"
            f"   📺 {canal}  |  👁 {vistas_fmt}  |  ❤️ {likes}\n"
            f"   🔗 {url_v}\n"
        )
    return "\n".join(lineas)


def _formatear_instagram(items: list, tema: str) -> str:
    if not items:
        return f"No encontré posts de Instagram sobre <b>{tema}</b> ahora mismo."
    lineas = [f"📸 <b>Instagram Viral — {tema.upper()}</b>\n"]
    for i, v in enumerate(items[:5], 1):
        caption = (v.get("caption") or v.get("text") or "Sin descripción")[:80]
        likes   = v.get("likesCount") or v.get("likes", 0)
        comms   = v.get("commentsCount") or v.get("comments", 0)
        owner   = v.get("ownerUsername") or v.get("owner", {}).get("username", "")
        url_v   = v.get("url") or v.get("shortCode", "")

        likes_fmt = f"{likes/1e3:.0f}K" if likes >= 1000 else str(likes)

        lineas.append(
            f"{i}. <b>{caption}</b>\n"
            f"   👤 @{owner}  |  ❤️ {likes_fmt}  |  💬 {comms}\n"
            f"   🔗 {url_v}\n"
        )
    return "\n".join(lineas)


FORMATEADORES = {
    "tiktok":    _formatear_tiktok,
    "youtube":   _formatear_youtube,
    "instagram": _formatear_instagram,
}


# ── Función principal ─────────────────────────────────────────────────────────
def buscar_viral(tema: str, plataforma: str) -> str:
    """
    Busca contenido viral en una plataforma.
    Devuelve texto formateado HTML para Telegram.
    """
    if not APIFY_TOKEN:
        return (
            "⚠️ <b>Falta la clave Apify</b>\n\n"
            "Para activar búsquedas virales:\n"
            "1. Crea cuenta gratis en apify.com\n"
            "2. Ve a Settings → API Tokens\n"
            "3. Crea token y pégalo aquí:\n\n"
            "Abre el archivo:\n"
            "<code>C:/Users/ASUS/jarvis-profe/.env</code>\n"
            "Agrega: <code>APIFY_TOKEN=apify_api_XXXXXXXX</code>"
        )

    plataforma = plataforma.lower().strip()
    if plataforma not in ACTORS:
        return f"⚠️ Plataforma <b>{plataforma}</b> no válida. Usa: tiktok, youtube, instagram"

    run_id = _iniciar_run(plataforma, tema)
    if not run_id:
        return f"⚠️ No pude iniciar la búsqueda en {plataforma}. Revisa el token Apify."

    ok = _esperar_run(run_id)
    if not ok:
        return f"⚠️ La búsqueda en {plataforma} tardó demasiado o falló. Intenta de nuevo."

    items = _get_items(run_id)
    return FORMATEADORES[plataforma](items, tema)


def buscar_viral_todas(tema: str) -> dict[str, str]:
    """Lanza búsqueda en TikTok + YouTube + Instagram en paralelo."""
    import concurrent.futures
    resultados = {}

    def _buscar_una(plat):
        return plat, buscar_viral(tema, plat)

    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as ex:
        futuros = {ex.submit(_buscar_una, p): p for p in ACTORS}
        for f in concurrent.futures.as_completed(futuros, timeout=TIMEOUT_ESPERA + 10):
            try:
                plat, res = f.result()
                resultados[plat] = res
            except Exception as e:
                plat = futuros[f]
                resultados[plat] = f"⚠️ Error en {plat}: {e}"

    return resultados
