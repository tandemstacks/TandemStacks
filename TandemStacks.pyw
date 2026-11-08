# -*- coding: utf-8 -*-
# Punto de entrada de TandemStacks. Uso: pythonw TandemStacks.pyw  (o el .exe que arma build.ps1)
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from tandemstacks.app import main

if __name__ == "__main__":
    main()
