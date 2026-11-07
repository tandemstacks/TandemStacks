# -*- coding: utf-8 -*-
"""Revisa que el JavaScript de assets/template.html no tenga errores de sintaxis (con Node, si está instalado).
Un error ahí deja la app trabada en la pantalla de carga, así que build.ps1 no arma nada si falla."""
import os, re, shutil, subprocess, sys, tempfile

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
node = shutil.which("node") or r"C:\Program Files\nodejs\node.exe"
if not os.path.exists(node):
    print("Node no está instalado: no se revisa el JavaScript")
    sys.exit(0)
html = open(os.path.join(RAIZ, "assets", "template.html"), encoding="utf-8").read()
js = "\n;\n".join(re.findall(r"<script>(.*?)</script>", html, re.S)).replace("/*DATA*/", "")
with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as f:
    f.write(js)
r = subprocess.run([node, "--check", f.name], capture_output=True, text=True)
os.remove(f.name)
if r.returncode:
    print(r.stderr.strip()[:1500])
    sys.exit(1)
print("JavaScript sin errores")
