"""
Módulo conector para la pasarela de pagos PágueloFácil.
Integración: Zync Suite Financiera / Jarvis v4.0 — A2K Digital Studio
"""

import os
import requests

# ─── Credenciales ────────────────────────────────────────────────────────────
# Reemplaza estos valores con tus credenciales reales antes de usar en producción.
CCLW              = os.getenv("PAGUELOFACIL_CCLW",            "TU_CCLW_AQUI")
ACCESS_TOKEN      = os.getenv("PAGUELOFACIL_TOKEN",           "TU_TOKEN_AQUI")
BASE_URL          = os.getenv("PAGUELOFACIL_BASE_URL",        "https://secure.paguelofacil.com")
_ENDPOINT_COBRO   = os.getenv("PAGUELOFACIL_ENDPOINT_COBRO",  "/rest/main.cgi/ProcessTx")
_ENDPOINT_STATUS  = os.getenv("PAGUELOFACIL_ENDPOINT_STATUS", "/rest/main.cgi/getPayInfo")

_HEADERS = {
    "Authorization": f"Bearer {ACCESS_TOKEN}",
    "CCLW": CCLW,
    "Content-Type": "application/json",
    "Accept": "application/json",
}

# ─── Función 1: Generar enlace de cobro ──────────────────────────────────────

def generar_link_cobro(monto: float, concepto: str, id_referencia: str) -> str:
    """
    Genera un enlace de pago en PágueloFácil.

    Args:
        monto:          Monto a cobrar (en la moneda configurada en la cuenta).
        concepto:       Descripción del cobro visible para el cliente.
        id_referencia:  Identificador único de la orden/transacción en Jarvis.

    Returns:
        URL del enlace de pago listo para enviar al cliente.

    Raises:
        ValueError: Si la API devuelve un error de validación.
        requests.HTTPError: Si el servidor responde con un código HTTP de error.
        requests.RequestException: Para errores de red o timeout.
    """
    endpoint = f"{BASE_URL.rstrip('/')}{_ENDPOINT_COBRO}"

    _webhook_url = os.getenv(
        "PAGUELOFACIL_RETURN_URL",
        "https://a2kdigitalstudio.online/webhook/paguelofacil"
    )

    payload = {
        "cclw":            CCLW,
        "amount":          round(float(monto), 2),
        "concept":         concepto,
        "reference":       str(id_referencia),
        "currency":        "USD",
        "returnUrl":       _webhook_url,
        "notificationUrl": _webhook_url,
    }

    try:
        response = requests.post(endpoint, json=payload, headers=_HEADERS, timeout=15)
        response.raise_for_status()
        data = response.json()

        # PágueloFácil retorna el link bajo distintas claves según versión de API
        link = (
            data.get("data", {}).get("linkPago")
            or data.get("linkPago")
            or data.get("link")
        )

        if not link:
            raise ValueError(
                f"La API no devolvió un enlace de pago. Respuesta: {data}"
            )

        return link

    except requests.exceptions.Timeout:
        raise requests.RequestException(
            "Tiempo de espera agotado al conectar con PágueloFácil."
        )
    except requests.exceptions.ConnectionError:
        raise requests.RequestException(
            "No se pudo conectar con la API de PágueloFácil. Verifica tu conexión."
        )
    except requests.exceptions.HTTPError as exc:
        raise requests.HTTPError(
            f"Error HTTP {exc.response.status_code} al generar enlace: {exc.response.text}"
        ) from exc


# ─── Función 2: Consultar estado de pago ─────────────────────────────────────

def consultar_estado_pago(id_transaccion: str) -> dict:
    """
    Consulta el estado de una transacción en PágueloFácil.

    Args:
        id_transaccion: ID de la transacción devuelto por PágueloFácil.

    Returns:
        Diccionario con el estado y los detalles de la transacción. Campos clave:
            - 'aprobado'  (bool):  True si el pago fue aprobado.
            - 'estado'    (str):   Estado textual ("APROBADA", "PENDIENTE", etc.).
            - 'monto'     (float): Monto confirmado por la pasarela.
            - 'raw'       (dict):  Respuesta completa de la API.

    Raises:
        requests.HTTPError: Si el servidor responde con un código HTTP de error.
        requests.RequestException: Para errores de red o timeout.
    """
    endpoint = f"{BASE_URL.rstrip('/')}{_ENDPOINT_STATUS}/{id_transaccion}/{CCLW}"

    try:
        response = requests.get(endpoint, headers=_HEADERS, timeout=15)
        response.raise_for_status()
        data = response.json()

        # Normalizar respuesta para que Jarvis la consuma de forma uniforme
        estado_raw = (
            data.get("data", {}).get("status")
            or data.get("status")
            or ""
        ).upper()

        aprobado = estado_raw in ("APROBADA", "APPROVED", "PAGADA", "PAID")

        return {
            "aprobado": aprobado,
            "estado": estado_raw or "DESCONOCIDO",
            "monto": data.get("data", {}).get("amount") or data.get("amount"),
            "id_transaccion": id_transaccion,
            "raw": data,
        }

    except requests.exceptions.Timeout:
        raise requests.RequestException(
            "Tiempo de espera agotado al consultar el estado del pago."
        )
    except requests.exceptions.ConnectionError:
        raise requests.RequestException(
            "No se pudo conectar con la API de PágueloFácil. Verifica tu conexión."
        )
    except requests.exceptions.HTTPError as exc:
        raise requests.HTTPError(
            f"Error HTTP {exc.response.status_code} al consultar estado: {exc.response.text}"
        ) from exc


# ─── Bloque de prueba rápida (solo en desarrollo) ────────────────────────────
if __name__ == "__main__":
    print("=== PágueloFácil Suite — Test de sintaxis OK ===")
    print(f"CCLW cargado    : {'[REAL]' if CCLW != 'TU_CCLW_AQUI' else '[placeholder]'}")
    print(f"TOKEN cargado   : {'[REAL]' if ACCESS_TOKEN != 'TU_TOKEN_AQUI' else '[placeholder]'}")
    print("Para probar en producción, define las variables de entorno:")
    print("  PAGUELOFACIL_CCLW=<tu_cclw>")
    print("  PAGUELOFACIL_TOKEN=<tu_token>")
