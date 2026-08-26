"""
Genera la imagen de vista previa (Open Graph) de cada aviso: 1200x630, con el
color de la categoria, el titulo del aviso y el negocio. Como Talcadatos vive
de que la gente reenvie avisos por WhatsApp, esta tarjeta es lo primero que
ve la persona que recibe el link -- vale la pena que no sea solo texto plano.

Usa fuentes del sistema (macOS) por simplicidad de este entorno de
desarrollo; en produccion conviene empaquetar los .ttf como estaticos para
que la imagen se vea igual en cualquier servidor.
"""
import os
import io
from PIL import Image, ImageDraw, ImageFont

W, H = 1200, 630

FONT_CANDIDATES_BOLD = [
    "/System/Library/Fonts/Supplemental/Georgia Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
]
FONT_CANDIDATES_REGULAR = [
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
]


def _load_font(candidates, size):
    for path in candidates:
        if os.path.isfile(path):
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    return ImageFont.load_default()


def _mix(hex_color, target, amount):
    hex_color = hex_color.lstrip("#")
    r, g, b = (int(hex_color[i:i + 2], 16) for i in (0, 2, 4))
    tr, tg, tb = target
    return (
        int(r + (tr - r) * amount),
        int(g + (tg - g) * amount),
        int(b + (tb - b) * amount),
    )


def _draw_pin(draw, x, y, size, color):
    """Dibuja un pin simple con primitivas (evita depender de una fuente con emoji a color)."""
    r = size * 0.32
    cx, cy = x + size / 2, y + r
    draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=color)
    draw.polygon([(cx - r * 0.8, cy + r * 0.3), (cx + r * 0.8, cy + r * 0.3), (cx, y + size)], fill=color)
    hole_r = r * 0.34
    draw.ellipse((cx - hole_r, cy - hole_r, cx + hole_r, cy + hole_r), fill=(0, 0, 0, 90))


def _wrap(draw, text, font, max_width):
    words = text.split()
    lines, current = [], ""
    for word in words:
        trial = (current + " " + word).strip()
        if draw.textlength(trial, font=font) <= max_width:
            current = trial
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def generar(aviso):
    accent = aviso["color"] or "#5E7CE2"
    bg = _mix(accent, (20, 24, 20), 0.55)
    img = Image.new("RGB", (W, H), bg)
    draw = ImageDraw.Draw(img, "RGBA")

    circle_color = _mix(accent, (255, 255, 255), 0.12) + (255,)
    draw.ellipse((W - 480, -220, W + 260, 460), fill=circle_color)
    stripe_color = _mix(accent, (0, 0, 0), 0.25) + (255,)
    draw.rectangle((0, H - 18, W, H), fill=stripe_color)

    font_wordmark = _load_font(FONT_CANDIDATES_BOLD, 34)
    font_label = _load_font(FONT_CANDIDATES_REGULAR, 30)
    font_title = _load_font(FONT_CANDIDATES_BOLD, 64)
    font_footer = _load_font(FONT_CANDIDATES_REGULAR, 30)

    pad = 80
    _draw_pin(draw, pad, 58, 34, (255, 255, 255, 235))
    draw.text((pad + 44, 64), "TALCADATOS", font=font_wordmark, fill=(255, 255, 255, 235))
    draw.text((pad, 116), aviso["categoria_nombre"].upper() + "  ·  " + aviso["comuna"],
              font=font_label, fill=(255, 255, 255, 185))

    title_lines = _wrap(draw, aviso["titulo"], font_title, W - pad * 2)[:3]
    y = 240
    for line in title_lines:
        draw.text((pad, y), line, font=font_title, fill=(255, 255, 255, 255))
        y += 76

    footer = f'{aviso["negocio_nombre"]} · Contacto directo por WhatsApp'
    draw.text((pad, H - 96), footer, font=font_footer, fill=(255, 255, 255, 215))

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def generar_default():
    img = Image.new("RGB", (W, H), (29, 29, 31))
    draw = ImageDraw.Draw(img, "RGBA")
    draw.ellipse((W - 480, -220, W + 260, 460), fill=(0, 113, 227, 255))
    font_wordmark = _load_font(FONT_CANDIDATES_BOLD, 46)
    font_title = _load_font(FONT_CANDIDATES_BOLD, 58)
    font_label = _load_font(FONT_CANDIDATES_REGULAR, 30)
    _draw_pin(draw, 80, 212, 44, (255, 255, 255, 255))
    draw.text((80 + 56, 220), "TALCADATOS", font=font_wordmark, fill=(255, 255, 255, 255))
    draw.text((80, 300), "Pymes y emprendedores de Talca,", font=font_title, fill=(255, 255, 255, 255))
    draw.text((80, 370), "a un WhatsApp de distancia.", font=font_title, fill=(255, 255, 255, 255))
    draw.text((80, 460), "Directorio de pymes de Talca", font=font_label, fill=(255, 255, 255, 190))
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()
