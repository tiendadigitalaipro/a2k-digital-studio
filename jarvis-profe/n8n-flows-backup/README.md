# Backup de flujos n8n (2026-07-18) + guía de migración a Jarvis/Hermes

Estos 4 flujos se crearon en n8n Cloud (`a2kdigitalstudio2025.app.n8n.cloud`) el 2026-07-18 como demos B2B para LinkedIn. Se exportaron aquí como JSON re-importables (Import from File en n8n) para no depender de que la cuenta/trial de n8n siga activa.

| Archivo | Flujo | Trigger en n8n |
|---|---|---|
| `01-motor-contenido-automatico.json` | Genera post + imagen para redes usando IA local | Manual |
| `02-asistente-ejecutivo-gmail-calendario.json` | Clasifica correos de Gmail, agenda en Calendar, avisa por WhatsApp | Gmail (poll cada minuto) |
| `03-onboarding-automatico-clientes.json` | Da bienvenida a cliente nuevo + checklist de documentos | Webhook `cliente-nuevo-a2k` |
| `04-respuesta-instantanea-leads.json` | Califica un lead entrante y responde al instante | Webhook `lead-nuevo-a2k` |

Los 4 comparten el mismo patrón interno:
```
trigger → armar prompt → IA local (Ollama, qwen2.5:3b vía tunel cloudflared) → parsear JSON → acción (WhatsApp / Calendar / responder)
```

## Por qué moverlos a Jarvis en vez de n8n

n8n Cloud llega a tu PC solo a través de dos túneles cloudflared (`hills-every-etc-excellent.trycloudflare.com` → Ollama local, `workflow-wheat-macro-strip.trycloudflare.com` → WhatsApp local). Si el trial de n8n vence, se cae un túnel, o cambia la URL del túnel, el flujo entero deja de funcionar sin avisar. Corriendo esto directo en `jarvis-profe` (Hermes), se elimina el salto por internet: Ollama y WhatsApp están en la misma máquina, se llaman directo por Python.

Jarvis ya tiene las piezas que estos flujos reinventan en n8n:

| Nodo de n8n | Ya existe en Jarvis |
|---|---|
| `IA Local (Ollama)` (HTTP POST a `/api/chat`) | `modulos/config_loader.get_ollama_url()` + el mismo patrón `requests.post(f"{url}/api/chat", json=...)` usado en `modulos/tecnico.py` y `modulos/vision.py` |
| `Notificar por WhatsApp` (HTTP POST a túnel) | `modulos/whatsapp_zapi.enviar_mensaje(telefono, mensaje)` — llamada directa, sin túnel |
| Webhook trigger | Agregar una ruta en `modulos/rutas.py` (Jarvis ya expone endpoints HTTP) |
| Gmail trigger (poll) | Un hilo daemon más (Jarvis ya corre ~18) que haga poll con la API de Gmail cada minuto |
| Google Calendar (crear evento) | No existe todavía — hay que dar de alta credenciales OAuth de Google Calendar para el proyecto (es trabajo nuevo, no una migración directa) |

## Ejemplo real: flujo 04 (Respuesta Instantánea de Leads) portado a Python

Esto es código funcional, no pseudocódigo — usa las funciones reales que ya existen en `jarvis-profe`. Se puede pegar en un módulo nuevo `modulos/automatizaciones_ia.py` y colgar la ruta desde `rutas.py`.

```python
# modulos/automatizaciones_ia.py
import json
import requests
from modulos.config_loader import get_ollama_url
from modulos.whatsapp_zapi import enviar_mensaje

TELEFONO_VENTAS = "584164117331"  # mismo numero que usaba el nodo n8n

def _llamar_ollama(system_prompt: str, user_prompt: str, modelo: str = "qwen2.5:3b") -> dict:
    resp = requests.post(
        f"{get_ollama_url()}/api/chat",
        json={
            "model": modelo,
            "stream": False,
            "format": "json",
            "options": {"num_predict": 350, "temperature": 0.2},
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        },
        timeout=60,
    )
    resp.raise_for_status()
    texto = resp.json()["message"]["content"].strip()
    texto = texto.removeprefix("```json").removesuffix("```").strip()
    return json.loads(texto)


def calificar_lead(nombre: str, empresa: str, mensaje: str, canal: str = "formulario web") -> dict:
    system_prompt = f"""Eres un asistente de calificacion de leads B2B para A2K Digital Studio, una empresa que construye automatizaciones con IA para negocios.

Datos del lead:
- nombre: {nombre}
- empresa: {empresa}
- canal: {canal}
- mensaje: {mensaje}

Reglas de calificacion:
- CALIENTE: menciona un dolor concreto (perdida de clientes, tiempo de respuesta, procesos manuales) o pide precio/demo directamente.
- TIBIO: pregunta general sobre servicios sin dolor especifico.
- FRIO: mensaje vago, spam, o sin intencion clara de compra.

Responde UNICAMENTE con un JSON valido, sin texto extra, con estas llaves:
- "categoria": "CALIENTE" o "TIBIO" o "FRIO"
- "puntuacion": numero de 0 a 100
- "razon": explicacion breve de la calificacion (1 frase)
- "respuesta_sugerida": mensaje corto, profesional y cercano en espanol, agradeciendo el contacto y proponiendo el siguiente paso. Maximo 3 frases."""

    resultado = _llamar_ollama(system_prompt, "Califica este lead y responde con el JSON pedido.")

    if resultado.get("categoria") == "CALIENTE":
        enviar_mensaje(
            TELEFONO_VENTAS,
            f"Lead CALIENTE nuevo ({resultado['puntuacion']}/100): {resultado['razon']}",
        )
    # TIBIO/FRIO: aqui se registraria en Sheet/Airtable (el NoOp que quedo pendiente en n8n tambien)

    return resultado
```

Y la ruta HTTP equivalente al webhook `lead-nuevo-a2k`, en `modulos/rutas.py`:
```python
@app.post("/webhook/lead-nuevo-a2k")
async def lead_nuevo(request: Request):
    body = await request.json()
    resultado = calificar_lead(
        nombre=body.get("nombre", "Sin nombre"),
        empresa=body.get("empresa", "Sin empresa"),
        mensaje=body.get("mensaje", ""),
        canal=body.get("canal", "formulario web"),
    )
    return {"mensaje": resultado["respuesta_sugerida"], "categoria": resultado["categoria"]}
```

El flujo `03-onboarding-automatico-clientes` se porta igual (mismo patrón: prompt → `_llamar_ollama` → `enviar_mensaje`). El `01-motor-contenido` es igual más una llamada a Pollinations (`requests.get` a `image.pollinations.ai/prompt/...`, ya sin usar tunel porque no depende de Ollama local para esa parte).

El flujo `02-asistente-ejecutivo-gmail-calendario` es el único que requiere trabajo nuevo real (credenciales OAuth de Gmail/Calendar de Google), no solo migración — los otros tres son un port directo de lo que ya existe.

## Cómo reimportar a n8n si hace falta

Panel de n8n → Workflows → Import from File → seleccionar el `.json` correspondiente de esta carpeta.

---

# Backup de flujos n8n (2026-07-20/21) — demos B2B para rubros nuevos

A pedido explícito de Abigail ("enfócate en otros rubros de otras empresas importantes, olvídate de barbería/bodega/farmacia/lo que hacemos"), se crearon estos 4 flujos nuevos en n8n Cloud para vender A2K a verticales que la empresa NO atiende hoy. Mismo patrón técnico que los 4 de arriba (Ollama local vía túnel cloudflared + WhatsApp + Google Calendar), reutilizando la credencial de Google Calendar ya autorizada.

| Archivo | Flujo | Trigger en n8n |
|---|---|---|
| `05-triage-medico-clinicas.json` | Clasifica mensajes de pacientes (urgencia/cita nueva/confirmación), notifica a la guardia y agenda en Calendar | Webhook `mensaje-paciente-clinica` |
| `06-captacion-legal-bufetes.json` | Califica consultas legales entrantes por área de práctica y urgencia, notifica al socio senior si es urgente | Webhook `consulta-legal-nueva` |
| `07-calificacion-leads-inmobiliaria.json` | Califica leads interesados en propiedades y agenda visita automática en Calendar si están listos para comprar | Webhook `interes-propiedad-nuevo` |
| `08-notificacion-envios-logistica.json` | Redacta actualizaciones de estado de envío para el cliente y alerta al gerente de cuenta si hay retraso | Webhook `actualizacion-envio` |

Mismo patrón interno que los primeros 4:
```
webhook → armar prompt → IA local (Ollama, qwen2.5:3b vía tunel cloudflared) → parsear JSON → enrutar (switch/if) → acción (WhatsApp / Calendar) → responder al webhook
```

**Diferencia con los 4 anteriores:** estos usan además el nodo `n8n-nodes-base.googleCalendar` (con la credencial de Google Calendar ya conectada en la cuenta de n8n) para revisar disponibilidad y crear eventos — no son solo IA + WhatsApp.

Los nodos HTTP Request hacia Ollama y WhatsApp siguen en `placeholder()` — hay que poner la URL del túnel cloudflared activo antes de una demo en vivo, las URLs viejas de sesiones anteriores ya no sirven.

Los videos demo de estos 4 (intro Canva + grabación real del canvas/ejecución en n8n + narración) están en `Desktop\Videos-Productos\intros-b2b-n8n\` en la laptop de Abigail (no en este repo, son archivos de video pesados).
