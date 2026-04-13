#!/usr/bin/env python3
"""
Generate 7 professional promo slides for "Bot WhatsApp Empresarial"
A2K Digital Studio — AI chatbot for WhatsApp Business
"""

import os
from PIL import Image, ImageDraw, ImageFont, ImageFilter

# === CONFIGURATION ===
W, H = 1920, 1080
BG_DARK = (10, 10, 15)
GREEN = (37, 211, 102)       # #25d366
GREEN_DARK = (18, 140, 78)   # #128c4e
GREEN_GLOW = (37, 211, 102, 60)
WHITE = (255, 255, 255)
GRAY = (136, 136, 153)
GRAY_DARK = (40, 40, 55)
CARD_BG = (20, 20, 30)
BUBBLE_IN = (40, 40, 55)     # incoming message
BUBBLE_OUT = (37, 211, 102)  # outgoing message

FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FONT_REG = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"

OUT_DIR = "/home/z/my-project/download/a2k-digital-studio/videos/slides/whatsapp/"
os.makedirs(OUT_DIR, exist_ok=True)


def get_font(path, size):
    try:
        return ImageFont.truetype(path, size)
    except:
        return ImageFont.load_default()


def rounded_rect(draw, xy, radius, fill=None, outline=None, width=1):
    """Draw a rounded rectangle."""
    x0, y0, x1, y1 = xy
    if fill:
        draw.rounded_rectangle(xy, radius=radius, fill=fill, outline=outline, width=width)
    else:
        draw.rounded_rectangle(xy, radius=radius, outline=outline, width=width)


def glow_circle(draw, cx, cy, r, color, alpha=40):
    """Draw a glow effect circle on a separate layer."""
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gdraw = ImageDraw.Draw(glow)
    for i in range(5, 0, -1):
        ri = r + i * 20
        a = max(5, alpha // (i * 2))
        c = (*color[:3], a)
        gdraw.ellipse([cx - ri, cy - ri, cx + ri, cy + ri], fill=c)
    return glow


def draw_whatsapp_phone(draw, cx, cy, scale=1.0):
    """Draw a stylized phone with WhatsApp elements."""
    s = scale
    # Phone body
    pw, ph = int(180 * s), int(340 * s)
    px, py = cx - pw // 2, cy - ph // 2
    draw.rounded_rectangle([px, py, px + pw, py + ph], radius=25, fill=(30, 30, 40), outline=(60, 60, 80), width=3)
    # Screen
    draw.rounded_rectangle([px + 10, py + 40, px + pw - 10, py + ph - 20], radius=15, fill=(15, 15, 20))
    # Status bar
    draw.rounded_rectangle([px + 10, py + 40, px + pw - 10, py + 75], radius=15, fill=GREEN_DARK)
    draw.rectangle([px + 10, py + 60, px + pw - 10, py + 75], fill=GREEN_DARK)
    # Header text
    f = get_font(FONT_BOLD, int(14 * s))
    draw.text((px + 30, py + 48), "A2K Bot", fill=WHITE, font=f)
    # Chat bubbles
    bw = int(120 * s)
    bh = int(35 * s)
    # Incoming
    draw.rounded_rectangle([px + 20, py + 95, px + 20 + bw, py + 95 + bh], radius=12, fill=BUBBLE_IN)
    f2 = get_font(FONT_REG, int(11 * s))
    draw.text((px + 30, py + 102), "Hola, necesito info", fill=WHITE, font=f2)
    # Outgoing
    draw.rounded_rectangle([px + pw - 20 - bw, py + 145, px + pw - 20, py + 145 + bh], radius=12, fill=BUBBLE_OUT)
    f3 = get_font(FONT_REG, int(11 * s))
    draw.text((px + pw - 20 - bw + 8, py + 152), "En que puedo ayudarle?", fill=WHITE, font=f3)
    # Incoming 2
    draw.rounded_rectangle([px + 20, py + 195, px + 20 + bw - 20, py + 195 + bh], radius=12, fill=BUBBLE_IN)
    draw.text((px + 30, py + 202), "Precio del plan?", fill=WHITE, font=f2)
    # Outgoing 2
    draw.rounded_rectangle([px + pw - 20 - bw, py + 245, px + pw - 20, py + 245 + bh], radius=12, fill=BUBBLE_OUT)
    draw.text((px + pw - 20 - bw + 8, py + 252), "Plan Pro: $49/mes", fill=WHITE, font=f3)
    # Typing indicator
    for i in range(3):
        tx = px + 30 + i * 15
        ty = py + 295
        draw.ellipse([tx, ty, tx + 10, ty + 10], fill=(80, 80, 100))


def draw_badge(draw, x, y, text, font):
    """Draw a badge/pill shape."""
    tw = draw.textlength(text, font=font)
    pw = int(tw + 40)
    ph = 44
    draw.rounded_rectangle([x - pw // 2, y, x + pw // 2, y + ph], radius=22, fill=(*GREEN_DARK, 180), outline=GREEN, width=2)
    draw.text((x - tw // 2, y + 11), text, fill=WHITE, font=font)


def draw_feature_card(draw, x, y, w, h, icon_text, title, desc):
    """Draw a feature card."""
    # Card background
    draw.rounded_rectangle([x, y, x + w, y + h], radius=16, fill=CARD_BG, outline=(40, 40, 55), width=2)
    # Icon circle
    ic = (x + w // 2, y + 40)
    draw.ellipse([ic[0] - 24, ic[1] - 24, ic[0] + 24, ic[1] + 24], fill=GREEN_DARK)
    fi = get_font(FONT_BOLD, 22)
    draw.text((ic[0] - fi.getlength(icon_text) // 2, ic[1] - 14), icon_text, fill=WHITE, font=fi)
    # Title
    ft = get_font(FONT_BOLD, 20)
    ttl = ft.getlength(title)
    draw.text((x + (w - ttl) // 2, y + 75), title, fill=WHITE, font=ft)
    # Description
    fd = get_font(FONT_REG, 15)
    dl = fd.getlength(desc)
    draw.text((x + (w - dl) // 2, y + 102), desc, fill=GRAY, font=fd)


def draw_stat_card(draw, x, y, w, h, number, label):
    """Draw a stat metric card."""
    draw.rounded_rectangle([x, y, x + w, y + h], radius=14, fill=(25, 25, 38), outline=(50, 50, 70), width=2)
    fn = get_font(FONT_BOLD, 42)
    nl = fn.getlength(number)
    draw.text((x + (w - nl) // 2, y + 18), number, fill=GREEN, font=fn)
    fl = get_font(FONT_REG, 17)
    ll = fl.getlength(label)
    draw.text((x + (w - ll) // 2, y + 72), label, fill=GRAY, font=fl)


def draw_chat_bubble(draw, x, y, text, is_outgoing=True, w=400, h=50):
    """Draw a WhatsApp-style chat bubble."""
    if is_outgoing:
        draw.rounded_rectangle([x, y, x + w, y + h], radius=14, fill=BUBBLE_OUT)
        ft = get_font(FONT_REG, 18)
        draw.text((x + 18, y + 14), text, fill=WHITE, font=ft)
    else:
        draw.rounded_rectangle([x, y, x + w, y + h], radius=14, fill=BUBBLE_IN)
        ft = get_font(FONT_REG, 18)
        draw.text((x + 18, y + 14), text, fill=WHITE, font=ft)


def draw_arrow(draw, x1, y1, x2, y2, color=GREEN):
    """Draw a downward arrow."""
    draw.line([(x1, y1), (x2, y2)], fill=color, width=4)
    # Arrowhead
    import math
    angle = math.atan2(y2 - y1, x2 - x1)
    al = 15
    for a in [angle + 2.6, angle - 2.6]:
        ax = x2 - al * math.cos(a)
        ay = y2 - al * math.sin(a)
        draw.line([(x2, y2), (ax, ay)], fill=color, width=4)


# ==========================================
# SLIDE 1 — INTRO
# ==========================================
def make_slide1():
    img = Image.new("RGBA", (W, H), (*BG_DARK, 255))
    draw = ImageDraw.Draw(img)
    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    odraw = ImageDraw.Draw(overlay)
    # Glow circles
    gc = glow_circle(odraw, W // 2, H // 2 - 60, 200, GREEN, 50)
    gc2 = glow_circle(odraw, W // 2 - 300, H // 2 + 100, 120, GREEN_DARK, 30)
    gc3 = glow_circle(odraw, W // 2 + 300, H // 2 + 100, 120, GREEN_DARK, 30)
    overlay = Image.alpha_composite(overlay, gc)
    overlay = Image.alpha_composite(overlay, gc2)
    overlay = Image.alpha_composite(overlay, gc3)
    img = Image.alpha_composite(img, overlay)
    draw = ImageDraw.Draw(img)
    # Phone
    draw_whatsapp_phone(draw, W // 2, H // 2 - 80, scale=1.2)
    # Main text
    ft = get_font(FONT_BOLD, 56)
    t = "Tu negocio contesta solo"
    draw.text(((W - ft.getlength(t)) // 2, H // 2 + 140), t, fill=WHITE, font=ft)
    ft2 = get_font(FONT_BOLD, 56)
    t2 = "con WhatsApp"
    tl2 = ft2.getlength(t2)
    # Draw "WhatsApp" in green
    tw_partial = ft2.getlength("con ")
    x_green = (W - tl2) // 2
    # Split: "con " in white, "WhatsApp" in green
    draw.text((x_green, H // 2 + 205), "con ", fill=WHITE, font=ft2)
    x_after = x_green + ft2.getlength("con ")
    draw.text((x_after, H // 2 + 205), "WhatsApp", fill=GREEN, font=ft2)
    # Subtitle
    fs = get_font(FONT_REG, 32)
    st = "Incluso mientras duermes"
    draw.text(((W - fs.getlength(st)) // 2, H // 2 + 285), st, fill=GRAY, font=fs)
    # Bottom accent line
    draw.rounded_rectangle([W // 2 - 80, H - 60, W // 2 + 80, H - 56], radius=3, fill=GREEN)
    img = img.convert("RGB")
    img.save(os.path.join(OUT_DIR, "slide_01_intro.png"), quality=95)
    print("  Slide 1 OK")


# ==========================================
# SLIDE 2 — PROBLEM
# ==========================================
def make_slide2():
    img = Image.new("RGBA", (W, H), (*BG_DARK, 255))
    draw = ImageDraw.Draw(img)
    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    odraw = ImageDraw.Draw(overlay)
    # Red-ish glow for problem
    gc = glow_circle(odraw, W // 2, H // 2, 250, (180, 50, 50), 25)
    overlay = Image.alpha_composite(overlay, gc)
    img = Image.alpha_composite(img, overlay)
    draw = ImageDraw.Draw(img)
    # Header icon
    draw.ellipse([W // 2 - 35, 160, W // 2 + 35, 230], outline=(200, 60, 60), width=4)
    fi = get_font(FONT_BOLD, 36)
    draw.text((W // 2 - fi.getlength("!") // 2, 173), "!", fill=(200, 60, 60), font=fi)
    # Title
    ft = get_font(FONT_BOLD, 50)
    t = "El problema:"
    draw.text(((W - ft.getlength(t)) // 2, 260), t, fill=(220, 80, 80), font=ft)
    ft2 = get_font(FONT_BOLD, 42)
    t2 = "Miles de mensajes sin respuesta"
    draw.text(((W - ft2.getlength(t2)) // 2, 325), t2, fill=WHITE, font=ft2)
    # Pain points
    pain_points = [
        ("Clientes preguntan precios", "y nadie responde a tiempo"),
        ("Quieren agendar citas", "pero pierden la paciencia"),
        ("Pedidos se pierden", "por falta de seguimiento"),
    ]
    fp = get_font(FONT_BOLD, 26)
    fd = get_font(FONT_REG, 22)
    start_y = 440
    for i, (title, desc) in enumerate(pain_points):
        y = start_y + i * 120
        # Card
        cw = 700
        cx = (W - cw) // 2
        draw.rounded_rectangle([cx, y, cx + cw, y + 95], radius=16, fill=(30, 20, 20), outline=(100, 50, 50), width=2)
        # Red dot
        draw.ellipse([cx + 25, y + 35, cx + 39, y + 49], fill=(200, 60, 60))
        # Text
        draw.text((cx + 55, y + 18), title, fill=WHITE, font=fp)
        draw.text((cx + 55, y + 55), desc, fill=GRAY, font=fd)
    # Bottom text
    fs = get_font(FONT_REG, 24)
    st = "¿Te suena familiar?"
    draw.text(((W - fs.getlength(st)) // 2, H - 80), st, fill=(200, 80, 80), font=fs)
    img = img.convert("RGB")
    img.save(os.path.join(OUT_DIR, "slide_02_problem.png"), quality=95)
    print("  Slide 2 OK")


# ==========================================
# SLIDE 3 — SOLUTION
# ==========================================
def make_slide3():
    img = Image.new("RGBA", (W, H), (*BG_DARK, 255))
    draw = ImageDraw.Draw(img)
    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    odraw = ImageDraw.Draw(overlay)
    # Big green glow
    gc = glow_circle(odraw, W // 2, 300, 300, GREEN, 60)
    gc2 = glow_circle(odraw, W // 2, 300, 150, GREEN, 40)
    overlay = Image.alpha_composite(overlay, gc)
    overlay = Image.alpha_composite(overlay, gc2)
    img = Image.alpha_composite(img, overlay)
    draw = ImageDraw.Draw(img)
    # Green bar at top
    draw.rounded_rectangle([0, 0, W, 8], radius=0, fill=GREEN)
    # Main title
    ft = get_font(FONT_BOLD, 72)
    t1 = "BOT WHATSAPP"
    draw.text(((W - ft.getlength(t1)) // 2, 140), t1, fill=WHITE, font=ft)
    ft2 = get_font(FONT_BOLD, 72)
    t2 = "EMPRESARIAL"
    tl2 = ft2.getlength(t2)
    # Draw in green
    draw.text(((W - tl2) // 2, 225), t2, fill=GREEN, font=ft2)
    # Subtitle
    fs = get_font(FONT_REG, 34)
    st = "IA que responde, vende y agenda por ti"
    draw.text(((W - fs.getlength(st)) // 2, 340), st, fill=GRAY, font=fs)
    # Badges row
    badges = ["Respuestas IA", "Catalogo", "Pedidos", "24/7"]
    fb = get_font(FONT_BOLD, 24)
    total_w = sum(fb.getlength(b) + 40 for b in badges) + 30 * (len(badges) - 1)
    bx = (W - total_w) // 2
    by = 430
    for badge in badges:
        bw = int(fb.getlength(badge) + 40)
        draw.rounded_rectangle([bx, by, bx + bw, by + 50], radius=25, fill=GREEN_DARK, outline=GREEN, width=2)
        draw.text((bx + 20, by + 12), badge, fill=WHITE, font=fb)
        bx += bw + 30
    # Phone mockup
    draw_whatsapp_phone(draw, W // 2, 680, scale=0.9)
    # Accent
    draw.rounded_rectangle([W // 2 - 60, H - 50, W // 2 + 60, H - 44], radius=3, fill=GREEN)
    img = img.convert("RGB")
    img.save(os.path.join(OUT_DIR, "slide_03_solution.png"), quality=95)
    print("  Slide 3 OK")


# ==========================================
# SLIDE 4 — HOW IT WORKS
# ==========================================
def make_slide4():
    img = Image.new("RGBA", (W, H), (*BG_DARK, 255))
    draw = ImageDraw.Draw(img)
    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    odraw = ImageDraw.Draw(overlay)
    gc = glow_circle(odraw, W // 2, H // 2, 300, GREEN, 25)
    overlay = Image.alpha_composite(overlay, gc)
    img = Image.alpha_composite(img, overlay)
    draw = ImageDraw.Draw(img)
    # Title
    ft = get_font(FONT_BOLD, 50)
    t = "Como funciona"
    draw.text(((W - ft.getlength(t)) // 2, 50), t, fill=WHITE, font=ft)
    # 4 steps
    steps = [
        ("1", "Cliente escribe", "por WhatsApp", "Hola, quiero info"),
        ("2", "La IA entiende y", "responde al instante", "Claro, el precio es..."),
        ("3", "Agenda citas", "automaticamente", "Cita confirmada: Lunes 10am"),
        ("4", "Procesa pedidos y", "envia al equipo", "Nuevo pedido #1234"),
    ]
    sx = 100
    sy = 160
    card_w = 400
    card_h = 260
    gap = 30
    total = len(steps) * card_w + (len(steps) - 1) * gap
    start_x = (W - total) // 2
    fs_num = get_font(FONT_BOLD, 44)
    fs_title = get_font(FONT_BOLD, 24)
    fs_sub = get_font(FONT_REG, 20)
    fs_chat = get_font(FONT_REG, 16)
    for i, (num, line1, line2, chat) in enumerate(steps):
        x = start_x + i * (card_w + gap)
        y = sy
        # Card
        draw.rounded_rectangle([x, y, x + card_w, y + card_h], radius=18, fill=CARD_BG, outline=(50, 50, 65), width=2)
        # Step number circle
        nc = (x + card_w // 2, y + 45)
        draw.ellipse([nc[0] - 28, nc[1] - 28, nc[0] + 28, nc[1] + 28], fill=GREEN_DARK, outline=GREEN, width=2)
        draw.text((nc[0] - fs_num.getlength(num) // 2, nc[1] - 18), num, fill=WHITE, font=fs_num)
        # Title
        draw.text((x + (card_w - fs_title.getlength(line1)) // 2, y + 85), line1, fill=WHITE, font=fs_title)
        draw.text((x + (card_w - fs_sub.getlength(line2)) // 2, y + 115), line2, fill=GRAY, font=fs_sub)
        # Chat bubble
        bw = card_w - 40
        bh = 50
        bx = x + 20
        by = y + 160
        if i % 2 == 0:
            draw.rounded_rectangle([bx, by, bx + bw, by + bh], radius=12, fill=BUBBLE_IN)
            draw.text((bx + 14, by + 15), chat, fill=(180, 180, 200), font=fs_chat)
        else:
            draw.rounded_rectangle([bx, by, bx + bw, by + bh], radius=12, fill=BUBBLE_OUT)
            draw.text((bx + 14, by + 15), chat, fill=WHITE, font=fs_chat)
        # Arrow between cards
        if i < len(steps) - 1:
            ax1 = x + card_w + 2
            ax2 = ax1 + gap - 4
            ay = sy + card_h // 2
            draw_arrow(draw, ax1, ay, ax2, ay, GREEN)
    # Bottom connector
    draw.rounded_rectangle([start_x, sy + card_h + 40, start_x + total, sy + card_h + 44], radius=2, fill=(40, 40, 55))
    # Footer
    ff = get_font(FONT_REG, 26)
    ft_text = "Proceso automatico, sin intervencion humana"
    draw.text(((W - ff.getlength(ft_text)) // 2, H - 90), ft_text, fill=GRAY, font=ff)
    img = img.convert("RGB")
    img.save(os.path.join(OUT_DIR, "slide_04_how.png"), quality=95)
    print("  Slide 4 OK")


# ==========================================
# SLIDE 5 — FEATURES GRID
# ==========================================
def make_slide5():
    img = Image.new("RGBA", (W, H), (*BG_DARK, 255))
    draw = ImageDraw.Draw(img)
    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    odraw = ImageDraw.Draw(overlay)
    gc = glow_circle(odraw, W // 2, H // 2 - 50, 350, GREEN, 20)
    overlay = Image.alpha_composite(overlay, gc)
    img = Image.alpha_composite(img, overlay)
    draw = ImageDraw.Draw(img)
    # Title
    ft = get_font(FONT_BOLD, 50)
    t = "Todo lo que necesitas"
    draw.text(((W - ft.getlength(t)) // 2, 45), t, fill=WHITE, font=ft)
    # Subtitle
    fs = get_font(FONT_REG, 26)
    st = "Funcionalidades completas para tu negocio"
    draw.text(((W - fs.getlength(st)) // 2, 108), st, fill=GRAY, font=fs)
    # 6 feature cards in 3x2 grid
    features = [
        ("24/7", "Atencion 24/7", "Siempre disponible"),
        ("IA", "IA Conversacional", "Respuestas naturales"),
        ("CAT", "Catalogo", "Tus productos en linea"),
        ("CAL", "Agenda de Citas", "Reserva automatica"),
        ("NOT", "Notificaciones", "Alertas en tiempo real"),
        ("ADM", "Panel Admin", "Dashboard completo"),
    ]
    cols = 3
    rows = 2
    cw = 520
    ch = 210
    gx = 40
    gy = 35
    total_w = cols * cw + (cols - 1) * gx
    total_h = rows * ch + (rows - 1) * gy
    sx = (W - total_w) // 2
    sy = 170
    for i, (icon, title, desc) in enumerate(features):
        r = i // cols
        c = i % cols
        x = sx + c * (cw + gx)
        y = sy + r * (ch + gy)
        draw_feature_card(draw, x, y, cw, ch, icon, title, desc)
    # Bottom line
    draw.rounded_rectangle([W // 2 - 80, H - 55, W // 2 + 80, H - 49], radius=3, fill=GREEN)
    img = img.convert("RGB")
    img.save(os.path.join(OUT_DIR, "slide_05_features.png"), quality=95)
    print("  Slide 5 OK")


# ==========================================
# SLIDE 6 — PANEL PREVIEW
# ==========================================
def make_slide6():
    img = Image.new("RGBA", (W, H), (*BG_DARK, 255))
    draw = ImageDraw.Draw(img)
    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    odraw = ImageDraw.Draw(overlay)
    gc = glow_circle(odraw, W // 2, 400, 250, GREEN, 20)
    overlay = Image.alpha_composite(overlay, gc)
    img = Image.alpha_composite(img, overlay)
    draw = ImageDraw.Draw(img)
    # Title
    ft = get_font(FONT_BOLD, 50)
    t = "Panel de administracion completo"
    draw.text(((W - ft.getlength(t)) // 2, 40), t, fill=WHITE, font=ft)
    # Dashboard mockup frame
    dash_x = 160
    dash_y = 120
    dash_w = W - 320
    dash_h = H - 200
    draw.rounded_rectangle([dash_x, dash_y, dash_x + dash_w, dash_y + dash_h], radius=20, fill=(18, 18, 25), outline=(45, 45, 60), width=2)
    # Top bar
    draw.rounded_rectangle([dash_x, dash_y, dash_x + dash_w, dash_y + 55], radius=20, fill=(25, 25, 35))
    draw.rectangle([dash_x, dash_y + 35, dash_x + dash_w, dash_y + 55], fill=(25, 25, 35))
    # Top bar dots
    for i, color in enumerate([(200, 60, 60), (200, 180, 50), (60, 200, 60)]):
        draw.ellipse([dash_x + 20 + i * 25, dash_y + 18, dash_x + 34 + i * 25, dash_y + 34], fill=color)
    # Top bar title
    fb = get_font(FONT_BOLD, 18)
    draw.text((dash_x + 110, dash_y + 16), "A2K WhatsApp Bot — Dashboard", fill=GRAY, font=fb)
    # Side bar
    draw.rounded_rectangle([dash_x, dash_y + 55, dash_x + 70, dash_y + dash_h], radius=0, fill=(22, 22, 32))
    # Side icons
    for i in range(6):
        iy = dash_y + 80 + i * 60
        if i == 0:
            draw.rounded_rectangle([dash_x + 8, iy - 5, dash_x + 62, iy + 40], radius=8, fill=GREEN_DARK)
        draw.ellipse([dash_x + 26, iy + 5, dash_x + 44, iy + 23], fill=GREEN if i == 0 else GRAY)
    # Stats cards
    stats = [
        ("500", "mensajes/semana"),
        ("120", "citas agendadas"),
        ("98%", "satisfaccion"),
        ("24/7", "disponibilidad"),
    ]
    scw = (dash_w - 100) // 4
    sch = 140
    scy = dash_y + 85
    for i, (num, label) in enumerate(stats):
        scx = dash_x + 90 + i * (scw + 20)
        draw_stat_card(draw, scx, scy, scw, sch, num, label)
    # Chart area
    chart_y = scy + sch + 40
    chart_h = dash_y + dash_h - chart_y - 30
    chart_w = (dash_w - 120) // 2
    # Left chart - bar chart
    draw.rounded_rectangle([dash_x + 90, chart_y, dash_x + 90 + chart_w, chart_y + chart_h], radius=14, fill=(22, 22, 32), outline=(40, 40, 55), width=1)
    fc = get_font(FONT_BOLD, 18)
    draw.text((dash_x + 110, chart_y + 12), "Mensajes por dia", fill=WHITE, font=fc)
    # Bars
    bar_data = [60, 80, 45, 90, 70, 85, 95, 75, 88, 65, 92, 78]
    bar_w = (chart_w - 60) // len(bar_data)
    max_h = chart_h - 70
    for i, val in enumerate(bar_data):
        bx = dash_x + 110 + i * bar_w
        bh_val = int(val * max_h / 100)
        by = chart_y + chart_h - 20 - bh_val
        draw.rounded_rectangle([bx + 4, by, bx + bar_w - 4, chart_y + chart_h - 20], radius=4, fill=GREEN_DARK)
        draw.rounded_rectangle([bx + 4, by, bx + bar_w - 4, by + 6], radius=4, fill=GREEN)
    # Right chart - recent conversations
    rx = dash_x + 110 + chart_w + 20
    draw.rounded_rectangle([rx, chart_y, rx + chart_w, chart_y + chart_h], radius=14, fill=(22, 22, 32), outline=(40, 40, 55), width=1)
    draw.text((rx + 20, chart_y + 12), "Conversaciones recientes", fill=WHITE, font=fc)
    # Mini chat items
    convos = [
        ("Maria Garcia", "Agendado: Lun 10am", True),
        ("Carlos Lopez", "Pedido #456 procesado", True),
        ("Ana Martinez", "Precio enviado", True),
        ("Pedro Ruiz", "En espera...", False),
    ]
    fr = get_font(FONT_REG, 15)
    fn2 = get_font(FONT_BOLD, 15)
    for i, (name, msg, ok) in enumerate(convos):
        cy = chart_y + 45 + i * 55
        draw.ellipse([rx + 20, cy + 4, rx + 36, cy + 20], fill=GREEN if ok else GRAY)
        draw.text((rx + 45, cy), name, fill=WHITE, font=fn2)
        draw.text((rx + 45, cy + 22), msg, fill=GRAY, font=fr)
    img = img.convert("RGB")
    img.save(os.path.join(OUT_DIR, "slide_06_panel.png"), quality=95)
    print("  Slide 6 OK")


# ==========================================
# SLIDE 7 — CTA
# ==========================================
def make_slide7():
    img = Image.new("RGBA", (W, H), (*BG_DARK, 255))
    draw = ImageDraw.Draw(img)
    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    odraw = ImageDraw.Draw(overlay)
    # Multiple glow effects
    gc = glow_circle(odraw, W // 2, 300, 350, GREEN, 50)
    gc2 = glow_circle(odraw, W // 2 - 400, 500, 150, GREEN_DARK, 20)
    gc3 = glow_circle(odraw, W // 2 + 400, 500, 150, GREEN_DARK, 20)
    overlay = Image.alpha_composite(overlay, gc)
    overlay = Image.alpha_composite(overlay, gc2)
    overlay = Image.alpha_composite(overlay, gc3)
    img = Image.alpha_composite(img, overlay)
    draw = ImageDraw.Draw(img)
    # Green top bar
    draw.rounded_rectangle([0, 0, W, 6], radius=0, fill=GREEN)
    # WhatsApp icon
    draw.ellipse([W // 2 - 55, 140, W // 2 + 55, 250], fill=GREEN)
    fi = get_font(FONT_BOLD, 52)
    # Draw a phone icon
    draw.rounded_rectangle([W // 2 - 18, 165, W // 2 + 18, 225], radius=5, fill=WHITE)
    draw.rounded_rectangle([W // 2 - 14, 175, W // 2 + 14, 220], radius=3, fill=GREEN)
    # Company name
    fc = get_font(FONT_BOLD, 36)
    ct = "A2K Digital Studio"
    draw.text(((W - fc.getlength(ct)) // 2, 280), ct, fill=WHITE, font=fc)
    # Main CTA
    ft = get_font(FONT_BOLD, 58)
    t = "Automatiza tu WhatsApp"
    draw.text(((W - ft.getlength(t)) // 2, 350), t, fill=WHITE, font=ft)
    ft2 = get_font(FONT_BOLD, 58)
    t2 = "hoy"
    draw.text(((W - ft2.getlength(t2)) // 2, 420), t2, fill=GREEN, font=ft2)
    # Green CTA button
    btn_w = 450
    btn_h = 75
    btn_x = (W - btn_w) // 2
    btn_y = 530
    # Button glow
    bgc = glow_circle(odraw := ImageDraw.Draw(overlay := Image.new("RGBA", (W, H), (0, 0, 0, 0))), W // 2, btn_y + btn_h // 2, 100, GREEN, 60)
    overlay = Image.alpha_composite(overlay, bgc)
    img = Image.alpha_composite(img, overlay)
    draw = ImageDraw.Draw(img)
    # Button
    draw.rounded_rectangle([btn_x, btn_y, btn_x + btn_w, btn_y + btn_h], radius=38, fill=GREEN, outline=(50, 230, 120), width=3)
    fb = get_font(FONT_BOLD, 32)
    bt = "Solicitar Info"
    draw.text((btn_x + (btn_w - fb.getlength(bt)) // 2, btn_y + 20), bt, fill=WHITE, font=fb)
    # Phone number
    fp = get_font(FONT_REG, 30)
    pt = "+58 416-411-7331"
    draw.text(((W - fp.getlength(pt)) // 2, 650), pt, fill=GRAY, font=fp)
    # WhatsApp badge
    fwb = get_font(FONT_BOLD, 22)
    wbt = "Escríbenos por WhatsApp"
    draw.text(((W - fwb.getlength(wbt)) // 2, 700), wbt, fill=GREEN, font=fwb)
    # Bottom accent
    draw.rounded_rectangle([W // 2 - 100, H - 40, W // 2 + 100, H - 34], radius=3, fill=GREEN)
    img = img.convert("RGB")
    img.save(os.path.join(OUT_DIR, "slide_07_cta.png"), quality=95)
    print("  Slide 7 OK")


# ==========================================
# MAIN
# ==========================================
if __name__ == "__main__":
    print("Generating WhatsApp Bot Promo Slides...")
    print()
    make_slide1()   # 4s intro
    make_slide2()   # 5s problem
    make_slide3()   # 5s solution
    make_slide4()   # 6s how it works
    make_slide5()   # 5s features
    make_slide6()   # 5s panel
    make_slide7()   # 5s cta
    print()
    print(f"All slides saved to: {OUT_DIR}")
    slides = sorted([f for f in os.listdir(OUT_DIR) if f.endswith(".png")])
    for s in slides:
        fp = os.path.join(OUT_DIR, s)
        size = os.path.getsize(fp)
        print(f"  {s}: {size / 1024:.0f} KB")
