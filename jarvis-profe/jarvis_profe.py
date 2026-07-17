import os
import sys
import threading
import time
import json
import math
import random
import re
import tkinter as tk
from datetime import datetime as _dt
from tkinter import messagebox

import requests
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(__file__))
from modulos import sistema, finanzas, importaciones, tecnico
from modulos import jarvis_chat, technical_db
from modulos import vision as vision_mod
from modulos import fintech_scraper as _fintech
from modulos import voz as _voz
from modulos import logger as _logger
from modulos import telegram_bridge as _tg_bridge
from modulos.config_loader import get_api_key
from modulos.rutas import base_exe as _base_exe
from modulos.comando_engine import procesar_comando as _cmd_engine, nombre_usuario as _nombre_usuario

# Carga .env desde la carpeta del exe (o raíz del proyecto en desarrollo)
load_dotenv(_base_exe() / ".env", override=True)

URL_ZYNC_PAY = "http://localhost/zync-pay/index.php"
VERSION      = "JARVIS MENTE MAESTRA  v4.0"

# ── PLAN DE TRADING A2K — reglas del plan aplicadas a la voz de Binarias ─────
# Nunca "adivina" si conviene operar — solo reporta datos reales (RSI, racha,
# horario, PnL del dia) y aplica las reglas ya escritas en GUIA-TRADING-A2K-v2.
# Ver memoria [[project_binarias_whatsapp_numeros]] y la guia en el Escritorio.
_HORARIO_PLAN_BUENO = ((6, 0, 10, 0), (14, 30, 16, 0))  # (hIni,mIni,hFin,mFin)
_JOURNAL_TRADES_PATH = r"C:\Users\ASUS\whatsapp-bot-a2k\journal-trades.json"
_RECOMENDACION_KW = (
    "me recomienda", "recomiendas", "recomendacion", "recomendación",
    "la tomo", "la autorizo", "autorizo la senal", "autorizo la señal",
    "debo operar", "debo entrar", "opero o no", "entro o no",
    "la apruebo", "que hago con esta", "qué hago con esta",
    "tomo la señal", "tomo la senal",
)


def _en_horario_plan(ahora=None):
    """True si la hora actual cae en una de las ventanas buenas del plan."""
    ahora = ahora or _dt.now()
    minutos_ahora = ahora.hour * 60 + ahora.minute
    for hIni, mIni, hFin, mFin in _HORARIO_PLAN_BUENO:
        if hIni * 60 + mIni <= minutos_ahora < hFin * 60 + mFin:
            return True
    return False


def _pnl_binarias_hoy():
    """Suma real del PnL de hoy en Binarias, leido directo del journal — no inventa nada."""
    try:
        with open(_JOURNAL_TRADES_PATH, encoding="utf-8") as f:
            trades = json.load(f)
        hoy = _dt.now().strftime("%Y-%m-%d")
        de_hoy = [t for t in trades if t.get("sistema") == "binarias" and t.get("fecha") == hoy]
        pnl = sum(t.get("pnl", 0) or 0 for t in de_hoy)
        return pnl, len(de_hoy)
    except Exception:
        return None, None

# ── CLASIFICACIÓN DE MONEDA POR BANCO ─────────────────────────────────────────
# Bancos nacionales → VES (Bolívares)
_BANCOS_VES = frozenset({
    "banesco", "mercantil", "bdv", "banco de venezuela", "venezuela",
    "provincial", "bnc", "banco nacional de crédito", "banco nacional de credito",
    "del tesoro", "banco del tesoro", "exterior", "banco exterior",
    "bancamiga", "bdt", "banco digital de los trabajadores",
})
# Pasarelas con link → USD  (métodos A2K Digital Studio)
_BANCOS_USD = frozenset({
    "zinli", "meru", "wally", "airtm", "binance",
    "mypal", "facebank",
    "mercantil panama", "mercantil panamá",
})

def _moneda_por_banco(banco_raw: str) -> tuple:
    """Devuelve ('USD', '$') o ('VES', 'Bs') según el banco o plataforma."""
    b = banco_raw.lower()
    if any(k in b for k in _BANCOS_USD):
        return "USD", "$"
    return "VES", "Bs"


# ── SYSTEM PROMPTS ESPECIALIZADOS (Google Gemini) ──────────────────────────────
_SYSTEM_BODEGA = """\
Eres Jarvis, asistente de gestión para bodegas, ferreterías y fruterías venezolanas.

REGLAS ESTRICTAS — CUMPLIMIENTO OBLIGATORIO:
1. SOLO usa los datos de inventario, precios y tasas que recibes en el contexto de cada mensaje.
   Si un dato no está en el contexto, responde exactamente: "No tengo ese dato en el sistema — verifica en caja."
2. NUNCA inventes precios, stocks, cantidades ni tasas de cambio.
3. Si la tasa Bs/$ está en el contexto, úsala para convertir montos. Si no está, solicita que la actualicen antes de responder.
4. Español venezolano, conversacional y directo. Máximo 4 líneas. Siempre termina con UNA acción concreta para hoy.
5. Sin disclaimers, sin tecnicismos, sin relleno.
"""

_SYSTEM_TECNICO_AIRES = """\
Eres Jarvis, recepcionista técnico especializado en servicio de aires acondicionados.

OBJETIVO ÚNICO: Capturar la falla del cliente y cerrar la cita en el calendario.

PROTOCOLO OBLIGATORIO:
1. En el primer mensaje pregunta SIEMPRE: tipo de equipo (split/ventana/cassette), marca, capacidad en BTU/toneladas y síntoma principal.
2. Una vez que tengas los datos de la falla, presenta los horarios disponibles del contexto y pide que el cliente elija uno.
3. POLÍTICA DE PRECIOS — no negociable: "El precio lo determina el técnico tras la revisión en sitio. El diagnóstico de visita es gratuito."
4. Si el cliente insiste en precios, repite la política sin ceder. Nunca des rangos, estimados ni valores de referencia.
5. Español venezolano, amable y profesional. Máximo 3 líneas por respuesta.
6. Siempre termina con una pregunta de confirmación o el próximo paso concreto.
"""


# ──────────────────────────────────────────────────────────────────────────────
#  PERSISTENCIA LOCAL — INVENTARIO, CALENDARIO Y VENTAS DEL DÍA
# ──────────────────────────────────────────────────────────────────────────────
def _leer_tasa_actual() -> float:
    """Tasa Bs/$ desde inventario_bodega.json. Default 100 si no existe o falla."""
    path = _base_exe() / "inventario_bodega.json"
    if path.exists():
        try:
            return float(json.loads(path.read_text(encoding="utf-8")).get("tasa_bs_usd", 100.0))
        except Exception:
            pass
    return 100.0


def _leer_inventario() -> dict:
    """
    Lee inventario_bodega.json y devuelve contexto listo para inyectar en Gemini.
    Crea una plantilla vacía la primera vez para que el Profe la rellene con datos reales.
    Estructura esperada del JSON:
      { "tasa_bs_usd": 100.0, "productos": [
          {"nombre": "Arroz 1kg", "stock": 50, "precio_bs": 150.0, "precio_usd": 1.5}
        ], "ultima_actualizacion": "2026-05-29" }
    """
    path = _base_exe() / "inventario_bodega.json"
    if not path.exists():
        plantilla = {
            "tasa_bs_usd": 100.0,
            "productos": [
                {"nombre": "Ejemplo Arroz 1kg",      "stock": 0, "precio_bs": 0.0, "precio_usd": 0.0},
                {"nombre": "Ejemplo Harina Pan 1kg",  "stock": 0, "precio_bs": 0.0, "precio_usd": 0.0},
            ],
            "ultima_actualizacion": "Edita este archivo con tus productos reales"
        }
        try:
            path.write_text(json.dumps(plantilla, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass
        return {"tasa": 100.0, "productos_total": 0, "sin_stock": 0,
                "stock_critico": 0, "resumen_productos": ""}
    try:
        data    = json.loads(path.read_text(encoding="utf-8"))
        tasa    = float(data.get("tasa_bs_usd", 100.0))
        prods   = data.get("productos", [])
        sin_st  = sum(1 for p in prods if int(p.get("stock", 0)) == 0)
        critico = sum(1 for p in prods if 0 < int(p.get("stock", 0)) <= 5)
        lineas  = [
            f"  {p['nombre']}: stock={p.get('stock','?')} | "
            f"Bs {float(p.get('precio_bs', 0)):.2f} | "
            f"${float(p.get('precio_usd', 0)):.2f}"
            for p in prods[:25]
        ]
        if sin_st > 0:
            _cprint("WARN", f"Inventario: {sin_st} producto(s) sin stock")
        if critico > 0:
            _cprint("WARN", f"Inventario: {critico} producto(s) en nivel crítico (≤5 uds)")
        return {
            "tasa":              tasa,
            "productos_total":   len(prods),
            "sin_stock":         sin_st,
            "stock_critico":     critico,
            "resumen_productos": "\n".join(lineas),
        }
    except Exception:
        return {"tasa": 100.0, "productos_total": 0, "sin_stock": 0,
                "stock_critico": 0, "resumen_productos": ""}


def _leer_slots_disponibles() -> list:
    """
    Lee calendario_tecnico.json y devuelve los slots libres (máx 8 strings).
    Crea un calendario para los próximos 7 días si el archivo no existe.
    Para marcar un slot como ocupado, pon 'disponible': false en el JSON.
    """
    from datetime import datetime, timedelta
    path = _base_exe() / "calendario_tecnico.json"
    if not path.exists():
        hoy   = datetime.now()
        dias  = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado"]
        slots = []
        for d in range(7):
            dia = hoy + timedelta(days=d + 1)
            if dia.weekday() == 6:          # saltar domingo
                continue
            nombre    = dias[dia.weekday()]
            fecha_str = dia.strftime("%d/%m")
            for hora in ["08:00-10:00", "10:00-12:00", "14:00-16:00", "16:00-18:00"]:
                slots.append({
                    "id":          f"{dia.strftime('%Y%m%d')}_{hora[:5].replace(':','')}",
                    "descripcion": f"{nombre} {fecha_str} {hora}",
                    "disponible":  True,
                    "cliente":     None,
                    "equipo":      None,
                })
        try:
            path.write_text(
                json.dumps({"slots": slots, "actualizado": hoy.isoformat()},
                           ensure_ascii=False, indent=2),
                encoding="utf-8"
            )
        except Exception:
            pass
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return [s["descripcion"] for s in data.get("slots", [])
                if s.get("disponible", True)][:8]
    except Exception:
        return ["Horarios no disponibles — contacta por teléfono"]


def _registrar_pago_consolidado(monto_orig: float, moneda: str, banco: str,
                                 referencia: str = "", tasa: float = None) -> tuple:
    """
    Guarda el pago en ventas_dia.json con conversión automática Bs ↔ USD.
    Resetea el archivo automáticamente cuando cambia el día.
    Devuelve (monto_bs, monto_usd).
    Estructura del JSON:
      { "fecha": "2026-05-29", "total_bs": 0.0, "total_usd": 0.0, "ventas": [...] }
    """
    from datetime import datetime
    path  = _base_exe() / "ventas_dia.json"
    hoy   = datetime.now().strftime("%Y-%m-%d")
    ahora = datetime.now().isoformat(timespec="seconds")

    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if data.get("fecha") != hoy:                       # nuevo día → resetear
                data = {"fecha": hoy, "ventas": [], "total_bs": 0.0, "total_usd": 0.0}
        except Exception:
            data = {"fecha": hoy, "ventas": [], "total_bs": 0.0, "total_usd": 0.0}
    else:
        data = {"fecha": hoy, "ventas": [], "total_bs": 0.0, "total_usd": 0.0}

    tasa_real = float(tasa) if tasa else _leer_tasa_actual()
    if moneda == "USD":
        monto_usd = round(float(monto_orig), 2)
        monto_bs  = round(monto_usd * tasa_real, 2)
    else:                                                       # VES / Bs
        monto_bs  = round(float(monto_orig), 2)
        monto_usd = round(monto_bs / tasa_real, 4) if tasa_real else 0.0

    data["ventas"].append({
        "timestamp":       ahora,
        "banco":           banco,
        "referencia":      referencia,
        "moneda_original": moneda,
        "monto_original":  float(monto_orig),
        "monto_bs":        monto_bs,
        "monto_usd":       monto_usd,
        "tasa":            tasa_real,
    })
    data["total_bs"]  = round(data.get("total_bs",  0.0) + monto_bs,  2)
    data["total_usd"] = round(data.get("total_usd", 0.0) + monto_usd, 4)

    simb_log = "$" if moneda == "USD" else "Bs"
    _cprint("PAGO", f"{simb_log} {monto_orig:.2f} {moneda} → Bs {monto_bs:.2f} | "
                    f"{banco} | Ref: {referencia or '—'} | Tasa: {tasa_real}")
    try:
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass
    # Verificar alertas WA proactivas en background — no bloquea el registro
    threading.Thread(target=_verificar_y_alertar, daemon=True).start()
    return monto_bs, monto_usd


# ──────────────────────────────────────────────────────────────────────────────
#  WHATSAPP — FORMATEO, SEGMENTACIÓN Y ENVÍO WEBHOOK
# ──────────────────────────────────────────────────────────────────────────────

# ── Credenciales — configuradas en .env (no editar este bloque) ───────────────
# Variables de entorno requeridas:
#   WA_ENABLED=true
#   WA_PROVEEDOR=zapi          (zapi | evolution | meta)
#   WA_URL=https://api.z-api.io/instances/ID/token/TOKEN/send-text
#   WA_API_KEY=TU_TOKEN_ZAPI   (Client-Token para Zapi | apikey para Evolution)
# load_dotenv() ya fue llamado antes de este punto — os.environ lee el .env
_WA_CONFIG = {
    "url":       os.environ.get("WA_URL", "").strip(),
    "api_key":   os.environ.get("WA_API_KEY", "").strip(),
    "enabled":   os.environ.get("WA_ENABLED", "false").lower() in ("true", "1", "yes"),
    "proveedor": os.environ.get("WA_PROVEEDOR", "zapi").lower().strip(),
}

# ── Patrones de auto-negritas (compilados una vez al arrancar) ─────────────────
_WA_BOLD = [
    # Montos Bs: Bs 1.234,56 / Bs1234
    (re.compile(r'(?<!\*)(Bs\.?\s*[\d.,]+)(?!\*)', re.IGNORECASE), r'*\1*'),
    # Montos dólares: $25.00 / $ 100
    (re.compile(r'(?<!\*)(\$\s*[\d.,]+)(?!\*)'), r'*\1*'),
    # Montos USD explícito: 25 USD
    (re.compile(r'(?<!\*)(\d+[\d.,]*\s*USD)(?!\*)', re.IGNORECASE), r'*\1*'),
    # Referencias bancarias: Ref. 261792 / REF123456
    (re.compile(r'(?<!\*)(Ref\.?\s*\d{4,})(?!\*)', re.IGNORECASE), r'*\1*'),
    # Horarios: 08:00-10:00 / 14:00
    (re.compile(r'(?<!\*)(\d{1,2}:\d{2}(?:-\d{1,2}:\d{2})?)(?!\*)'), r'*\1*'),
    # Día + fecha: Lunes 30/05 / Sábado 02/06
    (re.compile(
        r'(?<!\*)((?:Lunes|Martes|Mi[eé]rcoles|Jueves|Viernes|S[aá]bado|Domingo)'
        r'\s+\d{1,2}/\d{2})(?!\*)', re.IGNORECASE
    ), r'*\1*'),
]


def _formatear_whatsapp(texto: str) -> str:
    """
    Aplica *negritas* WhatsApp automáticamente a los campos clave:
    montos (Bs / $), referencias bancarias, horarios y fechas.
    El lookbehind (?<!*) impide el doble-formateo si ya hay asteriscos.
    """
    for patron, reemplazo in _WA_BOLD:
        texto = patron.sub(reemplazo, texto)
    return texto


def _segmentar_respuesta(texto: str, max_chars: int = 280) -> list:
    """
    Divide la respuesta en bloques cortos para simular escritura humana.

    Estrategia en 3 capas:
      Capa 1 — Párrafos (doble salto de línea): el bloque natural de separación.
      Capa 2 — Oraciones (. ! ?) dentro de un párrafo largo (> max_chars).
      Capa 3 — Corte duro cada max_chars si una oración sigue siendo muy larga.

    Devuelve lista de strings no vacíos, listos para enviar uno a uno.
    """
    # Capa 1
    parrafos = [p.strip() for p in re.split(r'\n{2,}', texto) if p.strip()]
    if not parrafos:
        parrafos = [texto.strip()]

    fragmentos = []
    for parrafo in parrafos:
        if len(parrafo) <= max_chars:
            fragmentos.append(parrafo)
            continue
        # Capa 2 — oraciones
        oraciones = re.split(r'(?<=[.!?])\s+', parrafo)
        bloque, chars = [], 0
        for oracion in oraciones:
            if chars + len(oracion) > max_chars and bloque:
                fragmentos.append(' '.join(bloque))
                bloque = [oracion]
                chars  = len(oracion)
            else:
                bloque.append(oracion)
                chars += len(oracion) + 1
        if bloque:
            fragmentos.append(' '.join(bloque))

    # Capa 3 — corte duro
    resultado = []
    for frag in fragmentos:
        if len(frag) <= max_chars:
            resultado.append(frag)
        else:
            for i in range(0, len(frag), max_chars):
                chunk = frag[i:i + max_chars].strip()
                if chunk:
                    resultado.append(chunk)

    return resultado or [texto.strip()]


def _enviar_whatsapp(numero: str, mensaje: str) -> bool:
    """
    Envía un bloque de texto a WhatsApp via webhook (POST JSON).

    ─ Evolution API ─────────────────────────────────────────────────────────
      _WA_CONFIG["url"]     = "http://TU_IP:8080/message/sendText/INSTANCIA"
      _WA_CONFIG["api_key"] = "TU_APIKEY"
      payload actual → {"number": numero, "text": mensaje}

    ─ Zapi ──────────────────────────────────────────────────────────────────
      _WA_CONFIG["url"] = "https://api.z-api.io/instances/ID/token/TOKEN/send-text"
      Descomentar payload Zapi abajo.

    ─ Meta WA Business API oficial ──────────────────────────────────────────
      _WA_CONFIG["url"]     = "https://graph.facebook.com/v19.0/PHONE_ID/messages"
      _WA_CONFIG["api_key"] = "Bearer EAAxxxxxxxx"
      Descomentar payload Meta abajo.
    """
    if not _WA_CONFIG.get("enabled") or not _WA_CONFIG.get("url"):
        return False   # webhook desactivado — falla silenciosa

    proveedor = _WA_CONFIG.get("proveedor", "zapi")
    api_key   = _WA_CONFIG.get("api_key", "")

    # Selección automática de payload y cabeceras según proveedor
    if proveedor == "zapi":
        payload = {"phone": numero, "message": mensaje}
        headers = {"Content-Type": "application/json", "Client-Token": api_key}
    elif proveedor == "meta":
        payload = {"messaging_product": "whatsapp", "to": numero,
                   "type": "text", "text": {"body": mensaje}}
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}
    else:  # evolution (default)
        payload = {"number": numero, "text": mensaje}
        headers = {"Content-Type": "application/json", "apikey": api_key}

    try:
        r = requests.post(_WA_CONFIG["url"], json=payload, headers=headers, timeout=10)
        return r.status_code in (200, 201)
    except Exception:
        return False


def _enviar_whatsapp_humano(numero: str, respuesta: str) -> bool:
    """
    Pipeline completo de envío human-like:
      1. _formatear_whatsapp  → aplica *negritas* en montos, refs y horarios
      2. _segmentar_respuesta → divide en bloques ≤ 280 chars
      3. _enviar_whatsapp     → POST al webhook por cada bloque
      4. time.sleep(random)   → pausa aleatoria 1.5–3.0 s entre bloques
                                 (evita detección de ráfaga / ban de número)

    Devuelve True si todos los fragmentos se enviaron OK.
    """
    texto_fmt  = _formatear_whatsapp(respuesta)
    fragmentos = _segmentar_respuesta(texto_fmt)
    todos_ok   = True
    _cprint("WA", f"Enviando a {numero[:6]}*** — {len(fragmentos)} bloque(s) | "
                  f"delay 1.5–3.0 s entre bloques")
    for i, frag in enumerate(fragmentos):
        ok = _enviar_whatsapp(numero, frag)
        if not ok:
            todos_ok = False
            _cprint("WARN", f"WhatsApp bloque {i+1}/{len(fragmentos)}: fallo de entrega")
        else:
            _cprint("WA", f"Bloque {i+1}/{len(fragmentos)} enviado ({len(frag)} chars)")
        if i < len(fragmentos) - 1:
            time.sleep(random.uniform(1.5, 3.0))
    return todos_ok


# ──────────────────────────────────────────────────────────────────────────────
#  LOGS DE TERMINAL POR COLORES Y TELEMETRÍA
# ──────────────────────────────────────────────────────────────────────────────
_ANSI = {
    "OK":    "\033[32m",       # Verde — pagos OK, stock bien
    "PAGO":  "\033[32;1m",     # Verde brillante — ingreso de dinero
    "INFO":  "\033[36m",       # Cian — eventos informativos
    "WA":    "\033[36;1m",     # Cian brillante — mensajes WhatsApp enviados
    "WARN":  "\033[33m",       # Amarillo — alertas stock crítico, sin conectividad
    "ERROR": "\033[31;1m",     # Rojo brillante — fallas de API / crédito agotado
    "HDR":   "\033[34;1m",     # Azul brillante — headers y separadores
    "DIM":   "\033[2;37m",     # Gris apagado — metadatos de tabla
    "RST":   "\033[0m",        # Reset
}
_ICON = {
    "OK":   "✓", "PAGO": "$", "INFO": "·",
    "WA":   "✉", "WARN": "⚠", "ERROR": "✗",
    "HDR":  "◈", "DIM":  "─",
}


def _cprint(nivel: str, msg: str) -> None:
    """
    Imprime en la terminal del sistema con color ANSI y timestamp [HH:MM:SS].
    Maneja terminales cp1252 (Windows cmd/PowerShell default) sustituyendo
    caracteres no representables con '?' en lugar de lanzar UnicodeEncodeError.
    """
    _ICON_ASCII = {
        "OK": "[+]", "PAGO": "[$]", "INFO": "[.]",
        "WA": "[W]", "WARN": "[!]", "ERROR": "[X]",
        "HDR": "[*]", "DIM": "---",
    }
    n     = nivel.upper()
    color = _ANSI.get(n, _ANSI["INFO"])
    ts    = _dt.now().strftime("%H:%M:%S")
    enc   = getattr(sys.stdout, "encoding", None) or "cp1252"

    # Intentar con icono Unicode primero
    for icono in (_ICON.get(n, "."), _ICON_ASCII.get(n, ".")):
        linea = f"{color}[{ts}] [{n:5}] {icono}  {msg}{_ANSI['RST']}"
        try:
            linea.encode(enc)           # prueba si el encoding lo soporta
            print(linea, flush=True)
            return
        except (UnicodeEncodeError, LookupError):
            pass                        # reintenta con icono ASCII

    # Fallback definitivo: sustituye cualquier carácter no encodable con '?'
    safe = f"[{ts}] [{n:5}] {_ICON_ASCII.get(n, '.')}  {msg}"
    print(safe.encode(enc, errors="replace").decode(enc), flush=True)


def _verificar_estado_apis() -> None:
    """
    Al arrancar Jarvis, imprime en terminal el estado de las API keys del .env
    y prueba la conectividad real con OpenRouter (Google Gemini).
    Verde = cargada y online. Amarillo = faltante u offline.
    """
    sep = "=" * 58
    _cprint("HDR", sep)
    _cprint("HDR", "  JARVIS v4.0 -- VERIFICACION DE APIS Y CREDENCIALES")
    _cprint("HDR", sep)

    claves = [
        ("OPENROUTER_API_KEY",             "OpenRouter / Google Gemini 2.0 Flash"),
        ("GOOGLE_APPLICATION_CREDENTIALS", "Google Cloud TTS Neural2"),
        ("ANTHROPIC_API_KEY",              "Anthropic Claude (fallback)"),
        ("FIREBASE_API_KEY",               "Firebase / Zync Pay"),
    ]
    for env_key, nombre in claves:
        val = os.environ.get(env_key, "")
        if val and len(val) > 8:
            preview = f"{val[:5]}...{val[-4:]}"
            _cprint("OK",   f"{nombre:<40} CARGADA ({preview})")
        else:
            _cprint("WARN", f"{nombre:<40} ─── NO CONFIGURADA")

    # ── Test de conectividad real con OpenRouter ────────────────────────────
    key = os.environ.get("OPENROUTER_API_KEY", "")
    if key:
        try:
            r = requests.get(
                "https://openrouter.ai/api/v1/models",
                headers={"Authorization": f"Bearer {key}"},
                timeout=6,
            )
            if r.status_code == 200:
                _cprint("OK",   "OpenRouter ping: CONECTADO — Gemini 2.0 Flash listo para usar")
            else:
                _cprint("WARN", f"OpenRouter ping: HTTP {r.status_code} — revisa tu key")
        except requests.exceptions.ConnectionError:
            _cprint("WARN", "OpenRouter ping: sin internet — modo offline activo")
        except requests.exceptions.Timeout:
            _cprint("WARN", "OpenRouter ping: timeout (6 s) — servidor lento")
        except Exception as e:
            _cprint("WARN", f"OpenRouter ping: {type(e).__name__}")
    else:
        _cprint("WARN", "OpenRouter: sin key — Google Gemini no disponible en este arranque")

    _cprint("HDR", sep)


def _mostrar_resumen_diario() -> tuple:
    """
    Lee ventas_dia.json e imprime un cuadro visual en la terminal del sistema.
    Devuelve también una tupla para que la GUI de Jarvis lo muestre en su consola.
    Invocar con el comando: 'resumen diario'
    """
    path = _base_exe() / "ventas_dia.json"
    if not path.exists():
        _cprint("WARN", "Sin registro de ventas para hoy — ningún pago procesado aún.")
        return ("__cian__", "[VENTAS HOY] Ningún pago procesado todavía.")

    try:
        data    = json.loads(path.read_text(encoding="utf-8"))
        ventas  = data.get("ventas", [])
        total_b = data.get("total_bs",  0.0)
        total_u = data.get("total_usd", 0.0)
        fecha   = data.get("fecha", "?")

        sep_d  = "-" * 58
        sep_d2 = "=" * 58

        print(f"\n{_ANSI['HDR']}  {sep_d2}{_ANSI['RST']}")
        print(f"{_ANSI['HDR']}  RESUMEN DE VENTAS — {fecha}  ({len(ventas)} transacciones){_ANSI['RST']}")
        print(f"{_ANSI['HDR']}  {sep_d2}{_ANSI['RST']}")

        if ventas:
            hdr = f"  {'HORA':<8}{'BANCO':<22}{'MONEDA':<8}{'MONTO ORIG':>13}{'Bs EQUIV':>12}"
            print(f"{_ANSI['DIM']}{hdr}{_ANSI['RST']}")
            print(f"{_ANSI['DIM']}  {sep_d}{_ANSI['RST']}")
            for v in ventas:
                hora   = (v.get("timestamp", "?")[:19]).split("T")[-1][:5]
                banco  = str(v.get("banco", "?"))[:21]
                moneda = v.get("moneda_original", "?")
                m_orig = v.get("monto_original", 0.0)
                m_bs   = v.get("monto_bs", 0.0)
                simb   = "$" if moneda == "USD" else "Bs"
                fila   = (f"  {hora:<8}{banco:<22}{moneda:<8}"
                          f"{simb} {m_orig:>9.2f}   Bs {m_bs:>8.2f}")
                color  = _ANSI["OK"] if moneda == "USD" else _ANSI["INFO"]
                print(f"{color}{fila}{_ANSI['RST']}")

        print(f"{_ANSI['HDR']}  {sep_d2}{_ANSI['RST']}")
        _cprint("PAGO", f"TOTAL VES HOY  : Bs {total_b:>12,.2f}")
        _cprint("PAGO", f"TOTAL USD HOY  : $  {total_u:>12,.4f}")
        print(f"{_ANSI['HDR']}  {sep_d2}{_ANSI['RST']}\n")

        # ── Analítica BI profunda ─────────────────────────────────────────────
        try:
            an = _calcular_analitica()
            _imprimir_analitica_terminal(an)
            gui_linea_bi = (
                f"  USD {an['ventas']['pct_usd']}% | VES {an['ventas']['pct_ves']}% "
                f"| Stock critico: {len(an['stock_critico'])}"
                + (" | [!] TASA DESVIADA" if an["alerta_tasa"]["activa"] else "")
            )
        except Exception:
            gui_linea_bi = ""

        return (
            "__cian__",
            f"[VENTAS HOY — {fecha}]\n"
            f"  Transacciones : {len(ventas)}\n"
            f"  Total en Bs   : Bs {total_b:,.2f}\n"
            f"  Total en USD  : $ {total_u:,.4f}\n"
            + (f"  BI            :{gui_linea_bi}" if gui_linea_bi else ""),
        )
    except Exception as e:
        _cprint("ERROR", f"ventas_dia.json — {e}")
        return ("__cian__", f"[ERROR VENTAS] {e}")


# ──────────────────────────────────────────────────────────────────────────────
#  MÓDULO DE INTELIGENCIA DE NEGOCIOS (BI) — Analítica y Conciliación de Tasas
# ──────────────────────────────────────────────────────────────────────────────
def _calcular_analitica() -> dict:
    """
    Lee ventas_dia.json e inventario_bodega.json y produce:
      · % de ventas por moneda (USD vs VES en equivalente Bs)
      · Alerta de desviación de tasa si la diferencia > 8 %
      · Mapa de stock crítico ordenado por urgencia
      · Estructura lista para Chart.js (labels, valores, colores)
    Devuelve dict JSON-serializable listo para el endpoint /analitica.
    """
    from datetime import datetime as _dt2

    resultado = {
        "fecha":    _dt2.now().strftime("%Y-%m-%d"),
        "hora":     _dt2.now().strftime("%H:%M"),
        "ventas": {
            "total_bs": 0.0, "total_usd": 0.0,
            "bs_usd": 0.0,   "bs_ves": 0.0,
            "pct_usd": 0.0,  "pct_ves": 0.0,
            "transacciones": 0,
            "tasa_usada": 100.0,
            "por_banco": {},
        },
        "alerta_tasa": {
            "activa": False, "mensaje": "",
            "tasa_inventario": 0.0,
            "tasa_implicita":  0.0,
            "desviacion_pct":  0.0,
        },
        "stock_critico": [],   # lista de productos en riesgo
        "grafica": {
            "labels":  ["USD — Zinli/Wally/Facebank", "VES — Bancos nacionales"],
            "valores": [0.0, 0.0],    # en equivalente Bs
            "colores": ["#10b981",  "#06d6a0"],
            "colores_hover": ["#00c853", "#00e5b0"],
        },
        "status": "ok",
    }

    # ── 1. Leer ventas del día ────────────────────────────────────────────────
    path_v = _base_exe() / "ventas_dia.json"
    ventas_list = []
    if path_v.exists():
        try:
            dv       = json.loads(path_v.read_text(encoding="utf-8"))
            ventas_list = dv.get("ventas", [])
            tasa     = _leer_tasa_actual()
            bs_usd, bs_ves, por_banco = 0.0, 0.0, {}
            tasas_impl = []

            for v in ventas_list:
                moneda  = v.get("moneda_original", "VES")
                m_bs    = float(v.get("monto_bs",       0))
                m_orig  = float(v.get("monto_original", 0))
                banco   = str(v.get("banco", "Otro"))[:20]
                por_banco[banco] = round(por_banco.get(banco, 0.0) + m_bs, 2)
                if moneda == "USD":
                    bs_usd += m_bs
                    if m_orig > 0:
                        tasas_impl.append(m_bs / m_orig)
                else:
                    bs_ves += m_bs

            total_equiv = bs_usd + bs_ves
            pct_usd = round(bs_usd / total_equiv * 100, 1) if total_equiv > 0 else 0.0
            pct_ves = round(100 - pct_usd, 1)

            resultado["ventas"].update({
                "total_bs":      dv.get("total_bs",  0.0),
                "total_usd":     dv.get("total_usd", 0.0),
                "bs_usd":        round(bs_usd,  2),
                "bs_ves":        round(bs_ves,  2),
                "pct_usd":       pct_usd,
                "pct_ves":       pct_ves,
                "transacciones": len(ventas_list),
                "tasa_usada":    tasa,
                "por_banco":     por_banco,
            })
            resultado["grafica"]["valores"] = [round(bs_usd, 2), round(bs_ves, 2)]

            # ── 2. Alerta de desviación de tasa ──────────────────────────────
            if tasas_impl:
                t_impl = round(sum(tasas_impl) / len(tasas_impl), 2)
                desv   = abs(tasa - t_impl) / tasa * 100 if tasa > 0 else 0.0
                if desv > 8.0:
                    resultado["alerta_tasa"] = {
                        "activa":           True,
                        "mensaje":          (f"TASA DESVIADA {desv:.1f}%: "
                                            f"inventario usa Bs {tasa:.2f}/$ "
                                            f"pero los pagos se registraron a "
                                            f"Bs {t_impl:.2f}/$. "
                                            f"Actualiza tasa_bs_usd en inventario_bodega.json."),
                        "tasa_inventario":  tasa,
                        "tasa_implicita":   t_impl,
                        "desviacion_pct":   round(desv, 1),
                    }
        except Exception as e:
            resultado["status"] = f"error_ventas: {e}"

    # ── 3. Mapa de stock crítico ──────────────────────────────────────────────
    path_i = _base_exe() / "inventario_bodega.json"
    if path_i.exists():
        try:
            di    = json.loads(path_i.read_text(encoding="utf-8"))
            prods = di.get("productos", [])
            criticos = []
            for p in prods:
                stock = int(p.get("stock", 0))
                if stock > 5:
                    continue
                nombre    = str(p.get("nombre", "?"))
                precio_bs = float(p.get("precio_bs", 0) or 0)
                urgencia  = "AGOTADO" if stock == 0 else ("CRITICO" if stock <= 2 else "BAJO")
                # Estimación de días restantes: stock / (ventas_promedio_diarias por producto)
                tx  = resultado["ventas"]["transacciones"]
                n_p = len([x for x in prods if float(x.get("precio_bs", 0) or 0) > 0]) or 1
                ingreso_bs_est = (resultado["ventas"]["bs_ves"] / n_p) if n_p > 0 else 0
                uds_est = round(ingreso_bs_est / precio_bs, 1) if precio_bs > 0 else 0
                dias = round(stock / uds_est, 1) if uds_est > 0 else 99
                criticos.append({
                    "nombre":      nombre,
                    "stock":       stock,
                    "urgencia":    urgencia,
                    "precio_bs":   precio_bs,
                    "precio_usd":  float(p.get("precio_usd", 0) or 0),
                    "dias_est":    min(dias, 99),
                    "accion":      "ORDENAR YA" if stock == 0 else (
                                   "Ordenar urgente" if dias <= 1 else "Planificar reposición"),
                })
            resultado["stock_critico"] = sorted(criticos, key=lambda x: (x["stock"], x["dias_est"]))
        except Exception as e:
            resultado["stock_critico"] = [{"error": str(e)}]

    return resultado


def _imprimir_analitica_terminal(an: dict) -> None:
    """
    Imprime el análisis BI en la terminal con colores ANSI.
    Llamado automáticamente por _mostrar_resumen_diario().
    """
    sep = "=" * 58
    v   = an["ventas"]
    if v["transacciones"] == 0:
        return

    _cprint("HDR", sep)
    _cprint("HDR", f"  ANALITICA BI — Conciliacion de Monedas y Tasa")
    _cprint("HDR", sep)

    # Distribución de monedas
    bar_usd = int(v["pct_usd"] / 5)   # barra de 20 chars máx
    bar_ves = 20 - bar_usd
    _cprint("OK",   f"USD (Zinli/Wally/Facebank) : {'#' * bar_usd:<20} {v['pct_usd']:>5.1f}%  Bs {v['bs_usd']:>10,.2f}")
    _cprint("INFO", f"VES (Bancos nacionales)    : {'#' * bar_ves:<20} {v['pct_ves']:>5.1f}%  Bs {v['bs_ves']:>10,.2f}")
    _cprint("DIM",  f"Tasa activa del inventario : Bs {v['tasa_usada']:.2f}/$")

    # Alerta de tasa
    at = an["alerta_tasa"]
    if at["activa"]:
        _cprint("WARN", f"[!] TASA DESVIADA {at['desviacion_pct']}%")
        _cprint("WARN", f"    Inventario: Bs {at['tasa_inventario']:.2f}  |  Implicita pagos: Bs {at['tasa_implicita']:.2f}")
        _cprint("WARN", f"    Actualiza tasa_bs_usd en inventario_bodega.json para recalcular.")

    # Stock crítico
    sc = an["stock_critico"]
    if sc:
        _cprint("HDR", sep)
        _cprint("WARN", f"RIESGO DE DESABASTO — {len(sc)} producto(s) en zona critica:")
        for p in sc[:8]:
            color = "ERROR" if p["urgencia"] == "AGOTADO" else "WARN"
            _cprint(color, f"  [{p['urgencia']:<8}] {p['nombre']:<30} stock={p['stock']:>3}  {p['accion']}")

    _cprint("HDR", sep)


# ──────────────────────────────────────────────────────────────────────────────
#  MÓDULO AUTÓNOMO — Alertas WA Proactivas, Backups Auto-Rotativos y Cron Nocturno
# ──────────────────────────────────────────────────────────────────────────────
#  Configuración de alertas: añade al .env del proyecto:
#    WA_ADMIN_NUMERO=584164117331   (sin +, sin espacios)
#  El número recibirá alertas de: AGOTADO, TASA DESVIADA y CIERRE DE CAJA.
# ──────────────────────────────────────────────────────────────────────────────

_ALERTA_COOLDOWN = 1800     # segundos mínimos entre alertas del mismo tipo (30 min)
_ultima_alerta: dict = {"agotado": 0.0, "tasa": 0.0, "cierre": 0.0}


def _alertas_proactivas_wa(an: dict) -> None:
    """
    Evalúa el dict de analítica y dispara WhatsApp al administrador cuando:
      · Hay productos en estado AGOTADO
      · La tasa de cambio está desviada > 8 %
    Cooldown de 30 min por tipo para evitar spam.
    Requiere: _WA_CONFIG["enabled"]=True  y  WA_ADMIN_NUMERO en .env.
    """
    if not _WA_CONFIG.get("enabled"):
        return
    numero = os.environ.get("WA_ADMIN_NUMERO", "").strip()
    if not numero:
        return
    ahora = time.time()

    # ── Productos AGOTADOS ─────────────────────────────────────────────────
    agotados = [p for p in an.get("stock_critico", []) if p.get("urgencia") == "AGOTADO"]
    if agotados and (ahora - _ultima_alerta["agotado"]) > _ALERTA_COOLDOWN:
        _ultima_alerta["agotado"] = ahora
        lista = "\n".join(f"  • *{p['nombre']}*" for p in agotados[:6])
        msg   = (
            f"*[JARVIS] ALERTA DE STOCK — AGOTADO*\n"
            f"Los siguientes productos tienen *0 unidades*:\n"
            f"{lista}\n\n"
            f"Realiza el pedido de reposicion de inmediato."
        )
        _cprint("WA", f"Alerta AGOTADO → {numero[:7]}*** ({len(agotados)} prod.)")
        threading.Thread(target=_enviar_whatsapp_humano, args=(numero, msg), daemon=True).start()

    # ── Desviación de tasa > 8 % ───────────────────────────────────────────
    at = an.get("alerta_tasa", {})
    if at.get("activa") and (ahora - _ultima_alerta["tasa"]) > _ALERTA_COOLDOWN:
        _ultima_alerta["tasa"] = ahora
        msg = (
            f"*[JARVIS] ALERTA DE TASA DE CAMBIO*\n"
            f"Desviacion: *{at.get('desviacion_pct', 0):.1f}%*\n"
            f"Tasa inventario : Bs *{at.get('tasa_inventario', 0):.2f}*/$\n"
            f"Tasa de pagos   : Bs *{at.get('tasa_implicita', 0):.2f}*/$\n\n"
            f"Actualiza el campo *tasa_bs_usd* en inventario_bodega.json "
            f"para evitar perdidas por conversion."
        )
        _cprint("WA", f"Alerta TASA → {numero[:7]}*** (desv {at.get('desviacion_pct',0):.1f}%)")
        threading.Thread(target=_enviar_whatsapp_humano, args=(numero, msg), daemon=True).start()


def _verificar_y_alertar() -> None:
    """
    Recalcula la analítica BI y dispara alertas WA si hay condiciones críticas.
    Se ejecuta en hilo daemon tras cada pago registrado — no bloquea el flujo.
    """
    try:
        an = _calcular_analitica()
        _alertas_proactivas_wa(an)
    except Exception as e:
        _cprint("WARN", f"Verificacion proactiva: {e}")


# ── BACKUPS AUTO-ROTATIVOS ─────────────────────────────────────────────────────
def _crear_backup_inicial() -> None:
    """
    Crea un backup fechado de los 3 JSON del negocio en backups/.
    Rota automáticamente: conserva solo los últimos 30 backups por archivo.
    Se ejecuta al arrancar el servidor y antes de cada cierre nocturno.
    """
    import shutil
    from datetime import datetime as _dtb

    base       = _base_exe()
    backup_dir = base / "backups"
    backup_dir.mkdir(exist_ok=True)
    ts         = _dtb.now().strftime("%Y%m%d_%H%M%S")
    archivos   = ["inventario_bodega.json", "calendario_tecnico.json",
                  "ventas_dia.json",        "cuentas_por_cobrar.json"]
    copiados   = []

    for nombre in archivos:
        origen = base / nombre
        if not origen.exists():
            continue
        destino = backup_dir / f"{origen.stem}_{ts}.json"
        try:
            shutil.copy2(str(origen), str(destino))
            copiados.append(nombre)
        except Exception as e:
            _cprint("WARN", f"Backup {nombre}: {e}")

    # Rotación: mantener solo los últimos 30 backups por archivo
    for nombre in archivos:
        stem  = nombre.replace(".json", "")
        todos = sorted(backup_dir.glob(f"{stem}_*.json"))
        for viejo in todos[:-30]:
            try:
                viejo.unlink()
            except Exception:
                pass

    if copiados:
        _cprint("OK", f"Backup {ts}: {', '.join(copiados)} guardados en backups/")
    else:
        _cprint("INFO", "Backup: sin archivos JSON que respaldar aun.")


# ── CRON NOCTURNO — CIERRE DE CAJA AUTOMÁTICO ──────────────────────────────────
def _ejecutar_cierre_diario(gui_app=None) -> None:
    """
    Cierre de caja nocturno (23:59):
      1. Lee ventas_dia.json
      2. Genera analítica BI completa
      3. Acumula en historicos/ventas_YYYY_MM.json  (histórico mensual)
      4. Crea backup de seguridad antes del reset
      5. Resetea ventas_dia.json para el nuevo día
      6. Envía resumen WhatsApp al administrador
    """
    from datetime import datetime as _dtc

    path_v = _base_exe() / "ventas_dia.json"
    if not path_v.exists() or path_v.stat().st_size < 20:
        _cprint("INFO", "Cierre automatico: sin ventas del dia — nada que archivar.")
        return

    try:
        data  = json.loads(path_v.read_text(encoding="utf-8"))
        fecha = data.get("fecha", _dtc.now().strftime("%Y-%m-%d"))
        an    = _calcular_analitica()

        # ── 1. Archivar en historicos/ ─────────────────────────────────────
        historicos = _base_exe() / "historicos"
        historicos.mkdir(exist_ok=True)
        anio_mes  = fecha[:7].replace("-", "_")           # "2026_05"
        path_hist = historicos / f"ventas_{anio_mes}.json"

        if path_hist.exists():
            hist = json.loads(path_hist.read_text(encoding="utf-8"))
        else:
            hist = {"periodo": anio_mes, "dias": [], "total_bs": 0.0, "total_usd": 0.0}

        hist["dias"].append({
            "fecha":         fecha,
            "total_bs":      data.get("total_bs",  0.0),
            "total_usd":     data.get("total_usd", 0.0),
            "transacciones": len(data.get("ventas", [])),
            "pct_usd":       an["ventas"]["pct_usd"],
            "pct_ves":       an["ventas"]["pct_ves"],
        })
        hist["total_bs"]  = round(hist.get("total_bs",  0.0) + data.get("total_bs",  0.0), 2)
        hist["total_usd"] = round(hist.get("total_usd", 0.0) + data.get("total_usd", 0.0), 4)
        path_hist.write_text(json.dumps(hist, ensure_ascii=False, indent=2), encoding="utf-8")
        _cprint("OK", f"Historico mensual: historicos/ventas_{anio_mes}.json actualizado")

        # ── 2. Backup antes del reset ──────────────────────────────────────
        _crear_backup_inicial()

        # ── 3. Resetear ventas_dia.json ────────────────────────────────────
        nuevo_dia = _dtc.now().strftime("%Y-%m-%d")
        path_v.write_text(
            json.dumps({"fecha": nuevo_dia, "ventas": [], "total_bs": 0.0, "total_usd": 0.0},
                       ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        _cprint("OK", f"ventas_dia.json reseteado para el dia {nuevo_dia}")
        _imprimir_analitica_terminal(an)     # resumen final en terminal

        # ── 4. Log en GUI ──────────────────────────────────────────────────
        if gui_app:
            gui_msg = (
                f"[CIERRE {fecha}] Archivado en historicos/ventas_{anio_mes}.json | "
                f"Bs {data['total_bs']:,.2f} | $ {data['total_usd']:,.4f}"
            )
            gui_app.root.after(0, lambda m=gui_msg: gui_app.log(m, "ok"))

        # ── 5. WhatsApp al administrador ───────────────────────────────────
        numero = os.environ.get("WA_ADMIN_NUMERO", "").strip()
        ahora  = time.time()
        if numero and _WA_CONFIG.get("enabled") and (ahora - _ultima_alerta["cierre"]) > 3600:
            _ultima_alerta["cierre"] = ahora
            sc_agot = len([p for p in an["stock_critico"] if p.get("urgencia") == "AGOTADO"])
            wa_msg  = (
                f"*[JARVIS] CIERRE DE CAJA — {fecha}*\n"
                f"Transacciones : *{len(data.get('ventas', []))}*\n"
                f"Total VES     : *Bs {data.get('total_bs', 0):,.2f}*\n"
                f"Total USD     : *$ {data.get('total_usd', 0):,.4f}*\n"
                f"Mix USD/VES   : *{an['ventas']['pct_usd']}%* / {an['ventas']['pct_ves']}%\n"
                f"Stock agotado : *{sc_agot}* producto(s)\n"
                f"Archivo       : historicos/ventas_{anio_mes}.json"
            )
            threading.Thread(target=_enviar_whatsapp_humano, args=(numero, wa_msg), daemon=True).start()
            _cprint("WA", f"Resumen de cierre enviado a {numero[:7]}***")

    except Exception as e:
        _cprint("ERROR", f"Cierre automatico fallido: {e}")


def _cierre_diario_automatico(gui_app=None) -> None:
    """
    Hilo daemon — reloj nocturno del cierre de caja automático.
    · Calcula los segundos restantes hasta las 23:59:00 de hoy.
    · Duerme con time.sleep() hasta ese instante exacto.
    · Ejecuta _ejecutar_cierre_diario() y vuelve a dormir 65 s
      (para evitar re-dispararse en el mismo minuto al dar la medianoche).
    · Anclado en _iniciar_servicios() como threading.Thread daemon=True.
    """
    from datetime import datetime as _dtd, timedelta

    _cprint("INFO", "Cron nocturno iniciado — cierre automatico programado para las 23:59 cada dia")
    while True:
        ahora    = _dtd.now()
        objetivo = ahora.replace(hour=23, minute=59, second=0, microsecond=0)
        if ahora >= objetivo:
            objetivo += timedelta(days=1)

        segundos = max((objetivo - _dtd.now()).total_seconds(), 1)
        _cprint("INFO",
                f"Proximo cierre: {objetivo.strftime('%Y-%m-%d 23:59')} "
                f"(en {segundos / 3600:.1f} h)")
        time.sleep(segundos)

        _cprint("HDR", "=" * 58)
        _cprint("HDR", "  EJECUTANDO CIERRE AUTOMATICO DE CAJA — 23:59")
        _cprint("HDR", "=" * 58)
        _ejecutar_cierre_diario(gui_app)

        time.sleep(65)   # pausa para no re-disparar al cruzar la medianoche


# ──────────────────────────────────────────────────────────────────────────────
#  MÓDULO DE CRÉDITOS Y COBRANZA — Cuentas por Cobrar (Fiado) + Cron Sábado
# ──────────────────────────────────────────────────────────────────────────────
#  Archivo de datos: cuentas_por_cobrar.json
#  Estructura de cada cliente:
#    nombre, telefono_wa, limite_credito_usd, deuda_bs, deuda_usd,
#    fecha_ultimo_pago, fecha_vencimiento, historial[]
# ──────────────────────────────────────────────────────────────────────────────

def _leer_cuentas_cobrar() -> dict:
    """
    Lee cuentas_por_cobrar.json. Crea el archivo con plantilla vacía si no existe.
    Devuelve dict con lista de clientes lista para modificar y guardar.
    """
    path = _base_exe() / "cuentas_por_cobrar.json"
    if not path.exists():
        plantilla = {
            "clientes": [
                {
                    "nombre":              "Ejemplo Cliente",
                    "telefono_wa":         "584160000000",
                    "limite_credito_usd":  50.0,
                    "deuda_bs":            0.0,
                    "deuda_usd":           0.0,
                    "fecha_ultimo_pago":   "",
                    "fecha_vencimiento":   "",
                    "historial":           [],
                }
            ],
            "ultima_actualizacion": "",
        }
        try:
            path.write_text(json.dumps(plantilla, ensure_ascii=False, indent=2), encoding="utf-8")
            _cprint("INFO", "cuentas_por_cobrar.json creado — edita con tus clientes reales.")
        except Exception as e:
            _cprint("WARN", f"No se pudo crear cuentas_por_cobrar.json: {e}")
        return plantilla
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        _cprint("ERROR", f"Error leyendo cuentas_por_cobrar.json: {e}")
        return {"clientes": [], "ultima_actualizacion": ""}


def _guardar_cuentas_cobrar(data: dict) -> bool:
    """Guarda el dict de créditos en cuentas_por_cobrar.json. Devuelve True si OK."""
    from datetime import datetime as _dta
    path = _base_exe() / "cuentas_por_cobrar.json"
    data["ultima_actualizacion"] = _dta.now().isoformat(timespec="seconds")
    try:
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return True
    except Exception as e:
        _cprint("ERROR", f"No se pudo guardar cuentas_por_cobrar.json: {e}")
        return False


def _buscar_cliente(query: str) -> list:
    """
    Busca clientes por nombre parcial o teléfono exacto.
    Devuelve lista de dicts de clientes que coinciden (puede ser vacía).
    """
    q      = query.lower().strip()
    data   = _leer_cuentas_cobrar()
    result = []
    for c in data.get("clientes", []):
        nombre   = str(c.get("nombre",      "")).lower()
        telefono = str(c.get("telefono_wa", ""))
        if q in nombre or q == telefono or telefono.endswith(q):
            result.append(c)
    return result


def _estado_cuenta_cliente(cliente: dict, tasa: float = None) -> dict:
    """
    Calcula el estado de cuenta de un cliente:
      · deuda_total_usd  — suma de deuda_usd + deuda_bs/tasa
      · porcentaje_limite — % del límite de crédito consumido
      · en_mora           — True si fecha_vencimiento ya pasó
      · dias_mora         — días transcurridos desde la fecha de vencimiento
      · credito_bloqueado — True si supera el límite o mora > 7 días
      · disponible_usd    — crédito disponible restante
    """
    from datetime import datetime as _dtb, date as _date
    if tasa is None:
        tasa = _leer_tasa_actual()

    deuda_bs  = float(cliente.get("deuda_bs",  0.0))
    deuda_usd = float(cliente.get("deuda_usd", 0.0))
    limite    = float(cliente.get("limite_credito_usd", 50.0))

    deuda_total_usd = round(deuda_usd + (deuda_bs / tasa if tasa > 0 else 0), 4)

    en_mora, dias_mora = False, 0
    venc_str = str(cliente.get("fecha_vencimiento", "")).strip()
    if venc_str:
        try:
            venc = _dtb.strptime(venc_str, "%Y-%m-%d").date()
            hoy  = _date.today()
            if hoy > venc:
                en_mora   = True
                dias_mora = (hoy - venc).days
        except Exception:
            pass

    bloqueado = deuda_total_usd > limite or (en_mora and dias_mora > 7)

    return {
        "deuda_total_usd":   deuda_total_usd,
        "porcentaje_limite": round(deuda_total_usd / limite * 100, 1) if limite > 0 else 0,
        "disponible_usd":    max(round(limite - deuda_total_usd, 4), 0),
        "en_mora":           en_mora,
        "dias_mora":         dias_mora,
        "credito_bloqueado": bloqueado,
        "tasa_usada":        tasa,
    }


def _enviar_recordatorio_cobro(cliente: dict) -> None:
    """
    Compone y envía mensaje cortés de recordatorio de pago por WhatsApp.
    Si el webhook está desactivado, imprime el mensaje simulado en terminal.
    """
    numero = str(cliente.get("telefono_wa", "")).strip()
    nombre = str(cliente.get("nombre", "Estimado cliente"))
    if not numero:
        _cprint("WARN", f"Sin telefono para {nombre} — recordatorio omitido")
        return

    tasa    = _leer_tasa_actual()
    estado  = _estado_cuenta_cliente(cliente, tasa)
    deuda_bs  = float(cliente.get("deuda_bs",  0.0))
    deuda_usd = float(cliente.get("deuda_usd", 0.0))

    saldo_str = (f"*$ {deuda_usd:.2f} USD* (equiv. Bs {deuda_bs:,.2f})"
                 if deuda_usd > 0 else f"*Bs {deuda_bs:,.2f}*")

    linea_mora = (f"Tu cuenta tiene *{estado['dias_mora']} dia(s) de mora*.\n"
                  if estado["en_mora"] else "")

    msg = (
        f"Hola *{nombre}*!\n"
        f"Te recordamos que tienes un saldo pendiente:\n\n"
        f"Saldo: {saldo_str}\n"
        f"{linea_mora}"
        f"\nCuando puedas realizarnos el pago, escribenos aqui mismo para coordinar.\n"
        f"Gracias por tu preferencia!"
    )

    if _WA_CONFIG.get("enabled"):
        _cprint("WA", f"Recordatorio cobro → {nombre} ({numero[:7]}***)")
        _enviar_whatsapp_humano(numero, msg)
    else:
        _cprint("INFO", f"[COBRO-SIM] {nombre} ({numero[:7]}***): {saldo_str}")


def _cron_cobros_sabado(gui_app=None) -> None:
    """
    Hilo daemon — recordatorios automáticos de cobro cada sábado a las 09:00.
    · Calcula segundos hasta el próximo sábado 09:00.
    · Recorre todos los clientes con deuda > 0 y llama a _enviar_recordatorio_cobro().
    · Espera 3–7 s entre mensajes para no ser detectado como spam.
    · Duerme 12 h tras la ronda para no re-disparar el mismo sábado.
    Anclado en _iniciar_servicios() como threading.Thread daemon=True.
    """
    from datetime import datetime as _dtc, timedelta

    _cprint("INFO", "Cron de cobros iniciado — recordatorios automaticos cada sabado 09:00")
    while True:
        ahora               = _dtc.now()
        dias_hasta_sabado   = (5 - ahora.weekday()) % 7   # 5 = sábado
        if dias_hasta_sabado == 0 and ahora.hour >= 9:
            dias_hasta_sabado = 7   # ya pasó este sábado → esperar el siguiente

        objetivo = (ahora + timedelta(days=dias_hasta_sabado)).replace(
            hour=9, minute=0, second=0, microsecond=0
        )
        segundos = max((objetivo - _dtc.now()).total_seconds(), 1)
        _cprint("INFO",
                f"Proximo cobro: {objetivo.strftime('%Y-%m-%d (sabado) %H:%M')} "
                f"(en {segundos / 3600:.1f} h)")
        time.sleep(segundos)

        _cprint("HDR", "=" * 58)
        _cprint("HDR", "  CRON DE COBROS — SABADO 09:00 — ENVIANDO RECORDATORIOS")
        _cprint("HDR", "=" * 58)

        try:
            data     = _leer_cuentas_cobrar()
            clientes = data.get("clientes", [])
            deudores = [
                c for c in clientes
                if float(c.get("deuda_bs", 0)) > 0 or float(c.get("deuda_usd", 0)) > 0
            ]
            _cprint("INFO", f"Deudores encontrados: {len(deudores)}")

            for cliente in deudores:
                try:
                    _enviar_recordatorio_cobro(cliente)
                    time.sleep(random.uniform(3.0, 7.0))
                except Exception as e:
                    _cprint("WARN", f"Recordatorio {cliente.get('nombre','?')}: {e}")

            if gui_app:
                gui_msg = f"[COBROS] Recordatorios enviados a {len(deudores)} deudor(es)"
                gui_app.root.after(0, lambda m=gui_msg: gui_app.log(m, "info"))

        except Exception as e:
            _cprint("ERROR", f"Cron cobros sabado: {e}")

        time.sleep(3600 * 12)   # dormir 12 h — no re-disparar el mismo sábado


# ── HELPERS DE CONSOLA Y VOZ ─────────────────────────────────────────────────
def _mostrar_deudores_terminal() -> tuple:
    """
    Imprime la lista de deudores en terminal con colores ANSI y devuelve
    la tupla para la GUI de Jarvis.
    Verde = al día  |  Amarillo = mora  |  Rojo = crédito bloqueado.
    Comando de consola: 'ver deudores'
    """
    tasa     = _leer_tasa_actual()
    data     = _leer_cuentas_cobrar()
    deudores = [
        c for c in data.get("clientes", [])
        if float(c.get("deuda_bs", 0)) > 0 or float(c.get("deuda_usd", 0)) > 0
    ]

    if not deudores:
        _cprint("INFO", "Sin deudores activos — cuaderno de fiado limpio.")
        return ("__cian__", "[FIADO] No hay cuentas pendientes actualmente.")

    sep = "=" * 62
    print(f"\n{_ANSI['HDR']}  {sep}{_ANSI['RST']}")
    print(f"{_ANSI['HDR']}  CUENTAS POR COBRAR ({len(deudores)} deudor(es))  "
          f"Tasa: Bs {tasa:.2f}/$  {_ANSI['RST']}")
    print(f"{_ANSI['HDR']}  {sep}{_ANSI['RST']}")
    hdr = f"  {'CLIENTE':<24}{'DEUDA USD':>10}{'DEUDA Bs':>12}{'MORA':>7}{'ESTADO':>12}"
    print(f"{_ANSI['DIM']}{hdr}{_ANSI['RST']}")
    print(f"{_ANSI['DIM']}  {'-'*60}{_ANSI['RST']}")

    total_bs = total_usd = 0.0
    for c in deudores:
        estado   = _estado_cuenta_cliente(c, tasa)
        nombre   = str(c.get("nombre", "?"))[:23]
        d_bs     = float(c.get("deuda_bs",  0))
        d_usd    = float(c.get("deuda_usd", 0))
        mora_txt = f"{estado['dias_mora']}d" if estado["en_mora"] else "OK"
        est_txt  = ("BLOQUEADO" if estado["credito_bloqueado"]
                    else ("MORA" if estado["en_mora"] else "Al dia"))
        color    = (_ANSI["ERROR"] if estado["credito_bloqueado"]
                    else (_ANSI["WARN"] if estado["en_mora"] else _ANSI["OK"]))
        fila = (f"  {nombre:<24}$ {d_usd:>7.2f}  Bs {d_bs:>9.2f}"
                f"  {mora_txt:>5}  {est_txt:>9}")
        print(f"{color}{fila}{_ANSI['RST']}")
        total_bs  += d_bs
        total_usd += d_usd

    print(f"{_ANSI['HDR']}  {sep}{_ANSI['RST']}")
    _cprint("PAGO", f"TOTAL DEUDA : $ {total_usd:,.2f} USD  |  Bs {total_bs:,.2f}")
    print(f"{_ANSI['HDR']}  {sep}{_ANSI['RST']}\n")

    return (
        "__cian__",
        f"[FIADO — {len(deudores)} deudores]\n"
        f"  Total USD : $ {total_usd:,.2f}\n"
        f"  Total Bs  : Bs {total_bs:,.2f}",
    )


def _humanizar_balance_cliente(nombre_query: str) -> tuple:
    """
    Busca al cliente, calcula su balance y devuelve una respuesta humanizada
    lista para que Jarvis la pronuncie por voz.
    Se activa con frases tipo: 'cuanto debe Maria', 'saldo de Carlos'.
    """
    encontrados = _buscar_cliente(nombre_query)
    if not encontrados:
        resp = (f"No encontre ningun cliente llamado {nombre_query} "
                f"en el cuaderno de fiado.")
        return ("__cian__", f"[FIADO] {resp}")

    tasa   = _leer_tasa_actual()
    c      = encontrados[0]
    nombre = c.get("nombre", nombre_query)
    d_bs   = float(c.get("deuda_bs",  0))
    d_usd  = float(c.get("deuda_usd", 0))
    estado = _estado_cuenta_cliente(c, tasa)

    if d_bs == 0 and d_usd == 0:
        resp = f"{nombre} no tiene deuda pendiente. Esta al dia."
    else:
        partes = []
        if d_usd > 0:
            partes.append(f"$ {d_usd:.2f} dolares")
        if d_bs > 0:
            partes.append(f"Bs {d_bs:,.2f}")
        saldo_str = " mas ".join(partes)

        if estado["credito_bloqueado"]:
            resp = (f"{nombre} debe {saldo_str}. "
                    f"Su credito esta BLOQUEADO con {estado['dias_mora']} dias de mora.")
        elif estado["en_mora"]:
            resp = (f"{nombre} debe {saldo_str}. "
                    f"Tiene {estado['dias_mora']} dias de mora.")
        else:
            resp = (f"{nombre} debe {saldo_str}. "
                    f"Credito disponible: $ {estado['disponible_usd']:.2f}.")

    return ("__cian__", f"[FIADO] {resp}")


# ──────────────────────────────────────────────────────────────────────────────
#  VERIFICACIÓN DE DEPENDENCIAS
# ──────────────────────────────────────────────────────────────────────────────
def _verificar_dependencias():
    """Instala paquetes faltantes antes de arrancar la GUI."""
    import importlib.util
    import subprocess as _sp
    _DEPS = {
        "cv2":         "opencv-python",
        "sounddevice": "sounddevice",
        "numpy":       "numpy",
        "requests":    "requests",
        "anthropic":   "anthropic",
        "dotenv":      "python-dotenv",
        "pyautogui":   "pyautogui",
    }
    for modulo, paquete in _DEPS.items():
        if importlib.util.find_spec(modulo) is None:
            print(f"[DEPS] {paquete} no encontrado — instalando...")
            _sp.run([sys.executable, "-m", "pip", "install", paquete], check=False)
            print(f"[DEPS] {paquete} listo.")

def speak(text):
    """Punto de entrada de voz para toda la GUI — delega a modulos/voz.py."""
    _voz.hablar(text)


# ── HELPER: LOG DE PAGOS ──────────────────────────────────────────────────────
def _ver_pagos_recibidos(n: int = 10) -> tuple:
    import json
    log = _base_exe() / "pagos_recibidos.log"
    if not log.exists() or log.stat().st_size == 0:
        return ("__cian__",
                "[FINTECH] No hay pagos registrados todavia.\n"
                "  Usa: leer correo [texto del correo]")
    lineas = [l.strip() for l in log.read_text(encoding="utf-8").splitlines() if l.strip()]
    if not lineas:
        return ("__cian__", "[FINTECH] El registro de pagos esta vacio.")
    ultimas = lineas[-n:]
    sep = "-" * 64
    filas = [f"\n[FINTECH] Ultimos {len(ultimas)} pago(s):\n{sep}"]
    total_usd = 0.0
    for linea in reversed(ultimas):
        partes = linea.split(" | ", 1)
        if len(partes) == 2:
            ts, datos_str = partes
            try:
                d = json.loads(datos_str)
                monto = d.get("monto", "?")
                try:
                    total_usd += float(monto.replace(",", "."))
                except (ValueError, AttributeError):
                    pass
                filas.append(
                    f"  {ts[:16]}  {d.get('banco','?'):<22}"
                    f"  {monto:<10}  Ref: {d.get('referencia','?')}"
                )
            except Exception:
                filas.append(f"  {linea}")
    filas.append(f"{sep}\n  Total acumulado: {total_usd:.2f}")
    return ("__cian__", "\n".join(filas))


# ──────────────────────────────────────────────────────────────────────────────
#  PROCESADOR CENTRAL DE COMANDOS
# ──────────────────────────────────────────────────────────────────────────────
class ComandoParser:
    def __init__(self, gui):
        self.gui = gui
        self.historial_tecnico = []

    def procesar(self, texto: str):
        cmd = texto.lower().strip()

        # ── Motor de comandos configurables (comandos_custom.json) ──────────────
        # Máxima prioridad — responde sin llamar a la IA ni gastar tokens.
        try:
            _res = _cmd_engine(texto)
        except Exception as e:
            _res = None
            _logger.registrar("comando", e, f"_cmd_engine('{texto[:40]}')")
        if _res:
            if _res["voz"]:
                speak(_res["voz"])
            return ("__cian__", f"[CMD:{_res['id']}] {_res['consola']}")

        # ── REPOSO / DESPERTAR ────────────────────────────────────────────────
        _KW_REPOSO    = ("descansa", "modo reposo", "entra en reposo", "pausa mic")
        _KW_DESPERTAR = ("despierta", "vuelve", "actívate", "sal del reposo")
        if any(x in cmd for x in _KW_REPOSO):
            self.gui.root.after(0, self.gui._activar_reposo)
            return ("__cian__", "[REPOSO] En espera. Di 'Jarvis despierta' para continuar.")
        if any(x in cmd for x in _KW_DESPERTAR):
            if self.gui._en_reposo:
                self.gui.root.after(0, self.gui._desactivar_reposo)
                speak("De vuelta al trabajo, Abigail.")
            return ("__cian__", "[REPOSO] Modo reposo desactivado — escuchando.")

        respuesta_chat = jarvis_chat.procesar(texto)
        if respuesta_chat is not None:
            voz = respuesta_chat.get("voz", "")
            if voz:
                speak(voz)
            accion = respuesta_chat.get("accion", "")
            if accion:
                return ("__accion__", accion)
            return ("__cian__", respuesta_chat["consola"])

        if cmd.startswith("db "):
            partes = texto.split()
            return technical_db.consultar(
                partes[1] if len(partes) > 1 else "",
                partes[2] if len(partes) > 2 else "",
                partes[3] if len(partes) > 3 else "",
            )

        if any(x in cmd for x in ("categorias db", "categorías db", "lista db", "ver db")):
            return technical_db.listar_categorias_db()

        if any(x in cmd for x in ("verificar sintaxis", "check sintaxis", "ast check")):
            return ("__cian__", jarvis_chat.verificar_sintaxis())

        if any(x in cmd for x in ("abrir vscode", "open vscode", "vs code", "vscode")):
            return sistema.abrir_vscode()
        if "powershell" in cmd:
            return sistema.abrir_terminal("powershell")
        if any(x in cmd for x in ("abrir cmd", "terminal cmd", "open cmd")):
            return sistema.abrir_terminal("cmd")
        if any(x in cmd for x in ("inicializar workspace", "crear workspace", "init workspace")):
            return sistema.inicializar_workspace()
        if any(x in cmd for x in ("listar workspace", "ver workspace")):
            return sistema.listar_workspace()

        # ── PAGOS FINTECH — leer correos de Zinli, MYPAL, Mercantil, Facebank, Pipol Pay ─
        _KW_CORREO = (
            "leer correo", "procesar correo", "leer pago", "registrar pago",
            "nuevo pago", "correo zinli", "correo mypal", "correo mercantil",
            "correo facebank", "correo pipol",
        )
        if any(cmd.startswith(kw) for kw in _KW_CORREO):
            texto_correo = texto
            for kw in sorted(_KW_CORREO, key=len, reverse=True):
                if cmd.startswith(kw):
                    texto_correo = texto[len(kw):].strip()
                    break
            if not texto_correo:
                return ("__cian__",
                        "[FINTECH] Pega el texto del correo despues del comando.\n"
                        "  Ej: leer correo Zinli Ref. 261792471332 Amount $25.00\n"
                        "  Bancos: Zinli | MYPAL | Mercantil | Facebank | Pipol Pay")
            resultado = _fintech.procesar_correo(texto_correo)
            if resultado:
                speak(f"Pago de {resultado['banco']} por {resultado['monto']} registrado.")
                return ("__cian__",
                        f"[PAGO REGISTRADO]\n"
                        f"  Banco      : {resultado['banco']}\n"
                        f"  Monto      : {resultado['monto']}\n"
                        f"  Referencia : {resultado['referencia']}")
            return ("__cian__",
                    "[FINTECH] Banco no reconocido en el texto.\n"
                    "  Bancos soportados: Zinli, MYPAL, Mercantil Banco Panama, Facebank, Pipol Pay\n"
                    "  Asegurate de incluir el nombre del banco y el monto.")

        if any(x in cmd for x in ("ver pagos", "ultimos pagos", "ultimos pagos",
                                   "historial pagos", "pagos recibidos", "mis pagos",
                                   "reporte pagos", "cuanto me han pagado")):
            return _ver_pagos_recibidos()

        if any(x in cmd for x in ("resumen diario", "resumen del dia", "resumen del día",
                                   "ventas hoy", "total hoy", "facturado hoy",
                                   "cuanto vendi", "cuánto vendí", "caja del dia")):
            return _mostrar_resumen_diario()

        # ── FIADO — ver deudores ───────────────────────────────────────────────
        if any(x in cmd for x in ("ver deudores", "lista deudores", "deudores",
                                   "cuaderno fiado", "ver fiado", "quien debe",
                                   "quienes deben", "cuentas cobrar")):
            return _mostrar_deudores_terminal()

        # ── FIADO — registrar cargo: fiado [nombre] [monto_usd] ───────────────
        if cmd.startswith("fiado "):
            partes = texto.split()
            if len(partes) >= 3:
                try:
                    monto_usd = float(partes[-1].replace(",", "."))
                    nombre_q  = " ".join(partes[1:-1])
                    encontrados = _buscar_cliente(nombre_q)
                    if not encontrados:
                        return ("__cian__",
                                f"[FIADO] Cliente '{nombre_q}' no encontrado.\n"
                                f"  Registra primero con el endpoint /clientes.")
                    nombre_real = encontrados[0]["nombre"]
                    data_c      = _leer_cuentas_cobrar()
                    tasa_c      = _leer_tasa_actual()
                    for c in data_c["clientes"]:
                        if c.get("nombre","").lower() == nombre_real.lower():
                            c["deuda_usd"] = round(float(c.get("deuda_usd", 0)) + monto_usd, 4)
                            c["deuda_bs"]  = round(float(c.get("deuda_bs",  0)) + monto_usd * tasa_c, 2)
                            break
                    _guardar_cuentas_cobrar(data_c)
                    _cprint("INFO", f"Fiado: $ {monto_usd:.2f} USD sumado a {nombre_real}")
                    speak(f"Fiado de {monto_usd} dolares registrado para {nombre_real}.")
                    nueva_deuda = next((c["deuda_usd"] for c in data_c["clientes"]
                                        if c.get("nombre","").lower() == nombre_real.lower()), monto_usd)
                    return ("__cian__",
                            f"[FIADO] $ {monto_usd:.2f} USD sumado a {nombre_real}.\n"
                            f"  Nueva deuda USD: $ {nueva_deuda:.2f}")
                except ValueError:
                    return ("__cian__",
                            "[FIADO] Formato: fiado [nombre] [monto_usd]\n"
                            "  Ej: fiado Maria 10.50")
            return ("__cian__",
                    "[FIADO] Formato: fiado [nombre] [monto_usd]\n"
                    "  Ej: fiado Carlos 5")

        # ── ZYNC SUITE — DIVISAS P2P ──────────────────────────────────────────
        if any(x in cmd for x in ("ver tasas", "tasas hoy", "tasa cambio",
                                   "tasa bcv", "tasa binance", "spread")):
            from modulos.divisas_suite import formatear_tasas_consola
            return ("__cian__", formatear_tasas_consola())

        if cmd.startswith("tasa bcv ") or cmd.startswith("set bcv "):
            val = texto.split()[-1].replace(",", ".")
            try:
                from modulos.divisas_suite import actualizar_tasas, formatear_tasas_consola
                t = actualizar_tasas(bcv=float(val))
                return ("__cian__", formatear_tasas_consola())
            except ValueError:
                return ("__cian__", f"[DIVISAS] Valor inválido: {val}")

        if cmd.startswith("tasa binance ") or cmd.startswith("set binance "):
            val = texto.split()[-1].replace(",", ".")
            try:
                from modulos.divisas_suite import actualizar_tasas, formatear_tasas_consola
                actualizar_tasas(binance=float(val))
                return ("__cian__", formatear_tasas_consola())
            except ValueError:
                return ("__cian__", f"[DIVISAS] Valor inválido: {val}")

        if any(x in cmd for x in ("actualizar tasas", "refrescar tasas",
                                   "update tasas", "auto tasas")):
            from modulos.divisas_suite import refrescar_tasas_auto, formatear_tasas_consola
            import threading as _thr
            def _ref():
                refrescar_tasas_auto()
                self.gui.root.after(0, lambda: self.gui.log(
                    formatear_tasas_consola(), "info"))
            _thr.Thread(target=_ref, daemon=True).start()
            return ("__cian__", "[DIVISAS] Actualizando tasas en segundo plano ...")

        if any(x in cmd for x in ("resumen p2p", "resumen mes p2p", "ganancias p2p",
                                   "resumen divisas", "ciclos mes")):
            from modulos.divisas_suite import formatear_resumen_mensual_consola
            return ("__cian__", formatear_resumen_mensual_consola())

        # ── ZYNC SUITE — IMPORTACIONES ────────────────────────────────────────
        if any(x in cmd for x in ("ver pedidos importacion", "listar importaciones",
                                   "mis pedidos china", "pedidos activos")):
            from modulos.importaciones_suite import resumen_listado_consola
            return ("__cian__", resumen_listado_consola())

        # ────────────────────────────────────────────────────────────────────────
        if any(x in cmd for x in ("calcular arbitraje", "calcular p2p", "arbitraje p2p")):
            self.gui.root.after(0, self.gui.abrir_dialogo_arbitraje)
            return "Calculadora P2P abierta."
        if any(x in cmd for x in ("mypal", "cargar mypal")):
            self.gui.root.after(0, self.gui.abrir_dialogo_mypal)
            return "Simulador Mypal abierto."
        for plat in finanzas.PLATAFORMAS_WEB:
            if plat in cmd:
                return finanzas.abrir_plataforma(plat)

        if any(x in cmd for x in ("calcular importacion", "calcular flete", "calcular importación")):
            self.gui.root.after(0, self.gui.abrir_dialogo_importacion)
            return "Calculadora de importación abierta."
        if cmd.startswith("crear pedido"):
            partes = texto.split()
            ref = partes[-1].upper() if len(partes) > 2 else "PEDIDO-001"
            return importaciones.crear_carpeta_pedido(ref)
        if "listar pedidos" in cmd:
            return importaciones.listar_pedidos()
        for tienda in importaciones.TIENDAS:
            if tienda in cmd:
                return importaciones.abrir_tienda(tienda)
        for courier in importaciones.COURIERS:
            if courier in cmd:
                return importaciones.abrir_courier(courier)

        if any(x in cmd for x in ("ver tecnico", "ver técnico", "analizar placa",
                                   "analizar tarjeta", "foto tecnico", "foto técnico")):
            contexto = texto.split(" ", 2)[2] if len(texto.split()) > 2 else ""
            return ("__vision__", "tecnico", contexto)
        if any(x in cmd for x in ("ver trading", "analizar grafica", "analizar gráfica",
                                   "señal trading", "foto trading")):
            return ("__vision__", "trading", "")
        if any(x in cmd for x in ("ver inventario", "identificar pieza",
                                   "identificar herramienta", "foto inventario")):
            return ("__vision__", "inventario", "")
        if any(x in cmd for x in ("estado vision", "estado descarga", "progreso vision",
                                   "estado modelo vision")):
            return vision_mod.estado_descarga()
        if any(x in cmd for x in ("instalar dependencias", "verificar libs",
                                   "verificar dependencias", "check libs")):
            return ("__verificar_deps__",)
        if any(x in cmd for x in ("instalar vision", "instalar llava",
                                   "instalar moondream", "descargar vision",
                                   "descargar moondream")):
            return ("__instalar_vision__",)
        _kw_vision_gen = (
            "ver general", "ver cara", "ver mano", "ver objeto",
            "qué tengo en", "que tengo en",
            "qué tengo puesta", "que tengo puesta",
            "qué tengo puesto", "que tengo puesto",
            "qué hay en mi", "que hay en mi",
            "qué ves", "que ves",
            "describe lo que ves", "analiza lo que tengo",
            "en la cara", "en la mano", "en mis manos",
            "en mis ojos", "en mi cabeza", "en mi cuello",
            "en mi muñeca", "en mis dedos", "en mi mano",
        )
        if any(x in cmd for x in _kw_vision_gen):
            contexto = texto if len(texto.split()) <= 3 else texto
            return ("__vision__", "general", contexto)
        if any(x in cmd for x in ("preview camara", "preview cámara", "ver camara", "encuadrar")):
            return vision_mod.preview_camara()
        if cmd.startswith("camara ") or cmd.startswith("cámara "):
            fuente = texto.split(" ", 1)[1].strip()
            try:
                fuente = int(fuente)
            except ValueError:
                pass
            return vision_mod.cambiar_camara(fuente)

        # ── DIAGNÓSTICO LOCAL — diagnosticos.txt (sin IA, sin internet) ──────────
        _KW_DIAG_LOCAL = ("error ", "diag local ", "codigo error ", "código error ")
        if any(cmd.startswith(kw) for kw in _KW_DIAG_LOCAL):
            consulta = texto.split(" ", 1)[1].strip()
            try:
                from diagnostico import buscar_diagnostico
                return ("__cian__", buscar_diagnostico(consulta))
            except Exception as e:
                msg = _logger.registrar("diagnostico", e, f"consulta: {consulta[:50]}")
                speak(msg)
                return ("__cian__", f"[ERROR DIAGNOSTICO] {type(e).__name__}: {e}")

        # ── INVENTARIO LOCAL ──────────────────────────────────────────────────────
        if cmd.startswith(("stock ", "buscar pieza ", "pieza ")):
            nombre = texto.split(" ", 1)[1].strip()
            try:
                from inventario import buscar_producto
                return ("__cian__", buscar_producto(nombre))
            except Exception as e:
                msg = _logger.registrar("inventario", e, f"buscar '{nombre}'")
                speak(msg)
                return ("__cian__", f"[ERROR INVENTARIO] {type(e).__name__}: {e}")

        if any(x in cmd for x in ("listar inventario", "listar stock",
                                   "ver stock completo", "todo el stock")):
            try:
                from inventario import listar_inventario
                return ("__cian__", listar_inventario())
            except Exception as e:
                msg = _logger.registrar("inventario", e, "listar")
                speak(msg)
                return ("__cian__", f"[ERROR INVENTARIO] {type(e).__name__}: {e}")

        if any(x in cmd for x in ("alertas stock", "stock bajo",
                                   "piezas agotadas", "repuestos agotados")):
            try:
                from inventario import alertas_stock_bajo
                return ("__cian__", alertas_stock_bajo())
            except Exception as e:
                msg = _logger.registrar("inventario", e, "alertas")
                speak(msg)
                return ("__cian__", f"[ERROR INVENTARIO] {type(e).__name__}: {e}")

        if cmd.startswith("actualizar stock "):
            partes = texto.split()
            if len(partes) >= 4:
                try:
                    from inventario import actualizar_stock
                    nombre, cantidad = partes[2], int(partes[3])
                    return ("__cian__", actualizar_stock(nombre, cantidad))
                except (ValueError, IndexError):
                    pass
                except Exception as e:
                    msg = _logger.registrar("inventario", e, f"actualizar {' '.join(partes[2:4])}")
                    speak(msg)
                    return ("__cian__", f"[ERROR INVENTARIO] {type(e).__name__}: {e}")
            return ("__cian__",
                    "[INVENTARIO] Formato: actualizar stock NOMBRE CANTIDAD\n"
                    "  Ej: actualizar stock Bomba_Desague 5")

        if any(cmd.startswith(x) for x in ("diagnostico ", "diagnóstico ")):
            falla = texto.split(" ", 1)[1] if " " in texto else texto
            return self._consulta_tecnica(falla)
        if any(x in cmd for x in ("categorias tecnicas", "categorías técnicas", "lista categorias")):
            return tecnico.listar_categorias()

        if any(x in cmd for x in ("ver errores", "ver log", "errores jarvis", "log errores")):
            return ("__cian__", _logger.ultimos_errores())
        if any(x in cmd for x in ("limpiar log", "borrar errores", "limpiar errores")):
            return ("__cian__", _logger.limpiar_log())
        if any(x in cmd for x in ("ayuda", "help", "comandos")):
            return _AYUDA
        if any(x in cmd for x in ("recargar comandos", "reload comandos", "actualizar comandos")):
            from modulos.comando_engine import recargar as _recargar
            return ("__cian__", _recargar())
        if any(x in cmd for x in ("reintentar voz", "reintentar gcloud", "reconectar voz", "voz neural")):
            _voz.reintentar_gcloud()
            speak("Reintentando voz neural de Google.")
            return ("__cian__", "[VOZ] gCloud flag reseteado — próxima llamada intentará Neural2.")

        if any(x in cmd for x in ("estado voz", "diagnostico voz", "diagnóstico voz",
                                   "probar voz", "test voz", "ver voz")):
            return ("__cian__", _voz.estado_voz())

        if any(x in cmd for x in ("ver error voz", "error voz", "por que no habla",
                                   "por qué no habla", "error gcloud")):
            return ("__cian__", f"[VOZ] Último error gCloud:\n  {_voz.ultimo_error_gcloud()}")

        # ── CONSULTA DE BALANCE POR VOZ / TEXTO ───────────────────────────────
        # Frases: "cuanto debe Juan", "saldo de Maria", "balance de Carlos"
        _KW_FIADO_Q = (
            "cuanto debe ",  "cuánto debe ",  "saldo de ",
            "balance de ",   "deuda de ",     "fiado de ",
            "cuenta de ",    "que debe ",     "qué debe ",
        )
        if any(cmd.startswith(kw) for kw in _KW_FIADO_Q):
            nombre_q = texto
            for kw in sorted(_KW_FIADO_Q, key=len, reverse=True):
                if cmd.startswith(kw):
                    nombre_q = texto[len(kw):].strip()
                    break
            if nombre_q:
                resultado = _humanizar_balance_cliente(nombre_q)
                # Pronunciar la respuesta por voz
                speak(resultado[1].replace("[FIADO] ", ""))
                return resultado

        if len(cmd) > 4:
            return self._consulta_tecnica(texto)
        return "Comando no reconocido. Escribe 'ayuda' para ver los comandos disponibles."

    def _consulta_tecnica(self, pregunta: str):
        # Reset streaming header — first on_token call will create the [AI] header line
        self.gui._streaming_header_logged = False

        def on_token(token):
            self.gui.root.after(0, lambda t=token: self.gui._append_log(t))

        try:
            respuesta = tecnico.consultar(pregunta, self.historial_tecnico, on_token=on_token)
        except Exception as e:
            msg = _logger.registrar("ia", e, pregunta[:60])
            speak(msg)
            return ("__cian__", f"[ERROR IA] {type(e).__name__}: {e}")

        # Créditos agotados → aviso claro + intento con DB local
        if any(x in respuesta for x in ("credit balance is too low",
                                         "Error code: 400", "Error code: 429")):
            db_res = technical_db.buscar_libre(pregunta)
            if db_res:
                return ("__cian__",
                        f"[DB LOCAL]\n{db_res}\n\n"
                        "⚠ API Anthropic sin créditos — recarga en console.anthropic.com")
            return ("__cian__",
                    "⚠ La API Anthropic no tiene créditos disponibles.\n"
                    "→ Recarga en: console.anthropic.com → Plans & Billing\n"
                    "Mientras tanto usa: 'db ac_presiones R410A', 'db lavadora', etc.")

        self.historial_tecnico.append({"role": "user",      "content": pregunta})
        self.historial_tecnico.append({"role": "assistant", "content": respuesta})
        if len(self.historial_tecnico) > 20:
            self.historial_tecnico = self.historial_tecnico[-20:]
        # Content already streamed to GUI — return sentinel so _mostrar_resultado only speaks
        return ("__streamed__", respuesta)

    def limpiar_historial(self):
        self.historial_tecnico = []
        return "Historial de conversación técnica reiniciado."


_AYUDA = """
═══════════════════════════════════════════════
  JARVIS v4.0 — COMANDOS DISPONIBLES
═══════════════════════════════════════════════
  HERRAMIENTAS
  • abrir vscode / abrir cmd / abrir powershell
  • inicializar workspace / listar workspace

  PAGOS FINTECH (correos + push notifications)
  • leer correo [texto del correo]
  • correo zinli / correo mypal / correo mercantil
  • correo facebank / correo pipol
  • ver pagos / historial pagos / reporte pagos
  MacroDroid → POST /alerta {title, text} (push notifications bancarias)

  FINANZAS P2P
  • calcular arbitraje / calcular p2p / mypal
  • binance / binance_p2p / bybit / el dorado
  • apolopay / airtm / banesco / mercantil

  IMPORTACIONES
  • calcular importacion / crear pedido [REF]
  • 1688 / alibaba / aliexpress / shopify
  • sgcargo / viajocargo / import2ven / mailroom

  DIAGNÓSTICO LOCAL (sin IA, sin internet)
  • error [Marca] [Modelo] [Código]
  • error Haier Split_12000 E5
  • error Samsung lavadora 5E
  • error LG OE

  INVENTARIO DE REPUESTOS
  • stock [nombre]          → buscar pieza
  • listar inventario       → tabla completa
  • alertas stock           → piezas agotadas
  • actualizar stock NOMBRE CANTIDAD

  BASE TÉCNICA LOCAL (sin API, instantáneo)
  • db ac_presiones [R410A|R22|R32]
  • db capacitor [BTU]
  • db nevera / lavadora / microondas / airfryer
  • categorias db

  VISIÓN MULTIMODAL
  • ver general [pregunta]  → qué ves / describe / cara / mano / objeto
  • ver tecnico [contexto]  → diagnóstico PCB
  • ver trading             → análisis gráfica
  • ver inventario          → identificar piezas
  • preview camara          → encuadrar cámara

  TÉCNICO IA
  • diagnostico [descripción]
  • Cualquier pregunta libre → IA Claude

  UTILIDADES
  • hora / fecha / hola / cómo estás / gracias
  • jarvis descansa    → modo reposo (mic en espera, sin CPU/IA)
  • jarvis despierta   → cancela reposo, vuelve a escuchar
  • recargar comandos  → recarga comandos_custom.json
  • ver errores        → últimos errores en jarvis_error.log
  • limpiar log        → borra jarvis_error.log
  • ayuda              → este menú

  COMANDOS PERSONALIZADOS
  • Edita comandos_custom.json para añadir los tuyos
  • Los cambios tienen efecto inmediato (sin reiniciar)
═══════════════════════════════════════════════"""


# ──────────────────────────────────────────────────────────────────────────────
#  DIÁLOGOS FLOTANTES
# ──────────────────────────────────────────────────────────────────────────────
def _dialogo_base(root, titulo, ancho=380, alto=300):
    d = tk.Toplevel(root)
    d.title(titulo)
    d.configure(bg="#111")
    d.geometry(f"{ancho}x{alto}")
    d.grab_set()
    d.resizable(False, False)
    return d


def _campo(parent, fila, label, default, bg="#111"):
    tk.Label(parent, text=label, fg="#00ffcc", bg=bg,
             font=("Consolas", 9)).grid(row=fila, column=0, padx=12, pady=5, sticky="w")
    e = tk.Entry(parent, bg="#222", fg="white", insertbackground="white",
                 font=("Consolas", 10), relief="flat", bd=4)
    e.insert(0, default)
    e.grid(row=fila, column=1, padx=10, pady=5, sticky="ew")
    return e


def _boton(parent, fila, texto, cmd, cols=2):
    tk.Button(parent, text=texto, command=cmd, bg="#004d40", fg="white",
              font=("Arial", 10, "bold"), relief="flat", cursor="hand2",
              activebackground="#006655").grid(row=fila, column=0, columnspan=cols, pady=10)


def _hablar_respuesta(text: str):
    """Habla la respuesta en voz alta, filtrando errores técnicos y textos largos."""
    if not text or len(text.strip()) < 3:
        return
    # No hablar volcados de error API
    if any(x in text for x in ("Error code:", "request_id", "credit balance",
                                "AuthenticationError", "traceback", "Traceback")):
        speak("Lo siento, la API no está disponible ahora.")
        return
    # No hablar mensajes de error — Jarvis ya los anunció desde el catch block
    if "[ERROR" in text:
        return
    # Limpiar caracteres especiales y truncar a ~380 chars para voz fluida
    voz = text.replace("\n", " ").replace("═", "").replace("─", "").strip()
    voz = " ".join(voz.split())   # colapsar espacios múltiples
    speak(voz[:380])


# ──────────────────────────────────────────────────────────────────────────────
#  GUI PRINCIPAL — MODO DIOS
# ──────────────────────────────────────────────────────────────────────────────
class JarvisGUI:
    # ── Paleta ────────────────────────────────────────────────────────────────
    BG       = "#050505"
    BG2      = "#0a0a0a"
    BG3      = "#0d0d0d"
    CYAN     = "#00ffcc"
    CYAN_DIM = "#005c55"
    BLUE     = "#00aaff"
    GREEN    = "#00ff41"
    RED      = "#ff5555"
    AMBER    = "#ffaa00"
    GRAY     = "#444444"

    def __init__(self, root):
        self.root = root
        self.root.title("JARVIS MENTE MAESTRA v4.0 — A2K DIGITAL STUDIO")
        self.root.geometry("1120x800")
        self.root.configure(bg=self.BG)
        self.root.resizable(True, True)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        self.parser       = ComandoParser(self)
        self._animating   = True
        self._voz_activa  = True
        self._mic_activo  = False
        self._pendiente_confirmacion   = None   # comando de diagnóstico esperando "sí"
        self._en_reposo               = False   # True = mic activo pero silenciado
        self._modo_libre              = True    # True = sin wake word (más cómodo para uso personal)
        self._streaming_header_logged = False   # reset antes de cada respuesta en streaming

        # ── métricas ──────────────────────────────────────────────────────────
        self.cnt_diagnosticos = 0
        self.cnt_pagos        = 0
        self.vol_pagos        = 0.0
        self.start_time       = time.time()

        self.var_diag    = tk.StringVar(value="0")
        self.var_pagos   = tk.StringVar(value="0  |  Bs 0.00")
        self.var_voz     = tk.StringVar(value="ACTIVO")
        self.var_uptime  = tk.StringVar(value="00:00:00")
        self.var_tracker = tk.StringVar(
            value="  PAGO MOVIL: 0 pagos  |  Bs 0.00  |  Esperando alertas SMS...")

        self._construir_ui()
        self._iniciar_uptime()
        self.root.after(120, self._animate_holo)
        # Capturar excepciones de todos los callbacks de Tkinter y mostrarlas en consola
        self.root.report_callback_exception = self._tk_error_handler

    def _tk_error_handler(self, exc, val, tb):
        import traceback
        detalle = ''.join(traceback.format_exception(exc, val, tb))
        try:
            self.log(f"[ERROR] {type(val).__name__}: {val}\n{detalle[:400]}", "err")
        except Exception:
            import sys
            print(f"[JARVIS ERROR] {val}", file=sys.stderr)

    # ── CONSTRUCCIÓN PRINCIPAL ────────────────────────────────────────────────
    def _construir_ui(self):
        self._hacer_header()
        self._hacer_metricas()

        cuerpo = tk.Frame(self.root, bg=self.BG)
        cuerpo.pack(fill="both", expand=True, padx=10, pady=(0, 2))

        # Columna izquierda
        col_izq = tk.Frame(cuerpo, bg=self.BG2, width=224)
        col_izq.pack(side="left", fill="y", padx=(0, 6))
        col_izq.pack_propagate(False)
        self._hacer_panel_izq(col_izq)

        # Columna derecha
        col_der = tk.Frame(cuerpo, bg=self.BG)
        col_der.pack(side="left", fill="both", expand=True)

        self._hacer_barra_acciones(col_der)

        self.btn_bar = tk.Frame(col_der, bg=self.BG)
        self.btn_bar.pack(fill="x", pady=(0, 3))

        self._hacer_consola(col_der)
        self._hacer_entrada(col_der)

        self._hacer_tracker()
        self._panel_sistema()

    # ── HEADER ────────────────────────────────────────────────────────────────
    def _hacer_header(self):
        hdr = tk.Frame(self.root, bg=self.BG, height=52)
        hdr.pack(fill="x", padx=10, pady=(8, 0))
        hdr.pack_propagate(False)

        izq = tk.Frame(hdr, bg=self.BG)
        izq.pack(side="left", fill="y")
        tk.Label(izq, text="◈ JARVIS", font=("Courier New", 21, "bold"),
                 fg=self.CYAN, bg=self.BG).pack(side="left", padx=(0, 8))
        tk.Label(izq, text="MENTE MAESTRA  v4.0", font=("Courier New", 11),
                 fg=self.CYAN_DIM, bg=self.BG).pack(side="left")

        der = tk.Frame(hdr, bg=self.BG)
        der.pack(side="right", fill="y")
        tk.Label(der, text="A2K DIGITAL STUDIO", font=("Courier New", 8),
                 fg="#2a2a2a", bg=self.BG).pack(side="right", padx=(10, 0))
        self.lbl_sms = tk.Label(der, text="● SMS: INICIANDO",
                                 font=("Arial", 8), fg=self.GRAY, bg=self.BG)
        self.lbl_sms.pack(side="right", padx=8)
        self.lbl_zync = tk.Label(der, text="● ZYNC PAY: VERIFICANDO",
                                  font=("Arial", 8), fg=self.GRAY, bg=self.BG)
        self.lbl_zync.pack(side="right", padx=8)

        tk.Frame(self.root, bg=self.CYAN_DIM, height=1).pack(fill="x", padx=10, pady=(2, 0))

    # ── MÉTRICAS ──────────────────────────────────────────────────────────────
    def _hacer_metricas(self):
        bar = tk.Frame(self.root, bg=self.BG3, height=62)
        bar.pack(fill="x", padx=10, pady=(3, 4))
        bar.pack_propagate(False)

        datos = [
            ("DIAGNÓSTICOS IA", self.var_diag,   self.CYAN),
            ("PAGOS RECIBIDOS", self.var_pagos,  self.GREEN),
            ("MOTOR DE VOZ",    self.var_voz,    self.BLUE),
            ("UPTIME SISTEMA",  self.var_uptime, self.AMBER),
        ]
        for i, (lbl, var, color) in enumerate(datos):
            if i > 0:
                tk.Frame(bar, bg="#1c1c1c", width=1).pack(side="left", fill="y", pady=8)
            f = tk.Frame(bar, bg=self.BG3)
            f.pack(side="left", expand=True, fill="both")
            tk.Label(f, text=lbl, font=("Courier New", 7, "bold"),
                     fg=self.GRAY, bg=self.BG3).pack(pady=(7, 0))
            tk.Label(f, textvariable=var, font=("Consolas", 11, "bold"),
                     fg=color, bg=self.BG3).pack()

    # ── PANEL IZQUIERDO ───────────────────────────────────────────────────────
    def _hacer_panel_izq(self, parent):
        # Holographic canvas
        holo_wrap = tk.Frame(parent, bg="#000000")
        holo_wrap.pack(fill="x")
        self.holo_canvas = tk.Canvas(holo_wrap, width=224, height=165,
                                      bg="#000000", highlightthickness=0)
        self.holo_canvas.pack()

        tk.Frame(parent, bg=self.CYAN_DIM, height=1).pack(fill="x", pady=(0, 3))

        tk.Label(parent, text="M Ó D U L O S", font=("Courier New", 7, "bold"),
                 fg=self.GRAY, bg=self.BG2).pack(pady=(0, 2))

        mods = [
            ("⚙  SISTEMA",        "#003344", self._panel_sistema),
            ("$  FINANZAS P2P",   "#002a1a", self._panel_finanzas),
            ("✈  IMPORTACIONES", "#2a1800", self._panel_importaciones),
            ("⚡ TÉCNICO IA",    "#1a0028", self._panel_tecnico),
        ]
        for txt, bg, cmd in mods:
            tk.Button(parent, text=txt, command=self._safe_cmd(cmd), anchor="w",
                      bg=bg, fg=self.CYAN, font=("Consolas", 9, "bold"),
                      relief="flat", cursor="hand2", padx=8, pady=4,
                      activebackground="#004466").pack(fill="x", pady=2, padx=5)

        tk.Frame(parent, bg="#1c1c1c", height=1).pack(fill="x", padx=5, pady=5)
        tk.Label(parent, text="A C C E S O S   R Á P I D O S", font=("Courier New", 6),
                 fg=self.GRAY, bg=self.BG2).pack(pady=(0, 2))

        rapidos = [
            ("▸ Binance P2P",  lambda: self._mostrar_resultado(self.parser.procesar("binance p2p"))),
            ("▸ El Dorado",    lambda: self._mostrar_resultado(self.parser.procesar("el dorado"))),
            ("▸ 1688.com",     lambda: self._mostrar_resultado(self.parser.procesar("1688"))),
            ("▸ VS Code",      lambda: self.log(sistema.abrir_vscode())),
            ("▸ Verificar ✓",  lambda: self._mostrar_resultado(("__cian__", jarvis_chat.verificar_sintaxis()))),
            ("▸ Limpiar chat", lambda: self.log(self.parser.limpiar_historial(), "info")),
        ]
        for txt, cmd in rapidos:
            tk.Button(parent, text=txt, command=cmd, anchor="w",
                      bg=self.BG2, fg="#666666", font=("Consolas", 8),
                      relief="flat", cursor="hand2", padx=8, pady=2,
                      activebackground="#1a1a1a").pack(fill="x", pady=1, padx=5)

    # ── BARRA DE ACCIONES PERMANENTES ────────────────────────────────────────
    def _hacer_barra_acciones(self, parent):
        bar = tk.Frame(parent, bg=self.BG, height=34)
        bar.pack(fill="x", pady=(0, 2))
        bar.pack_propagate(False)

        acciones = [
            ("▶ PROBAR VOZ", "#003344",
             lambda: (speak("Centro de mando activo. Jarvis en línea."),
                      self.log("Prueba de voz ejecutada.", "info"))),
            ("VOZ: ON/OFF", "#002233", self._toggle_voz),
            ("SIMULAR SMS",  "#002a00", self._simular_sms),
            ("MODO NOCHE",   "#1a1a1a", self._modo_noche),
            ("LIMPIAR LOG",  "#1a0000", self._limpiar_log),
        ]
        for txt, bg, cmd in acciones:
            tk.Button(bar, text=txt, command=cmd,
                      bg=bg, fg=self.CYAN, font=("Consolas", 8, "bold"),
                      relief="flat", cursor="hand2", padx=10, pady=4,
                      activebackground="#004466").pack(side="left", padx=2)

        self.btn_mic = tk.Button(bar, text="🎤 MIC: OFF",
                                  command=self._toggle_mic,
                                  bg="#1a0800", fg="#ff6633",
                                  font=("Consolas", 8, "bold"),
                                  relief="flat", cursor="hand2", padx=10, pady=4,
                                  activebackground="#004466")
        self.btn_mic.pack(side="left", padx=2)

        self.btn_libre = tk.Button(bar, text="🎙 LIBRE: ON",
                                    command=self._toggle_modo_libre,
                                    bg="#003a10", fg="#00ff41",
                                    font=("Consolas", 8, "bold"),
                                    relief="flat", cursor="hand2", padx=10, pady=4,
                                    activebackground="#005520")
        self.btn_libre.pack(side="left", padx=2)

        tk.Button(bar, text="🌙 REPOSO",
                  command=self._activar_reposo,
                  bg="#1a1a00", fg="#ffaa00",
                  font=("Consolas", 8, "bold"),
                  relief="flat", cursor="hand2", padx=10, pady=4,
                  activebackground="#333300").pack(side="left", padx=2)

    # ── CONSOLA ───────────────────────────────────────────────────────────────
    def _hacer_consola(self, parent):
        wrap = tk.Frame(parent, bg="#000000",
                        highlightbackground=self.CYAN_DIM, highlightthickness=1)
        wrap.pack(fill="both", expand=True, pady=(0, 3))

        self.console = tk.Text(
            wrap, bg="#000000", fg=self.GREEN,
            font=("Consolas", 9), bd=0, padx=10, pady=8,
            wrap="word", state="disabled", cursor="arrow",
        )
        self.console.pack(side="left", fill="both", expand=True)

        self.console.tag_configure("ts",   foreground="#2e2e2e")
        self.console.tag_configure("cmd",  foreground="#ffcc00")
        self.console.tag_configure("ok",   foreground="#00ff41")
        self.console.tag_configure("info", foreground="#00aaff")
        self.console.tag_configure("hdr",  foreground="#00ffcc")
        self.console.tag_configure("err",  foreground="#ff5555")
        self.console.tag_configure("cian", foreground="#00ffcc")
        self.console.tag_configure("sms",  foreground="#ffaa00")

        sb = tk.Scrollbar(wrap, command=self.console.yview,
                          bg="#111", troughcolor="#000",
                          activebackground=self.CYAN_DIM)
        sb.pack(side="right", fill="y")
        self.console.configure(yscrollcommand=sb.set)

    # ── ENTRADA ───────────────────────────────────────────────────────────────
    def _hacer_entrada(self, parent):
        frame = tk.Frame(parent, bg=self.BG)
        frame.pack(fill="x", pady=(0, 2))

        tk.Label(frame, text="►", font=("Consolas", 13, "bold"),
                 fg=self.CYAN, bg=self.BG).pack(side="left", padx=(0, 5))

        self.entry = tk.Entry(
            frame, bg="#0a0a0a", fg="white", insertbackground=self.CYAN,
            font=("Consolas", 10), relief="flat", bd=0,
            highlightbackground=self.CYAN_DIM, highlightthickness=1,
            highlightcolor=self.CYAN,
        )
        self.entry.pack(side="left", fill="x", expand=True, ipady=5)
        self.entry.bind("<Return>", self._ejecutar)
        self.entry.focus_set()

        tk.Button(frame, text=" EJECUTAR ", command=lambda: self._ejecutar(None),
                  bg="#004d40", fg="white", font=("Consolas", 9, "bold"),
                  relief="flat", cursor="hand2", padx=12, pady=5,
                  activebackground="#006655").pack(side="right", padx=(5, 0))

    # ── TRACKER INFERIOR ──────────────────────────────────────────────────────
    def _hacer_tracker(self):
        frame = tk.Frame(self.root, bg="#0a0a0a", height=28)
        frame.pack(fill="x", padx=10, pady=(0, 6))
        frame.pack_propagate(False)

        self.lbl_pulse = tk.Label(frame, text="●", font=("Arial", 10),
                                   fg="#004d40", bg="#0a0a0a")
        self.lbl_pulse.pack(side="right", padx=10)

        tk.Label(frame, textvariable=self.var_tracker,
                 font=("Consolas", 8), fg=self.AMBER, bg="#0a0a0a",
                 anchor="w").pack(side="left", padx=10, fill="y")

        self._pulsar_indicador()

    # ── ANIMACIÓN HOLOGRÁFICA ─────────────────────────────────────────────────
    def _draw_arc(self, c, cx, cy, r, start, extent, color, tag, width=2):
        c.create_arc(cx-r, cy-r, cx+r, cy+r,
                     start=start, extent=extent,
                     style="arc", outline=color, width=width, tags=tag)

    def _animate_holo(self):
        if not self._animating:
            return
        c       = self.holo_canvas
        t       = time.time()
        W, H    = 224, 165
        cx, cy  = W // 2, H // 2
        pulse   = (math.sin(t * 1.8) + 1) / 2

        c.delete("anim")

        # Fondo concéntrico sutil
        for r, col in [(82, "#040c0a"), (64, "#051210"), (46, "#061814")]:
            c.create_oval(cx-r, cy-r, cx+r, cy+r, fill=col, outline="", tags="anim")

        # Anillo externo — lento
        a1 = (t * 22) % 360
        self._draw_arc(c, cx, cy, 80, a1,       210, "#004433", "anim", 2)
        self._draw_arc(c, cx, cy, 80, a1 + 215,  55, "#00ffcc", "anim", 2)
        self._draw_arc(c, cx, cy, 80, a1 + 276,  28, "#007766", "anim", 3)

        # Anillo medio — inverso
        a2 = -(t * 52) % 360
        self._draw_arc(c, cx, cy, 62, a2,       170, "#003322", "anim", 2)
        self._draw_arc(c, cx, cy, 62, a2 + 175,  65, "#00aaff", "anim", 2)
        self._draw_arc(c, cx, cy, 62, a2 + 248,  44, "#004455", "anim", 3)

        # Anillo interno — rápido
        a3 = (t * 108) % 360
        self._draw_arc(c, cx, cy, 42, a3,       130, "#001a2a", "anim", 2)
        self._draw_arc(c, cx, cy, 42, a3 + 135,  75, "#00ccaa", "anim", 2)

        # Dots rotantes en anillo externo
        for i in range(12):
            ang   = math.radians(a1 + i * 30)
            dx    = math.cos(ang) * 80
            dy    = math.sin(ang) * 80
            r_dot = int(2 + pulse * 2) if i % 3 == 0 else 1
            col   = "#00ffcc" if i % 3 == 0 else "#003322"
            c.create_oval(cx+dx-r_dot, cy+dy-r_dot,
                          cx+dx+r_dot, cy+dy+r_dot,
                          fill=col, outline="", tags="anim")

        # Núcleo
        nr = int(17 + pulse * 4)
        c.create_oval(cx-nr, cy-nr, cx+nr, cy+nr,
                      fill="#000000", outline="#00ffcc", width=1, tags="anim")
        c.create_oval(cx-9, cy-9, cx+9, cy+9,
                      fill="#001a10", outline="#005533", width=1, tags="anim")

        # Cruz de referencia
        c.create_line(cx-7, cy, cx+7, cy, fill="#003322", tags="anim")
        c.create_line(cx, cy-7, cx, cy+7, fill="#003322", tags="anim")

        # Texto JARVIS
        c.create_text(cx, cy, text="JARVIS",
                      font=("Courier New", 10, "bold"), fill="#00ffcc", tags="anim")

        # Etiqueta inferior
        c.create_text(cx, H - 10, text="NÚCLEO HOLOGRÁFICO",
                      font=("Courier New", 6), fill="#1e1e1e", tags="anim")

        self.root.after(50, self._animate_holo)

    # ── UPTIME TICKER ─────────────────────────────────────────────────────────
    def _iniciar_uptime(self):
        def _tick():
            elapsed = int(time.time() - self.start_time)
            h = elapsed // 3600
            m = (elapsed % 3600) // 60
            s = elapsed % 60
            self.var_uptime.set(f"{h:02d}:{m:02d}:{s:02d}")
            self.root.after(1000, _tick)
        _tick()

    # ── PULSO DEL INDICADOR ───────────────────────────────────────────────────
    def _pulsar_indicador(self):
        cols = [self.CYAN, "#007766", "#004433", "#007766"]
        idx  = int(time.time() * 2) % len(cols)
        try:
            self.lbl_pulse.config(fg=cols[idx])
        except Exception:
            return
        self.root.after(500, self._pulsar_indicador)

    # ── ACCIONES PERMANENTES ──────────────────────────────────────────────────
    def _toggle_mic(self):
        self._mic_activo = not self._mic_activo
        if self._mic_activo:
            self.btn_mic.config(text="🎤 MIC: ON", bg="#003a10", fg="#00ff41")
            self.log("Micrófono activado — grabación dinámica (se corta sola al detectar silencio).", "info")
            speak("Micrófono activado. Te escucho.")
            threading.Thread(target=self._escuchar_continuo, daemon=True).start()
        else:
            self.btn_mic.config(text="🎤 MIC: OFF", bg="#1a0800", fg="#ff6633")
            self.log("Micrófono desactivado.", "info")

    def _escuchar_continuo(self):
        """Escucha continua con wake word 'Jarvis', filtro de ruido y confirmación de diagnóstico."""
        try:
            import speech_recognition as sr
            import sounddevice as sd
            import numpy as np
            import io, wave, queue
        except ImportError as e:
            self.root.after(0, lambda err=str(e): self.log(
                f"Dependencia faltante: {err} — ejecuta: pip install SpeechRecognition sounddevice numpy", "err"))
            self._mic_activo = False
            self.root.after(0, lambda: self.btn_mic.config(
                text="🎤 MIC: OFF", bg="#1a0800", fg="#ff6633"))
            return

        rec = sr.Recognizer()
        rec.energy_threshold         = 3000   # filtra ruido de fondo
        rec.dynamic_energy_threshold = True   # se ajusta al entorno real
        RATE     = 16000
        CHANNELS = 1
        RMS_MIN  = 70    # umbral de energía RMS — ignora silencio y ruido bajo

        # Grabación dinámica (reemplaza la duración fija de 5s de antes, que
        # cortaba preguntas largas a la mitad y producía texto basura):
        CHUNK_SEG     = 0.25   # tamaño de cada pedazo que se analiza
        ESPERA_INICIO = 6.0    # cuánto espera a que la persona empiece a hablar
        SILENCIO_FIN  = 1.1    # silencio después de hablar = ya terminó la frase
        MAX_DURACION  = 25.0   # tope de seguridad por si nunca hay silencio

        # "jarvis" + variantes que Google SR en español produce al escuchar "Jarvis"
        _WAKE = {"jarvis", "harry", "harvis", "davis", "travis", "javi",
                 "jarvis,", "harry,", "javi,"}
        _DIAG_KW = (
            "diagnostico", "diagnóstico", "error ", "lavadora",
            "nevera", "aire acondicionado", "ac split", "reparar",
            "microondas", "secadora", "air fryer",
        )
        _VISION_KW = (
            "analiza lo que veo", "que ves", "qué ves", "ver tecnico", "ver técnico",
            "analiza imagen", "foto tecnico", "foto técnico",
            "ver grafica", "analiza la grafica", "ver inventario",
            "ver general", "ver cara", "ver mano", "ver objeto",
            "que tengo en", "qué tengo en", "describe lo que ves",
            "analiza lo que tengo", "que hay en mi", "qué hay en mi",
            # variantes de voz con palabras intermedias
            "que tengo puesta", "qué tengo puesta",
            "que tengo puesto", "qué tengo puesto",
            "en la cara", "en la mano", "en mis manos",
            "en mis ojos", "en mi cabeza", "en mi cuello",
            "en mi muñeca", "en mis dedos", "en mi mano",
        )
        _TRADING_KW = (
            "el mercado", "los mercados", "revisar el mercado", "revisar el grafico",
            "revisar el gráfico", "el grafico", "el gráfico", "ver el grafico", "ver el gráfico",
            "como ves el grafico", "cómo ves el gráfico", "como ves el formato",
            "binarias", "que esta pasando en el mercado", "qué está pasando en el mercado",
            "hay alguna señal", "hay alguna senal", "alguna señal", "alguna senal",
            "como esta el mercado", "cómo está el mercado",
            "es de compra o de venta", "compra o venta", "el rsi", "que dice el rsi", "qué dice el rsi",
            "la vela", "las velas", "vela actual", "patron de vela", "patrón de vela",
            "estrella de la manana", "estrella de la mañana", "estrella en la manana", "estrella en la mañana",
            "me recomienda", "recomiendas", "recomendacion", "recomendación",
            "la tomo", "la autorizo", "autorizo la senal", "autorizo la señal",
            "debo operar", "debo entrar", "opero o no", "entro o no",
            "la apruebo", "tomo la señal", "tomo la senal",
        )

        modo_txt = "sin wake word" if self._modo_libre else "di 'Jarvis [comando]' para activar"

        # Micrófono abierto UNA sola vez y leído en continuo — abrir/cerrar el
        # dispositivo cada fracción de segundo (como se hacía antes) es lo que
        # causaba "[WinError 50] Solicitud no compatible" en Windows.
        _q = queue.Queue()

        def _callback(indata, frames, time_info, status):
            _q.put(indata.copy())

        try:
            stream = sd.InputStream(samplerate=RATE, channels=CHANNELS,
                                     dtype="int16", blocksize=int(CHUNK_SEG * RATE),
                                     callback=_callback)
            stream.start()
        except Exception as e:
            self.root.after(0, lambda err=str(e): self.log(
                f"Error abriendo micrófono: {err} — revisa que no esté en uso por otro programa.", "err"))
            self._mic_activo = False
            self.root.after(0, lambda: self.btn_mic.config(
                text="🎤 MIC: OFF", bg="#1a0800", fg="#ff6633"))
            return

        self.root.after(0, lambda m=modo_txt: self.log(
            f"Micrófono listo — {m}.", "info"))

        def _leer_chunk():
            """Un pedazo de audio del micrófono, o silencio si no llegó nada a tiempo."""
            try:
                return _q.get(timeout=CHUNK_SEG * 4)
            except queue.Empty:
                return np.zeros((int(CHUNK_SEG * RATE), CHANNELS), dtype="int16")

        _ciclo = 0
        while self._mic_activo:
            try:
                _ciclo += 1
                if _ciclo % 5 == 1:   # "Escuchando..." solo 1 de cada 5 ciclos (~25 seg)
                    self.root.after(0, lambda: self.log("Escuchando...", "info"))

                # Esperar a que Jarvis termine de hablar antes de grabar (evita capturar eco TTS)
                while _voz._JARVIS_HABLANDO.is_set() and self._mic_activo:
                    time.sleep(0.1)
                if not self._mic_activo:
                    break

                # Vacía lo que se haya acumulado en la cola mientras esperaba
                # o mientras Jarvis hablaba — para no procesar audio viejo.
                while not _q.empty():
                    try:
                        _q.get_nowait()
                    except queue.Empty:
                        break

                chunks            = []
                hablando          = False
                silencio_acum     = 0.0
                tiempo_total      = 0.0
                tiempo_sin_hablar = 0.0

                while self._mic_activo:
                    if _voz.esta_hablando():
                        break   # Jarvis empezó a hablar — descarta esta captura

                    chunk = _leer_chunk()
                    chunk_rms = float(np.sqrt(np.mean(chunk.astype(np.float32) ** 2)))
                    tiempo_total += CHUNK_SEG

                    if chunk_rms >= RMS_MIN:
                        hablando = True
                        silencio_acum = 0.0
                        tiempo_sin_hablar = 0.0
                        chunks.append(chunk)
                    elif hablando:
                        silencio_acum += CHUNK_SEG
                        chunks.append(chunk)   # incluye pausas cortas entre palabras
                        if silencio_acum >= SILENCIO_FIN:
                            break
                    else:
                        tiempo_sin_hablar += CHUNK_SEG
                        if tiempo_sin_hablar >= ESPERA_INICIO:
                            break   # nunca empezó a hablar — silencio o ruido bajo

                    if tiempo_total >= MAX_DURACION:
                        break

                if not self._mic_activo:
                    break

                # Descartar: nunca habló, o Jarvis empezó a hablar (evita eco TTS)
                if not hablando or _voz.esta_hablando():
                    continue

                raw = np.concatenate(chunks, axis=0)

                buf = io.BytesIO()
                with wave.open(buf, "wb") as wf:
                    wf.setnchannels(CHANNELS)
                    wf.setsampwidth(2)
                    wf.setframerate(RATE)
                    wf.writeframes(raw.tobytes())
                buf.seek(0)

                with sr.AudioFile(buf) as src:
                    audio = rec.record(src)

                texto = rec.recognize_google(audio, language="es-US")
                cmd   = texto.strip().lower()
                if not cmd:
                    continue

                self.root.after(0, lambda t=texto: self.log(f"[MIC] Entendí: '{t}'", "info"))

                # ── MODO CONFIRMACIÓN PENDIENTE ──────────────────────────────
                if self._pendiente_confirmacion:
                    if any(x in cmd for x in ("sí", "si", "yes", "afirmativo", "dale", "procede")):
                        cmd_pendiente = self._pendiente_confirmacion
                        self._pendiente_confirmacion = None
                        self.root.after(0, lambda: self.log(
                            "[VOZ] Confirmado. Ejecutando diagnóstico.", "info"))
                        speak("Confirmado. Iniciando diagnóstico.")
                        def _run_confirmed(c=cmd_pendiente):
                            res = self.parser.procesar(c)
                            self.root.after(0, lambda r=res: self._mostrar_resultado(r))
                        threading.Thread(target=_run_confirmed, daemon=True).start()
                    else:
                        self._pendiente_confirmacion = None
                        self.root.after(0, lambda: self.log(
                            "[VOZ] Diagnóstico cancelado.", "info"))
                        speak("Diagnóstico cancelado.")
                    continue

                # ── WAKE WORD / MODO LIBRE ────────────────────────────────────
                palabras = cmd.split()
                if self._modo_libre:
                    # Sin wake word — procesa todo directamente
                    cmd_limpio = cmd
                else:
                    # Busca "Jarvis" (o variante) en las 3 primeras palabras
                    wake_idx = -1
                    for i, p in enumerate(palabras[:3]):
                        if p.strip(",.!?¿¡;:\"'") in _WAKE:
                            wake_idx = i
                            break
                    if wake_idx == -1:
                        self.root.after(0, lambda t=texto: self.log(
                            f"[MIC] Sin wake word (escuché: '{t}') — activa LIBRE o di 'Jarvis'", "info"))
                        continue
                    cmd_limpio = " ".join(palabras[wake_idx + 1:]).strip()

                # ── MODO REPOSO — solo escucha palabras de despertar ──────────
                if self._en_reposo:
                    _DESPERTAR = ("despierta", "actívate", "activar")
                    es_despertar = (cmd_limpio.strip() == "vuelve" or
                                    any(kw in cmd_limpio for kw in _DESPERTAR))
                    if es_despertar:
                        self.root.after(0, self._desactivar_reposo)
                        speak("De vuelta al trabajo, Abigail.")
                    continue   # en reposo: ignorar todo lo demás

                self.root.after(0, lambda t=texto: self.log(f"► [VOZ] {t}", "cmd"))

                if not cmd_limpio:
                    speak("Aquí estoy. ¿En qué te ayudo?")
                    continue

                # ── VISIÓN — hilo independiente, no bloquea el loop de voz ───
                if any(x in cmd_limpio for x in _VISION_KW):
                    _kw_general = (
                        "ver general", "ver cara", "ver mano", "ver objeto",
                        "que tengo en", "qué tengo en", "describe lo que ves",
                        "analiza lo que tengo", "que hay en mi", "qué hay en mi",
                        "que ves", "qué ves",
                        "que tengo puesta", "qué tengo puesta",
                        "que tengo puesto", "qué tengo puesto",
                        "en la cara", "en la mano", "en mis manos",
                        "en mis ojos", "en mi cabeza", "en mi cuello",
                        "en mi muñeca", "en mis dedos", "en mi mano",
                    )
                    if "grafica" in cmd_limpio:
                        modo = "trading"
                    elif any(x in cmd_limpio for x in _kw_general):
                        modo = "general"
                    else:
                        modo = "tecnico"
                    threading.Thread(
                        target=lambda m=modo, t=texto: self._vision_async(m, t),
                        daemon=True).start()
                    continue

                # ── BINARIAS — estado del mercado en vivo, hilo aparte ────────
                if any(x in cmd_limpio for x in _TRADING_KW):
                    threading.Thread(
                        target=lambda c=cmd_limpio: self._trading_voz_async(c),
                        daemon=True).start()
                    continue

                # ── DIAGNÓSTICO — confirmar antes de ejecutar ─────────────────
                if any(x in cmd_limpio for x in _DIAG_KW):
                    self._pendiente_confirmacion = cmd_limpio
                    self.parser.limpiar_historial()   # limpiar contexto anterior
                    self.root.after(0, lambda c=cmd_limpio: self.log(
                        f"[VOZ] Diagnóstico pendiente: '{c}'", "info"))
                    speak("¿Quieres iniciar el diagnóstico? Responde sí o no.")
                    continue

                # ── COMANDO GENERAL ───────────────────────────────────────────
                def _proc(c=cmd_limpio):
                    # Mostrar "pensando..." si parece consulta técnica larga
                    if len(c) > 15:
                        self.root.after(0, lambda: self.log(
                            "[IA] Procesando consulta... espera la respuesta.", "info"))
                    res = self.parser.procesar(c)
                    self.root.after(0, lambda r=res: self._mostrar_resultado(r))
                threading.Thread(target=_proc, daemon=True).start()

            except sr.UnknownValueError:
                pass   # audio grabado pero no inteligible
            except sr.RequestError as e:
                self.root.after(0, lambda err=str(e): self.log(
                    f"Error Google Speech: {err}", "err"))
                self._mic_activo = False
                self.root.after(0, lambda: self.btn_mic.config(
                    text="🎤 MIC: OFF", bg="#1a0800", fg="#ff6633"))
                break
            except Exception as e:
                if self._mic_activo:
                    self.root.after(0, lambda err=str(e): self.log(
                        f"Error mic: {err}", "err"))
                self._mic_activo = False
                self.root.after(0, lambda: self.btn_mic.config(
                    text="🎤 MIC: OFF", bg="#1a0800", fg="#ff6633"))
                break

        try:
            stream.stop()
            stream.close()
        except Exception:
            pass

    def _activar_reposo(self):
        if not self._mic_activo:
            speak("El micrófono no está activo, Abigail.")
            return
        self._en_reposo = True
        self.btn_mic.config(text="🌙 MIC: REPOSO", bg="#1a1a00", fg="#ffaa00")
        self.log("Modo reposo — di 'Jarvis despierta' para continuar.", "info")
        speak("Entendido, Abigail, quedo en espera.")

    def _desactivar_reposo(self):
        self._en_reposo = False
        if self._mic_activo:
            self.btn_mic.config(text="🎤 MIC: ON", bg="#003a10", fg="#00ff41")
        self.log("Jarvis activo — escuchando.", "info")

    def _toggle_modo_libre(self):
        self._modo_libre = not self._modo_libre
        if self._modo_libre:
            self.btn_libre.config(text="🎙 LIBRE: ON", bg="#003a10", fg="#00ff41")
            self.log("Modo libre ON — habla directo sin decir 'Jarvis'", "info")
            speak("Modo libre activado. Habla directo.")
        else:
            self.btn_libre.config(text="🎙 LIBRE: OFF", bg="#1a0800", fg="#ff6633")
            self.log("Modo libre OFF — di 'Jarvis [comando]' para activar", "info")
            speak("Modo libre desactivado. Di Jarvis antes del comando.")

    def _toggle_voz(self):
        habilitada       = _voz.toggle()
        self._voz_activa = habilitada
        estado = "ACTIVO" if habilitada else "SILENCIO"
        self.var_voz.set(estado)
        self.log(f"Motor de voz ({_voz._cfg()['motor'].upper()}): {estado}", "info")

    def _simular_sms(self):
        txt = ("[PAGO MOVIL]\n  Pagador: TEST USUARIO\n"
               "  Banco  : Banesco\n  Monto  : Bs 50.00\n  Ref    : 123456789")
        self.log(txt, "sms")
        self._registrar_pago(50.0)
        speak("Alerta de prueba recibida.")

    def _modo_noche(self):
        actual = self.console.cget("bg")
        nuevo  = "#000000" if actual != "#000000" else "#030608"
        self.console.config(bg=nuevo)
        self.log("Modo pantalla ajustado.", "info")

    def _limpiar_log(self):
        self.console.config(state="normal")
        self.console.delete("1.0", tk.END)
        self.console.config(state="disabled")
        self.log("Log limpiado.", "info")

    # ── REGISTRO DE PAGOS ─────────────────────────────────────────────────────
    def _registrar_pago(self, monto: float):
        self.cnt_pagos += 1
        self.vol_pagos += monto
        self.var_pagos.set(f"{self.cnt_pagos}  |  Bs {self.vol_pagos:.2f}")
        self.var_tracker.set(
            f"  PAGO MOVIL: {self.cnt_pagos} pago{'s' if self.cnt_pagos != 1 else ''}  "
            f"|  Bs {self.vol_pagos:.2f}  |  Último: Bs {monto:.2f}"
        )

    # ── PANELES CONTEXTUALES ──────────────────────────────────────────────────
    def _safe_cmd(self, fn):
        """Envuelve cualquier función de botón en try/except para mostrar errores en consola."""
        def _wrapper():
            try:
                result = fn()
                if result is None:
                    return
                if isinstance(result, str) and result:
                    self.log(result)
                elif isinstance(result, tuple):
                    self._mostrar_resultado(result)
            except Exception as e:
                import traceback
                self.log(f"[ERROR] {type(e).__name__}: {e}", "err")
                self.log(traceback.format_exc()[:300], "err")
        return _wrapper

    def _clear_bar(self):
        for w in self.btn_bar.winfo_children():
            w.destroy()

    def _btn(self, parent, texto, color, cmd):
        tk.Button(parent, text=texto, command=cmd, bg=color, fg="white",
                  font=("Consolas", 8), relief="flat", padx=7, pady=3,
                  cursor="hand2", activebackground="#006655"
                  ).pack(side="left", padx=2)

    def _panel_sistema(self):
        self._clear_bar()
        for t, c, f in [
            ("VS Code",        "#003366", self._safe_cmd(lambda: self.log(sistema.abrir_vscode()))),
            ("PowerShell",     "#1a1a44", self._safe_cmd(lambda: self.log(sistema.abrir_terminal("powershell")))),
            ("CMD",            "#2a1800", self._safe_cmd(lambda: self.log(sistema.abrir_terminal("cmd")))),
            ("Init Workspace", "#003333", self._safe_cmd(lambda: self.log(sistema.inicializar_workspace()))),
            ("Ver Workspace",  "#1a2a1a", self._safe_cmd(lambda: self.log(sistema.listar_workspace()))),
        ]:
            self._btn(self.btn_bar, t, c, f)
        self.log("[ MÓDULO SISTEMA ] Automatización de entorno de trabajo", "info")

    def _panel_finanzas(self):
        self._clear_bar()
        for t, c, f in [
            ("Binance P2P", "#002a00", self._safe_cmd(lambda: self.log(finanzas.abrir_plataforma("binance_p2p")))),
            ("Airtm",       "#001a2a", self._safe_cmd(lambda: self.log(finanzas.abrir_plataforma("airtm")))),
            ("Bybit",       "#1a0020", self._safe_cmd(lambda: self.log(finanzas.abrir_plataforma("bybit")))),
            ("ApoloPay",    "#2a1000", self._safe_cmd(lambda: self.log(finanzas.abrir_plataforma("apolopay")))),
            ("Banesco",     "#001a00", self._safe_cmd(lambda: self.log(finanzas.abrir_plataforma("banesco")))),
            ("Mercantil",   "#001a10", self._safe_cmd(lambda: self.log(finanzas.abrir_plataforma("mercantil")))),
            ("Calc P2P",    "#004d40", self._safe_cmd(self.abrir_dialogo_arbitraje)),
            ("Mypal",       "#002040", self._safe_cmd(self.abrir_dialogo_mypal)),
        ]:
            self._btn(self.btn_bar, t, c, f)
        self.log("[ MÓDULO FINANZAS ] Plataformas P2P y calculadora de arbitraje", "info")

    def _panel_importaciones(self):
        self._clear_bar()
        for t, c, f in [
            ("1688.com",   "#2a1800", self._safe_cmd(lambda: self.log(importaciones.abrir_tienda("1688")))),
            ("Alibaba",    "#1a0a00", self._safe_cmd(lambda: self.log(importaciones.abrir_tienda("alibaba")))),
            ("AliExpress", "#1a0500", self._safe_cmd(lambda: self.log(importaciones.abrir_tienda("aliexpress")))),
            ("SGCargo",    "#001a2a", self._safe_cmd(lambda: self.log(importaciones.abrir_courier("sgcargo")))),
            ("VIajoCargo", "#00102a", self._safe_cmd(lambda: self.log(importaciones.abrir_courier("viajocargo")))),
            ("Import2Ven", "#0a002a", self._safe_cmd(lambda: self.log(importaciones.abrir_courier("import2ven")))),
            ("Mailroom",   "#0a0a20", self._safe_cmd(lambda: self.log(importaciones.abrir_courier("mailroom")))),
            ("Calc Flete", "#2a1500", self._safe_cmd(self.abrir_dialogo_importacion)),
        ]:
            self._btn(self.btn_bar, t, c, f)
        self.log("[ MÓDULO IMPORTACIONES ] Tiendas, couriers y calculadora de flete", "info")

    def _panel_tecnico(self):
        self._clear_bar()

        # Fila 1 — diagnósticos rápidos
        row1 = tk.Frame(self.btn_bar, bg=self.BG)
        row1.pack(fill="x", pady=(0, 1))

        for txt, cat, falla in [
            ("AC Split",    "ac_split",         "no enfría"),
            ("Lavadora",    "lavadora_digital",  "no centrifuga"),
            ("Nevera",      "nevera_nofrost",    "no enfría"),
            ("Microondas",  "microondas",        "no calienta"),
            ("Air Fryer",   "air_fryer",         "no enciende"),
            ("PCB",         "tarjeta_logica",    "apaga solo"),
        ]:
            tk.Button(row1, text=txt,
                      command=self._safe_cmd(lambda c=cat, f=falla: self._diag_async(c, f)),
                      bg="#1a0028", fg="white", font=("Consolas", 8),
                      relief="flat", padx=7, pady=3, cursor="hand2",
                      activebackground="#330055").pack(side="left", padx=2)

        # Fila 2 — DB técnica + Visión
        row2 = tk.Frame(self.btn_bar, bg=self.BG)
        row2.pack(fill="x")

        for txt, cmd in [
            ("R410A PSI",  self._safe_cmd(lambda: self.log(technical_db.consultar("ac_presiones", "R410A"), "cian"))),
            ("R22 PSI",    self._safe_cmd(lambda: self.log(technical_db.consultar("ac_presiones", "R22"),   "cian"))),
            ("DB Técnica", self._safe_cmd(lambda: self.log(technical_db.listar_categorias_db(),             "cian"))),
            ("Stock",      self._safe_cmd(lambda: self._mostrar_resultado(self.parser.procesar("listar inventario")))),
            ("Stock Bajo", self._safe_cmd(lambda: self._mostrar_resultado(self.parser.procesar("alertas stock")))),
        ]:
            tk.Button(row2, text=txt, command=cmd,
                      bg="#003322", fg="white", font=("Consolas", 8),
                      relief="flat", padx=7, pady=3, cursor="hand2",
                      activebackground="#004433").pack(side="left", padx=2)

        tk.Frame(row2, bg=self.BG, width=14).pack(side="left")

        for txt, color, cmd in [
            ("👁 Ver PCB",     "#1a003a", self._safe_cmd(lambda: self._vision_async("tecnico"))),
            ("📈 Ver Gráfica", "#002a1a", self._safe_cmd(lambda: self._vision_async("trading"))),
            ("📦 Ver Pieza",   "#2a1a00", self._safe_cmd(lambda: self._vision_async("inventario"))),
            ("🎥 Preview Cam", "#002233",
             self._safe_cmd(lambda: threading.Thread(target=vision_mod.preview_camara, daemon=True).start())),
        ]:
            tk.Button(row2, text=txt, command=cmd,
                      bg=color, fg="white", font=("Consolas", 8),
                      relief="flat", padx=7, pady=3, cursor="hand2",
                      activebackground="#004455").pack(side="left", padx=2)

        self.log("[ MÓDULO TÉCNICO IA ] Motor Claude + Base de datos local + Visión Multimodal", "info")

    # ── DIAGNÓSTICO ASÍNCRONO ─────────────────────────────────────────────────
    def _diag_async(self, categoria, falla):
        nombre = tecnico.CATEGORIAS.get(categoria, categoria)
        self.log(f"Diagnóstico: {nombre} — {falla}", "cmd")
        self.log("Consultando motor de diagnóstico IA...", "info")
        self.cnt_diagnosticos += 1
        self.var_diag.set(str(self.cnt_diagnosticos))
        def _run():
            res = tecnico.diagnostico_rapido(categoria, falla)
            self.root.after(0, lambda: self.log(res))
        threading.Thread(target=_run, daemon=True).start()

    # ── EJECUCIÓN DE COMANDOS ─────────────────────────────────────────────────
    def _ejecutar(self, _event):
        texto = self.entry.get().strip()
        if not texto:
            return
        self.log(f"► {texto}", "cmd")
        self.entry.delete(0, tk.END)

        necesita_ia = (
            any(x in texto.lower() for x in ("diagnostico", "diagnóstico"))
            or (len(texto) > 20 and not texto.lower().startswith("db "))
        )
        if necesita_ia:
            if any(x in texto.lower() for x in ("diagnostico", "diagnóstico")):
                self.cnt_diagnosticos += 1
                self.var_diag.set(str(self.cnt_diagnosticos))
            self.log("Procesando con motor IA...", "info")
            def _run():
                res = self.parser.procesar(texto)
                self.root.after(0, lambda r=res: self._mostrar_resultado(r))
            threading.Thread(target=_run, daemon=True).start()
        else:
            self._mostrar_resultado(self.parser.procesar(texto))

    def _mostrar_resultado(self, res):
        if isinstance(res, tuple) and res[0] == "__cian__":
            self.log(res[1], "cian")
            _hablar_respuesta(res[1])
        elif isinstance(res, tuple) and res[0] == "__accion__":
            accion = res[1]
            if accion == "dialog_arbitraje":
                self.abrir_dialogo_arbitraje()
            elif accion == "dialog_importacion":
                self.abrir_dialogo_importacion()
            elif accion == "dialog_mypal":
                self.abrir_dialogo_mypal()
        elif isinstance(res, tuple) and res[0] == "__vision__":
            _, modo, contexto = res
            self._vision_async(modo, contexto)
        elif isinstance(res, tuple) and res[0] == "__instalar_vision__":
            self._instalar_vision_async()
        elif isinstance(res, tuple) and res[0] == "__streamed__":
            # Content already in console via streaming — just speak the response
            _hablar_respuesta(res[1])
        elif isinstance(res, tuple) and res[0] == "__verificar_deps__":
            def _run_deps():
                _verificar_dependencias()
                self.root.after(0, lambda: self.log("[DEPS] Verificación completada.", "ok"))
            threading.Thread(target=_run_deps, daemon=True).start()
        else:
            text = res if isinstance(res, str) else str(res)
            self.log(text)
            _hablar_respuesta(text)

    def _vision_async(self, modo: str, contexto: str = ""):
        label = {"tecnico": "TÉCNICO", "trading": "TRADING",
                 "inventario": "INVENTARIO", "general": "GENERAL"}
        modo_label = label.get(modo, modo.upper())
        def _run():
            self.root.after(0, lambda: self.log(
                f"[VISIÓN {modo_label}] Capturando... analizando con moondream — puede tardar 1 a 4 minutos. No repitas el comando.", "info"))
            try:
                if modo == "tecnico":
                    res = vision_mod.ver_tecnico(contexto)
                elif modo == "trading":
                    res = vision_mod.ver_trading()
                elif modo == "inventario":
                    res = vision_mod.ver_inventario()
                elif modo == "general":
                    res = vision_mod.ver_general(contexto)
                else:
                    res = "Modo de visión desconocido."
            except Exception as e:
                res = f"[VISIÓN ERROR] {e}"

            es_error = res.startswith(("[VISIÓN", "[ERROR"))
            if es_error:
                self.root.after(0, lambda r=res: self.log(r, "cian"))
                speak("Error en visión, revisa la consola.")
            else:
                self.root.after(0, lambda: self.log("[VISIÓN] ✓ Análisis completado:", "info"))
                self.root.after(0, lambda r=res: self.log(r, "cian"))
                if len(res) > 30:
                    speak(res[:200])
        threading.Thread(target=_run, daemon=True).start()

    def _trading_voz_async(self, pregunta: str):
        """
        Contesta por voz preguntas sobre el mercado del bot de binarias,
        con datos reales (RSI, tendencia, patrón de vela) — no adivina nada,
        si el servicio no responde lo dice claro en vez de inventar.
        """
        def _run():
            try:
                r = requests.get("http://localhost:3099/binarias/estado", timeout=5)
                data = r.json()
            except Exception:
                msg = "No pude conectarme al bot de binarias — revisa que el servicio de WhatsApp esté corriendo."
                self.root.after(0, lambda: self.log(f"[BINARIAS VOZ] {msg}", "err"))
                speak(msg)
                return

            mercados = data.get("mercados", [])
            if not mercados:
                speak("El bot de binarias no está vigilando ningún mercado todavía.")
                return

            # ¿Pregunta por un símbolo específico? (75 / 100 / 50)
            pedido = None
            for num in ("75", "100", "50"):
                if num in pregunta:
                    pedido = num
                    break
            if pedido:
                mercados = [m for m in mercados if pedido in m["simbolo"]] or mercados

            pide_recomendacion = any(kw in pregunta for kw in _RECOMENDACION_KW)

            partes = []
            racha = data.get("perdidasSeguidas", 0)
            if data.get("pausado"):
                partes.append(
                    f"El bot está pausado ahora mismo, no va a operar. "
                    f"Lleva {racha} pérdida(s) seguida(s) — la regla del plan es parar en 3."
                )

            pendientes = [m for m in mercados if m.get("senalPendiente")]
            for m in pendientes:
                partes.append(
                    f"Ojo, hay una señal pendiente en {m['simbolo']}: {m['senalPendiente']}. "
                    f"Contéstala por WhatsApp."
                )

            # ── Recomendación basada en TU plan, no en adivinar el mercado ────
            if pide_recomendacion and not data.get("pausado"):
                if racha >= 2:
                    partes.append(
                        f"Cuidado, ya llevas {racha} pérdida(s) seguida(s) — "
                        f"estás a una de que el bot se pause solo por la regla del plan."
                    )
                if not _en_horario_plan():
                    partes.append(
                        "Estás fuera del horario que recomienda tu plan — la mejor hora es "
                        "de 6 a 10 de la mañana o de 2:30 a 4 de la tarde. Mejor espera."
                    )
                pnl_hoy, n_trades_hoy = _pnl_binarias_hoy()
                if pnl_hoy is not None and n_trades_hoy:
                    signo = "ganancia" if pnl_hoy >= 0 else "pérdida"
                    partes.append(
                        f"Hoy en Binarias llevas {n_trades_hoy} operación(es) con "
                        f"{signo} de {abs(pnl_hoy):.2f} dólares."
                    )
                if not pendientes:
                    partes.append("No tengo ninguna señal pendiente esperando confirmación ahora mismo.")
                else:
                    partes.append(
                        "Yo no te puedo decir si va a ganar o perder — eso no lo sabe nadie con certeza. "
                        "Fíjate en la confianza que te mandó el mensaje de WhatsApp: si dice alta, tu plan "
                        "dice que la tomes con más confianza; si dice media, tómala con el monto más bajo."
                    )

            for m in mercados:
                if m.get("senalPendiente"):
                    continue
                if not m.get("conectado"):
                    partes.append(f"{m['simbolo']} está desconectado ahora mismo.")
                    continue
                trozo = f"{m['simbolo']}: RSI en {m['rsi']}, tendencia {m['tendencia']}"
                if m.get("patronVela"):
                    trozo += f", con un patrón {m['patronVela']['patron']}, {m['patronVela']['descripcion']}"
                trozo += f". Necesita {m['umbralAlto']} arriba o {m['umbralBajo']} abajo para dar señal."
                partes.append(trozo)

            respuesta = " ".join(partes)
            self.root.after(0, lambda: self.log(f"[BINARIAS VOZ] {respuesta}", "cian"))
            speak(respuesta)
        threading.Thread(target=_run, daemon=True).start()

    def _instalar_vision_async(self):
        """Lanza ollama pull moondream en background y loguea el progreso."""
        self.log("[VISIÓN] Iniciando descarga de moondream (~800MB)... esto toma unos minutos.", "info")
        speak("Iniciando descarga de modelo de visión moondream.")
        def _gui_log(msg):
            self.root.after(0, lambda m=msg: self.log(m, "info"))
        vision_mod._get()._auto_pull_moondream(_gui_log=_gui_log)

    # ── DIÁLOGOS ──────────────────────────────────────────────────────────────
    def abrir_dialogo_arbitraje(self):
        d = _dialogo_base(self.root, "Calculadora P2P — Arbitraje", 400, 310)
        campos_cfg = [
            ("Inversión (monto):",        "1000"),
            ("Tasa compra (VES/USDT):",   "38.50"),
            ("Tasa venta (VES/USDT):",    "39.20"),
            ("Comisión pasarela (%):",    "0"),
            ("Comisión fija:",            "0"),
        ]
        entries = [_campo(d, i, lbl, dflt) for i, (lbl, dflt) in enumerate(campos_cfg)]
        def calcular():
            try:
                vals = [float(e.get()) for e in entries]
                res  = finanzas.calcular_arbitraje(*vals)
                self.log(finanzas.formatear_arbitraje(res), "cian")
                estado   = "RENTABLE" if res.get("ganancia_neta", 0) > 0 else "NO RENTABLE"
                ganancia = abs(res.get("ganancia_neta", 0))
                margen   = res.get("margen_pct", 0)
                speak(f"Operacion {estado}. Ganancia neta {ganancia:.0f}. Margen del {margen} por ciento.")
                d.destroy()
            except ValueError:
                messagebox.showerror("Error", "Ingresa solo números.", parent=d)
        _boton(d, len(campos_cfg), "CALCULAR", calcular)

    def abrir_dialogo_mypal(self):
        d       = _dialogo_base(self.root, "Mypal — Simulador Recarga", 360, 200)
        e_monto = _campo(d, 0, "Monto USD a cargar:", "100")
        e_com   = _campo(d, 1, "Comisión recarga (%):", "0")
        def calcular():
            try:
                res = finanzas.simular_carga_mypal(float(e_monto.get()),
                                                    comision_pct=float(e_com.get()))
                txt = (f"Mypal — Carga USDC/USDT\n"
                       f"  Objetivo:         ${res['objetivo_usd']} USD\n"
                       f"  USDC necesarios:   {res['usdc_necesario']}\n"
                       f"  Comisión:          {res['comision']}\n"
                       f"  {res['nota']}")
                self.log(txt)
                d.destroy()
            except ValueError:
                messagebox.showerror("Error", "Ingresa valores válidos.", parent=d)
        _boton(d, 2, "CALCULAR", calcular)

    def abrir_dialogo_importacion(self):
        d = _dialogo_base(self.root, "Calculadora de Importación", 400, 310)
        campos_cfg = [
            ("Precio producto (USD):",    "50"),
            ("Peso (kg):",                "1"),
            ("Tarifa courier (USD/kg):",  "8"),
            ("Aranceles (%):",            "0"),
            ("Otros gastos (USD):",       "0"),
        ]
        entries = [_campo(d, i, lbl, dflt) for i, (lbl, dflt) in enumerate(campos_cfg)]
        def calcular():
            try:
                vals = [float(e.get()) for e in entries]
                res  = importaciones.calcular_costo_importacion(*vals)
                self.log(importaciones.formatear_costo_importacion(res), "cian")
                total = res.get("total_usd", 0)
                envio = res.get("costo_envio", 0)
                speak(f"Costo de aterrizaje por unidad: {total:.2f} dolares. Envio incluido: {envio:.2f}.")
                d.destroy()
            except ValueError:
                messagebox.showerror("Error", "Ingresa solo números.", parent=d)
        _boton(d, len(campos_cfg), "CALCULAR", calcular)

    def _ejecutar_cmd_externo(self, cmd: str):
        self.log(f"► [REMOTO] {cmd}", "cmd")
        self._mostrar_resultado(self.parser.procesar(cmd))

    # ── HELPERS CONSOLA ───────────────────────────────────────────────────────
    def log(self, msg, tag="ok"):
        ts = time.strftime("%H:%M:%S")
        PREFIX = {
            "ok":   "[OK] ",
            "info": "[INF]",
            "cmd":  "[CMD]",
            "err":  "[ERR]",
            "hdr":  "[SYS]",
            "cian": "[AI] ",
            "sms":  "[SMS]",
        }
        prefix = PREFIX.get(tag, "[LOG]")
        self.console.config(state="normal")
        self.console.insert(tk.END, f"\n{ts} ", "ts")
        self.console.insert(tk.END, f"{prefix} ", tag)
        self.console.insert(tk.END, str(msg), tag)
        self.console.see(tk.END)
        self.console.config(state="disabled")

    def _append_log(self, token: str):
        """Append a streaming token to the console. First call creates the [AI] header line."""
        self.console.config(state="normal")
        if not self._streaming_header_logged:
            self._streaming_header_logged = True
            ts = time.strftime("%H:%M:%S")
            self.console.insert(tk.END, f"\n{ts} ", "ts")
            self.console.insert(tk.END, "[AI] ", "cian")
        self.console.insert(tk.END, token, "cian")
        self.console.see(tk.END)
        self.console.config(state="disabled")

    def update_zync(self, text, color):
        try:
            self.root.after(0, lambda: self.lbl_zync.config(text=text, fg=color))
        except Exception:
            pass

    def update_sms(self, text, color):
        try:
            self.root.after(0, lambda: self.lbl_sms.config(text=text, fg=color))
        except Exception:
            pass

    def _on_close(self):
        self._animating = False
        self.root.destroy()


# ──────────────────────────────────────────────────────────────────────────────
#  MONITOR ZYNC PAY
# ──────────────────────────────────────────────────────────────────────────────
def _monitor_zync(gui):
    time.sleep(5)
    while True:
        try:
            r = requests.get(URL_ZYNC_PAY, timeout=2)
            texto = "● ZYNC PAY: ONLINE" if r.status_code == 200 else "● ZYNC PAY: ONLINE ⚠"
            color = "#00ff00" if r.status_code == 200 else "yellow"
        except Exception:
            texto, color = "● ZYNC PAY: OFFLINE", "gray"
        try:
            gui.update_zync(texto, color)
        except Exception:
            break
        time.sleep(15)


# ──────────────────────────────────────────────────────────────────────────────
#  ZYNC ELECTRONICS — SERVIDOR DE VENTAS (puerto 7799)
# ──────────────────────────────────────────────────────────────────────────────
def _arrancar_servidor_zync(gui_app):
    """
    Escucha POST /venta-zync desde la app ZYNC Electronics.
    Reduce stock en inventario_zync.json y muestra la venta en el log de Jarvis.
    """
    import json as _json
    from http.server import HTTPServer, BaseHTTPRequestHandler
    from socketserver import ThreadingMixIn
    from datetime import datetime as _dt

    PORT_ZYNC = 7799
    inv_path  = _base_exe() / "inventario_zync.json"

    def _leer_inv():
        try:
            with open(inv_path, encoding="utf-8") as f:
                return _json.load(f)
        except Exception:
            return {"grupos": {}, "ventas_hoy": 0}

    def _guardar_inv(data):
        data["ultima_actualizacion"] = _dt.now().strftime("%Y-%m-%d %H:%M")
        with open(inv_path, "w", encoding="utf-8") as f:
            _json.dump(data, f, ensure_ascii=False, indent=2)

    def _grupo_por_sku(grupos: dict, sku: str) -> str | None:
        """Devuelve la clave del grupo al que pertenece un SKU."""
        for key, g in grupos.items():
            if sku in g.get("skus", []):
                return key
        return None

    class _ZyncHandler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_OPTIONS(self):
            self.send_response(200)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.end_headers()

        def do_POST(self):
            if self.path == "/venta-web":
                try:
                    length = int(self.headers.get("Content-Length", 0))
                    body   = _json.loads(self.rfile.read(length))
                    metodo = body.get("metodo_pago", "?")
                    total  = body.get("total", 0)
                    moneda = body.get("moneda", "USD")
                    items  = body.get("items", [])
                    items_txt = ", ".join(
                        f"{i.get('nombre', '?')} x{i.get('qty', 1)}" for i in items
                    ) or "productos"

                    msg = f"[WEB A2K] Pedido — {moneda} {total:.2f} ({metodo}) | {items_txt}"
                    gui_app.root.after(0, lambda m=msg: gui_app.log(m, "ok"))

                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Access-Control-Allow-Origin", "*")
                    self.end_headers()
                    self.wfile.write(_json.dumps({"ok": True}).encode())
                except Exception as _e:
                    self.send_response(500)
                    self.end_headers()
                    gui_app.root.after(0, lambda e=str(_e): gui_app.log(f"[WEB A2K] Error webhook: {e}", "err"))
                return

            if self.path != "/venta-zync":
                self.send_response(404)
                self.end_headers()
                return

            try:
                length   = int(self.headers.get("Content-Length", 0))
                body     = _json.loads(self.rfile.read(length))
                ticket   = body.get("ticket", "?")
                total    = body.get("total", 0)
                metodo   = body.get("metodo", "?")
                productos = body.get("productos", [])

                # Reducir stock por grupo
                inv     = _leer_inv()
                grupos  = inv.get("grupos", {})
                alertas = []

                for item in productos:
                    sku  = item.get("sku", "")
                    qty  = int(item.get("qty", 1))
                    nom  = item.get("nombre", sku)
                    gkey = _grupo_por_sku(grupos, sku)
                    if gkey:
                        grupos[gkey]["stock"] = max(0, grupos[gkey]["stock"] - qty)
                        stk = grupos[gkey]["stock"]
                        if stk <= 3:
                            alertas.append(f"{grupos[gkey]['label']}: {stk} und")

                inv["grupos"]     = grupos
                inv["ventas_hoy"] = inv.get("ventas_hoy", 0) + 1
                _guardar_inv(inv)

                # Resumen de la venta para el log
                items_txt = ", ".join(
                    f"{i.get('nombre', i.get('sku','?'))} x{i.get('qty',1)}"
                    for i in productos
                ) or "productos"

                msg_venta = f"[ZYNC] Venta #{ticket} — ${total:.2f} ({metodo}) | {items_txt}"
                gui_app.root.after(0, lambda m=msg_venta: gui_app.log(m, "ok"))

                # Resumen de stock actualizado
                relojes = grupos.get("relojes", {}).get("stock", "?")
                mics    = grupos.get("microfonos", {}).get("stock", "?")
                auds    = grupos.get("audifonos", {}).get("stock", "?")
                msg_stk = f"[ZYNC] Stock actual — Relojes: {relojes} | Micrófonos: {mics} | Audífonos: {auds}"
                gui_app.root.after(0, lambda m=msg_stk: gui_app.log(m, "info"))

                if alertas:
                    msg_alerta = f"[ZYNC] ⚠ Stock bajo: {' | '.join(alertas)}"
                    gui_app.root.after(0, lambda m=msg_alerta: gui_app.log(m, "warn"))

                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(_json.dumps({"ok": True}).encode())

            except Exception as _e:
                self.send_response(500)
                self.end_headers()
                gui_app.root.after(0, lambda e=str(_e): gui_app.log(f"[ZYNC] Error webhook: {e}", "err"))

    class _ZyncServer(ThreadingMixIn, HTTPServer):
        allow_reuse_address = True
        daemon_threads      = True

    try:
        srv = _ZyncServer(("127.0.0.1", PORT_ZYNC), _ZyncHandler)
        gui_app.root.after(0, lambda: gui_app.log(
            f"[ZYNC SERVER] Escuchando en puerto {PORT_ZYNC} — inventario automático activo", "ok"))
        srv.serve_forever()
    except OSError as e:
        gui_app.root.after(0, lambda: gui_app.log(
            f"[ZYNC SERVER] Puerto {PORT_ZYNC} ocupado: {e}", "warn"))
    except Exception as e:
        gui_app.root.after(0, lambda: gui_app.log(
            f"[ZYNC SERVER] Error: {e}", "err"))


# ──────────────────────────────────────────────────────────────────────────────
#  SÍNTESIS DE VOZ PARA FRONTEND — Google Cloud Neural2 → bytes WAV
# ──────────────────────────────────────────────────────────────────────────────
def _sintetizar_wav(texto: str) -> bytes | None:
    """
    Llama a Google Cloud TTS Neural2 y devuelve los bytes WAV sin reproducirlos.
    Reutiliza el token OAuth cacheado de modulos/voz.py (sin llamada extra al servidor).
    Devuelve None si no hay credenciales o la llamada falla.
    Usado por el endpoint /voz del servidor HTTP para servir audio al frontend HTML.
    """
    import base64 as _b64
    import requests as _req

    try:
        from modulos.voz import _get_token
        token = _get_token()
    except Exception as e:
        _cprint("WARN", f"TTS /voz: no se pudo obtener token OAuth — {e}")
        return None

    if not token:
        _cprint("WARN", "TTS /voz: token OAuth nulo — verifica GOOGLE_APPLICATION_CREDENTIALS")
        return None

    try:
        import config as _cfg_m
        idioma     = getattr(_cfg_m, "VOZ_IDIOMA",         "es-US")
        voz_nombre = getattr(_cfg_m, "GCLOUD_VOZ_NOMBRE",  "es-US-Neural2-B")
    except Exception:
        idioma, voz_nombre = "es-US", "es-US-Neural2-B"

    payload = {
        "input": {"text": texto[:480]},
        "voice": {"languageCode": idioma, "name": voz_nombre},
        "audioConfig": {
            "audioEncoding":   "LINEAR16",   # WAV — reproducible directamente en el navegador
            "speakingRate":    1.05,
            "pitch":           0.0,
            "sampleRateHertz": 24000,
        },
    }
    try:
        r = _req.post(
            "https://texttospeech.googleapis.com/v1/text:synthesize",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json=payload,
            timeout=8,
        )
        r.raise_for_status()
        wav_bytes = _b64.b64decode(r.json()["audioContent"])
        _cprint("INFO", f"TTS /voz: {len(wav_bytes)} bytes WAV ({voz_nombre})")
        return wav_bytes
    except Exception as e:
        _cprint("ERROR", f"TTS /voz: Google Cloud TTS falló — {e}")
        return None


# ──────────────────────────────────────────────────────────────────────────────
#  MOTOR IA — GOOGLE GEMINI via OpenRouter
# ──────────────────────────────────────────────────────────────────────────────
def _llamar_gemini(system: str, prompt: str, timeout: int = 30) -> str:
    """Envía prompt a Google Gemini 2.0 Flash via OpenRouter. Fallback a Ollama si no hay clave."""
    import json as _json, requests as _req, os as _os
    api_key = _os.environ.get("OPENROUTER_API_KEY", "")
    if not api_key:
        from modulos.tecnico import consultar_negocio
        return consultar_negocio(prompt)
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://jarvis-profe.local",
        "X-Title": "Jarvis Mente Maestra v4.0",
    }
    body = {
        "model": "google/gemini-2.0-flash-001",
        "messages": [
            {"role": "system", "content": system},
            {"role": "user",   "content": prompt},
        ],
        "max_tokens": 512,
        "temperature": 0.3,
    }
    try:
        r = _req.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers=headers, json=body, timeout=timeout,
        )
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"].strip()
    except _req.exceptions.Timeout:
        _cprint("ERROR", "Gemini: Timeout — OpenRouter no respondió en 30 s")
        return "[GEMINI] Timeout — servidor tardó demasiado. Reintenta."
    except _req.exceptions.ConnectionError:
        _cprint("WARN",  "Gemini: sin internet — modo offline activo")
        return "[GEMINI] Sin conexión a internet."
    except Exception as e:
        _cprint("ERROR", f"Gemini: {type(e).__name__}: {e}")
        return f"[GEMINI ERROR] {type(e).__name__}: {e}"


# ──────────────────────────────────────────────────────────────────────────────
#  SERVIDOR SMS
# ──────────────────────────────────────────────────────────────────────────────
def _arrancar_servidor_sms(gui_app):
    try:
        import json, re
        from http.server import HTTPServer, BaseHTTPRequestHandler
        from socketserver import ThreadingMixIn
        from urllib.parse import urlparse, parse_qs

        try:
            import config as _cfg
            HOST_SMS = getattr(_cfg, "SMS_HOST", "0.0.0.0")
            PORT_SMS = getattr(_cfg, "SMS_PORT", 5000)
        except ImportError:
            HOST_SMS, PORT_SMS = "0.0.0.0", 5000

        RUTAS_SMS = {"/ping", "/alerta", "/pago", "/arbitraje", "/comando",
"/chat", "/bodega", "/tecnico", "/voz", "/analitica", "/clientes", "/telegram", "/importaciones", "/divisas"}

        _RE_MONTO = re.compile(
            r'[Bb][Ss]\.?\s*[Ff]?\.?\s*([\d]{1,10}[,\.][\d]{2})'
            r'|[Mm]onto:?\s*[Bb][Ss]?\.?\s*([\d]{1,10}[,\.][\d]{2})',
            re.IGNORECASE
        )
        _RE_REF = re.compile(
            r'(?:[Rr]ef(?:erencia)?\.?\s*[:#N°]?\s*|[Nn][o°]\.?\s*[Rr]ef\.?\s*|#)(\d{6,})',
            re.IGNORECASE
        )

        def _parsear_sms(texto):
            monto = None
            m = _RE_MONTO.search(texto)
            if m:
                raw = m.group(1) or m.group(2)
                try:
                    monto = float(raw.replace(",", "."))
                except ValueError:
                    pass
            ref = None
            r   = _RE_REF.search(texto)
            if r:
                ref = r.group(1)
            return monto, ref

        class _Handler(BaseHTTPRequestHandler):
            def log_message(self, fmt, *args):
                gui_app.root.after(0, lambda: gui_app.log(
                    f"[SMS SERVER] {fmt % args}", "info"))

            def do_GET(self):
                ruta = urlparse(self.path).path

                # ── Interfaz web — siempre lee el disco, nunca caché ───────
                if ruta in ("/", "/index.html"):
                    self._servir_index()
                    return
                if ruta.startswith("/jarvis_frontend.js"):
                    self._servir_js()
                    return

                if ruta == "/analitica":
                    self._ok(_calcular_analitica())
                    return
                if ruta == "/clientes":
                    tasa = _leer_tasa_actual()
                    data = _leer_cuentas_cobrar()
                    resp = [{**c, "estado": _estado_cuenta_cliente(c, tasa)}
                            for c in data.get("clientes", [])]
                    self._ok({"clientes": resp, "total": len(resp),
                              "tasa": tasa, "status": "ok"})
                    return
                if ruta == "/importaciones":
                    from modulos.importaciones_suite import listar_pedidos
                    estado = parse_qs(urlparse(self.path).query).get("estado", [None])[0]
                    self._ok({"pedidos": listar_pedidos(estado), "status": "ok"})
                    return
                if ruta == "/divisas":
                    from modulos.divisas_suite import obtener_tasas, resumen_mensual
                    self._ok({"tasas": obtener_tasas(),
                              "resumen_mes": resumen_mensual(), "status": "ok"})
                    return
                if ruta in RUTAS_SMS:
                    self._ok({"status": "ok", "ruta": ruta})
                else:
                    self._ok({"error": "ruta no existe"}, 404)

            def do_OPTIONS(self):
                self.send_response(200)
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Access-Control-Allow-Methods", "POST,GET,OPTIONS")
                self.send_header("Access-Control-Allow-Headers", "Content-Type")
                self.send_header("Content-Length", "0")
                self.end_headers()

            def do_POST(self):
                largo  = int(self.headers.get("Content-Length", 0))
                cuerpo = self.rfile.read(largo).decode("utf-8") if largo else "{}"
                ct     = self.headers.get("Content-Type", "")
                if "application/json" in ct or cuerpo.strip().startswith("{"):
                    try:
                        datos = json.loads(cuerpo)
                    except Exception:
                        datos = {}
                elif cuerpo.strip():
                    p     = parse_qs(cuerpo)
                    datos = {k: v[0] if len(v) == 1 else v for k, v in p.items()}
                else:
                    datos = {}

                ruta = urlparse(self.path).path
                if ruta not in RUTAS_SMS:
                    self._ok({"error": "ruta no existe"}, 404)
                    return

                # /chat, /bodega y /tecnico necesitan respuesta síncrona (Gemini)
                if ruta in ("/chat", "/bodega", "/tecnico"):
                    self._manejar_chat(datos, ruta)
                    return

                # /voz necesita respuesta síncrona (TTS Neural2 → bytes WAV)
                if ruta == "/voz":
                    self._manejar_voz(datos)
                    return

                # /analitica — BI síncrono, GET o POST (frontend usa GET)
                if ruta == "/analitica":
                    self._ok(_calcular_analitica())
                    return

                # /clientes — CRUD de cuentas por cobrar
                if ruta == "/clientes":
                    self._manejar_clientes(datos)
                    return

                # /telegram — webhook entrante del Bot de Telegram
                if ruta == "/telegram":
                    self._manejar_telegram(datos)
                    return

                # /importaciones — CRUD de pedidos China→VE (síncrono)
                if ruta == "/importaciones":
                    self._manejar_importaciones(datos)
                    return

                # /divisas — tasas BCV/Binance P2P + ciclos arbitraje (síncrono)
                if ruta == "/divisas":
                    self._manejar_divisas(datos)
                    return


                self._ok({"recibido": True, "status": "ok"})
                threading.Thread(target=self._despachar,
                                 args=(ruta, datos), daemon=True).start()

            def _despachar(self, ruta, datos):
                if ruta == "/alerta":
                    banco   = datos.get("Banco")
                    monto_s = datos.get("Monto")
                    refe    = datos.get("refe")
                    pagador = datos.get("Pagador")
                    sender  = datos.get("sender", "?")
                    mensaje = datos.get("message", "")

                    # Modo 1: app ya extrajo campos estructurados {Banco, Monto}
                    if banco and monto_s:
                        try:
                            mv = float(str(monto_s).replace(",", "."))
                        except ValueError:
                            mv = monto_s
                        # ── Detectar moneda por banco ──────────────────────
                        moneda, simbolo = _moneda_por_banco(str(banco))
                        txt = (f"[PAGO {moneda}]\n  Pagador: {pagador or sender}"
                               f"\n  Banco  : {banco}\n  Monto  : {simbolo} {mv}"
                               f"\n  Ref    : {refe or '—'}")
                        gui_app.root.after(0, lambda t=txt: gui_app.log(t, "sms"))
                        if isinstance(mv, float):
                            gui_app.root.after(0, lambda m=mv: gui_app._registrar_pago(m))
                            _registrar_pago_consolidado(mv, moneda, str(banco), str(refe or ""))
                            # ── Disparador WA: notifica al admin de inmediato, hilo daemon ──
                            _num_admin = os.environ.get("WA_ADMIN_NUMERO", "").strip()
                            if _num_admin and _WA_CONFIG.get("enabled"):
                                _wa_pago = (
                                    f"*[JARVIS] PAGO RECIBIDO*\n"
                                    f"Banco   : *{banco}*\n"
                                    f"Monto   : *{simbolo} {mv:.2f} {moneda}*\n"
                                    f"Ref     : *{refe or '—'}*\n"
                                    f"Pagador : {pagador or sender}"
                                )
                                threading.Thread(
                                    target=_enviar_whatsapp_humano,
                                    args=(_num_admin, _wa_pago),
                                    daemon=True,
                                ).start()
                        speak(f"Pago recibido de {banco}. Monto {simbolo} {mv} en {moneda}.")

                    else:
                        # Modo 2: Push notification (MacroDroid) o SMS crudo
                        # MacroDroid envía: {title, text} / {notif_title, notif_text}
                        title = (datos.get("title") or datos.get("notif_title")
                                 or datos.get("titulo") or datos.get("app_name") or "")
                        text  = (datos.get("text")  or datos.get("notif_text")
                                 or datos.get("body") or datos.get("notif_content") or "")
                        if title or text:
                            sender  = title.lower().strip() or sender
                            mensaje = f"{title} {text}".strip() or mensaje

                        # ── Detectar moneda por título/sender ──────────────
                        moneda, simbolo = _moneda_por_banco(title or sender or "")

                        # fintech_scraper identifica banco por sender y/o contenido
                        res = _fintech.procesar_sms_pago(sender, mensaje)
                        if res:
                            # Si fintech devuelve monto con "Bs " prefijo, el simbolo
                            # viene del campo — respetar el que ya detectamos
                            monto_str = res['monto']
                            txt = (f"[PAGO {moneda}]\n  Banco  : {res['banco']}"
                                   f"\n  Monto  : {monto_str}"
                                   f"\n  Ref    : {res['referencia']}"
                                   f"\n  Pagador: {res['pagador']}")
                            gui_app.root.after(0, lambda t=txt: gui_app.log(t, "sms"))
                            try:
                                mv = float(monto_str.replace("Bs ", "").replace("$", "").replace(",", ".").strip())
                                gui_app.root.after(0, lambda m=mv: gui_app._registrar_pago(m))
                                _registrar_pago_consolidado(
                                    mv, moneda,
                                    res.get("banco", sender),
                                    res.get("referencia", ""),
                                )
                            except Exception:
                                pass
                        else:
                            # Fallback regex genérico
                            monto, ref = _parsear_sms(mensaje)
                            txt = (f"[PAGO {moneda}] De: {sender}\n  Monto: {simbolo} {monto:.2f}  Ref: {ref}"
                                   if monto else f"[ALERTA] De: {sender}\n  {mensaje[:120]}")
                            gui_app.root.after(0, lambda t=txt: gui_app.log(t, "sms"))
                            if monto:
                                gui_app.root.after(0, lambda m=monto: gui_app._registrar_pago(m))
                                _registrar_pago_consolidado(monto, moneda, sender, str(ref or ""))
                elif ruta == "/pago":
                    txt = f"[PAGO MOVIL] Bs {datos.get('monto','?')} | {datos.get('banco','?')}"
                    gui_app.root.after(0, lambda t=txt: gui_app.log(t, "sms"))
                elif ruta == "/comando":
                    cmd = datos.get("cmd", "").strip()
                    if cmd:
                        gui_app.root.after(0, lambda c=cmd: gui_app._ejecutar_cmd_externo(c))

            def _manejar_chat(self, datos, ruta="/chat"):
                """
                Responde síncronamente a /chat, /bodega y /tecnico.
                Auto-inyecta inventario_bodega.json (bodega) o calendario_tecnico.json (técnico).
                Usa Google Gemini 2.0 Flash via OpenRouter.
                """
                mensaje  = datos.get("message", datos.get("texto", datos.get("pregunta", ""))).strip()
                contexto = datos.get("context", datos.get("contexto", {}))
                tipo     = datos.get("tipo", "bodega")   # "bodega" | "tecnico_aires"
                moneda   = datos.get("moneda", "VES")    # "VES" | "USD"
                tasa     = datos.get("tasa", None)       # tasa Bs/$ (float o str)
                slots    = datos.get("slots", [])        # horarios explícitos del llamador
                numero   = datos.get("numero", datos.get("phone", "")).strip()  # WhatsApp destino

                if not mensaje:
                    self._ok({"error": "mensaje vacío", "status": "error"})
                    return

                es_tecnico = ruta == "/tecnico" or tipo == "tecnico_aires"

                # ── Contexto desde el payload del llamador ─────────────────────────
                ctx_lines = []
                if isinstance(contexto, dict) and contexto:
                    simbolo = "$" if moneda == "USD" else "Bs"
                    mapa = {
                        "productos_total": "Productos totales",
                        "sin_stock":       "Sin stock",
                        "stock_critico":   "Stock crítico (≤5)",
                        "ventas_hoy":      "Ventas hoy",
                        "ingreso_hoy":     f"Ingreso hoy ({simbolo})",
                        "deudores":        "Clientes con fiado",
                        "tasa":            "Tasa Bs/$",
                    }
                    for k, label in mapa.items():
                        if k in contexto and contexto[k] is not None:
                            ctx_lines.append(f"- {label}: {contexto[k]}")

                # ── Auto-inyectar datos locales según contexto ─────────────────────
                if not es_tecnico:
                    # BODEGA: leer inventario_bodega.json
                    inv = _leer_inventario()
                    if not tasa:
                        tasa = inv.get("tasa", _leer_tasa_actual())
                    ctx_lines.append(f"- Tasa activa: Bs {tasa}/$ (inventario local)")
                    ctx_lines.append(f"- Productos en sistema: {inv.get('productos_total', 0)}")
                    ctx_lines.append(f"- Sin stock: {inv.get('sin_stock', 0)}")
                    ctx_lines.append(f"- Stock crítico (≤5 uds): {inv.get('stock_critico', 0)}")
                    resumen = inv.get("resumen_productos", "")
                    if resumen:
                        ctx_lines.append("\nCatálogo actual:")
                        ctx_lines.append(resumen)
                else:
                    # TÉCNICO AIRES: leer calendario_tecnico.json
                    if tasa:
                        ctx_lines.append(f"- Tasa activa: Bs {tasa}/$ (BCV)")
                    slots_auto = _leer_slots_disponibles() if not slots else []
                    todos_slots = slots if slots else slots_auto
                    if todos_slots:
                        ctx_lines.append("\nHorarios disponibles para cita:")
                        ctx_lines.extend(f"  • {s}" for s in todos_slots)

                ctx_str = "\n".join(ctx_lines)

                # ── Seleccionar system prompt ──────────────────────────────────────
                system_prompt = _SYSTEM_TECNICO_AIRES if es_tecnico else _SYSTEM_BODEGA

                # ── Prompt final ───────────────────────────────────────────────────
                prompt = f"Datos actuales:\n{ctx_str}\n\nPregunta: {mensaje}" if ctx_str else mensaje

                # ── Google Gemini 2.0 Flash via OpenRouter ─────────────────────────
                try:
                    respuesta = _llamar_gemini(system_prompt, prompt)
                except Exception as e:
                    respuesta = f"Error al procesar: {e}"

                tag = "TECNICO" if es_tecnico else "BODEGA"
                gui_app.root.after(0, lambda m=mensaje: gui_app.log(
                    f"[IA {tag}] {m[:70]}", "info"))
                self._ok({"response": respuesta, "status": "ok", "moneda": moneda})

                # ── Envío a WhatsApp (solo si viene número y webhook activo) ──────
                if numero:
                    threading.Thread(
                        target=_enviar_whatsapp_humano,
                        args=(numero, respuesta),
                        daemon=True,
                    ).start()

            def _manejar_voz(self, datos):
                """
                Sintetiza el texto con Google Cloud TTS Neural2 y devuelve los bytes WAV.
                El frontend JavaScript reproduce el audio directamente en el navegador.
                Si no hay credenciales, devuelve 503 para que el JS use el fallback del navegador.
                """
                texto = datos.get("texto", datos.get("text", "")).strip()
                if not texto:
                    self._ok({"error": "texto vacío"}, 400)
                    return
                wav = _sintetizar_wav(texto)
                if not wav:
                    self._ok({"error": "TTS no disponible — verifica GOOGLE_APPLICATION_CREDENTIALS"}, 503)
                    return
                self.send_response(200)
                self.send_header("Content-Type",               "audio/wav")
                self.send_header("Content-Length",             str(len(wav)))
                self.send_header("Access-Control-Allow-Origin","*")
                self.send_header("Cache-Control",              "no-store")
                self.end_headers()
                self.wfile.write(wav)
                self.wfile.flush()

            def _manejar_clientes(self, datos):
                """
                CRUD de cuentas por cobrar — endpoint /clientes.
                Campo 'accion' (o 'tipo') controla la operación:
                  lista      → todos los clientes con estado de cuenta calculado
                  consulta   → buscar por nombre o teléfono (campo 'query')
                  registrar  → crear o actualizar cliente (campos del esquema)
                  pago       → registrar abono: reduce deuda_bs / deuda_usd
                """
                from datetime import datetime as _dtd
                accion = str(datos.get("accion", datos.get("tipo", "lista"))).lower().strip()
                tasa   = _leer_tasa_actual()

                # ── lista ──────────────────────────────────────────────────────
                if accion in ("lista", "listar", "todos", "all"):
                    data = _leer_cuentas_cobrar()
                    resp = [{**c, "estado": _estado_cuenta_cliente(c, tasa)}
                            for c in data.get("clientes", [])]
                    self._ok({"clientes": resp, "total": len(resp),
                              "tasa": tasa, "status": "ok"})

                # ── consulta ───────────────────────────────────────────────────
                elif accion in ("consulta", "buscar", "query", "balance"):
                    q = str(datos.get("query", datos.get("nombre",
                                       datos.get("telefono", "")))).strip()
                    if not q:
                        self._ok({"error": "Falta el campo 'query'", "status": "error"}, 400)
                        return
                    encontrados = _buscar_cliente(q)
                    for r in encontrados:
                        r["estado"] = _estado_cuenta_cliente(r, tasa)
                    self._ok({"clientes": encontrados, "total": len(encontrados),
                              "tasa": tasa, "status": "ok"})

                # ── registrar ──────────────────────────────────────────────────
                elif accion in ("registrar", "crear", "actualizar", "upsert"):
                    nombre   = str(datos.get("nombre", "")).strip()
                    telefono = str(datos.get("telefono_wa", datos.get("telefono", ""))).strip()
                    if not nombre:
                        self._ok({"error": "Falta el campo 'nombre'", "status": "error"}, 400)
                        return
                    data = _leer_cuentas_cobrar()
                    # Buscar existente por nombre o teléfono
                    existente = next(
                        (c for c in data["clientes"]
                         if c.get("nombre","").lower() == nombre.lower()
                         or (telefono and c.get("telefono_wa","") == telefono)),
                        None,
                    )
                    campos = ("telefono_wa", "limite_credito_usd", "deuda_bs",
                              "deuda_usd", "fecha_vencimiento", "fecha_ultimo_pago")
                    if existente:
                        for k in campos:
                            if k in datos:
                                existente[k] = datos[k]
                        msg = f"Cliente '{nombre}' actualizado."
                    else:
                        data["clientes"].append({
                            "nombre":             nombre,
                            "telefono_wa":        telefono,
                            "limite_credito_usd": float(datos.get("limite_credito_usd", 50.0)),
                            "deuda_bs":           float(datos.get("deuda_bs",  0.0)),
                            "deuda_usd":          float(datos.get("deuda_usd", 0.0)),
                            "fecha_ultimo_pago":  str(datos.get("fecha_ultimo_pago", "")),
                            "fecha_vencimiento":  str(datos.get("fecha_vencimiento", "")),
                            "historial":          [],
                        })
                        msg = f"Cliente '{nombre}' registrado."
                    _guardar_cuentas_cobrar(data)
                    _cprint("INFO", msg)
                    self._ok({"mensaje": msg, "status": "ok"})

                # ── pago ───────────────────────────────────────────────────────
                elif accion in ("pago", "abono", "cobro"):
                    q = str(datos.get("query", datos.get("nombre",
                                       datos.get("telefono", "")))).strip()
                    monto_bs  = float(datos.get("monto_bs",  0.0))
                    monto_usd = float(datos.get("monto_usd", 0.0))
                    ref       = str(datos.get("referencia", "")).strip()
                    if not q:
                        self._ok({"error": "Falta 'query' para identificar al cliente"}, 400)
                        return
                    encontrados = _buscar_cliente(q)
                    if not encontrados:
                        self._ok({"error": f"Cliente '{q}' no encontrado"}, 404)
                        return
                    data   = _leer_cuentas_cobrar()
                    nombre = encontrados[0]["nombre"]
                    cliente = next(
                        (c for c in data["clientes"]
                         if c.get("nombre","").lower() == nombre.lower()), None
                    )
                    if not cliente:
                        self._ok({"error": "Cliente no encontrado en el JSON"}, 404)
                        return
                    hoy = _dtd.now().strftime("%Y-%m-%d")
                    cliente["deuda_bs"]  = max(round(float(cliente.get("deuda_bs",  0)) - monto_bs,  2), 0.0)
                    cliente["deuda_usd"] = max(round(float(cliente.get("deuda_usd", 0)) - monto_usd, 4), 0.0)
                    cliente["fecha_ultimo_pago"] = hoy
                    cliente.setdefault("historial", []).append({
                        "fecha":      hoy,
                        "monto_bs":   monto_bs,
                        "monto_usd":  monto_usd,
                        "referencia": ref,
                    })
                    _guardar_cuentas_cobrar(data)
                    msg = (f"Pago de {nombre}: Bs {monto_bs:.2f} | $ {monto_usd:.2f}. "
                           f"Saldo: Bs {cliente['deuda_bs']:.2f} | $ {cliente['deuda_usd']:.2f}")
                    _cprint("PAGO", msg)
                    self._ok({"mensaje": msg, "cliente": cliente, "status": "ok"})

                else:
                    self._ok({
                        "error":    f"Accion '{accion}' no reconocida",
                        "acciones": ["lista", "consulta", "registrar", "pago"],
                        "status":   "error",
                    }, 400)

            # ──────────────────────────────────────────────────────────────
            #  ZYNC SUITE — IMPORTACIONES China → Venezuela
            # ──────────────────────────────────────────────────────────────
            def _manejar_importaciones(self, datos):
                """
                CRUD de pedidos de importación — endpoint /importaciones POST.
                Campo 'accion' controla la operación:
                  listar     → todos los pedidos (o filtrar por ?estado=)
                  crear      → nuevo pedido con cálculo automático de desembarque
                  actualizar → modificar pedido existente (requiere 'id')
                  calcular   → calcular costo sin guardar (preview)
                  detalle    → un pedido por 'id'
                """
                from modulos.importaciones_suite import (
                    listar_pedidos, crear_pedido, actualizar_pedido,
                    calcular_desembarque, formatear_pedido_consola,
                    resumen_listado_consola,
                )
                import os as _os
                accion  = str(datos.get("accion", datos.get("tipo", "listar"))).lower()
                margen  = float(datos.get("margen_pct",
                                          float(_os.environ.get("MARGEN_IMPORTACION_DEFAULT_PCT", "80"))))

                if accion in ("listar", "lista", "todos"):
                    estado = datos.get("estado")
                    self._ok({"pedidos": listar_pedidos(estado), "status": "ok"})

                elif accion in ("crear", "nuevo", "create"):
                    try:
                        pedido = crear_pedido(datos, margen)
                        _cprint("OK", f"[IMPORT] Pedido {pedido['id']} creado — "
                                f"unit ${pedido['resumen']['costo_unitario_desembarque']:.3f} USD")
                        gui_app.root.after(0, lambda p=pedido: gui_app.log(
                            formatear_pedido_consola(p), "ok"))
                        self._ok({"pedido": pedido, "status": "ok"})
                    except Exception as e:
                        self._ok({"error": str(e), "status": "error"}, 400)

                elif accion in ("actualizar", "update", "editar"):
                    pid = str(datos.get("id", "")).strip()
                    if not pid:
                        self._ok({"error": "Falta el campo 'id'", "status": "error"}, 400)
                        return
                    pedido = actualizar_pedido(pid, datos, margen)
                    if pedido:
                        _cprint("OK", f"[IMPORT] Pedido {pid} actualizado")
                        self._ok({"pedido": pedido, "status": "ok"})
                    else:
                        self._ok({"error": f"Pedido '{pid}' no encontrado"}, 404)

                elif accion in ("calcular", "preview", "simular"):
                    resumen = calcular_desembarque(datos, margen)
                    self._ok({"resumen": resumen, "status": "ok"})

                elif accion in ("detalle", "get", "ver"):
                    pid    = str(datos.get("id", "")).strip()
                    pedidos = listar_pedidos()
                    p = next((p for p in pedidos if p.get("id") == pid), None)
                    if p:
                        self._ok({"pedido": p, "status": "ok"})
                    else:
                        self._ok({"error": f"Pedido '{pid}' no encontrado"}, 404)

                else:
                    self._ok({
                        "error":    f"Acción '{accion}' no reconocida",
                        "acciones": ["listar", "crear", "actualizar", "calcular", "detalle"],
                        "status":   "error",
                    }, 400)

            # ──────────────────────────────────────────────────────────────
            #  ZYNC SUITE — DIVISAS P2P y ARBITRAJE
            # ──────────────────────────────────────────────────────────────
            def _manejar_divisas(self, datos):
                """
                Suite de divisas P2P — endpoint /divisas POST.
                Campo 'accion' controla la operación:
                  tasas      → consultar tasas actuales BCV + Binance
                  actualizar → actualizar tasas manualmente (bcv=X, binance=Y)
                  calcular   → calculadora de puente (sin guardar)
                  ciclo      → registrar ciclo de cajero/arbitraje
                  resumen    → resumen mensual de ganancias
                  refrescar  → forzar scraping de tasas desde fuentes externas
                """
                from modulos.divisas_suite import (
                    obtener_tasas, actualizar_tasas, calcular_puente,
                    registrar_ciclo, resumen_mensual, refrescar_tasas_auto,
                    formatear_tasas_consola, formatear_ciclo_consola,
                    formatear_resumen_mensual_consola,
                )
                accion = str(datos.get("accion", datos.get("tipo", "tasas"))).lower()

                if accion in ("tasas", "ver_tasas", "consultar"):
                    self._ok({"tasas": obtener_tasas(),
                              "resumen_mes": resumen_mensual(), "status": "ok"})

                elif accion in ("actualizar", "update", "tasa", "set_tasa"):
                    bcv     = datos.get("bcv")
                    binance = datos.get("binance")
                    if not bcv and not binance:
                        self._ok({"error": "Falta 'bcv' y/o 'binance'", "status": "error"}, 400)
                        return
                    tasas = actualizar_tasas(
                        bcv=float(bcv) if bcv else None,
                        binance=float(binance) if binance else None,
                        fuente="manual",
                    )
                    _cprint("OK", f"[DIVISAS] Tasas actualizadas: "
                            f"BCV={tasas.get('bcv_usd_bs')} | "
                            f"Binance={tasas.get('binance_p2p_usdt_bs')} | "
                            f"Spread={tasas.get('spread_pct')}%")
                    gui_app.root.after(0, lambda: gui_app.log(
                        formatear_tasas_consola(), "info"))
                    self._ok({"tasas": tasas, "status": "ok"})

                elif accion in ("calcular", "puente", "preview", "simular"):
                    monto   = float(datos.get("monto", datos.get("monto_entrada", 0)))
                    moneda  = str(datos.get("moneda", datos.get("moneda_entrada", "VES"))).upper()
                    ruta    = str(datos.get("ruta", datos.get("ruta_salida", ""))).lower()
                    tasa_ov = datos.get("tasa")
                    resultado = calcular_puente(
                        monto, moneda, ruta,
                        tasa_override=float(tasa_ov) if tasa_ov else None,
                    )
                    self._ok({**resultado, "status": "ok"})

                elif accion in ("ciclo", "registrar", "cajero", "arbitraje"):
                    try:
                        ciclo = registrar_ciclo(datos)
                        _cprint("PAGO", f"[P2P] Ciclo {ciclo['id']} — "
                                f"ganancia ${ciclo['ganancia_neta_usd']:.4f} USD")
                        gui_app.root.after(0, lambda c=ciclo: gui_app.log(
                            formatear_ciclo_consola(c), "ok"))
                        self._ok({"ciclo": ciclo, "status": "ok"})
                    except Exception as e:
                        self._ok({"error": str(e), "status": "error"}, 400)

                elif accion in ("resumen", "resumen_mes", "mes"):
                    rs = resumen_mensual()
                    gui_app.root.after(0, lambda: gui_app.log(
                        formatear_resumen_mensual_consola(), "info"))
                    self._ok({"resumen_mes": rs, "status": "ok"})

                elif accion in ("refrescar", "refresh", "auto"):
                    # Lanzar en hilo — el scraping puede tardar hasta 8 s
                    def _do_refresh():
                        res = refrescar_tasas_auto()
                        tasas = obtener_tasas()
                        gui_app.root.after(0, lambda: gui_app.log(
                            formatear_tasas_consola(), "ok"))
                        _cprint("INFO", f"[DIVISAS] Auto-refresh: "
                                f"Binance={tasas.get('binance_p2p_usdt_bs')} | "
                                f"BCV={tasas.get('bcv_usd_bs')} | "
                                f"errores={res.get('errores')}")
                    threading.Thread(target=_do_refresh, daemon=True).start()
                    self._ok({"mensaje": "Actualizando tasas en segundo plano...",
                              "status": "ok"})

                elif accion in ("guardar_manual", "manual", "set_manual"):
                    # ── Entrada manual de tasas desde el frontend web ──────
                    # Recibe { "bcv": X, "binance": Y } y guarda con fuente="manual".
                    # Cada campo es opcional: si solo llega uno, el otro se conserva.
                    bcv_raw     = datos.get("bcv")
                    binance_raw = datos.get("binance")
                    if not bcv_raw and not binance_raw:
                        self._ok({"error": "Falta 'bcv' y/o 'binance'",
                                  "status": "error"}, 400)
                        return
                    try:
                        bcv_val     = float(bcv_raw)     if bcv_raw     else None
                        binance_val = float(binance_raw) if binance_raw else None
                    except (ValueError, TypeError) as ex:
                        self._ok({"error": f"Valor inválido: {ex}",
                                  "status": "error"}, 400)
                        return
                    tasas = actualizar_tasas(
                        bcv=bcv_val, binance=binance_val, fuente="manual",
                    )
                    _cprint("OK", f"[DIVISAS] Manual guardado: "
                            f"BCV={tasas.get('bcv_usd_bs')} | "
                            f"Binance={tasas.get('binance_p2p_usdt_bs')} | "
                            f"Spread={tasas.get('spread_pct')}%")
                    gui_app.root.after(0, lambda: gui_app.log(
                        formatear_tasas_consola(), "info"))
                    self._ok({"tasas": tasas, "fuente": "manual", "status": "ok"})

                else:
                    self._ok({
                        "error":    f"Acción '{accion}' no reconocida",
                        "acciones": ["tasas", "actualizar", "calcular",
                                     "ciclo", "resumen", "refrescar",
                                     "guardar_manual"],
                        "status":   "error",
                    }, 400)


            # ──────────────────────────────────────────────────────────────
            #  SERVIR FRONTEND WEB — index.html + jarvis_frontend.js
            # ──────────────────────────────────────────────────────────────
            def _servir_index(self):
                """
                Sirve la página HTML wrapper del widget Jarvis.
                - Usa window.location.origin como host dinámico → funciona en
                  localhost Y desde cualquier celular/tablet en la LAN.
                - Cache-Control: no-store garantiza que Chrome lea siempre el
                  jarvis_frontend.js del disco sin usar la caché del navegador.
                """
                import time as _tt
                ver  = str(int(_tt.time()))   # cache-buster dinámico por request
                html = f"""<!DOCTYPE html>
 <html lang="es">
 <head>
   <meta charset="UTF-8">
   <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0">
   <title>Jarvis Mente Maestra v4.0 — A2K Digital Studio</title>
   <style>
     * {{ margin:0; padding:0; box-sizing:border-box; }}
     body {{
       background: #050505;
       display: flex;
       justify-content: center;
       align-items: center;
       min-height: 100vh;
       font-family: 'Segoe UI', system-ui, sans-serif;
     }}
     /* Estilos del carrito de compras */
     #cart-icon {{
       position: relative;
       font-size: 20px;
       cursor: pointer;
       color: var(--jv-cyan);
       margin-left: 10px;
     }}
     #cart-badge {{
       position: absolute;
       top: -8px;
       right: -8px;
       background: var(--jv-red);
       color: white;
       border-radius: 50%;
       padding: 2px 6px;
       font-size: 12px;
       min-width: 20px;
       text-align: center;
     }}
     #cart-panel {{
       position: fixed;
       top: 0;
       right: -350px;
       width: 300px;
       height: 100vh;
       background: var(--jv-bg2);
       border-left: 1px solid var(--jv-cyan-d);
       box-shadow: -2px 0 10px rgba(0,0,0,0.3);
       transition: right 0.3s ease;
       z-index: 1000;
       display: flex;
       flex-direction: column;
       overflow-y: auto;
     }}
     #cart-panel.active {{
       right: 0;
     }}
     #cart-panel-header {{
       background: var(--jv-bg);
       padding: 15px;
       border-bottom: 1px solid var(--jv-cyan-d);
       display: flex;
       justify-content: space-between;
       align-items: center;
     }}
     #cart-panel-header h3 {{
       margin: 0;
       color: var(--jv-text);
       font-size: 18px;
     }}
     #close-cart {{
       background: none;
       border: none;
       color: var(--jv-gray);
       font-size: 20px;
       cursor: pointer;
     }}
     #close-cart:hover {{
       color: var(--jv-text);
     }}
     #cart-items {{
       flex: 1;
       padding: 15px;
       overflow-y: auto;
     }}
     .cart-item {{
       display: flex;
       justify-content: space-between;
       align-items: center;
       padding: 10px;
       border-bottom: 1px solid rgba(0,255,204,0.1);
     }}
     .cart-item-info {{
       flex: 1;
     }}
     .cart-item-name {{
       font-weight: 600;
       color: var(--jv-text);
       margin-bottom: 5px;
     }}
     .cart-item-price {{
       color: var(--jv-cyan);
       font-size: 14px;
     }}
     .cart-item-quantity {{
       display: flex;
       align-items: center;
       gap: 10px;
       margin-top: 5px;
     }}
     .cart-item-quantity button {{
       background: var(--jv-bg);
       border: 1px solid var(--jv-gray);
       color: var(--jv-text);
       width: 30px;
       height: 30px;
       border-radius: 4px;
       cursor: pointer;
     }}
     .cart-item-quantity button:hover {{
       background: var(--jv-gray);
     }}
     .cart-item-quantity span {{
       min-width: 20px;
       text-align: center;
     }}
     .cart-item-remove {{
       background: none;
       border: none;
       color: var(--jv-red);
       font-size: 18px;
       cursor: pointer;
     }}
     .cart-item-remove:hover {{
       color: #ff1a1a;
     }}
     #cart-total {{
       padding: 15px;
       border-top: 2px solid var(--jv-cyan-d);
       background: var(--jv-bg);
       text-align: center;
     }}
     #cart-total-label {{
       font-size: 18px;
       font-weight: 700;
       color: var(--jv-text);
       margin-bottom: 10px;
     }}
     #cart-total-amount {{
       font-size: 24px;
       font-weight: 800;
       color: var(--jv-green);
     }}
     #checkout-btn {{
       width: 100%;
       padding: 15px;
       background: var(--jv-cyan);
       border: none;
       color: #050505;
       font-size: 16px;
       font-weight: 700;
       cursor: pointer;
       border-radius: 8px;
       transition: background 0.3s;
     }}
     #checkout-btn:hover {{
       background: #009999;
     }}
     #checkout-btn:disabled {{
       background: var(--jv-gray);
       cursor: not-allowed;
       opacity: 0.7;
     }}
     /* Estilos para el modal de pago */
     #payment-modal {{
       display: none;
       position: fixed;
       top: 0;
       left: 0;
       width: 100%;
       height: 100vh;
       background: rgba(0,0,0,0.8);
       z-index: 2000;
       justify-content: center;
       align-items: center;
     }}
     #payment-modal-content {{
       background: var(--jv-bg2);
       border-radius: 12px;
       padding: 30px;
       width: 90%;
       max-width: 400px;
       text-align: center;
       box-shadow: 0 0 30px rgba(0,255,204,0.3);
     }}
     #payment-modal-content h3 {{
       color: var(--jv-text);
       margin-bottom: 20px;
     }}
     #payment-link-display {{
       background: var(--jv-bg);
       border: 1px solid var(--jv-cyan);
       border-radius: 8px;
       padding: 15px;
       margin: 20px 0;
       word-break: break-all;
       font-family: monospace;
       font-size: 14px;
       color: var(--jv-cyan);
     }}
     #payment-instructions {{
       color: var(--jv-gray);
       font-size: 14px;
       margin-top: 20px;
       line-height: 1.5;
     }}
     #close-payment-modal {{
       background: var(--jv-red);
       color: white;
       border: none;
       padding: 12px 25px;
       font-size: 16px;
       border-radius: 6px;
       cursor: pointer;
       margin-top: 20px;
     }}
     #close-payment-modal:hover {{
       background: #ff1a1a;
     }}
     /* Estilos responsivos */
     @media (max-width: 768px) {{
       #cart-panel {{
         width: 80%;
       }}
     }}
   </style>
 </head>
 <body>
   <div id="jarvis-app"></div>
   <!-- Carrito Panel -->
   <div id="cart-panel">
     <div id="cart-panel-header">
       <h3>Carrito de Compras</h3>
       <button id="close-cart">×</button>
     </div>
     <div id="cart-items">
       <!-- Los ítems del carrito se insertarán aquí dinámicamente -->
     </div>
     <div id="cart-total">
       <div id="cart-total-label">Total a Pagar</div>
       <div id="cart-total-amount">Bs 0,00</div>
       <button id="checkout-btn" disabled>Finalizar Compra</button>
     </div>
   </div>
   <!-- Modal de Pago -->
   <div id="payment-modal">
     <div id="payment-modal-content">
       <h3>Completa tu Pago</h3>
       <p>Haz clic en el botón abaixo para proceder con el pago seguro:</p>
       <div id="payment-link-display">Cargando enlace de pago...</div>
       <div id="payment-instructions">
         1. Haz clic en el enlace de pago<br>
         2. Completa la información requerida<br>
         3. Confirma el pago<br>
         4. Recibirás confirmación automática
       </div>
       <button id="close-payment-modal">Cerrar</button>
     </div>
   </div>
   <script src="/jarvis_frontend.js?v={ver}"></script>
   <script>
     /* Inicializar con el host real del servidor — funciona en localhost
        y desde cualquier dispositivo en la red LAN sin cambiar configs */
     window.JarvisChat.init("#jarvis-app", {{
       host: window.location.origin
     }});
   </script>
 </body>
 </html>""".encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type",   "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(html)))
                self.send_header("Cache-Control",  "no-store, max-age=0")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(html)
                self.wfile.flush()

            def _servir_js(self):
                """
                Sirve jarvis_frontend.js directo del disco con Cache-Control: no-store.
                Chrome nunca reutiliza la versión en caché — cada recarga lee el
                archivo real modificado.
                """
                js_path = _base_exe() / "jarvis_frontend.js"
                if not js_path.exists():
                    self._ok({"error": "jarvis_frontend.js no encontrado en " + str(js_path)}, 404)
                    return
                body = js_path.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type",   "application/javascript; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control",  "no-store, max-age=0")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(body)
                self.wfile.flush()

            def _ok(self, data, code=200):
                body = json.dumps(data, ensure_ascii=False).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(body)
                self.wfile.flush()

            # ──────────────────────────────────────────────────────────────────
            #  DISPARADOR TELEGRAM — webhook entrante → relay cloud → respuesta
            # ──────────────────────────────────────────────────────────────────
            def _manejar_telegram(self, datos):
                """
                Recibe un update del Bot de Telegram (webhook POST /telegram).
                Responde 200 inmediatamente para evitar reintentos de Telegram,
                y despacha el relay al catálogo cloud en un hilo daemon.

                Variables .env requeridas:
                  TELEGRAM_BOT_TOKEN   — token del bot (obtenido de @BotFather)
                  CLOUD_CATALOG_URL    — URL del endpoint cloud
                                         (default: https://a2kdigitalstudio.online/api/bot)
                """
                # ── Log de depuración — confirma recepción de cualquier update ──
                _cprint("INFO", f"[TG WEBHOOK] Update recibido — keys={list(datos.keys())}")
                mensaje_tg = datos.get("message", {})
                chat_id    = str(mensaje_tg.get("chat", {}).get("id", ""))
                # ── Soporte foto + caption (para /costo con foto) ─────────────
                fotos      = mensaje_tg.get("photo", [])
                caption    = mensaje_tg.get("caption", "").strip()
                texto      = mensaje_tg.get("text", "").strip()
                # Si hay foto con caption que empieza en /costo, usamos el caption como comando
                file_id    = None
                if fotos and caption.lower().startswith("/costo"):
                    texto   = caption
                    file_id = fotos[-1].get("file_id", None)  # foto más grande = última
                # Confirmar recepción a Telegram antes de 5 s (evita reintentos)
                self._ok({"ok": True})
                if not texto or not chat_id:
                    _cprint("INFO", f"[TG WEBHOOK] Update sin texto/chat ignorado — datos={str(datos)[:120]}")
                    return
                _cprint("INFO", f"[TG MSG] chat={chat_id[:10]}  cmd/texto='{texto[:60]}'  foto={'sí' if file_id else 'no'}")
                threading.Thread(
                    target=self._relay_telegram,
                    args=(chat_id, texto, file_id),
                    daemon=True,
                ).start()

            def _relay_telegram(self, chat_id: str, texto: str, file_id: str = None):
                """
                Retransmite el mensaje al endpoint cloud de catálogos y devuelve
                la respuesta al usuario vía Telegram sendMessage.
                Anclado siempre en un hilo daemon — no bloquea el servidor HTTP.

                Comandos locales interceptados antes del relay:
                  /cobrar [monto] [concepto]  — genera solicitud de cobro (Zinli/JotForm)
                  /costo [datos]              — calculadora de importación ZYNC
                  /start /help               — menú de bienvenida
                  Métodos de Pago            — info de métodos disponibles
                """
                tg_token   = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
                # Guardavalla: si algo explota fuera de los try/except internos,
                # el hilo no muere mudo — avisa al chat
                try:
                    self._relay_telegram_inner(chat_id, texto, tg_token, file_id)
                except Exception as _e_outer:
                    _cprint("WARN", f"[TG UNCAUGHT] {type(_e_outer).__name__}: {_e_outer}")
                    if tg_token and chat_id:
                        try:
                            requests.post(
                                f"https://api.telegram.org/bot{tg_token}/sendMessage",
                                json={"chat_id": chat_id,
                                      "text": f"⚠️ Error interno de Jarvis: {type(_e_outer).__name__}: {_e_outer}"},
                                timeout=10,
                            )
                        except Exception:
                            pass

            def _relay_telegram_inner(self, chat_id: str, texto: str, tg_token: str, file_id: str = None):
                """Cuerpo real del relay — llamado desde _relay_telegram con guardavalla."""
                tg_token   = tg_token or os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
                cloud_url  = os.environ.get(
                    "CLOUD_CATALOG_URL",
                    "https://a2kdigitalstudio.online/api/bot",
                ).strip()
                respuesta  = "Servicio no disponible en este momento."
                parse_mode = None  # HTML para respuestas /cobrar y /status

                # ── Métodos de Pago — handler local (evita 404 del cloud) ───────
                _txt_lower = texto.strip().lower()
                if any(x in _txt_lower for x in ("métodos de pago", "metodos de pago",
                                                   "💳 métodos", "metodo de pago",
                                                   "formas de pago")):
                    respuesta = (
                        "💳 <b>Métodos de Pago Disponibles</b>\n\n"
                        "🔗 <b>Generar enlace de cobro con tarjeta:</b>\n"
                        "   /cobrar [monto] [concepto]\n"
                        "   <i>Ej: /cobrar 45.50 Servicio Técnico</i>\n\n"
                        "🔍 <b>Consultar estado de un pago:</b>\n"
                        "   /status [id_transaccion]\n\n"
                        "💵 <b>Efectivo</b> — Registra la venta en el POS\n"
                        "📱 <b>Pago Móvil / Zelle / Binance</b> — Confirma manualmente"
                    )
                    parse_mode = "HTML"
                    _cprint("INFO", f"[TG métodos pago] chat={chat_id[:10]}")

                # ── /start — bienvenida y menú de comandos ───────────────────────
                elif texto.strip().lower() in ("/start", "/help", "/ayuda"):
                    respuesta = (
                        "👋 <b>Hola, soy Jarvis — A2K Digital Studio</b>\n\n"
                        "📦 <b>Catálogo e Inventario:</b>\n"
                        "/catalogo — Ver todos los productos y precios\n"
                        "/precio [producto] — Buscar precio de un artículo\n"
                        "/stock — Ver disponibilidad del inventario\n"
                        "/tasa — Ver tasa del día Bs/USD\n\n"
                        "🧮 <b>Suite Financiera ZYNC:</b>\n"
                        "/costo [nombre] [costo$] [cant] [flete$] [envio_vzla$]\n"
                        "   <i>Ej: /costo RelojH55 8.50 10 25.00 40.00</i>\n"
                        "   Calcula precio de venta USD y Bs con 50% ganancia.\n\n"
                        "💳 <b>Cobros:</b>\n"
                        "/cobrar [monto] [concepto] — Generar enlace de pago\n"
                        "   <i>Ej: /cobrar 45.50 Servicio Técnico Aire</i>\n\n"
                        "💬 Cualquier otro mensaje se procesa con IA."
                    )
                    parse_mode = "HTML"
                    _cprint("INFO", f"[TG /start] chat={chat_id[:10]}")

                # ── /cobrar — solicitud de pago vía formulario JotForm ───────────
                elif texto.strip().lower().startswith("/cobrar"):
                    try:
                        partes = texto.strip().split(None, 2)
                        fecha  = _dt.now().strftime("%Y%m%d")
                        ref    = f"REF-{fecha}-{random.randint(1000, 9999)}"

                        if len(partes) < 3:
                            respuesta = (
                                "💳 <b>Solicitud de Pago — A2K Digital Studio</b>\n"
                                "──────────────────────\n"
                                "Envía este formulario al cliente:\n\n"
                                "📋 <a href='https://form.jotform.com/261694668966076'>👉 FORMULARIO DE PAGO</a>\n\n"
                                "<i>El cliente llena sus datos, tú recibes la info y "
                                "le envías el link de Zinli.</i>\n\n"
                                "💡 Tip: /cobrar 45.50 Servicio — incluye monto y concepto."
                            )
                        else:
                            try:
                                monto = float(partes[1].replace(",", "."))
                            except ValueError:
                                respuesta = (
                                    "⚠️ Monto inválido.\n"
                                    f"'{partes[1]}' no es un número válido.\n"
                                    "Ejemplo: /cobrar 45.50 Servicio Técnico"
                                )
                                raise
                            concepto  = partes[2].strip()
                            respuesta = (
                                f"💳 <b>Solicitud de Pago Generada</b>\n"
                                f"──────────────────────\n"
                                f"💰 <b>Monto:</b>    ${monto:,.2f}\n"
                                f"📋 <b>Concepto:</b> {concepto}\n"
                                f"🔖 <b>Ref:</b>      <code>{ref}</code>\n"
                                f"──────────────────────\n"
                                f"📋 <a href='https://form.jotform.com/261694668966076'>👉 FORMULARIO DE PAGO</a>\n\n"
                                f"<b>Pasos:</b>\n"
                                f"1️⃣ Envía el formulario al cliente\n"
                                f"2️⃣ Cliente llena sus datos\n"
                                f"3️⃣ Recibes su WhatsApp y monto\n"
                                f"4️⃣ Generas link Zinli y se lo envías\n"
                                f"5️⃣ Cliente paga y manda captura\n"
                                f"6️⃣ Confirmas con /confirmar {ref}"
                            )
                            _cprint("INFO", f"[TG /cobrar] ref={ref}  monto={monto}")
                        parse_mode = "HTML"

                    except ValueError:
                        pass
                    except Exception as e:
                        respuesta = f"⚠️ Error: {type(e).__name__}: {e}"
                        _cprint("WARN", f"[TG /cobrar] {type(e).__name__}: {e}")

                # ── /tasa — tasa del día ────────────────────────────────────────
                elif texto.strip().lower().startswith("/tasa"):
                    try:
                        _inv_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "inventario_bodega.json")
                        with open(_inv_path, "r", encoding="utf-8") as _f:
                            _inv = json.load(_f)
                        _tasa = _inv.get("tasa_bs_usd", "N/D")
                        respuesta = (
                            f"💱 <b>Tasa del día</b>\n"
                            f"──────────────────────\n"
                            f"1 USD = <b>{_tasa:,.2f} Bs</b>\n"
                            f"──────────────────────\n"
                            f"<i>{_inv.get('ultima_actualizacion', '')}</i>"
                        )
                        parse_mode = "HTML"
                        _cprint("INFO", f"[TG /tasa] tasa={_tasa}")
                    except Exception as _e:
                        respuesta = f"⚠️ No pude leer la tasa: {_e}"
                        _cprint("WARN", f"[TG /tasa] {_e}")

                # ── /precio — precio de un producto ─────────────────────────────
                elif texto.strip().lower().startswith("/precio"):
                    try:
                        _inv_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "inventario_bodega.json")
                        with open(_inv_path, "r", encoding="utf-8") as _f:
                            _inv = json.load(_f)
                        _partes = texto.strip().split(None, 1)
                        if len(_partes) < 2:
                            respuesta = "⚠️ Uso: /precio [nombre del producto]\nEj: /precio arroz"
                        else:
                            _busq = _partes[1].strip().lower()
                            _encontrados = [p for p in _inv.get("productos", []) if _busq in p["nombre"].lower()]
                            if not _encontrados:
                                respuesta = f"❌ No encontré «{_partes[1]}».\nPrueba /catalogo para ver todos."
                            else:
                                _lineas = [f"🔍 <b>Resultados para «{_partes[1]}»</b>\n──────────────────────"]
                                for _p in _encontrados[:5]:
                                    _stock_txt = "✅ Disponible" if _p["stock"] > 0 else "❌ Agotado"
                                    _lineas.append(
                                        f"📦 <b>{_p['nombre']}</b>\n"
                                        f"   💵 ${_p['precio_usd']:.2f}  |  Bs {_p['precio_bs']:,.2f}\n"
                                        f"   Stock: {_p['stock']}  {_stock_txt}"
                                    )
                                respuesta = "\n".join(_lineas)
                                parse_mode = "HTML"
                        _cprint("INFO", f"[TG /precio] busq='{_busq if len(_partes) > 1 else '?'}' resultados={len(_encontrados) if len(_partes) > 1 else 0}")
                    except Exception as _e:
                        respuesta = f"⚠️ Error al buscar producto: {_e}"
                        _cprint("WARN", f"[TG /precio] {_e}")

                # ── /stock — resumen de stock ────────────────────────────────────
                elif texto.strip().lower().startswith("/stock"):
                    try:
                        _inv_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "inventario_bodega.json")
                        with open(_inv_path, "r", encoding="utf-8") as _f:
                            _inv = json.load(_f)
                        _prods      = _inv.get("productos", [])
                        _disponibles = [p for p in _prods if p["stock"] > 0]
                        _agotados    = [p for p in _prods if p["stock"] == 0]
                        _lineas = [
                            f"📊 <b>Estado del Stock</b>\n──────────────────────\n"
                            f"Total: {len(_prods)}  |  ✅ {len(_disponibles)}  |  ❌ {len(_agotados)}\n"
                        ]
                        if _agotados:
                            _lineas.append("❌ <b>Agotados:</b>")
                            for _p in _agotados[:10]:
                                _lineas.append(f"  • {_p['nombre']}")
                        if _disponibles:
                            _lineas.append("\n✅ <b>Con stock:</b>")
                            for _p in sorted(_disponibles, key=lambda x: x["stock"])[:10]:
                                _lineas.append(f"  • {_p['nombre']} — {_p['stock']} unid.")
                        respuesta = "\n".join(_lineas)
                        parse_mode = "HTML"
                        _cprint("INFO", f"[TG /stock] total={len(_prods)} agotados={len(_agotados)}")
                    except Exception as _e:
                        respuesta = f"⚠️ Error al leer stock: {_e}"
                        _cprint("WARN", f"[TG /stock] {_e}")

                # ── /catalogo — listado completo con precios ─────────────────────
                elif texto.strip().lower().startswith(("/catalogo", "/catálogo")):
                    try:
                        _inv_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "inventario_bodega.json")
                        with open(_inv_path, "r", encoding="utf-8") as _f:
                            _inv = json.load(_f)
                        _prods = _inv.get("productos", [])
                        _tasa  = _inv.get("tasa_bs_usd", 1)
                        if not _prods:
                            respuesta = "📭 El catálogo está vacío.\nAgrega productos en inventario_bodega.json"
                        else:
                            _lineas = ["🛒 <b>Catálogo A2K Digital Studio</b>\n──────────────────────"]
                            for _p in _prods:
                                _ico = "✅" if _p["stock"] > 0 else "❌"
                                _lineas.append(
                                    f"{_ico} <b>{_p['nombre']}</b>\n"
                                    f"   💵 ${_p['precio_usd']:.2f}  |  Bs {_p['precio_bs']:,.2f}"
                                )
                            _lineas.append(f"\n──────────────────────\n💱 Tasa: 1 USD = {_tasa:,.2f} Bs")
                            respuesta = "\n".join(_lineas)
                            parse_mode = "HTML"
                        _cprint("INFO", f"[TG /catalogo] productos={len(_prods)}")
                    except Exception as _e:
                        respuesta = f"⚠️ Error al leer catálogo: {_e}"
                        _cprint("WARN", f"[TG /catalogo] {_e}")

                # ── /costo — calculadora de importación ZYNC ────────────────────
                elif texto.strip().lower().startswith("/costo"):
                    _INTERNET_MES  = 30.0   # USD/mes fijo
                    _ENVIO_LOCAL   = 5.0    # USD por pieza (MRW/Zoom)
                    _MARGEN        = 0.50   # 50% ganancia sobre costo
                    try:
                        _partes = texto.strip().split()
                        # /costo nombre costo_unit qty flete_china envio_vzla
                        if len(_partes) < 6:
                            respuesta = (
                                "📦 <b>Calculadora de Importación ZYNC</b>\n\n"
                                "<b>Uso:</b>\n"
                                "<code>/costo [nombre] [costo$] [cant] [flete_china$] [envio_vzla$]</code>\n\n"
                                "<b>Ejemplo:</b>\n"
                                "<code>/costo RelojH55 8.50 10 25.00 40.00</code>\n\n"
                                "📌 <i>Internet $30/mes y envío local $5/pieza se aplican automáticamente.</i>"
                            )
                            parse_mode = "HTML"
                        else:
                            _nombre     = _partes[1].replace("_", " ")
                            _costo_u    = float(_partes[2].replace(",", "."))
                            _qty        = int(_partes[3])
                            _flete_ch   = float(_partes[4].replace(",", "."))
                            _envio_vzla = float(_partes[5].replace(",", "."))

                            # ── Desglose por unidad ──────────────────────────────
                            _c_producto  = _costo_u
                            _c_flete     = _flete_ch   / _qty
                            _c_envio_vzl = _envio_vzla / _qty
                            _c_internet  = _INTERNET_MES / _qty
                            _c_local     = _ENVIO_LOCAL

                            _costo_total = _c_producto + _c_flete + _c_envio_vzl + _c_internet + _c_local
                            _ganancia    = _costo_total * _MARGEN
                            _precio_usd  = _costo_total + _ganancia

                            # ── Tasa P2P desde inventario_bodega.json ────────────
                            try:
                                _inv_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "inventario_bodega.json")
                                with open(_inv_path, "r", encoding="utf-8") as _f:
                                    _inv_b = json.load(_f)
                                _tasa_p2p = float(_inv_b.get("tasa_bs_usd", 980))
                            except Exception:
                                _tasa_p2p = 980.0

                            _precio_bs = _precio_usd * _tasa_p2p

                            respuesta = (
                                f"📦 <b>{_nombre}</b> — Lote x{_qty}\n"
                                f"──────────────────────────\n"
                                f"Costo producto:      <b>${_c_producto:.2f}</b>\n"
                                f"Flete China ÷{_qty}:  ${_c_flete:.2f}\n"
                                f"Envío Venezuela ÷{_qty}: ${_c_envio_vzl:.2f}\n"
                                f"Internet ÷{_qty}:    ${_c_internet:.2f}\n"
                                f"Envío local MRW:     ${_c_local:.2f}\n"
                                f"──────────────────────────\n"
                                f"Costo total:         <b>${_costo_total:.2f}</b>\n"
                                f"Ganancia 50%:        +${_ganancia:.2f}\n"
                                f"──────────────────────────\n"
                                f"💵 Precio USD:  <b>${_precio_usd:.2f}</b>\n"
                                f"🇻🇪 Precio P2P: <b>{_precio_bs:,.0f} Bs</b>\n"
                                f"   <i>(Tasa: {_tasa_p2p:,.0f} Bs/$)</i>"
                            )
                            parse_mode = "HTML"

                            # ── Descargar foto si viene con el mensaje ────────────
                            _foto_path = None
                            if file_id and tg_token:
                                try:
                                    _fotos_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fotos_suite")
                                    os.makedirs(_fotos_dir, exist_ok=True)
                                    _r_file = requests.get(
                                        f"https://api.telegram.org/bot{tg_token}/getFile",
                                        params={"file_id": file_id},
                                        timeout=10,
                                    )
                                    if _r_file.ok:
                                        _file_path_tg = _r_file.json()["result"]["file_path"]
                                        _r_foto = requests.get(
                                            f"https://api.telegram.org/file/bot{tg_token}/{_file_path_tg}",
                                            timeout=20,
                                        )
                                        if _r_foto.ok:
                                            _ext        = _file_path_tg.split(".")[-1] or "jpg"
                                            _safe_name  = "".join(c if c.isalnum() or c in "-_" else "_" for c in _nombre)
                                            _foto_path  = os.path.join(_fotos_dir, f"{_safe_name}.{_ext}")
                                            with open(_foto_path, "wb") as _ff:
                                                _ff.write(_r_foto.content)
                                            _cprint("INFO", f"[/costo] Foto guardada: {_foto_path}")
                                except Exception as _e_foto:
                                    _cprint("WARN", f"[/costo] No pudo descargar foto: {_e_foto}")

                            # ── Guardar en historial de productos Suite Financiera ─
                            try:
                                _suite_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "productos_suite.json")
                                try:
                                    with open(_suite_path, "r", encoding="utf-8") as _sf:
                                        _suite = json.load(_sf)
                                except Exception:
                                    _suite = {"productos": []}
                                _suite["productos"] = [
                                    p for p in _suite["productos"]
                                    if p.get("nombre", "").lower() != _nombre.lower()
                                ]
                                _entrada = {
                                    "nombre":       _nombre,
                                    "costo_usd":    round(_costo_total, 2),
                                    "precio_usd":   round(_precio_usd, 2),
                                    "precio_bs":    round(_precio_bs, 0),
                                    "qty_lote":     _qty,
                                    "tasa":         _tasa_p2p,
                                    "desglose": {
                                        "costo_producto":  round(_c_producto, 2),
                                        "flete_china":     round(_c_flete, 2),
                                        "envio_venezuela": round(_c_envio_vzl, 2),
                                        "internet":        round(_c_internet, 2),
                                        "envio_local":     round(_c_local, 2),
                                    },
                                    "fecha":        _dt.now().strftime("%Y-%m-%d %H:%M"),
                                }
                                if _foto_path:
                                    _entrada["foto"] = _foto_path
                                _suite["productos"].append(_entrada)
                                with open(_suite_path, "w", encoding="utf-8") as _sf:
                                    json.dump(_suite, _sf, ensure_ascii=False, indent=2)
                                _cprint("INFO", f"[/costo] '{_nombre}' guardado en productos_suite.json")
                            except Exception as _e_save:
                                _cprint("WARN", f"[/costo] No pudo guardar en suite: {_e_save}")

                            # ── Añadir confirmación de foto en respuesta ──────────
                            if _foto_path:
                                respuesta += "\n📸 <i>Foto guardada en Suite Financiera</i>"

                            gui_app.root.after(0, lambda n=_nombre, p=_precio_usd: gui_app.log(
                                f"[/costo] {n} → ${p:.2f}", "info"))

                    except (ValueError, IndexError) as _e_c:
                        respuesta = (
                            f"⚠️ Error en los datos: <code>{_e_c}</code>\n\n"
                            "Formato correcto:\n"
                            "<code>/costo RelojH55 8.50 10 25.00 40.00</code>\n"
                            "nombre · costo$ · cantidad · flete_china$ · envio_vzla$"
                        )
                        parse_mode = "HTML"
                    except Exception as _e_c:
                        respuesta = f"⚠️ Error: {type(_e_c).__name__}: {_e_c}"
                        _cprint("WARN", f"[TG /costo] {_e_c}")

                # ── Precios de servicios A2K Digital Studio — link directo ───────
                # (excluye menciones a electrónicos ZYNC, esas van al relay cloud
                #  que sabe responder precios puntuales de smartwatch/micrófonos/etc.)
                elif (not any(z in _txt_lower for z in (
                            "smartwatch", "smart watch", "reloj", "watch", "microfono",
                            "micrófono", "k9", "audifono", "audífono", "airmax", "combo"))
                        and any(x in _txt_lower for x in (
                            # preguntas genéricas de precio
                            "precio", "precios", "cuanto cuesta", "cuánto cuesta",
                            "quiero contratar", "servicios", "lista de precios",
                            "tabla de precios", "tarifas", "costos",
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
                            "manual de marca", "mockup"))):
                    respuesta = (
                        "¡Claro! Aquí tienes nuestra tabla de precios completa con todos los "
                        "servicios de A2K Digital Studio 👇\n"
                        "👉 https://www.a2kdigitalstudio.online/precios.html\n\n"
                        "Tenemos 4 niveles:\n"
                        "⭐ Básicos: desde $5\n"
                        "🔥 Intermedios: desde $20\n"
                        "💎 Avanzados: desde $60\n"
                        "👑 Premium: desde $200\n\n"
                        "¿Sobre qué servicio te gustaría más información? Escríbeme y te ayudo 🤖🔥"
                    )
                    _cprint("INFO", f"[TG precios servicios] chat={chat_id[:10]}")

                else:
                    # ── Relay estándar al cloud de catálogos ─────────────────────
                    try:
                        r = requests.post(
                            cloud_url,
                            json={"chat_id": chat_id, "message": texto, "source": "telegram"},
                            timeout=15,
                        )
                        if r.ok:
                            respuesta = r.json().get("response", r.text[:400])
                        else:
                            respuesta = f"Error del servidor ({r.status_code})"
                        _cprint("INFO", f"[TG RELAY] cloud {r.status_code} → chat={chat_id[:10]}")
                    except requests.exceptions.ConnectionError:
                        respuesta = "Sin conexión con el servidor de catálogos."
                        _cprint("WARN", "[TG RELAY] Sin conexión con cloud")
                    except requests.exceptions.Timeout:
                        respuesta = "El servidor tardó demasiado — intenta de nuevo."
                        _cprint("WARN", "[TG RELAY] Timeout con cloud (15 s)")
                    except Exception as e:
                        _cprint("WARN", f"[TG RELAY] {type(e).__name__}: {e}")

                # ── Enviar respuesta al chat de Telegram ─────────────────────────
                if tg_token and chat_id:
                    try:
                        payload_tg = {"chat_id": chat_id, "text": respuesta}
                        if parse_mode:
                            payload_tg["parse_mode"] = parse_mode
                        r_tg = requests.post(
                            f"https://api.telegram.org/bot{tg_token}/sendMessage",
                            json=payload_tg,
                            timeout=10,
                        )
                        # Si Telegram rechaza el HTML (400), reintenta como texto plano
                        if not r_tg.ok and parse_mode == "HTML":
                            import re as _re
                            texto_plano = _re.sub(r"<[^>]+>", "", respuesta)
                            requests.post(
                                f"https://api.telegram.org/bot{tg_token}/sendMessage",
                                json={"chat_id": chat_id, "text": texto_plano},
                                timeout=10,
                            )
                    except Exception as _e_tg:
                        _cprint("WARN", f"[TG SEND] Error enviando respuesta: {_e_tg}")

                gui_app.root.after(0, lambda m=texto[:60]: gui_app.log(
                    f"[TELEGRAM] {chat_id[:10]}... → {m}", "info"))

        class _Server(ThreadingMixIn, HTTPServer):
            allow_reuse_address = True
            daemon_threads      = True

        srv = _Server((HOST_SMS, PORT_SMS), _Handler)
        gui_app.root.after(0, lambda p=PORT_SMS: gui_app.log(
            f"[SMS SERVER] Escuchando en puerto {p} — SMS y pagos activos", "info"))
        gui_app.root.after(0, lambda p=PORT_SMS: gui_app.update_sms(
            f"● SMS :{p} ONLINE", "#00ffcc"))
        srv.serve_forever()

    except OSError as e:
        gui_app.root.after(0, lambda: gui_app.log(
            f"[SMS SERVER] Puerto ocupado o error de red: {e}", "err"))
        gui_app.root.after(0, lambda: gui_app.update_sms("● SMS: ERROR", "#ff5555"))
    except Exception as e:
        gui_app.root.after(0, lambda: gui_app.log(
            f"[SMS SERVER] Error al arrancar: {e}", "err"))
        gui_app.root.after(0, lambda: gui_app.update_sms("● SMS: ERROR", "#ff5555"))


# ──────────────────────────────────────────────────────────────────────────────
#  ZYNC SUITE — MONITOR DE TASAS AUTOMÁTICO (hilo daemon)
# ──────────────────────────────────────────────────────────────────────────────
def _monitor_tasas_automatico(gui_app) -> None:
    """
    Hilo daemon — refresca tasas BCV y Binance P2P en segundo plano.
    · Intervalo configurable: DIVISAS_MONITOR_INTERVAL segundos (default 900 = 15 min).
    · Si el scraping falla, mantiene las tasas manuales sin tocarlas.
    · Alerta por WhatsApp si el spread supera BCV_SPREAD_ALERTA_PCT (default 10%).
    · No bloquea el core de Tkinter bajo ninguna circunstancia.
    Anclado en _iniciar_servicios() como threading.Thread daemon=True.
    """
    from modulos.divisas_suite import (
        refrescar_tasas_auto, obtener_tasas, formatear_tasas_consola,
    )
    intervalo   = int(os.environ.get("DIVISAS_MONITOR_INTERVAL",  "900"))
    spread_max  = float(os.environ.get("BCV_SPREAD_ALERTA_PCT",   "10.0"))
    _ultima_alerta_spread = 0.0

    _cprint("INFO", f"[DIVISAS] Monitor de tasas iniciado — "
            f"intervalo {intervalo//60} min | alerta spread >{spread_max}%")

    while True:
        time.sleep(intervalo)
        try:
            res = refrescar_tasas_auto()
            tasas = obtener_tasas()
            spread = tasas.get("spread_pct", 0.0)

            if tasas.get("binance_p2p_usdt_bs", 0) > 0:
                _cprint("OK", f"[DIVISAS] Tasas actualizadas: "
                        f"BCV={tasas.get('bcv_usd_bs')} | "
                        f"Binance={tasas.get('binance_p2p_usdt_bs')} | "
                        f"Spread={spread}%")
                gui_app.root.after(0, lambda: gui_app.log(
                    formatear_tasas_consola(), "info"))
            else:
                errores = res.get("errores", [])
                if errores:
                    _cprint("WARN", f"[DIVISAS] Monitor: {errores}")

            # Alerta WA si spread supera el umbral (cooldown 1 h)
            ahora = time.time()
            if (spread > spread_max
                    and _WA_CONFIG.get("enabled")
                    and (ahora - _ultima_alerta_spread) > 3600):
                _ultima_alerta_spread = ahora
                numero = os.environ.get("WA_ADMIN_NUMERO", "").strip()
                if numero:
                    msg = (
                        f"*[JARVIS] ALERTA DE SPREAD P2P*\n"
                        f"Spread actual : *{spread:.2f}%* (umbral {spread_max:.1f}%)\n"
                        f"BCV           : Bs *{tasas.get('bcv_usd_bs',0):.4f}*/$\n"
                        f"Binance P2P   : Bs *{tasas.get('binance_p2p_usdt_bs',0):.4f}*/USDT\n\n"
                        f"Oportunidad de arbitraje detectada."
                    )
                    threading.Thread(
                        target=_enviar_whatsapp_humano,
                        args=(numero, msg),
                        daemon=True,
                    ).start()
                    _cprint("WA", f"[DIVISAS] Alerta spread {spread:.1f}% → {numero[:7]}***")

        except Exception as e:
            _cprint("WARN", f"[DIVISAS] Monitor error: {type(e).__name__}: {e}")


# ──────────────────────────────────────────────────────────────────────────────
#  RED — RUTA LAN (funciona con VPN activo o sin VPN)
# ──────────────────────────────────────────────────────────────────────────────
def _fix_lan_route() -> str:
    """
    Añade una ruta de red que mantiene el tráfico LAN por Wi-Fi
    aunque ProtonVPN (u otro VPN) esté activo.
    Requiere que Jarvis corra como Administrador para persistir la ruta.
    """
    import subprocess, re

    try:
        out = subprocess.run(
            ["ipconfig"], capture_output=True,
            text=True, encoding="cp1252", errors="ignore"
        ).stdout

        wifi_ip      = None
        wifi_gateway = None
        in_wifi      = False

        for line in out.splitlines():
            if re.search(r"Wi.Fi|inalámbrica Wi", line, re.IGNORECASE):
                in_wifi = True
            if not in_wifi:
                continue
            # Nuevo adaptador — salir si ya pasamos el bloque Wi-Fi
            if re.match(r"^Adaptador", line) and wifi_ip:
                break
            if re.search(r"Direcci.n IPv4", line):
                m = re.search(r"(\d+\.\d+\.\d+\.\d+)", line)
                if m:
                    wifi_ip = m.group(1)
            if re.search(r"Puerta de enlace|Default Gateway", line):
                m = re.search(r"(\d+\.\d+\.\d+\.\d+)", line)
                if m and m.group(1) != "0.0.0.0":
                    wifi_gateway = m.group(1)

        if not wifi_ip or not wifi_gateway:
            return "[RED] Wi-Fi no detectado — conecta a la red antes de abrir Jarvis."

        parts  = wifi_ip.split(".")
        subnet = f"{parts[0]}.{parts[1]}.{parts[2]}.0"

        # Añadir ruta: tráfico 192.168.10.0/24 → gateway Wi-Fi (no por VPN)
        r = subprocess.run(
            ["route", "add", subnet, "mask", "255.255.255.0",
             wifi_gateway, "metric", "1"],
            capture_output=True, text=True
        )
        if r.returncode == 0:
            return (f"[RED] Ruta LAN configurada: {subnet}/24 → {wifi_gateway}\n"
                    f"       IP de este PC: {wifi_ip} — usa este IP en la app del teléfono.\n"
                    f"       SMS funciona con VPN activo y sin VPN.")
        else:
            # Falló (falta permisos admin) — la ruta ya puede existir o falta admin
            return (f"[RED] IP Wi-Fi: {wifi_ip}  |  Gateway: {wifi_gateway}\n"
                    f"       Para que SMS funcione con VPN: ejecuta Jarvis como Administrador\n"
                    f"       (clic derecho → Ejecutar como administrador).")

    except Exception as e:
        return f"[RED] Error al configurar ruta LAN: {e}"


# ──────────────────────────────────────────────────────────────────────────────
#  ARRANQUE
# ──────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    _verificar_dependencias()
    root = tk.Tk()
    app  = JarvisGUI(root)
    # Conectar progreso de descarga de moondream a la consola Jarvis
    vision_mod.set_gui_log(lambda msg: app.root.after(0, lambda m=msg: app.log(m, "info")))

    def _iniciar_servicios():
        # ── Módulos en paralelo ─────────────────────────────────────────────
        threading.Thread(target=_verificar_estado_apis,                    daemon=True).start()
        threading.Thread(target=_arrancar_servidor_sms,     args=(app,),   daemon=True).start()
        threading.Thread(target=_monitor_zync,              args=(app,),   daemon=True).start()
        threading.Thread(target=_arrancar_servidor_zync,    args=(app,),   daemon=True).start()
        threading.Thread(target=_cierre_diario_automatico,  args=(app,),   daemon=True).start()
        threading.Thread(target=_cron_cobros_sabado,        args=(app,),   daemon=True).start()
        threading.Thread(target=_monitor_tasas_automatico,  args=(app,),   daemon=True).start()

        # ── Telegram Bot ────────────────────────────────────────────────────
        _tg_bridge.iniciar(
            on_texto=app.parser.procesar,
            log_fn=lambda m, t="info": app.root.after(
                0, lambda msg=m, tag=t: app.log(msg, tag)
            ),
        )

        # ── WhatsApp local service — auto-arranca si no está corriendo ──────
        def _chk_whatsapp():
            import urllib.request, json as _json, subprocess, time as _time
            wa_url = os.environ.get("WA_URL", "")
            base   = wa_url.replace("/send-text", "") if wa_url else "http://localhost:3099"

            def _status():
                with urllib.request.urlopen(f"{base}/status", timeout=4) as resp:
                    return _json.loads(resp.read())

            # La tarea "PM2 Resurrect Jarvis" ya deja wa-jarvis-service.js corriendo
            # solo al iniciar sesión, pero Puppeteer/Chrome puede tardar bastante más
            # de unos segundos en levantar tras un reinicio. Si no le damos tiempo real
            # aquí antes de decidir "no está corriendo", este bloque lanza un SEGUNDO
            # proceso node que choca con el de PM2 por el mismo perfil de Chrome
            # (bug real confirmado en logs: "browser is already running for
            # session-jarvis-wa-service", 2026-07-16 y 2026-07-17) — eso rompe la
            # sesión de WhatsApp y con ella el bot de binarias, que depende de que
            # esa sesión esté sana para recibir "activar binarias".
            for _intento in range(12):  # ~60s dándole tiempo a PM2 antes de asumir que no está
                try:
                    data = _status()
                    if data.get("connected"):
                        app.root.after(0, lambda: app.log("[WHATSAPP] Servicio local conectado — +584164117331 activo ✓", "ok"))
                    else:
                        app.root.after(0, lambda: app.log("[WHATSAPP] Servicio local iniciado pero sin sesión — abre http://localhost:3099/qr", "warn"))
                    return
                except Exception:
                    _time.sleep(5)

            # No respondió en ~60s — arrancarlo solo, igual que JARVIS-WHATSAPP.bat
            wa_dir = r"C:\Users\ASUS\whatsapp-bot-a2k"
            try:
                subprocess.Popen(
                    ["node", "wa-jarvis-service.js"],
                    cwd=wa_dir,
                    creationflags=subprocess.CREATE_NEW_CONSOLE,
                )
                app.root.after(0, lambda: app.log("[WHATSAPP] Servicio local no encontrado — arrancando automáticamente (revisa la ventana nueva por si pide QR)...", "warn"))
            except Exception as _e:
                app.root.after(0, lambda m=str(_e): app.log(f"[WHATSAPP] No se pudo arrancar el servicio solo — ejecuta JARVIS-WHATSAPP.bat a mano ({m})", "error"))
                return

            # Reintentar el status cada 5s — Puppeteer/Chromium puede tardar en conectar
            import time as _time
            for _intento in range(9):  # ~45s en total
                _time.sleep(5)
                try:
                    data = _status()
                    if data.get("connected"):
                        app.root.after(0, lambda: app.log("[WHATSAPP] Servicio arrancado y conectado ✓", "ok"))
                    else:
                        app.root.after(0, lambda: app.log("[WHATSAPP] Servicio arrancado — abre http://localhost:3099/qr si pide sesión", "warn"))
                    return
                except Exception:
                    continue
            app.root.after(0, lambda: app.log("[WHATSAPP] Sigue arrancando después de 45s — revisa la ventana nueva por si hay un error", "warn"))
        threading.Thread(target=_chk_whatsapp, daemon=True).start()

        # ── License Engine — estado al arrancar ────────────────────────────
        def _chk_license_engine():
            import time as _time
            _time.sleep(3)
            engine_url = "https://a2k-license-engine.shoppingelectronics3112.workers.dev"
            admin_key  = "A2K-ADMIN-2026-ABIGAIL"
            try:
                resp = requests.get(
                    f"{engine_url}/todas",
                    headers={"X-Admin-Key": admin_key},
                    timeout=10,
                )
                resp.raise_for_status()
                data = resp.json()

                licencias = data.get("licencias", [])
                total     = len(licencias)
                activas   = [l for l in licencias if l.get("activa")]
                pro       = [l for l in activas if l.get("type") == "pro"]
                demo      = [l for l in activas if l.get("type") == "demo"]
                revocadas = total - len(activas)

                partes = []
                if pro:
                    partes.append(f"{len(pro)} PRO")
                if demo:
                    partes.append(f"{len(demo)} demo activa{'s' if len(demo) > 1 else ''}")
                if revocadas:
                    partes.append(f"{revocadas} revocada{'s' if revocadas > 1 else ''}")

                resumen = " · ".join(partes) if partes else "sin licencias emitidas"
                msg = f"[LICENSE ENGINE] Cloudflare activo — 14 productos · {resumen}"
                app.root.after(0, lambda m=msg: app.log(m, "ok"))

            except Exception as _e:
                msg = f"[LICENSE ENGINE] Sin respuesta — {type(_e).__name__}: verifica conexión"
                app.root.after(0, lambda m=msg: app.log(m, "warn"))
        threading.Thread(target=_chk_license_engine, daemon=True).start()

        # ── FiadosPro — cobros pendientes al arrancar ───────────────────────
        def _chk_fiadospro():
            import json as _json, time as _time
            from datetime import date as _date, timedelta as _td
            _time.sleep(4)
            # Buscar el archivo en la carpeta hermana whatsapp-bot-a2k
            base = _base_exe()
            candidatos = [
                base.parent / "whatsapp-bot-a2k" / "fiadospro-data.json",
                base / ".." / "whatsapp-bot-a2k" / "fiadospro-data.json",
            ]
            data_path = next((p for p in candidatos if p.exists()), None)
            try:
                if data_path is None:
                    raise FileNotFoundError("fiadospro-data.json no encontrado")
                with open(data_path, encoding="utf-8") as f:
                    data = _json.load(f)
                fiados     = data.get("fiados", [])
                pendientes = [x for x in fiados if x.get("estado") == "pendiente"]
                hoy        = _date.today()
                hoy_str    = str(hoy)
                limite_str = str(hoy + _td(days=3))
                vencidos   = [x for x in pendientes if x.get("fechaVence", "9999") <= hoy_str]

                if not pendientes:
                    msg, tag = "[FIADOSPRO] Sin cobros pendientes — todo al día ✓", "ok"
                elif vencidos:
                    total_venc = sum(x.get("monto", 0) for x in vencidos)
                    msg = f"[FIADOSPRO] {len(vencidos)} fiado(s) VENCIDO(S) — ${total_venc:.0f} por cobrar ⚠"
                    tag = "warn"
                else:
                    total_pend = sum(x.get("monto", 0) for x in pendientes)
                    msg = f"[FIADOSPRO] {len(pendientes)} cobro(s) pendiente(s) — ${total_pend:.0f} total"
                    tag = "info"
                app.root.after(0, lambda m=msg, t=tag: app.log(m, t))
            except Exception:
                app.root.after(0, lambda: app.log("[FIADOSPRO] Sin datos — verifica whatsapp-bot-a2k/fiadospro-data.json", "warn"))
        threading.Thread(target=_chk_fiadospro, daemon=True).start()

        # ── Apify Viral — confirmar módulo activo ───────────────────────────
        def _chk_apify_viral():
            import time as _time
            _time.sleep(4.5)
            tiene_token  = bool(os.environ.get("APIFY_TOKEN", ""))
            tiene_modulo = (_base_exe() / "modulos" / "apify_viral.py").exists()
            if tiene_modulo and tiene_token:
                app.root.after(0, lambda: app.log("[APIFY VIRAL] Módulo activo — usa /viral [tema] [plataforma] en Telegram", "ok"))
            elif tiene_modulo and not tiene_token:
                app.root.after(0, lambda: app.log("[APIFY VIRAL] Módulo cargado pero falta APIFY_TOKEN en .env", "warn"))
            else:
                app.root.after(0, lambda: app.log("[APIFY VIRAL] Módulo no encontrado — verifica modulos/apify_viral.py", "warn"))
        threading.Thread(target=_chk_apify_viral, daemon=True).start()

        # ── ZYNC Electrónica — inventario al arrancar ───────────────────────
        def _chk_inventario_zync():
            import json as _json, time as _time
            _time.sleep(5)
            inv_path = _base_exe() / "inventario_zync.json"
            try:
                with open(inv_path, encoding="utf-8") as f:
                    inv = _json.load(f)
                grupos   = inv.get("grupos", {})
                criticos = [(g["label"], g["stock"]) for g in grupos.values() if 0 < g.get("stock", 0) <= 3]
                partes   = [f"{g['label'].split('(')[0].strip()}: {g['stock']}" for g in grupos.values()]
                if criticos:
                    alertas = " | ".join(f"{n}: {s} und" for n, s in criticos)
                    msg = f"[ZYNC STOCK] Stock bajo — {alertas}"
                    tag = "warn"
                else:
                    msg = f"[ZYNC STOCK] {' | '.join(partes)}"
                    tag = "ok"
                app.root.after(0, lambda m=msg, t=tag: app.log(m, t))
            except Exception:
                app.root.after(0, lambda: app.log("[ZYNC STOCK] inventario_zync.json no encontrado", "warn"))
        threading.Thread(target=_chk_inventario_zync, daemon=True).start()

        # ── Backup inicial al arrancar (síncrono, rápido) ───────────────────
        _crear_backup_inicial()

        app.log("Sistema Jarvis Mente Maestra v4.0 — Zync Suite activa.", "hdr")
        app.log("Comandos: 'ayuda' | 'db [cat]' | 'ver tecnico' | 'ver trading' | 'ver inventario'", "info")

        # Configurar ruta LAN — SMS funciona con VPN y sin VPN
        msg_red = _fix_lan_route()
        tag_red = "ok" if "configurada" in msg_red else "info"
        app.log(msg_red, tag_red)

        nombre = _nombre_usuario()
        saludo = f"Centro de mando listo. {nombre}, Jarvis en línea." if nombre else "Centro de mando listo. Jarvis en línea."
        speak(saludo)

        def _chk_voz():
            err = _voz.ultimo_error_gcloud()
            if "Sin errores" in err:
                app.log("[VOZ] Google Cloud Neural2 activo — voz profesional OK", "ok")
            else:
                app.log(f"[VOZ] gCloud falló: {err}", "err")
                app.log("[VOZ] Usando pyttsx3 — escribe 'reintentar voz' cuando tengas internet", "info")
        root.after(4000, _chk_voz)

    root.after(400, _iniciar_servicios)
    root.mainloop()
