# -*- coding: utf-8 -*-
# Logo de TandemStacks: cuadrado naranja industrial con "TS" blanco armado con bloques apilados
# (barras rectas con una sombra corta, estilo bloque/estantería).
# Salida: logo.png (256) e icon.ico (16-256 px), junto a este script.
import os
from PIL import Image, ImageDraw

BASE = os.path.dirname(os.path.abspath(__file__))
N = 1024
NARANJA, OSCURO, BLANCO, SOMBRA = (255, 106, 0, 255), (205, 78, 0, 255), (255, 255, 255, 255), (170, 62, 0, 255)

img = Image.new("RGBA", (N, N), (0, 0, 0, 0))
d = ImageDraw.Draw(img)
d.rounded_rectangle((24, 24, N - 24, N - 24), radius=60, fill=NARANJA)
# banda inferior oscura (base industrial)
d.rectangle((24, N - 150, N - 24, N - 84), fill=OSCURO)
d.rounded_rectangle((24, N - 150, N - 24, N - 24), radius=60, fill=OSCURO)

g = 92                       # grosor de barra
ancho, sep = 300, 64         # ancho de cada letra y espacio entre las dos
y_top = 210
y_bot = y_top + 5 * g + 40   # alto total = 6 barras + aire
y_mid = (y_top + y_bot) // 2
r = 12
bloques = []
bloque = bloques.append  # se dibujan al final: primero todas las sombras, después el blanco (sin costuras)

# "T": barra de arriba + palo al centro
tx0 = (N - (2 * ancho + sep)) // 2; tx1 = tx0 + ancho
bloque((tx0 + (ancho - g) // 2, y_top, tx0 + (ancho + g) // 2, y_bot + g))  # palo
bloque((tx0, y_top, tx1, y_top + g))                                        # arriba

# "S": 3 barras + 2 uniones (izquierda arriba, derecha abajo)
sx0 = tx1 + sep; sx1 = sx0 + ancho
bloque((sx0, y_bot, sx1, y_bot + g))                    # abajo
bloque((sx1 - g, y_mid, sx1, y_bot + g))                # unión derecha
bloque((sx0, y_mid, sx1, y_mid + g))                    # medio
bloque((sx0, y_top, sx0 + g, y_mid + g))                # unión izquierda
bloque((sx0, y_top, sx1, y_top + g))                    # arriba

for x0, y0, x1, y1 in bloques:  # sombra corta hacia abajo-derecha para el efecto apilado
    d.rounded_rectangle((x0 + 14, y0 + 14, x1 + 14, y1 + 14), radius=r, fill=SOMBRA)
for box in bloques:
    d.rounded_rectangle(box, radius=r, fill=BLANCO)

png = img.resize((256, 256), Image.LANCZOS)
png.save(os.path.join(BASE, "logo.png"))
png.save(os.path.join(BASE, "icon.ico"), sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
print("ok")
