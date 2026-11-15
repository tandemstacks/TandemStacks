# -*- coding: utf-8 -*-
"""Lectura de MSI Afterburner (gratis, cualquier placa) si el usuario lo tiene abierto.

Afterburner deja lo que mide en una memoria compartida ("MAHMSharedMemory") que otros programas pueden leer.
Solo se lee: TandemStacks no lo abre, no lo deja prendido y no cambia nada de la placa.
Con esto hay temperatura del procesador y temperatura/vatios de placas AMD o Intel (nvidia-smi es solo NVIDIA).
Formato (SDK de Afterburner, v2.0): encabezado de 5 DWORD (firma 'MAHM', versión, tamaño del encabezado,
cantidad de entradas, tamaño de cada entrada); cada entrada: 5 textos de 260 bytes y después
dato, mínimo, máximo (float), flags, número de placa/núcleo y tipo de medida (DWORD).
"""
import os, struct, ctypes

FIRMA = 0x4D41484D  # 'MAHM'
SIN_DATO = 3.0e38   # Afterburner pone FLT_MAX cuando no tiene la medida
TODOS = 0xFFFFFFFF  # "núcleo" del total del procesador
# tipo de medida (MONITORING_SOURCE_ID_*) → nombre nuestro; (placa, total del procesador)
TIPOS = {0x00: "gpuTemp", 0x61: "gpuW", 0x10: "gpuFan", 0x80: "cpuTemp", 0x100: "cpuW"}
WEB = "https://www.msi.com/Landing/afterburner/graphics-cards"  # página oficial para bajarlo

_k = ctypes.windll.kernel32
_k.OpenFileMappingW.restype = ctypes.c_void_p
_k.MapViewOfFile.restype = ctypes.c_void_p
_k.MapViewOfFile.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_size_t]
_k.UnmapViewOfFile.argtypes = [ctypes.c_void_p]
_k.CloseHandle.argtypes = [ctypes.c_void_p]

def leer():
    """{gpuTemp, gpuW, gpuFan, cpuTemp, cpuW} con lo que haya, o None si Afterburner no está abierto.
    Se abre con OpenFileMapping (no la crea si no existe) y se suelta enseguida: ~0,1 ms."""
    h = _k.OpenFileMappingW(0x0004, False, "MAHMSharedMemory")  # FILE_MAP_READ
    if not h:
        return None
    p = None
    try:
        p = _k.MapViewOfFile(h, 0x0004, 0, 0, 0)
        if not p:
            return None
        firma, _ver, tam_enc, n, tam = struct.unpack("<5I", ctypes.string_at(p, 20))
        if firma != FIRMA or not n or tam < 1324 or n > 2000:
            return None
        out = {}
        for i in range(n):
            b = ctypes.string_at(p + tam_enc + i * tam + 1300, 24)
            dato, _mn, _mx, _fl, num, tipo = struct.unpack("<3f3I", b)
            clave = TIPOS.get(tipo)
            if not clave or clave in out or abs(dato) >= SIN_DATO:
                continue
            if clave.startswith("cpu"):
                if tipo == 0x80 and num != TODOS: continue  # la del procesador entero, no la de cada núcleo
            elif num != 0:
                continue  # solo la primera placa
            out[clave] = round(dato)
        return out or None
    except Exception:
        return None
    finally:
        if p: _k.UnmapViewOfFile(p)
        _k.CloseHandle(h)

def instalado():
    """¿Está MSI Afterburner en la PC? (para decir "abrilo" en vez de "bajalo")."""
    for base in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles")):
        if base and os.path.exists(os.path.join(base, "MSI Afterburner", "MSIAfterburner.exe")):
            return True
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\MSI\Afterburner"):
            return True
    except OSError:
        return False
