# -*- coding: utf-8 -*-
# Punto de entrada de TasloStacks. Uso: pythonw TasloStacks.pyw  (o el .exe que arma build.ps1)
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from taslostacks.app import main

if __name__ == "__main__":
    main()
