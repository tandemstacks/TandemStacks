# -*- coding: utf-8 -*-
# Logo de SantiStacks: cuadrado naranja industrial con una "S" blanca armada con bloques apilados
# (tres barras horizontales unidas por dos verticales, estilo bloque/estantería).
# Salida: santistacks-logo.png (256) y santistacks.ico (16-256 px).
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

# "S" de bloques: 3 barras (arriba, medio, abajo) + 2 uniones (izquierda arriba, derecha abajo)
g = 112          # grosor de barra
x0, x1 = 200, N - 200
y_top, y_mid, y_bot = 190, 190 + 2 * g + 40, 190 + 4 * g + 80
r = 14
def bloque(box, fill=BLANCO):
    # sombra corta hacia abajo-derecha para el efecto apilado
    d.rounded_rectangle((box[0] + 16, box[1] + 16, box[2] + 16, box[3] + 16), radius=r, fill=SOMBRA)
    d.rounded_rectangle(box, radius=r, fill=fill)
bloque((x0, y_bot, x1, y_bot + g))                    # abajo
bloque((x1 - g, y_mid, x1, y_bot + g))                # unión derecha (medio -> abajo)
bloque((x0, y_mid, x1, y_mid + g))                    # medio
bloque((x0, y_top, x0 + g, y_mid + g))                # unión izquierda (arriba -> medio)
bloque((x0, y_top, x1, y_top + g))                    # arriba

png = img.resize((256, 256), Image.LANCZOS)
png.save(os.path.join(BASE, "santistacks-logo.png"))
png.save(os.path.join(BASE, "santistacks.ico"), sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
print("ok")
