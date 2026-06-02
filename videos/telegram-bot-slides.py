#!/usr/bin/env python3
"""Telegram Bot Promotional Video Slides Generator"""
from PIL import Image, ImageDraw, ImageFont, ImageFilter
import os

W, H = 1920, 1080
OUT = "slides/telegram"

# Colors
BG = (10, 10, 15)
BLUE = (0, 136, 204)
DBLUE = (0, 95, 163)
WHITE = (255, 255, 255)
GRAY = (136, 136, 153)
CARD_BG = (18, 18, 26)
GREEN = (0, 255, 136)

font_bold = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 56)
font_big = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 80)
font_huge = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 120)
font_title = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 44)
font_sub = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 36)
font_sm = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 28)
font_xs = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 22)

def create_slide():
    img = Image.new('RGB', (W, H), BG)
    return img, ImageDraw.Draw(img)

def add_glow(draw, cx, cy, color, radius=200):
    for r in range(radius, 0, -4):
        alpha = int(30 * (r / radius))
        c = tuple(int(v * alpha / 255) for v in color)
        draw.ellipse([cx-r, cy-r, cx+r, cy+r], fill=c)

def draw_rounded_rect(draw, xy, radius, fill, outline=None):
    draw.rounded_rectangle(xy, radius=radius, fill=fill, outline=outline)

def center_text(draw, y, text, font, fill=WHITE):
    bbox = draw.textbbox((0,0), text, font=font)
    tw = bbox[2] - bbox[0]
    x = (W - tw) // 2
    draw.text((x, y), text, font=font, fill=fill)

def draw_badge(draw, x, y, text, color=BLUE):
    bbox = draw.textbbox((0,0), text, font=font_sm)
    tw, th = bbox[2]-bbox[0], bbox[3]-bbox[1]
    pad = 16
    draw.rounded_rectangle([x, y, x+tw+pad*2, y+th+pad], radius=30, fill=tuple(v//10 for v in color), outline=color)
    draw.text((x+pad, y+pad//2), text, font=font_sm, fill=color)

def save(img, idx):
    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, f"slide_{idx:02d}.png")
    img.save(path, quality=95)
    print(f"Saved {path}")
    return path

# ═══ SLIDE 1: INTRO ═══
img, draw = create_slide()
add_glow(draw, W//2, H//2, BLUE, 300)
# Paper plane icon
px, py = W//2, 260
draw.polygon([(px, py-60), (px+70, py+10), (px+10, py+40)], fill=BLUE)
draw.polygon([(px, py-60), (px-70, py+10), (px-10, py+40)], fill=DBLUE)
draw.line([(px-20, py+30), (px+20, py+30)], fill=BG, width=3)
draw.line([(px, py-60), (px, py+40)], fill=BG, width=3)
center_text(draw, 380, "Automatiza tu negocio", font_big, WHITE)
center_text(draw, 480, "con Telegram", font_big, BLUE)
center_text(draw, 600, "El canal mas rapido para tus clientes", font_sub, GRAY)
save(img, 1)

# ═══ SLIDE 2: PROBLEM ═══
img, draw = create_slide()
add_glow(draw, W//2, 200, BLUE, 250)
center_text(draw, 120, "Miles de consultas", font_big, BLUE)
center_text(draw, 220, "y no puedes responder a todas", font_bold, WHITE)
pains = [
    "Demoras en respuestas de horas",
    "Clientes se van a la competencia",
    "Informacion desactualizada en tu canal",
    "No puedes estar 24 horas en linea"
]
cy = 350
for i, pain in enumerate(pains):
    draw_rounded_rect(draw, [200, cy, W-200, cy+65], 16, tuple(v//10 for v in BLUE), BLUE)
    draw.ellipse([220, cy+12, 260, cy+52], fill=BLUE)
    draw.text((230, cy+14), "!", font=font_bold, fill=BG)
    draw.text((280, cy+16), pain, font=font_sub, fill=WHITE)
    cy += 90
save(img, 2)

# ═══ SLIDE 3: SOLUTION ═══
img, draw = create_slide()
add_glow(draw, W//2, 350, BLUE, 350)
# Telegram icon
px, py = W//2, 200
draw.ellipse([px-55, py-55, px+55, py+55], fill=BLUE)
draw.polygon([(px-20, py-15), (px+25, py+15), (px-5, py+5)], fill=WHITE)
center_text(draw, 300, "BOT TELEGRAM", font_huge, BLUE)
center_text(draw, 430, "Tu asistente IA 24/7", font_bold, WHITE)
center_text(draw, 500, "Atiende, vende y gestiona por ti", font_sub, GRAY)
badges = ["Atencion 24/7", "Agenda", "Catalogo", "IA"]
total_w = sum(len(b)*18 + 50 for b in badges) + (len(badges)-1)*20
bx = (W - total_w) // 2
for b in badges:
    bbox = draw.textbbox((0,0), b, font=font_sm)
    tw = bbox[2]-bbox[0]
    draw_badge(draw, bx, 590, b, BLUE)
    bx += tw + 50 + 20
save(img, 3)

# ═══ SLIDE 4: HOW IT WORKS ═══
img, draw = create_slide()
add_glow(draw, W//2, H//2, BLUE, 250)
center_text(draw, 60, "Como funciona", font_big, BLUE)
center_text(draw, 145, "Flujo automatizado completo", font_sub, GRAY)

steps = [
    ("1", "Cliente escribe por Telegram", BLUE),
    ("2", "La IA responde al instante", DBLUE),
    ("3", "Muestra catalogo y precios", GREEN),
    ("4", "Agenda citas automaticamente", (136,68,255)),
]
cy = 230
for num, text, color in steps:
    draw_rounded_rect(draw, [250, cy, W-250, cy+90], 16, CARD_BG, color)
    draw.ellipse([280, cy+18, 340, cy+72], fill=color)
    draw.text((300, cy+22), num, font=font_bold, fill=WHITE)
    draw.text((370, cy+25), text, font=font_sub, fill=WHITE)
    # Arrow
    if num != "4":
        ax = W//2
        draw.polygon([(ax-12, cy+110), (ax+12, cy+110), (ax, cy+130)], fill=color)
    cy += 150

# Chat preview
draw_rounded_rect(draw, [250, 850, W-250, 1000], 16, CARD_BG, BLUE)
draw.text((290, 870), "Cliente: Quiero info del catalogo", font=font_xs, fill=WHITE)
draw.text((290, 900), "Bot: Claro! Estos son nuestros servicios...", font=font_xs, fill=BLUE)
save(img, 4)

# ═══ SLIDE 5: FEATURES ═══
img, draw = create_slide()
center_text(draw, 60, "Todo lo que incluye tu Bot", font_big, BLUE)

features = [
    ("Atencion 24/7", "Siempre disponible para tus clientes", BLUE),
    ("IA Conversacional", "Entiende el contexto y responde natural", DBLUE),
    ("Agenda de Citas", "Reserva automatica sin intervencion", GREEN),
    ("Catalogo Interactivo", "Productos y servicios al instante", (136,68,255)),
    ("Notificaciones", "Alertas en tiempo real al equipo", (255,204,0)),
    ("Panel Admin", "Dashboard completo de metricas", (255,51,85)),
]
positions = [(100,180,980,340), (940,180,1820,340), (100,370,980,530), (940,370,1820,530), (100,560,980,720), (940,560,1820,720)]
for i, ((feat, desc, color), (x1,y1,x2,y2)) in enumerate(zip(features, positions)):
    draw_rounded_rect(draw, [x1,y1,x2,y2], 16, CARD_BG, color)
    cx, cy = x1+40, y1+50
    draw.ellipse([cx-20,cy-20,cx+20,cy+20], fill=color)
    draw.text((cx-8, cy-12), str(i+1), font=font_xs, fill=BG)
    draw.text((x1+75, y1+30), feat, font=font_title, fill=color)
    draw.text((x1+75, y1+85), desc, font=font_xs, fill=GRAY)
save(img, 5)

# ═══ SLIDE 6: INTEGRATION ═══
img, draw = create_slide()
center_text(draw, 60, "Integracion total", font_big, BLUE)
center_text(draw, 145, "con tu negocio", font_sub, GRAY)

# Stats
stats = [("1000+", "Mensajes procesados", BLUE), ("99%", "Uptime garantizado", GREEN), ("24/7", "Disponibilidad total", (136,68,255))]
sx = 100
for num, label, color in stats:
    draw_rounded_rect(draw, [sx, 230, sx+560, 400], 16, CARD_BG, color)
    bbox = draw.textbbox((0,0), num, font=font_huge)
    tw = bbox[2]-bbox[0]
    draw.text(((2*(sx+280)-tw)//2, 250), num, font=font_huge, fill=color)
    bbox2 = draw.textbbox((0,0), label, font=font_sm)
    tw2 = bbox2[2]-bbox2[0]
    draw.text(((2*(sx+280)-tw2)//2, 370), label, font=font_sm, fill=GRAY)
    sx += 600

# Connected platforms
center_text(draw, 450, "Conectado con:", font_bold, WHITE)
platforms = [("Telegram", BLUE), ("WhatsApp", (37,211,102)), ("Web", (108,99,255))]
px = (W - len(platforms)*400)//2
for name, color in platforms:
    draw_rounded_rect(draw, [px, 520, px+340, 640], 20, CARD_BG, color)
    bbox = draw.textbbox((0,0), name, font=font_sub)
    tw = bbox[2]-bbox[0]
    draw.text((px+(340-tw)//2, 560), name, font=font_sub, fill=color)
    px += 400

# Dashboard preview
draw_rounded_rect(draw, [100, 700, W-100, 950], 16, CARD_BG, BLUE)
draw.text((140, 720), "Panel de Administracion", font=font_bold, fill=BLUE)
draw.text((140, 790), "Metricas en tiempo real  |  Historial completo  |  Multi-idioma", font=font_sub, fill=GRAY)
draw_rounded_rect(draw, [140, 850, 400, 910], 16, BLUE)
draw.text((160, 860), "Ver Demo", font=font_xs, fill=WHITE)
save(img, 6)

# ═══ SLIDE 7: CTA ═══
img, draw = create_slide()
add_glow(draw, W//2, 400, BLUE, 350)
center_text(draw, 100, "A2K DIGITAL STUDIO", font_bold, GRAY)
draw.rounded_rectangle([W//2-30, 175, W//2+30, 179], radius=2, fill=BLUE)
center_text(draw, 220, "Tu bot empresarial", font_huge, WHITE)
center_text(draw, 360, "listo en dias", font_huge, BLUE)
center_text(draw, 510, "Automatiza Telegram hoy", font_sub, GRAY)

# Big blue button
bw, bh = 500, 80
bx, by = (W-bw)//2, 600
draw.rounded_rectangle([bx, by, bx+bw, by+bh], radius=40, fill=BLUE)
bbox = draw.textbbox((0,0), "Solicitar Info", font=font_bold)
tw = bbox[2]-bbox[0]
draw.text(((W-tw)//2, by+15), "Solicitar Info", font=font_bold, fill=WHITE)

center_text(draw, 730, "@zync_shop_bot  |  +58 416-411-7331", font_xs, GRAY)
center_text(draw, 780, "a2kdigitalstudio2025@gmail.com", font_xs, GRAY)
save(img, 7)

print("\nAll 7 Telegram Bot slides generated!")
