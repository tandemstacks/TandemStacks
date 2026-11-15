# -*- coding: utf-8 -*-
# Logo de TandemStacks (elegido el 15/11/2026 entre 10 propuestas): tres fichas apiladas en isométrico
# (stacks), dos azules arriba y una naranja abajo, sobre un cuadrado blanco con borde plata.
# Salida: logo.png (256) e icon.ico (16-256 px), junto a este script.
import os
from PIL import Image, ImageDraw

BASE = os.path.dirname(os.path.abspath(__file__))
N = 1024
AZUL, AZUL_OSC = (0, 107, 182, 255), (0, 78, 135, 255)
NARANJA, NARANJA_OSC = (245, 132, 38, 255), (200, 100, 20, 255)
PLATA, BLANCO = (190, 192, 194, 255), (255, 255, 255, 255)

img = Image.new("RGBA", (N, N), (0, 0, 0, 0))
d = ImageDraw.Draw(img)
d.rounded_rectangle((24, 24, N - 24, N - 24), radius=150, fill=PLATA)    # borde plata: que se vea sobre fondos blancos
d.rounded_rectangle((44, 44, N - 44, N - 44), radius=132, fill=BLANCO)

def oscurecer(c, k=30):
    return tuple(max(0, v - k) for v in c[:3]) + (255,)

def ficha(cy, arriba, lado):
    """Una ficha isométrica: cara de arriba y los dos lados (el derecho un poco más oscuro)."""
    cx, w, h, t = 512, 300, 150, 70
    d.polygon([(cx, cy - h), (cx + w, cy), (cx, cy + h), (cx - w, cy)], fill=arriba)
    d.polygon([(cx - w, cy), (cx, cy + h), (cx, cy + h + t), (cx - w, cy + t)], fill=lado)
    d.polygon([(cx + w, cy), (cx, cy + h), (cx, cy + h + t), (cx + w, cy + t)], fill=oscurecer(lado))

# de abajo hacia arriba, así cada ficha tapa a la de abajo
ficha(640, NARANJA, NARANJA_OSC)
ficha(500, AZUL, AZUL_OSC)
ficha(360, AZUL, AZUL_OSC)

png = img.resize((256, 256), Image.LANCZOS)
png.save(os.path.join(BASE, "logo.png"))
png.save(os.path.join(BASE, "icon.ico"), sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
print("ok")
