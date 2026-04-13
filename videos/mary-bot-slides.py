#!/usr/bin/env python3
"""Mary Bot Promotional Video Slides Generator"""
from PIL import Image, ImageDraw, ImageFont, ImageFilter
import os

W, H = 1920, 1080
OUT = "slides/mary"

# Colors
BG = (10, 10, 15)
GREEN = (0, 255, 136)
BLUE = (0, 136, 255)
RED = (255, 51, 85)
YELLOW = (255, 204, 0)
WHITE = (255, 255, 255)
GRAY = (136, 136, 153)
DARK_GREEN = (0, 80, 50)
CARD_BG = (18, 18, 26)

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
    x1, y1, x2, y2 = xy
    draw.rounded_rectangle(xy, radius=radius, fill=fill, outline=outline)

def center_text(draw, y, text, font, fill=WHITE):
    bbox = draw.textbbox((0,0), text, font=font)
    tw = bbox[2] - bbox[0]
    x = (W - tw) // 2
    draw.text((x, y), text, font=font, fill=fill)

def draw_badge(draw, x, y, text, color=GREEN):
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
add_glow(draw, W//2, H//2, RED, 300)
# Phone icon (simple)
px, py = W//2, 280
draw.rounded_rectangle([px-50, py-90, px+50, py+90], radius=20, outline=RED, width=4)
draw.line([px-20, py-50, px+20, py-50], fill=RED, width=3)
draw.line([px-10, py+30, px+10, py+30], fill=RED, width=2)
center_text(draw, 400, "Cuantas clientas perdiste hoy", font_big, WHITE)
center_text(draw, 500, "por no contestar?", font_big, RED)
center_text(draw, 620, "Cada llamada sin respuesta es una cita perdida.", font_sub, GRAY)
# Red line
draw.rounded_rectangle([W//2-100, 700, W//2+100, 704], radius=2, fill=RED)
save(img, 1)

# ═══ SLIDE 2: PROBLEM ═══
img, draw = create_slide()
add_glow(draw, W//2, 200, RED, 250)
center_text(draw, 120, "El problema real", font_big, RED)
center_text(draw, 220, "3", font_huge, RED)
center_text(draw, 360, "llamadas perdidas hoy", font_bold, GRAY)
# Pain cards
pains = [
    "Estabas ocupada atendiendo otra clienta",
    "Era fuera de tu horario de atencion",
    "Esa clienta llamo a otro salon"
]
icons = ["!", "Z", "$"]
cy = 460
for i, (pain, icon) in enumerate(zip(pains, icons)):
    draw_rounded_rect(draw, [200, cy, W-200, cy+70], 16, (255,51,85,20), RED)
    draw.ellipse([220, cy+10, 270, cy+60], fill=RED)
    draw.text((237, cy+15), icon, font=font_bold, fill=BG)
    draw.text((290, cy+16), pain, font=font_sub, fill=WHITE)
    cy += 100
save(img, 2)

# ═══ SLIDE 3: SOLUTION ═══
img, draw = create_slide()
add_glow(draw, W//2, 350, GREEN, 350)
# Mic icon
px, py = W//2, 200
draw.ellipse([px-55, py-55, px+55, py+55], fill=GREEN)
draw.rounded_rectangle([px-15, py-40, px+15, py+20], radius=8, fill=BG)
draw.rounded_rectangle([px-25, py+10, px+25, py+50], radius=8, fill=BG)
draw.line([px, py+50, px, py+70], fill=BG, width=4)
draw.line([px-20, py+70, px+20, py+70], fill=BG, width=4)
center_text(draw, 300, "MARY BOT", font_huge, GREEN)
center_text(draw, 450, "Tu recepcionista virtual con IA 24/7", font_bold, BLUE)
# Badges row
badges = ["IA Real", "Voz Natural", "WhatsApp", "24/7"]
total_w = sum(len(b)*18 + 50 for b in badges) + (len(badges)-1)*20
bx = (W - total_w) // 2
for b in badges:
    bbox = draw.textbbox((0,0), b, font=font_sm)
    tw = bbox[2]-bbox[0]
    draw_badge(draw, bx, 550, b, GREEN)
    bx += tw + 50 + 20
save(img, 3)

# ═══ SLIDE 4: HOW IT WORKS ═══
img, draw = create_slide()
add_glow(draw, W//2, H//2, BLUE, 250)
center_text(draw, 80, "Como funciona Mary Bot", font_big, BLUE)
center_text(draw, 145, "En vivo", font_sub, GREEN)

# Chat simulation
chat_y = 220
# Incoming call banner
draw_rounded_rect(draw, [200, chat_y, W-200, chat_y+80], 16, (0,255,136,15), GREEN)
draw.text((240, chat_y+12), "LLAMADA ENTRANTE", font=font_xs, fill=GREEN)
draw.text((240, chat_y+40), "+1 (305) 555-8821", font=font_sub, fill=WHITE)
draw.rounded_rectangle([W-420, chat_y+18, W-240, chat_y+62], radius=20, fill=GREEN)
draw.text((W-400, chat_y+22), "RESPONDIDA", font=font_xs, fill=BG)
chat_y += 110

# Chat bubbles
msgs = [
    ("client", "Hola! Quiero sacar cita para manicure"),
    ("mary", "Hola! Soy Mary, la asistente del salon."),
    ("mary", "Con gusto te ayudo. Que dia prefieres?"),
    ("client", "El martes a las 3pm"),
    ("mary", "Cita confirmada: martes 3:00 PM"),
]
for role, text in msgs:
    if role == "client":
        bx = W - 200 - len(text)*14 - 40
        draw_rounded_rect(draw, [bx, chat_y, W-200, chat_y+55], 16, CARD_BG, WHITE)
        draw.text((bx+20, chat_y+12), text, font=font_xs, fill=WHITE)
    else:
        draw_rounded_rect(draw, [200, chat_y, 200+len(text)*14+40, chat_y+55], 16, (0,255,136,15), GREEN)
        draw.text((220, chat_y+4), "MARY BOT", font=font_xs, fill=GREEN)
        draw.text((220, chat_y+28), text, font=font_xs, fill=WHITE)
    chat_y += 75

# Confirm banner
draw_rounded_rect(draw, [200, chat_y+20, W-200, chat_y+80], 16, (0,255,136,15), GREEN)
draw.text((260, chat_y+38), "Cita agendada automaticamente", font=font_sub, fill=GREEN)
save(img, 4)

# ═══ SLIDE 5: WHATSAPP ═══
img, draw = create_slide()
add_glow(draw, W//2, H//2, (37, 211, 102), 300)

# Phone mockup
px, py = W//2-250, 100
pw, ph = 500, 700
draw.rounded_rectangle([px, py, px+pw, py+ph], radius=40, fill=(17,17,24), outline=(51,51,68), width=3)
# Status bar
draw.rounded_rectangle([px, py, px+pw, py+45], radius=40, fill=(26,26,36))
draw.text((px+20, py+10), "9:41", font=font_xs, fill=GRAY)
draw.text((px+pw-80, py+10), "100%", font=font_xs, fill=GRAY)
# WA header
draw.rounded_rectangle([px, py+45, px+pw, py+105], radius=0, fill=(7,94,84))
draw.ellipse([px+15, py+55, px+55, py+95], fill=GREEN)
draw.text((px+30, py+60), "M", font=font_bold, fill=BG)
draw.text((px+70, py+58), "Mary Bot", font=font_sub, fill=WHITE)
draw.text((px+70, py+85), "en linea", font=font_xs, fill=(170,255,204))
# Chat content
draw.rounded_rectangle([px+15, py+120, px+pw-15, py+250], radius=12, fill=(31,44,51), outline=(0,255,136,40))
draw.text((px+30, py+135), "NUEVA CITA AGENDADA", font=font_xs, fill=GREEN)
draw.text((px+30, py+170), "Clienta: Maria Garcia", font=font_xs, fill=WHITE)
draw.text((px+30, py+195), "Servicio: Manicure", font=font_xs, fill=WHITE)
draw.text((px+30, py+220), "Dia: Martes 3:00 PM", font=font_xs, fill=WHITE)
draw.rounded_rectangle([px+15, py+270, px+pw-15, py+390], radius=12, fill=(31,44,51), outline=(0,136,255,40))
draw.text((px+30, py+285), "RESUMEN DE LLAMADA", font=font_xs, fill=BLUE)
draw.text((px+30, py+320), "Duracion: 1m 42s", font=font_xs, fill=WHITE)
draw.text((px+30, py+345), "Resultado: Confirmada", font=font_xs, fill=GREEN)

# Right side text
tx = W//2 + 80
draw.text((tx, 200), "Te avisamos por", font=font_big, fill=WHITE)
draw.text((tx, 300), "WhatsApp", font=font_big, fill=(37,211,102))
draw.text((tx, 400), "al instante", font=font_bold, fill=GREEN)
draw.text((tx, 500), "Tu siempre sabes que paso", font=font_sub, fill=GRAY)
draw.text((tx, 540), "sin revisar nada.", font=font_sub, fill=GRAY)
save(img, 5)

# ═══ SLIDE 6: ADMIN PANEL ═══
img, draw = create_slide()
center_text(draw, 60, "Panel de Control", font_big, GREEN)

# Panel header
draw_rounded_rect(draw, [100, 150, W-100, 230], 16, CARD_BG, GREEN)
draw.text((140, 168), "Panel de Mary Bot", font=font_bold, fill=WHITE)
draw.text((140, 210), "nail-bot-mary.web.app", font=font_xs, fill=GRAY)
draw.rounded_rectangle([W-320, 170, W-140, 210], radius=20, fill=(0,255,136,20), outline=GREEN)
draw.text((W-305, 178), "EN VIVO", font=font_xs, fill=GREEN)

# Stats cards
stats = [("47", "Llamadas semana", BLUE), ("23", "Citas agendadas", GREEN), ("0", "Perdidas", YELLOW)]
sx = 160
for num, label, color in stats:
    draw_rounded_rect(draw, [sx, 270, sx+480, 430], 16, CARD_BG, color)
    center_text_on_x = lambda t, f, c, cx=sx+240: draw.text(((2*cx - (draw.textbbox((0,0),t,font=f)[2]-draw.textbbox((0,0),t,font=f)[0]))//2, 310), t, font=f, fill=c)
    bbox = draw.textbbox((0,0), num, font=font_huge)
    tw = bbox[2] - bbox[0]
    draw.text(((2*(sx+240)-tw)//2, 295), num, font=font_huge, fill=color)
    bbox2 = draw.textbbox((0,0), label, font=font_sm)
    tw2 = bbox2[2] - bbox2[0]
    draw.text(((2*(sx+240)-tw2)//2, 400), label, font=font_sm, fill=GRAY)
    sx += 520

# Bar chart
draw_rounded_rect(draw, [100, 470, W-100, 750], 16, CARD_BG, (255,255,255,10))
draw.text((140, 490), "Llamadas por dia - esta semana", font=font_sub, fill=GRAY)
bars = [("L",60),("M",80),("X",45),("J",95),("V",75),("S",100, True),("D",30)]
bx = 200
for b in bars:
    label = b[0]
    h = b[1]
    featured = len(b) > 2
    color = GREEN if featured else BLUE
    bar_h = int(h * 2)
    by = 710 - bar_h
    draw.rounded_rectangle([bx, by, bx+80, 710], radius=6, fill=color)
    draw.text((bx+20, 720), label, font=font_xs, fill=GREEN if featured else GRAY)
    bx += 210
save(img, 6)

# ═══ SLIDE 7: FEATURES ═══
img, draw = create_slide()
center_text(draw, 60, "Todo lo que incluye Mary Bot", font_big, GREEN)

features = [
    ("24/7 Sin Descanso", "Atiende de noche, fines de semana y feriados", BLUE),
    ("IA Real", "Google Gemini 2.0 - Conversacion natural", GREEN),
    ("Voz Natural", "Suena como persona, no robot", (136,68,255)),
    ("WhatsApp Instantaneo", "Notificacion cada vez que se agenda", (37,211,102)),
    ("Panel de Control", "Estadisticas, historial y transcripciones", YELLOW),
    ("Lista en 72 Horas", "Configuramos todo sin que sepas nada de tech", RED),
]
positions = [(100,180,980,350), (940,180,1820,350), (100,380,980,550), (940,380,1820,550), (100,580,980,750), (940,580,1820,750)]
icons_shapes = ["phone", "brain", "mic", "msg", "chart", "clock"]
for i, ((feat, desc, color), (x1,y1,x2,y2)) in enumerate(zip(features, positions)):
    draw_rounded_rect(draw, [x1,y1,x2,y2], 16, CARD_BG, color)
    # Draw icon
    cx, cy = x1+40, y1+50
    draw.ellipse([cx-20,cy-20,cx+20,cy+20], fill=color)
    draw.text((cx-8, cy-12), str(i+1), font=font_xs, fill=BG)
    draw.text((x1+75, y1+30), feat, font=font_title, fill=color)
    draw.text((x1+75, y1+85), desc, font=font_xs, fill=GRAY)
save(img, 7)

# ═══ SLIDE 8: CTA ═══
img, draw = create_slide()
add_glow(draw, W//2, 400, GREEN, 350)
center_text(draw, 100, "A2K DIGITAL STUDIO", font_bold, GRAY)
# Green line
draw.rounded_rectangle([W//2-30, 175, W//2+30, 179], radius=2, fill=GREEN)
center_text(draw, 220, "Lista para nunca", font_huge, WHITE)
center_text(draw, 360, "perder una clienta?", font_huge, GREEN)
center_text(draw, 510, "Pidelo hoy y recupera tu inversion", font_sub, GRAY)
center_text(draw, 560, "con solo 5 clientas extra al mes", font_sub, GRAY)

# Big green button
bw, bh = 600, 80
bx, by = (W-bw)//2, 640
draw.rounded_rectangle([bx, by, bx+bw, by+bh], radius=40, fill=(37,211,102))
bbox = draw.textbbox((0,0), "Escribenos por WhatsApp", font=font_bold)
tw = bbox[2]-bbox[0]
draw.text(((W-tw)//2, by+15), "Escribenos por WhatsApp", font=font_bold, fill=WHITE)

center_text(draw, 760, "+58 416-411-7331  |  a2kdigitalstudio2025@gmail.com", font_xs, GRAY)
center_text(draw, 830, "La tecnologia que trabaja para ti", font_sm, (255,255,255,80))
save(img, 8)

print("\nAll 8 Mary Bot slides generated!")
