"""
telegram_bridge.py — Puente bidireccional Telegram ↔ Jarvis Mente Maestra.

Seguridad:
  - Solo procesa mensajes cuyo chat_id coincida exactamente con TELEGRAM_CHAT_ID del .env.
  - Cualquier otro origen es rechazado en silencio (log de advertencia).

Arquitectura:
  - Corre en hilo daemon con su propio event loop asyncio → no bloquea la GUI tkinter.
  - Callbacks inyectados en iniciar() para desacoplar este módulo de la GUI.

Dependencias:
  pip install python-telegram-bot pydub SpeechRecognition pyautogui
  (pydub requiere ffmpeg en PATH para transcribir audio)
"""

import asyncio
import json
import os
import tempfile
import threading
from pathlib import Path
from pathlib import Path

try:
    from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
    from telegram.ext import (
        ApplicationBuilder,
        CommandHandler,
        ContextTypes,
        MessageHandler,
        filters,
    )
    _TELEGRAM_OK = True
except ImportError:
    _TELEGRAM_OK = False

# ── Estado interno ────────────────────────────────────────────────────────────
_hilo: threading.Thread | None = None


# ══════════════════════════════════════════════════════════════════════════════
#  Helpers
# ══════════════════════════════════════════════════════════════════════════════

def _log(fn, msg: str, tag: str = "info"):
    if fn:
        try:
            fn(msg, tag)
        except Exception:
            print(msg)
    else:
        print(msg)


PRECIOS_URL = "https://www.a2kdigitalstudio.online/precios.html"
# Si el mensaje menciona un producto ZYNC específico, dejamos que el flujo
# normal (on_texto → ComandoParser / IA) responda el precio puntual.
_ZYNC_KEYWORDS = ("smartwatch", "smart watch", "reloj", "watch", "microfono",
                  "micrófono", "k9", "audifono", "audífono", "airmax", "combo")
_PRECIOS_KEYWORDS = (
    # preguntas genéricas de precio
    "precio", "precios", "cuanto cuesta", "cuánto cuesta", "quiero contratar",
    "servicios", "lista de precios", "tabla de precios", "tarifas", "costos",
    # nombres de trabajos concretos del catálogo de diseño
    "volante", "flyer", "tarjeta de presentacion", "tarjetas de presentación",
    "publicacion", "publicación", "edicion de fotos", "edición de fotos",
    "landing page", "landing", "branding", "video promocional",
    "presentacion corporativa", "presentación corporativa",
    "pagina web", "página web", "sitio web", "bot de ventas",
    "pack de marketing", "asistente virtual", "catalogo digital",
    "catálogo digital", "imagen de marca", "automatizacion integral",
    "automatización integral", "desarrollo web", "ecosistema de bots",
    "e-commerce", "ecommerce", "tienda online", "logo", "logotipo",
    "diseño grafico", "diseño gráfico", "identidad visual",
    "manual de marca", "mockup",
)


def _es_consulta_precios_servicios(texto: str) -> bool:
    lower = texto.lower()
    if any(z in lower for z in _ZYNC_KEYWORDS):
        return False
    return any(k in lower for k in _PRECIOS_KEYWORDS)


# ── Precios exactos verificados en vivo en a2kdigitalstudio.online/precios.html
# (2026-07-20) — se responden puntuales en vez del resumen genérico por nivel.
_PRECIOS_ESPECIFICOS = (
    (
        ("edicion de fotos", "edición de fotos", "editar fotos", "editar foto"),
        "🖼️ Edición de fotos básica: $5\n"
        "Corrección de color · recorte · limpieza de fondo · hasta 3 fotos",
    ),
    (
        ("flyer", "flyers", "volante", "volantes"),
        "📋 Flyers / Volantes:\n"
        "• Básico: $10–$18 (1 diseño, texto promocional, logo, 1 ajuste, entrega 24h)\n"
        "• Profesional: $20–$35 (diseño avanzado, copywriting, iconografía, 2 ajustes, 48h)",
    ),
    (
        ("landing page", "landing"),
        "🌐 Landing page:\n"
        "• Básica: $40–$80 (1 sección, responsive, formulario, hosting Vercel gratis, SEO básico)\n"
        "• Alto impacto: $80–$150 (estructura AIDA, copy persuasivo, CTA, contador, testimonios, pago integrado)",
    ),
)


def _mensaje_precio_especifico(texto_lower: str) -> str | None:
    """
    Si el mensaje pregunta por landing/flyer/edición de fotos, responde con el
    precio exacto de la página en vez del resumen genérico por nivel.
    """
    for keywords, mensaje in _PRECIOS_ESPECIFICOS:
        if any(k in texto_lower for k in keywords):
            return mensaje + f"\n\n👉 Catálogo completo: {PRECIOS_URL}"
    return None


def _mensaje_precios_servicios() -> str:
    return (
        "¡Claro! Aquí tienes nuestra tabla de precios completa con todos los "
        "servicios de A2K Digital Studio 👇\n"
        f"👉 {PRECIOS_URL}\n\n"
        "Tenemos 4 niveles:\n"
        "⭐ Básicos: desde $5\n"
        "🔥 Intermedios: desde $20\n"
        "💎 Avanzados: desde $60\n"
        "👑 Premium: desde $200\n\n"
        "¿Sobre qué servicio te gustaría más información? Escríbeme y te ayudo 🤖🔥"
    )


def _texto_desde_resultado(res) -> str:
    """
    Convierte cualquier tipo de retorno de ComandoParser.procesar() en texto plano
    para enviarlo de vuelta por Telegram.
    """
    if isinstance(res, str):
        return res
    if isinstance(res, tuple) and len(res) >= 2:
        tag = res[0]
        if tag in ("__cian__", "__streamed__"):
            return res[1]
        if tag == "__accion__":
            return f"[Acción ejecutada en Jarvis: {res[1]}]"
        # __vision__, __instalar_vision__, __verificar_deps__, etc.
        return str(res[1])
    return str(res)


# ══════════════════════════════════════════════════════════════════════════════
#  Transcripción de audio (voice notes de Telegram → texto)
# ══════════════════════════════════════════════════════════════════════════════

async def _transcribir_audio(update: Update) -> str | None:
    """
    Descarga el voice note / audio de Telegram, lo convierte de .ogg a .wav
    (necesita ffmpeg en PATH vía pydub) y lo transcribe con Google Speech Recognition.
    Retorna None si falla o no hay ffmpeg disponible.
    """
    voice_obj = update.message.voice or update.message.audio
    if not voice_obj:
        return None

    tg_file = await voice_obj.get_file()

    ogg_path = Path(tempfile.mktemp(suffix=".ogg"))
    wav_path = ogg_path.with_suffix(".wav")

    try:
        await tg_file.download_to_drive(str(ogg_path))

        # Convertir ogg/opus → wav mono 16 kHz (mismo formato que el mic de Jarvis)
        try:
            from pydub import AudioSegment
            seg = AudioSegment.from_file(str(ogg_path))
            seg = seg.set_channels(1).set_frame_rate(16000)
            seg.export(str(wav_path), format="wav")
        except Exception:
            return None     # sin ffmpeg — fallo silencioso

        import speech_recognition as sr
        rec = sr.Recognizer()
        with sr.AudioFile(str(wav_path)) as src:
            audio = rec.record(src)
        return rec.recognize_google(audio, language="es-US")

    except Exception:
        return None
    finally:
        ogg_path.unlink(missing_ok=True)
        wav_path.unlink(missing_ok=True)


# ══════════════════════════════════════════════════════════════════════════════
#  Núcleo del bot (corre dentro del hilo daemon)
# ══════════════════════════════════════════════════════════════════════════════

async def _bot_main(token: str, chat_id: str, on_texto, log_fn):
    """Construye la Application de Telegram y entra en el bucle de polling."""

    app = ApplicationBuilder().token(token).build()
    loop = asyncio.get_running_loop()

    # ── Verificación de origen ────────────────────────────────────────────────
    async def _autorizado(update: Update) -> bool:
        uid = str(update.effective_chat.id)
        if uid != chat_id:
            _log(log_fn,
                 f"[TELEGRAM] Mensaje rechazado — chat_id no autorizado: {uid}", "err")
            return False
        return True

    # ── Handler: mensajes de texto ────────────────────────────────────────────
    async def _handle_texto(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not await _autorizado(update):
            return
        texto = (update.message.text or "").strip()
        if not texto:
            return
        _log(log_fn, f"[TELEGRAM] → '{texto[:80]}'", "info")

        if _es_consulta_precios_servicios(texto):
            especifico = _mensaje_precio_especifico(texto.lower())
            await update.message.reply_text(especifico or _mensaje_precios_servicios())
            _log(log_fn, "[TELEGRAM] Precio de servicios enviado"
                 + (" (específico)" if especifico else " (tabla genérica)"), "ok")
            return

        try:
            res      = await loop.run_in_executor(None, on_texto, texto)
            respuesta = _texto_desde_resultado(res)
        except Exception as exc:
            respuesta = f"[Jarvis error interno: {exc}]"
        await update.message.reply_text(respuesta)

    # ── Handler: fotos ────────────────────────────────────────────────────────
    async def _handle_foto(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not await _autorizado(update):
            return
        _log(log_fn, "[TELEGRAM] Foto recibida — ignorada (solo texto y audio).", "info")
        await update.message.reply_text("Procesando archivo...")

    # ── Handler: audio / notas de voz ────────────────────────────────────────
    async def _handle_audio(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not await _autorizado(update):
            return
        _log(log_fn, "[TELEGRAM] Audio recibido — transcribiendo...", "info")

        texto = await _transcribir_audio(update)

        if not texto:
            await update.message.reply_text(
                "No pude transcribir el audio.\n"
                "Asegúrate de tener ffmpeg instalado, o escríbeme el texto directamente."
            )
            return

        _log(log_fn, f"[TELEGRAM] Audio → '{texto[:80]}'", "info")
        try:
            res      = await loop.run_in_executor(None, on_texto, texto)
            respuesta = _texto_desde_resultado(res)
        except Exception as exc:
            respuesta = f"[Jarvis error interno: {exc}]"
        await update.message.reply_text(respuesta)

    # ── Helper: ruta base de Jarvis ──────────────────────────────────────────
    _BASE = Path(__file__).resolve().parent.parent

    def _leer_json(nombre: str) -> dict:
        try:
            with open(_BASE / nombre, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def _guardar_json(nombre: str, data: dict):
        with open(_BASE / nombre, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    # ── Supabase REST helper (no depende de librería externa) ─────────────────
    import urllib.request as _urlreq
    _SB_URL  = "https://peyemxxqgkhagvxjcbjf.supabase.co"
    _SB_KEY  = "sb_publishable_h3e2XZ1hhGSv1kb4gaKpPg_4SdZz4rg"
    _SB_HDRS = {
        "apikey":         _SB_KEY,
        "Authorization":  f"Bearer {_SB_KEY}",
        "Content-Type":   "application/json",
        "Prefer":         "resolution=merge-duplicates",
    }

    def _sb_upsert(table: str, payload: dict) -> bool:
        """Hace UPSERT a Supabase vía REST. Retorna True si OK."""
        try:
            body = json.dumps(payload).encode()
            req  = _urlreq.Request(
                f"{_SB_URL}/rest/v1/{table}",
                data=body, method="POST",
                headers={**_SB_HDRS, "Prefer": "resolution=merge-duplicates,return=minimal"}
            )
            with _urlreq.urlopen(req, timeout=8):
                return True
        except Exception as e:
            _log(log_fn, f"[SUPABASE] Error upsert {table}: {e}", "warn")
            return False

    def _sb_push_tasas(bcv: float = None, usdt: float = None, p2p: float = None) -> bool:
        """Actualiza la fila singleton id=1 en zync_tasas."""
        from datetime import datetime as _dtnow
        payload: dict = {"id": 1, "updated_at": _dtnow.now().isoformat(), "updated_by": "jarvis"}
        if bcv  is not None: payload["bcv"]  = bcv
        if usdt is not None: payload["usdt"] = usdt
        if p2p  is not None: payload["p2p"]  = p2p
        return _sb_upsert("zync_tasas", payload)

    def _sb_upsert_inv(entry: dict) -> bool:
        """Guarda/actualiza un producto en zync_inventario."""
        payload = {
            "id":               entry.get("id"),
            "nombre":           entry.get("product") or entry.get("nombre", ""),
            "qty":              entry.get("qty", 0),
            "fob_usd":          entry.get("fobCost") or entry.get("fob_usd", 0),
            "precio_venta_usd": entry.get("sellingPrice") or entry.get("precio_venta_usd", 0),
            "vendido":          entry.get("sold") or entry.get("vendido", 0),
            "merma_pct":        entry.get("mermaR") or entry.get("merma_pct", 3),
            "fecha":            entry.get("date") or entry.get("fecha", ""),
            "imagen_url":       entry.get("imageUrl") or entry.get("imagen_url"),
        }
        return _sb_upsert("zync_inventario", payload)

    # ── Comando /start — menú de bienvenida ──────────────────────────────────
    async def _cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not await _autorizado(update):
            return
        teclado = ReplyKeyboardMarkup(
            [
                [KeyboardButton("📦 /catalogo"),     KeyboardButton("💱 /tasa")],
                [KeyboardButton("🔍 /precio"),        KeyboardButton("📊 /stock")],
                [KeyboardButton("🚨 /stock_critico"), KeyboardButton("📊 /resumen")],
                [KeyboardButton("💳 /cobrar"),        KeyboardButton("👥 /deudores")],
                [KeyboardButton("🔥 /viral"),         KeyboardButton("📸 /screen")],
            ],
            resize_keyboard=True,
            input_field_placeholder="Escribe un comando o mensaje...",
        )
        await update.message.reply_text(
            "👋 <b>Hola, soy Jarvis — A2K Digital Studio</b>\n\n"
            "📦 <b>Inventario:</b>\n"
            "/catalogo — Ver todos los productos\n"
            "/precio [nombre] — Precio de un producto\n"
            "/stock — Stock completo\n"
            "/stock_critico — Productos agotados o bajos\n"
            "/tasa — Ver tasa Bs/$\n\n"
            "📊 <b>Admin:</b>\n"
            "/resumen — Ventas del día\n"
            "/deudores — Clientes con deuda\n\n"
            "💳 <b>Cobros:</b>\n"
            "/cobrar [monto] [concepto] — Enlace de pago\n"
            "   <i>Ej: /cobrar 45.50 Reloj Smartwatch</i>\n"
            "/clientenuevo tel|nombre|empresa|rubro|servicio — Onboarding\n\n"
            "🔥 <b>Contenido Viral:</b>\n"
            "/viral [tema] [plataforma] — Busca videos virales\n"
            "   <i>Ej: /viral barberia tiktok</i>\n"
            "   <i>Ej: /viral sistema pos youtube</i>\n\n"
            "📸 /screen — Captura pantalla Jarvis\n\n"
            "💬 Cualquier mensaje se procesa con IA.",
            parse_mode="HTML",
            reply_markup=teclado,
        )

    # ── Comando /cobrar — genera solicitud de pago vía JotForm ───────────────
    async def _cmd_cobrar(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not await _autorizado(update):
            return
        texto_cmd = update.message.text or ""
        partes = texto_cmd.strip().split(None, 2)

        import random
        from datetime import datetime as _dt

        ref = f"REF-{_dt.now().strftime('%Y%m%d')}-{random.randint(1000,9999)}"

        if len(partes) < 3:
            # Sin argumentos — envía solo el formulario genérico
            await update.message.reply_text(
                "💳 <b>Solicitud de Pago — A2K Digital Studio</b>\n"
                "──────────────────────\n"
                "Envía este formulario al cliente para que complete sus datos:\n\n"
                "📋 <a href='https://form.jotform.com/261694668966076'>👉 FORMULARIO DE PAGO</a>\n\n"
                "<i>El cliente llena nombre, WhatsApp, monto y método de pago.\n"
                "Cuando lo recibas, generas el link de Zinli y se lo envías.</i>\n\n"
                "💡 Tip: /cobrar 45.50 Servicio Técnico — para incluir monto y concepto.",
                parse_mode="HTML",
                disable_web_page_preview=True,
            )
            return

        try:
            monto = float(partes[1].replace(",", "."))
        except ValueError:
            await update.message.reply_text(
                f"⚠️ Monto inválido: '{partes[1]}'\nEjemplo: /cobrar 45.50 Reloj Smartwatch"
            )
            return

        concepto = partes[2].strip()
        _log(log_fn, f"[TELEGRAM] /cobrar ${monto:.2f} — {concepto}", "info")

        await update.message.reply_text(
            f"💳 <b>Solicitud de Pago Generada</b>\n"
            f"──────────────────────\n"
            f"💰 <b>Monto:</b>    ${monto:,.2f}\n"
            f"📋 <b>Concepto:</b> {concepto}\n"
            f"🔖 <b>Ref:</b>      <code>{ref}</code>\n"
            f"──────────────────────\n"
            f"📋 <a href='https://form.jotform.com/261694668966076'>👉 FORMULARIO DE PAGO</a>\n\n"
            f"<b>Pasos:</b>\n"
            f"1️⃣ Envía el formulario al cliente\n"
            f"2️⃣ Cliente llena sus datos y lo envía\n"
            f"3️⃣ Recibes notificación con su WhatsApp\n"
            f"4️⃣ Generas link Zinli y se lo envías\n"
            f"5️⃣ Cliente paga y manda captura\n"
            f"6️⃣ Confirmas con /confirmar {ref}",
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
        _log(log_fn, f"[TELEGRAM] /cobrar formulario enviado — ref={ref} monto={monto}", "ok")

    # ── Comando /clientenuevo — dispara onboarding real tras confirmar pago ──
    async def _cmd_cliente_nuevo(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not await _autorizado(update):
            return
        texto_cmd = (update.message.text or "").split(None, 1)
        if len(texto_cmd) < 2 or "|" not in texto_cmd[1]:
            await update.message.reply_text(
                "⚠️ Uso: /clientenuevo telefono|nombre|empresa|rubro|servicio\n"
                "Ej: /clientenuevo 584121234567|Juan Perez|Barberia Los Amigos|barberia|Recepcionista IA"
            )
            return

        partes = [p.strip() for p in texto_cmd[1].split("|")]
        while len(partes) < 5:
            partes.append("")
        telefono, nombre, empresa, rubro, servicio = partes[:5]

        if not telefono or not nombre:
            await update.message.reply_text("⚠️ Falta el teléfono o el nombre. Formato: telefono|nombre|empresa|rubro|servicio")
            return

        await update.message.reply_text(f"⏳ Generando onboarding para {nombre}...")
        try:
            from modulos.automatizaciones_ia import onboarding_cliente, enviar_mensaje
            resultado = onboarding_cliente(
                nombre=nombre,
                empresa=empresa or "su negocio",
                rubro=rubro or "servicios profesionales",
                servicio_contratado=servicio or "el servicio contratado",
                cerrado_por="Abigail",
            )
            enviar_mensaje(telefono.replace("+", "").strip(), resultado["bienvenida_cliente"])
            docs = "\n".join(f"• {d}" for d in resultado.get("documentos_requeridos", []))
            await update.message.reply_text(
                f"✅ Bienvenida enviada a +{telefono}\n\n"
                f"📋 Documentos a pedirle:\n{docs}\n\n"
                f"🏢 Responsable: {resultado.get('departamento_responsable', '?')}"
            )
            _log(log_fn, f"[TELEGRAM] /clientenuevo → {nombre} ({telefono})", "ok")
        except Exception as exc:
            await update.message.reply_text(f"⚠️ Error generando onboarding: {exc}")
            _log(log_fn, f"[TELEGRAM] /clientenuevo error: {exc}", "err")

    # ── Comando /screen — captura de pantalla ─────────────────────────────────
    async def _cmd_screen(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not await _autorizado(update):
            return
        _log(log_fn, "[TELEGRAM] /screen — capturando pantalla...", "info")
        try:
            import pyautogui
            import io
            img = pyautogui.screenshot()
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            buf.seek(0)
            await update.message.reply_photo(
                photo=buf,
                caption=f"Pantalla Jarvis — {__import__('datetime').datetime.now().strftime('%H:%M:%S')}",
            )
            _log(log_fn, "[TELEGRAM] /screen enviado.", "ok")
        except ImportError:
            await update.message.reply_text(
                "pyautogui no instalado — ejecuta: pip install pyautogui"
            )
        except Exception as exc:
            await update.message.reply_text(f"Error al capturar pantalla: {exc}")

    # ── Comando /catalogo ─────────────────────────────────────────────────────
    async def _cmd_catalogo(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not await _autorizado(update):
            return
        inv = _leer_json("inventario_bodega.json")
        productos = inv.get("productos", [])
        tasa = inv.get("tasa_bs_usd", 1)
        if not productos:
            await update.message.reply_text("📦 No hay productos en el catálogo aún.")
            return
        lineas = ["📦 <b>Catálogo de Productos</b>", f"💱 Tasa: <b>Bs {tasa:,.2f}/$</b>\n"]
        for p in productos:
            stock = p.get("stock", 0)
            emoji = "✅" if stock > 5 else ("⚠️" if stock > 0 else "❌")
            lineas.append(
                f"{emoji} <b>{p['nombre']}</b>\n"
                f"   💵 ${p.get('precio_usd', 0):.2f}  |  Bs {p.get('precio_bs', 0):,.0f}  |  Stock: {stock}"
            )
        await update.message.reply_text("\n".join(lineas), parse_mode="HTML")

    # ── Comando /precio ───────────────────────────────────────────────────────
    async def _cmd_precio(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not await _autorizado(update):
            return
        partes = (update.message.text or "").strip().split(None, 1)
        if len(partes) < 2:
            await update.message.reply_text("⚠️ Uso: /precio [nombre]\nEj: /precio arroz")
            return
        busqueda = partes[1].lower()
        inv = _leer_json("inventario_bodega.json")
        tasa = inv.get("tasa_bs_usd", 1)
        encontrados = [p for p in inv.get("productos", []) if busqueda in p["nombre"].lower()]
        if not encontrados:
            await update.message.reply_text(f"🔍 No encontré productos con '{partes[1]}'.")
            return
        lineas = [f"🔍 <b>Resultados para '{partes[1]}'</b>\n"]
        for p in encontrados:
            stock = p.get("stock", 0)
            emoji = "✅" if stock > 5 else ("⚠️" if stock > 0 else "❌")
            lineas.append(
                f"{emoji} <b>{p['nombre']}</b>\n"
                f"   💵 ${p.get('precio_usd', 0):.2f}  |  Bs {p.get('precio_bs', 0):,.0f}\n"
                f"   📦 Stock: {stock} unidades"
            )
        await update.message.reply_text("\n".join(lineas), parse_mode="HTML")

    # ── Comando /stock ────────────────────────────────────────────────────────
    async def _cmd_stock(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not await _autorizado(update):
            return
        inv = _leer_json("inventario_bodega.json")
        productos = inv.get("productos", [])
        if not productos:
            await update.message.reply_text("📦 No hay productos en inventario.")
            return
        total = sum(p.get("stock", 0) for p in productos)
        lineas = [f"📦 <b>Stock Actual</b> — {len(productos)} productos\n"]
        for p in productos:
            stock = p.get("stock", 0)
            emoji = "🟢" if stock > 5 else ("🟡" if stock > 0 else "🔴")
            lineas.append(f"{emoji} {p['nombre']}: <b>{stock}</b> u.")
        lineas.append(f"\n<b>Total unidades:</b> {total}")
        await update.message.reply_text("\n".join(lineas), parse_mode="HTML")

    # ── Comando /stock_critico ────────────────────────────────────────────────
    async def _cmd_stock_critico(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not await _autorizado(update):
            return
        inv = _leer_json("inventario_bodega.json")
        criticos = [p for p in inv.get("productos", []) if p.get("stock", 0) <= 3]
        if not criticos:
            await update.message.reply_text("✅ Todo el stock está en niveles normales.")
            return
        lineas = [f"🚨 <b>Stock Crítico ({len(criticos)} productos)</b>\n"]
        for p in criticos:
            stock = p.get("stock", 0)
            emoji = "❌" if stock == 0 else "⚠️"
            lineas.append(f"{emoji} <b>{p['nombre']}</b> — {stock} unidades")
        lineas.append("\n<i>Repone estos productos pronto.</i>")
        await update.message.reply_text("\n".join(lineas), parse_mode="HTML")

    # ── Comando /tasa ─────────────────────────────────────────────────────────
    # Uso:
    #   /tasa              — ver las 3 tasas actuales
    #   /tasa bcv 596.78   — actualizar BCV oficial
    #   /tasa usdt 734.03  — actualizar USDT / Binance P2P
    #   /tasa p2p 837.20   — actualizar P2P Efectivo (inventario bodega)
    async def _cmd_tasa(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not await _autorizado(update):
            return
        partes = (update.message.text or "").strip().split()

        # ── Leer estado actual de ambos archivos ──────────────────────────
        try:
            from modulos.divisas_suite import obtener_tasas, actualizar_tasas
            tasas_div = obtener_tasas()
        except Exception:
            tasas_div = {}

        inv = _leer_json("inventario_bodega.json")

        bcv_actual   = tasas_div.get("bcv_usd_bs",          0.0)
        usdt_actual  = tasas_div.get("binance_p2p_usdt_bs", 0.0)
        p2p_actual   = inv.get("tasa_bs_usd",               0.0)

        # ── Sin argumentos: solo mostrar ─────────────────────────────────
        if len(partes) == 1:
            spread = tasas_div.get("spread_pct", 0.0)
            await update.message.reply_text(
                "💱 <b>Tasas actuales</b>\n\n"
                f"🏦 <b>BCV Oficial:</b>   Bs <b>{bcv_actual:,.2f}</b>/$\n"
                f"₿  <b>USDT / Binance:</b> Bs <b>{usdt_actual:,.2f}</b>/USDT\n"
                f"⚡ <b>P2P Efectivo:</b>   Bs <b>{p2p_actual:,.2f}</b>/$\n"
                f"📊 <b>Spread BCV↔P2P:</b> {spread:.1f}%\n\n"
                "Para actualizar:\n"
                "/tasa bcv 596.78\n"
                "/tasa usdt 734.03\n"
                "/tasa p2p 837.20",
                parse_mode="HTML",
            )
            return

        # ── Con argumentos: /tasa [tipo] [valor] ─────────────────────────
        if len(partes) < 3:
            await update.message.reply_text(
                "⚠️ Uso:\n"
                "/tasa bcv 596.78\n"
                "/tasa usdt 734.03\n"
                "/tasa p2p 837.20"
            )
            return

        tipo = partes[1].lower()
        try:
            valor = float(partes[2].replace(",", "."))
        except ValueError:
            await update.message.reply_text(f"⚠️ Valor inválido: '{partes[2]}'")
            return

        from datetime import datetime as _dt2

        if tipo == "bcv":
            try:
                actualizar_tasas(bcv=valor)
                sb_ok = _sb_push_tasas(bcv=valor)
                _log(log_fn, f"[TELEGRAM] Tasa BCV → Bs {valor} | Supabase: {'✓' if sb_ok else '✗'}", "ok")
                await update.message.reply_text(
                    f"✅ <b>BCV actualizado</b>\n"
                    f"🏦 Bs <b>{valor:,.2f}</b> por $1\n"
                    f"{'📡 Suite Financiera actualizada en vivo' if sb_ok else '⚠️ Sin conexión a Suite'}",
                    parse_mode="HTML",
                )
            except Exception as e:
                await update.message.reply_text(f"⚠️ Error: {e}")

        elif tipo in ("usdt", "binance"):
            try:
                actualizar_tasas(binance=valor)
                sb_ok = _sb_push_tasas(usdt=valor)
                _log(log_fn, f"[TELEGRAM] Tasa USDT → Bs {valor} | Supabase: {'✓' if sb_ok else '✗'}", "ok")
                await update.message.reply_text(
                    f"✅ <b>USDT / Binance actualizado</b>\n"
                    f"₿ Bs <b>{valor:,.2f}</b> por USDT\n"
                    f"{'📡 Suite Financiera actualizada en vivo' if sb_ok else '⚠️ Sin conexión a Suite'}",
                    parse_mode="HTML",
                )
            except Exception as e:
                await update.message.reply_text(f"⚠️ Error: {e}")

        elif tipo == "p2p":
            inv["tasa_bs_usd"] = valor
            inv["ultima_actualizacion"] = _dt2.now().strftime("%Y-%m-%d %H:%M")
            for p in inv.get("productos", []):
                usd = p.get("precio_usd", 0)
                p["precio_bs"] = round(usd * valor, 2)
            _guardar_json("inventario_bodega.json", inv)
            sb_ok = _sb_push_tasas(p2p=valor)
            _log(log_fn, f"[TELEGRAM] Tasa P2P → Bs {valor} | Supabase: {'✓' if sb_ok else '✗'}", "ok")
            prods = len(inv.get("productos", []))
            await update.message.reply_text(
                f"✅ <b>P2P Efectivo actualizado</b>\n"
                f"⚡ Bs <b>{valor:,.2f}</b> por $1\n"
                f"📦 Precios Bs recalculados: {prods} productos\n"
                f"{'📡 Suite Financiera actualizada en vivo' if sb_ok else '⚠️ Sin conexión a Suite'}",
                parse_mode="HTML",
            )
        else:
            await update.message.reply_text(
                "⚠️ Tipo no reconocido. Usa: bcv, usdt o p2p\n"
                "Ej: /tasa bcv 596.78"
            )

    # ── Comando /resumen ──────────────────────────────────────────────────────
    async def _cmd_resumen(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not await _autorizado(update):
            return
        ventas = _leer_json("ventas_dia.json")
        items  = ventas.get("ventas", [])
        total_usd = ventas.get("total_usd", 0.0)
        total_bs  = ventas.get("total_bs",  0.0)
        fecha     = ventas.get("fecha", "hoy")
        if not items:
            await update.message.reply_text(
                f"📊 <b>Resumen del día ({fecha})</b>\n\n"
                "Sin ventas registradas aún.",
                parse_mode="HTML",
            )
            return
        lineas = [f"📊 <b>Resumen del día ({fecha})</b>\n"]
        for v in items[-10:]:  # últimas 10
            lineas.append(
                f"• {v.get('hora','—')} — {v.get('descripcion', v.get('concepto', '?'))}: "
                f"${v.get('monto_usd', 0):.2f}"
            )
        lineas.append(f"\n💵 <b>Total USD:</b> ${total_usd:,.2f}")
        lineas.append(f"💴 <b>Total Bs:</b>  Bs {total_bs:,.2f}")
        lineas.append(f"🧾 <b>Transacciones:</b> {len(items)}")
        await update.message.reply_text("\n".join(lineas), parse_mode="HTML")

    # ── Comando /deudores ─────────────────────────────────────────────────────
    async def _cmd_deudores(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not await _autorizado(update):
            return
        cxc = _leer_json("cuentas_por_cobrar.json")
        clientes = [c for c in cxc.get("clientes", []) if c.get("deuda_usd", 0) > 0 or c.get("deuda_bs", 0) > 0]
        if not clientes:
            await update.message.reply_text("✅ No hay clientes con deudas pendientes.")
            return
        total_usd = sum(c.get("deuda_usd", 0) for c in clientes)
        total_bs  = sum(c.get("deuda_bs",  0) for c in clientes)
        lineas = [f"📋 <b>Deudores ({len(clientes)} clientes)</b>\n"]
        for c in clientes:
            venc = c.get("fecha_vencimiento", "")
            venc_txt = f" · vence {venc}" if venc else ""
            lineas.append(
                f"👤 <b>{c['nombre']}</b>\n"
                f"   💵 ${c.get('deuda_usd', 0):.2f}  |  Bs {c.get('deuda_bs', 0):,.0f}{venc_txt}"
            )
        lineas.append(f"\n💵 <b>Total a cobrar:</b> ${total_usd:,.2f}  |  Bs {total_bs:,.0f}")
        await update.message.reply_text("\n".join(lineas), parse_mode="HTML")

    # ── Comando /inv — gestión de inventario en Suite Financiera ─────────────
    # Uso:
    #   /inv                          — ver inventario actual
    #   /inv agregar [nombre] [fob] [qty] [precio_venta]
    #   /inv vender [nombre] [qty]
    async def _cmd_inv(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not await _autorizado(update):
            return
        partes = (update.message.text or "").strip().split(None, 4)

        # ── /inv solo → listar desde Supabase o inventario bodega ────────
        if len(partes) == 1:
            try:
                import urllib.request as _ur2
                req = _ur2.Request(
                    f"{_SB_URL}/rest/v1/zync_inventario?select=nombre,qty,vendido,precio_venta_usd,fob_usd&order=created_at.desc&limit=10",
                    headers={**_SB_HDRS}
                )
                with _ur2.urlopen(req, timeout=8) as r:
                    items = json.loads(r.read())
                if not items:
                    await update.message.reply_text("📦 Inventario ZYNC vacío en Supabase.\nUsa /inv agregar [nombre] [fob] [qty] [precio]")
                    return
                lineas = ["📦 <b>Inventario ZYNC Suite</b>\n"]
                for it in items:
                    disp = it.get("qty", 0) - it.get("vendido", 0)
                    icon = "✅" if disp > 5 else ("⚠️" if disp > 0 else "❌")
                    lineas.append(
                        f"{icon} <b>{it['nombre'][:30]}</b>\n"
                        f"   📦 {disp} disp  |  ${it.get('precio_venta_usd', 0):.2f}/ud  |  FOB ${it.get('fob_usd', 0):.2f}"
                    )
                await update.message.reply_text("\n".join(lineas), parse_mode="HTML")
            except Exception as e:
                await update.message.reply_text(f"⚠️ Error consultando Supabase: {e}")
            return

        subcomando = partes[1].lower()

        # ── /inv agregar ─────────────────────────────────────────────────
        if subcomando == "agregar":
            # /inv agregar Audífonos Bluetooth 7.50 50 12.99
            if len(partes) < 4:
                await update.message.reply_text(
                    "⚠️ Uso: /inv agregar [nombre] [fob_usd] [cantidad] [precio_venta]\n"
                    "Ej: /inv agregar Audífonos Bluetooth 7.50 50 12.99"
                )
                return
            try:
                import time as _time
                # El nombre puede tener espacios — parsear al revés
                # Formato: /inv agregar NOMBRE FOB QTY PRECIO
                tokens = partes[2:]  # todo lo que queda
                # Intentar extraer los 3 números del final
                all_parts = " ".join(tokens).split()
                if len(all_parts) < 4:
                    await update.message.reply_text("⚠️ Faltan parámetros. Ej: /inv agregar Audífonos 7.50 50 12.99")
                    return
                precio_v = float(all_parts[-1])
                qty      = int(all_parts[-2])
                fob      = float(all_parts[-3])
                nombre   = " ".join(all_parts[:-3]).strip().upper()
                if not nombre:
                    await update.message.reply_text("⚠️ Falta el nombre del producto.")
                    return
                from datetime import datetime as _dtnow2
                entry = {
                    "id":               int(_time.time() * 1000),
                    "nombre":           nombre,
                    "qty":              qty,
                    "fob_usd":          fob,
                    "precio_venta_usd": precio_v,
                    "vendido":          0,
                    "merma_pct":        3,
                    "fecha":            _dtnow2.now().strftime("%d %b. %Y"),
                }
                ok = _sb_upsert("zync_inventario", entry)
                _log(log_fn, f"[TELEGRAM] Producto agregado a Suite: {nombre} | Supabase: {'✓' if ok else '✗'}", "ok")
                margen = round((precio_v - fob) / fob * 100, 1) if fob > 0 else 0
                await update.message.reply_text(
                    f"{'✅' if ok else '⚠️'} <b>Producto {'agregado a Suite' if ok else 'pendiente (sin red)'}</b>\n\n"
                    f"📦 <b>{nombre}</b>\n"
                    f"   FOB: ${fob:.2f}  |  PV: ${precio_v:.2f}  |  Margen: {margen}%\n"
                    f"   Cantidad: {qty} uds\n"
                    f"{'📡 Visible en Suite Financiera ahora mismo' if ok else '⚠️ Reconectar para sincronizar'}",
                    parse_mode="HTML",
                )
            except (ValueError, IndexError) as ex:
                await update.message.reply_text(f"⚠️ Formato inválido: {ex}\nEj: /inv agregar Audífonos 7.50 50 12.99")
            return

        # ── /inv vender ──────────────────────────────────────────────────
        if subcomando == "vender":
            await update.message.reply_text(
                "💡 Para registrar ventas usa la <b>Suite Financiera</b> directamente:\n"
                "El botón 🛒 VENDER en cada producto del inventario.\n\n"
                "Las ventas se sincronizan automáticamente con Jarvis.",
                parse_mode="HTML",
            )
            return

        await update.message.reply_text(
            "⚠️ Subcomando no reconocido.\n"
            "/inv — ver inventario\n"
            "/inv agregar [nombre] [fob] [qty] [precio]\n"
        )

    # ── /viral [tema] [plataforma] ────────────────────────────────────────────
    async def _cmd_viral(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not await _autorizado(update):
            return

        partes = (update.message.text or "").strip().split()
        # Ejemplos: /viral barberia tiktok  | /viral sistema pos youtube | /viral barberia
        PLATS = {"tiktok", "youtube", "instagram", "yt", "ig", "tt"}

        if len(partes) < 2:
            await update.message.reply_text(
                "🔍 <b>Buscador de Contenido Viral</b>\n\n"
                "Uso:\n"
                "  /viral [tema] [plataforma]\n\n"
                "Ejemplos:\n"
                "  /viral barberia tiktok\n"
                "  /viral sistema pos youtube\n"
                "  /viral bodega instagram\n"
                "  /viral barberia   ← busca en TikTok + YouTube + Instagram\n\n"
                "Plataformas: tiktok · youtube · instagram",
                parse_mode="HTML"
            )
            return

        # Detectar plataforma (última palabra si está en PLATS)
        ultima = partes[-1].lower()
        aliases = {"yt": "youtube", "ig": "instagram", "tt": "tiktok"}
        plataforma = aliases.get(ultima, ultima) if ultima in PLATS else None
        tema = " ".join(partes[1:-1] if plataforma else partes[1:])

        if not tema:
            await update.message.reply_text("⚠️ Falta el tema. Ej: /viral barberia tiktok")
            return

        try:
            from modulos.apify_viral import buscar_viral, buscar_viral_todas
        except ImportError:
            await update.message.reply_text("⚠️ Módulo apify_viral no encontrado.")
            return

        # Respuesta inmediata para que no haya timeout
        plat_txt = plataforma or "TikTok + YouTube + Instagram"
        await update.message.reply_text(
            f"🔍 Buscando contenido viral sobre <b>{tema}</b> en <b>{plat_txt}</b>...\n"
            f"Esto puede tomar 1-2 minutos ⏳",
            parse_mode="HTML"
        )

        import asyncio as _aio

        if plataforma:
            # Una sola plataforma
            resultado = await _aio.get_event_loop().run_in_executor(
                None, buscar_viral, tema, plataforma
            )
            await update.message.reply_text(resultado, parse_mode="HTML",
                                             disable_web_page_preview=True)
        else:
            # Las 3 plataformas en paralelo
            resultados = await _aio.get_event_loop().run_in_executor(
                None, buscar_viral_todas, tema
            )
            for plat in ("tiktok", "youtube", "instagram"):
                if plat in resultados:
                    await update.message.reply_text(resultados[plat], parse_mode="HTML",
                                                    disable_web_page_preview=True)
                    await _aio.sleep(0.5)

        _log(log_fn, f"[TELEGRAM] /viral {tema} {plataforma or 'all'}", "ok")

    # ── Registrar handlers ────────────────────────────────────────────────────
    app.add_handler(CommandHandler("start",                          _cmd_start))
    app.add_handler(CommandHandler("help",                           _cmd_start))
    app.add_handler(CommandHandler("catalogo",                       _cmd_catalogo))
    app.add_handler(CommandHandler("precio",                         _cmd_precio))
    app.add_handler(CommandHandler("stock",                          _cmd_stock))
    app.add_handler(CommandHandler("stock_critico",                  _cmd_stock_critico))
    app.add_handler(CommandHandler("tasa",                           _cmd_tasa))
    app.add_handler(CommandHandler("resumen",                        _cmd_resumen))
    app.add_handler(CommandHandler("deudores",                       _cmd_deudores))
    app.add_handler(CommandHandler("cobrar",                         _cmd_cobrar))
    app.add_handler(CommandHandler("clientenuevo",                   _cmd_cliente_nuevo))
    app.add_handler(CommandHandler("inv",                            _cmd_inv))
    app.add_handler(CommandHandler("viral",                          _cmd_viral))
    app.add_handler(CommandHandler("screen",                         _cmd_screen))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, _handle_texto))
    app.add_handler(MessageHandler(filters.PHOTO,                   _handle_foto))
    app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO,   _handle_audio))

    # ── Arrancar polling ──────────────────────────────────────────────────────
    async with app:
        await app.start()
        await app.updater.start_polling(drop_pending_updates=True)
        _log(log_fn, "[TELEGRAM] Bot conectado y escuchando...", "ok")
        # Bloquea indefinidamente — el hilo daemon muere al cerrar Jarvis
        await asyncio.Event().wait()
        await app.updater.stop()


# ══════════════════════════════════════════════════════════════════════════════
#  API pública
# ══════════════════════════════════════════════════════════════════════════════

def iniciar(on_texto, log_fn=None):
    """
    Lanza el bot de Telegram en un hilo daemon separado.

    Parámetros
    ----------
    on_texto : callable(str) → cualquier valor de ComandoParser.procesar()
        Se llama con cada mensaje de texto o audio transcrito.
    log_fn : callable(msg, tag) | None
        Función para escribir en la consola de Jarvis (app.log).
    """
    global _hilo

    if not _TELEGRAM_OK:
        _log(log_fn,
             "[TELEGRAM] Dependencia faltante — ejecuta: pip install python-telegram-bot",
             "err")
        return

    token   = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()

    if not token:
        _log(log_fn,
             "[TELEGRAM] TELEGRAM_BOT_TOKEN no configurado en .env — bot desactivado.", "info")
        return
    if not chat_id:
        _log(log_fn,
             "[TELEGRAM] TELEGRAM_CHAT_ID no configurado en .env — bot desactivado.", "info")
        return

    def _run():
        import time as _time
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        intento = 0
        while True:
            intento += 1
            try:
                loop.run_until_complete(_bot_main(token, chat_id, on_texto, log_fn))
                break  # terminó limpiamente
            except Exception as exc:
                espera = min(60, 5 * intento)
                _log(log_fn,
                     f"[TELEGRAM] Desconectado (intento {intento}): {exc} "
                     f"— reconectando en {espera}s…", "err")
                _time.sleep(espera)
        loop.close()

    _hilo = threading.Thread(target=_run, name="jarvis-telegram", daemon=True)
    _hilo.start()
