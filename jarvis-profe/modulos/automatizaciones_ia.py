"""
automatizaciones_ia.py — Automatizaciones que antes vivian en n8n, portadas a Jarvis
A2K Digital Studio

Modulo nuevo e independiente: no lo importa jarvis_profe.py ni ningun otro
modulo existente, asi que no puede romper nada de lo que ya funciona.
Se ejecuta solo desde los scripts sueltos ejecutar_contenido_diario.py y
servidor_onboarding.py (o desde donde tu decidas engancharlo mas adelante).

Usa las mismas piezas que ya existen en Jarvis:
- modulos.config_loader.get_ollama_url() / get_ollama_modelo()  (igual que tecnico.py y vision.py)
- modulos.whatsapp_zapi.enviar_mensaje()                        (igual que el resto de Jarvis)
"""
import json
from pathlib import Path

import requests

from modulos.config_loader import get_ollama_url, get_ollama_modelo, get_ollama_timeout
from modulos.whatsapp_zapi import enviar_mensaje

# Mismos numeros que usaban los flujos en n8n
TELEFONO_ABIGAIL = "584126148666"
TELEFONO_EQUIPO_INTERNO = "584164117331"


def _llamar_ollama(system_prompt: str, user_prompt: str) -> dict:
    """Llama al Ollama local y parsea la respuesta como JSON. Lanza excepcion si algo falla."""
    resp = requests.post(
        f"{get_ollama_url()}/api/chat",
        json={
            "model": get_ollama_modelo(),
            "stream": False,
            "format": "json",
            "options": {"num_predict": 400, "temperature": 0.3},
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        },
        timeout=get_ollama_timeout(),
    )
    resp.raise_for_status()
    texto = resp.json()["message"]["content"].strip()
    if texto.startswith("```"):
        texto = texto.split("```")[1]
        if texto.startswith("json"):
            texto = texto[4:]
    return json.loads(texto.strip())


# ── 1. Motor de Contenido Automatico ────────────────────────────────────────

def generar_contenido_diario(
    nombre_empresa: str = "A2K Digital Studio",
    nicho: str = "soluciones de IA y automatizacion para negocios",
    tono: str = "profesional, cercano, seguro de si mismo",
    publico_objetivo: str = "dueños de pequeños negocios (barberias, restaurantes, bodegas) que pierden clientes por no contestar rapido",
    productos_servicios: str = "Recepcionista IA por WhatsApp, POS con IA (Comandas/Bodega/Barberia Pro)",
    plataforma_principal: str = "LinkedIn",
    avisar_whatsapp: bool = True,
    carpeta_salida: Path | None = None,
) -> dict:
    """
    Genera una pieza de contenido (idea + caption + hashtags + imagen) con IA local.
    Equivalente al flujo n8n "Motor de Contenido Automatico".

    Devuelve: {"idea", "caption", "hashtags", "image_prompt", "imagen_path"}
    """
    system_prompt = f"""Eres el estratega de contenido de {nombre_empresa}, negocio de {nicho}.
Tono: {tono}. Publico: {publico_objetivo}. Productos: {productos_servicios}. Plataforma principal: {plataforma_principal}.

Genera UNA pieza de contenido que conecte un dolor real de ese publico con uno de los productos, y cierre con una accion clara.
Estilo: humano y cercano, sin cliches de IA (nada de "revoluciona", "en la era digital"). Incluye una microprueba (dato o ejemplo).

Responde UNICAMENTE con JSON valido, sin texto extra, con estas llaves:
- "idea": concepto central en 1 frase.
- "caption": listo para publicar (gancho, dolor, beneficio+microprueba, CTA). Maximo 80 palabras.
- "hashtags": array de 4 a 6 strings.
- "image_prompt": escena fotografica realista (sujeto, entorno, luz), sin texto ni marcas de agua."""

    contenido = _llamar_ollama(system_prompt, "Genera la pieza de contenido de hoy. Responde solo el JSON pedido, breve y directo.")

    imagen_path = None
    try:
        url_imagen = f"https://image.pollinations.ai/prompt/{requests.utils.quote(contenido['image_prompt'])}"
        r = requests.get(url_imagen, timeout=60)
        r.raise_for_status()
        destino = carpeta_salida or (Path(__file__).parent.parent / "contenido_generado")
        destino.mkdir(parents=True, exist_ok=True)
        imagen_path = destino / f"post_{abs(hash(contenido['idea'])) % 100000}.jpg"
        imagen_path.write_bytes(r.content)
    except Exception as e:
        print(f"[Contenido IA] No se pudo generar la imagen: {e}")

    contenido["imagen_path"] = str(imagen_path) if imagen_path else None

    if avisar_whatsapp:
        mensaje = f"Se generó contenido nuevo: {contenido['idea']}\n\nCaption:\n{contenido['caption']}"
        if imagen_path:
            mensaje += f"\n\nImagen guardada en:\n{imagen_path}"
        enviar_mensaje(TELEFONO_ABIGAIL, mensaje)

    return contenido


# ── 2. Onboarding Automatico de Clientes ────────────────────────────────────

def onboarding_cliente(
    nombre: str,
    empresa: str,
    rubro: str = "servicios profesionales",
    servicio_contratado: str = "el servicio contratado",
    cerrado_por: str = "el equipo comercial",
    avisar_whatsapp: bool = True,
) -> dict:
    """
    Genera el paquete de bienvenida de un cliente nuevo (mensaje + checklist de documentos)
    y avisa al equipo interno por WhatsApp.
    Equivalente al flujo n8n "Onboarding Automatico de Clientes".

    Devuelve: {"bienvenida_cliente", "documentos_requeridos", "resumen_interno", "departamento_responsable"}
    """
    system_prompt = f"""Eres el asistente de onboarding de A2K Digital Studio, encargado de arrancar bien a cada cliente nuevo que firma.

Datos del cliente nuevo:
- nombre: {nombre}
- empresa: {empresa}
- rubro de la empresa: {rubro}
- servicio contratado: {servicio_contratado}
- cerrado por: {cerrado_por}

Tarea: genera el paquete de bienvenida y arranque para este cliente.

Responde UNICAMENTE con un JSON valido, sin texto extra, con estas llaves:
- "bienvenida_cliente": mensaje corto, calido y profesional en espanol dirigido al cliente, agradeciendo su confianza y explicando el siguiente paso. Maximo 4 frases.
- "documentos_requeridos": array de 2 a 5 strings con los documentos o datos tipicos que se necesitarian pedirle a una empresa de ese rubro para arrancar.
- "resumen_interno": 1-2 frases para que el equipo interno sepa quien es el cliente y que necesita, sin lenguaje de venta.
- "departamento_responsable": el area interna que deberia encargarse del arranque (ej. "Legal", "Operaciones", "Cuentas", "Exito del Cliente")."""

    resultado = _llamar_ollama(system_prompt, "Genera el paquete de onboarding para este cliente nuevo siguiendo las instrucciones.")

    if avisar_whatsapp:
        docs = ", ".join(resultado.get("documentos_requeridos", []))
        mensaje = (
            f"Cliente nuevo ({resultado.get('departamento_responsable', '?')}): "
            f"{resultado.get('resumen_interno', '')} Documentos a pedir: {docs}"
        )
        enviar_mensaje(TELEFONO_EQUIPO_INTERNO, mensaje)

    return resultado
