"""
servidor_onboarding.py — Recibe clientes nuevos y dispara el onboarding automático con IA
A2K Digital Studio

Reemplaza al flujo n8n "Onboarding Automático de Clientes" (webhook cliente-nuevo-a2k).
Servidor propio e independiente en el puerto 3100 — no toca jarvis_profe.py ni
comparte proceso con el resto de Jarvis. Solo corre cuando tú lo arrancas.

Uso:
  python servidor_onboarding.py
      → Levanta el servidor en http://localhost:3100

  Luego, cuando cierres un cliente nuevo (a mano o desde un formulario/checkout
  que apunte aquí), se hace POST a http://localhost:3100/cliente-nuevo-a2k con:
      { "nombre": "...", "empresa": "...", "rubro": "...",
        "servicio_contratado": "...", "cerrado_por": "..." }

  Prueba manual con curl:
      curl -X POST http://localhost:3100/cliente-nuevo-a2k ^
           -H "Content-Type: application/json" ^
           -d "{\"nombre\":\"Juan\",\"empresa\":\"Barberia Los Amigos\",\"rubro\":\"barberia\",\"servicio_contratado\":\"Recepcionista IA\",\"cerrado_por\":\"Abigail\"}"
"""
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env", override=True)

from flask import Flask, request, jsonify

from modulos.automatizaciones_ia import onboarding_cliente

app = Flask(__name__)


@app.route("/cliente-nuevo-a2k", methods=["POST"])
def cliente_nuevo():
    datos = request.get_json(force=True, silent=True) or {}
    try:
        resultado = onboarding_cliente(
            nombre=datos.get("nombre", "Cliente"),
            empresa=datos.get("empresa", "su empresa"),
            rubro=datos.get("rubro", "servicios profesionales"),
            servicio_contratado=datos.get("servicio_contratado", "el servicio contratado"),
            cerrado_por=datos.get("cerrado_por", "el equipo comercial"),
        )
    except Exception as e:
        print(f"❌ Error en onboarding: {e}")
        return jsonify({"error": str(e)}), 500

    return jsonify({
        "mensaje": resultado["bienvenida_cliente"],
        "departamento_responsable": resultado["departamento_responsable"],
        "documentos_requeridos": resultado["documentos_requeridos"],
    })


if __name__ == "__main__":
    print("=" * 60)
    print("Servidor de onboarding — A2K Digital Studio")
    print("Escuchando en http://localhost:3100/cliente-nuevo-a2k")
    print("(Ctrl+C para detener — no afecta a Jarvis, es un proceso aparte)")
    print("=" * 60)
    app.run(host="0.0.0.0", port=3100)
