"""
ejecutar_contenido_diario.py — Genera una pieza de contenido (post + imagen) con IA local
A2K Digital Studio

Reemplaza al flujo n8n "Motor de Contenido Automático" (que era de disparo manual).
No depende de n8n ni de ningún túnel — usa el Ollama que ya tienes corriendo en esta PC.

Uso:
  python ejecutar_contenido_diario.py
      → Genera idea + caption + hashtags + imagen, guarda la imagen en
        jarvis-profe/contenido_generado/ y te avisa por WhatsApp.

  python ejecutar_contenido_diario.py --sin-whatsapp
      → Igual, pero no manda el aviso por WhatsApp (para probar sin generar ruido).
"""
import argparse
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env", override=True)

from modulos.automatizaciones_ia import generar_contenido_diario


def main():
    ap = argparse.ArgumentParser(description="Generador de contenido diario — A2K Digital Studio")
    ap.add_argument("--sin-whatsapp", action="store_true", help="No enviar el aviso por WhatsApp")
    args = ap.parse_args()

    print("=" * 60)
    print("Generando contenido con IA local (Ollama)...")
    print("=" * 60)

    try:
        contenido = generar_contenido_diario(avisar_whatsapp=not args.sin_whatsapp)
    except Exception as e:
        print(f"❌ Error generando contenido: {e}")
        print("   Verifica que Ollama esté corriendo (ollama serve) antes de reintentar.")
        return

    print(f"\n💡 Idea: {contenido['idea']}")
    print(f"\n📝 Caption:\n{contenido['caption']}")
    print(f"\n🏷️  Hashtags: {' '.join('#' + h.lstrip('#') for h in contenido['hashtags'])}")
    print(f"\n🖼️  Imagen: {contenido['imagen_path'] or 'no se pudo generar'}")
    print(f"\n{'✅ Aviso enviado por WhatsApp' if not args.sin_whatsapp else '🟡 Aviso por WhatsApp omitido (--sin-whatsapp)'}")


if __name__ == "__main__":
    main()
