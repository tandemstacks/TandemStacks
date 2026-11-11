# -*- coding: utf-8 -*-
"""Ajustes del driver de NVIDIA por juego (como el Panel de control de NVIDIA → Administrar configuración 3D → Programa).

Se usa la librería del propio driver (nvapi64.dll, perfiles "DRS"); no hace falta administrador.
Pedido del dueño (10/11/2026): que TandemStacks ajuste NVIDIA sola según lo que midió Pulso. Reglas:
- Solo lo aplica la persona con un botón, y siempre se guarda lo que había antes (botón Deshacer).
- Lo usa la escalera de ajustes (escalera.py): sacar el tope de FPS, caché de sombreadores sin límite.
- Nada de esto usa IA: son reglas fijas sobre los números de Pulso.
"""
import os, json, ctypes, datetime
from . import paths

RESPALDO = os.path.join(os.path.dirname(paths.CONFIG), "nvidia.json")  # junto a la config: lo que había antes de cada cambio

FPS_LIMITE = 0x10835002      # Frame Rate Limiter (0 = sin límite)
ENERGIA = 0x1057EB71         # Power management mode (1 = máximo rendimiento)
CACHE_SOMBREADORES = 0x00AC8497  # Shader disk cache maximum size (0xFFFFFFFF = sin límite)

NOMBRES = {FPS_LIMITE: "límite de FPS", ENERGIA: "modo de energía", CACHE_SOMBREADORES: "caché de sombreadores"}

# ---------- NVAPI ----------
_U = 2048  # NvAPI_UnicodeString: 2048 caracteres de 16 bits

class _Ajuste(ctypes.Structure):  # NVDRS_SETTING_V1
    _fields_ = [("version", ctypes.c_uint32), ("nombre", ctypes.c_wchar * _U), ("id", ctypes.c_uint32), ("tipo", ctypes.c_uint32),
                ("lugar", ctypes.c_uint32), ("esPredefinido", ctypes.c_uint32), ("predefinidoValido", ctypes.c_uint32),
                ("predefinido", ctypes.c_uint32), ("_p", ctypes.c_byte * 4096), ("valor", ctypes.c_uint32), ("_v", ctypes.c_byte * 4096)]

class _Perfil(ctypes.Structure):  # NVDRS_PROFILE_V1
    _fields_ = [("version", ctypes.c_uint32), ("nombre", ctypes.c_wchar * _U), ("gpu", ctypes.c_uint32),
                ("esPredefinido", ctypes.c_uint32), ("apps", ctypes.c_uint32), ("ajustes", ctypes.c_uint32)]

class _App(ctypes.Structure):  # NVDRS_APPLICATION_V3
    _fields_ = [("version", ctypes.c_uint32), ("esPredefinido", ctypes.c_uint32), ("nombre", ctypes.c_wchar * _U),
                ("amigable", ctypes.c_wchar * _U), ("launcher", ctypes.c_wchar * _U), ("enCarpeta", ctypes.c_wchar * _U),
                ("flags", ctypes.c_uint32)]

def _ver(est, n): return ctypes.sizeof(est) | (n << 16)

NO_ENCONTRADO = (-160, -161, -163)  # ajuste, perfil o programa que no existe

class _Sesion:
    """Abre la base de ajustes del driver; al salir la cierra (guardando solo si se pidió)."""
    _nv = None
    def __init__(self):
        if _Sesion._nv is None:
            _Sesion._nv = ctypes.WinDLL("nvapi64.dll")
            qi = _Sesion._nv.nvapi_QueryInterface; qi.restype = ctypes.c_void_p; qi.argtypes = [ctypes.c_uint]
            _Sesion._qi = qi
            self._f(0x0150E828)()  # Initialize
        self.h = ctypes.c_void_p()
        self.guardar = False
    def _f(self, i, *t):
        p = _Sesion._qi(i)
        if not p: raise OSError("el driver de NVIDIA no tiene la función %x" % i)
        return ctypes.CFUNCTYPE(ctypes.c_int, *t)(p)
    def __enter__(self):
        self._ok(self._f(0x0694D52E, ctypes.POINTER(ctypes.c_void_p))(ctypes.byref(self.h)), "abrir")
        self._ok(self._f(0x375DBD6B, ctypes.c_void_p)(self.h), "leer")
        return self
    def __exit__(self, *a):
        try:
            if self.guardar and not a[0]:
                self._ok(self._f(0xFCBC7E14, ctypes.c_void_p)(self.h), "guardar")
        finally:
            self._f(0xDAD9CFF8, ctypes.c_void_p)(self.h)
    @staticmethod
    def _ok(r, que):
        if r != 0: raise OSError("NVIDIA no dejó %s (código %d)" % (que, r))
    # perfiles
    def perfil_de(self, exe):
        """Perfil donde está el programa (predefinido de NVIDIA o uno nuestro). None si no está en ninguno."""
        hp, app = ctypes.c_void_p(), _App(version=_ver(_App, 3))
        r = self._f(0xEEE566B2, ctypes.c_void_p, ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(_App))(
            self.h, exe, ctypes.byref(hp), ctypes.byref(app))
        if r in NO_ENCONTRADO: return None
        self._ok(r, "buscar el juego")
        return hp
    def perfil_por_nombre(self, nombre):
        hp = ctypes.c_void_p()
        r = self._f(0x7E4A9A0B, ctypes.c_void_p, ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_void_p))(self.h, nombre, ctypes.byref(hp))
        if r in NO_ENCONTRADO: return None
        self._ok(r, "buscar el perfil")
        return hp
    def crear_perfil(self, nombre, exe):
        hp, p = ctypes.c_void_p(), _Perfil(version=_ver(_Perfil, 1), nombre=nombre[:_U - 1])
        self._ok(self._f(0xCC176068, ctypes.c_void_p, ctypes.POINTER(_Perfil), ctypes.POINTER(ctypes.c_void_p))(
            self.h, ctypes.byref(p), ctypes.byref(hp)), "crear el perfil")
        a = _App(version=_ver(_App, 3), nombre=exe, amigable=nombre[:_U - 1])
        self._ok(self._f(0x4347A9DE, ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(_App))(self.h, hp, ctypes.byref(a)), "sumar el juego al perfil")
        return hp
    def borrar_perfil(self, hp):
        self._ok(self._f(0x17093206, ctypes.c_void_p, ctypes.c_void_p)(self.h, hp), "borrar el perfil")
    def base(self):
        hp = ctypes.c_void_p()
        self._ok(self._f(0xDA8466A0, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p))(self.h, ctypes.byref(hp)), "leer el perfil general")
        return hp
    # ajustes
    def leer(self, hp, i):
        """(valor, puesto_por_el_usuario). (None, False) si el perfil no lo tiene."""
        s = _Ajuste(version=_ver(_Ajuste, 1))
        r = self._f(0x73BF8338, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32, ctypes.POINTER(_Ajuste))(self.h, hp, i, ctypes.byref(s))
        if r in NO_ENCONTRADO: return None, False
        self._ok(r, "leer un ajuste")
        return s.valor, (not s.esPredefinido) and s.lugar == 0  # puesto a mano en este perfil (no el valor de fábrica de NVIDIA)
    def poner(self, hp, i, valor):
        s = _Ajuste(version=_ver(_Ajuste, 1), id=i, tipo=0, valor=valor)  # tipo 0 = número
        self._ok(self._f(0x577DD202, ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(_Ajuste))(self.h, hp, ctypes.byref(s)), "cambiar un ajuste")
        self.guardar = True
    def sacar(self, hp, i):
        r = self._f(0xE4A26362, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32)(self.h, hp, i)
        if r not in NO_ENCONTRADO: self._ok(r, "volver un ajuste a como estaba")
        self.guardar = True

_hay = []
def hay_nvidia():
    """Se averigua una vez por sesión de TandemStacks (abrir el driver carga toda su base de perfiles)."""
    if not _hay:
        try:
            with _Sesion(): _hay.append(True)
        except Exception:
            _hay.append(False)
    return _hay[0]

# ---------- respaldo ----------
def _respaldos():
    try:
        with open(RESPALDO, encoding="utf-8") as f: return json.load(f)
    except (OSError, ValueError):
        return {}

def _guardar_respaldos(d):
    with open(RESPALDO + ".tmp", "w", encoding="utf-8") as f: json.dump(d, f, ensure_ascii=False, indent=1)
    os.replace(RESPALDO + ".tmp", RESPALDO)

def aplicado(gid):
    """Lo que TandemStacks cambió para ese juego (o None)."""
    return _respaldos().get(gid)

def deshacer(gid):
    """Vuelve todo a como estaba antes del cambio de TandemStacks."""
    resp = _respaldos()
    reg = resp.get(gid)
    if not reg: return False
    with _Sesion() as s:
        hp = s.perfil_por_nombre(reg["perfilNuevo"]) if reg.get("perfilNuevo") else s.perfil_de(reg["exe"])
        base = None
        for a in reg["antes"]:
            donde = (base := base or s.base()) if a["global"] else hp
            if donde is None: continue
            if a["valor"] is None: s.sacar(donde, a["id"])  # no lo había tocado nadie: vuelve al valor de NVIDIA
            else: s.poner(donde, a["id"], a["valor"])
        if reg.get("perfilNuevo") and hp is not None:
            s.borrar_perfil(hp); s.guardar = True
    del resp[gid]
    _guardar_respaldos(resp)
    paths.log("nvidia deshecho:", reg.get("nombre"))
    return True

# ---------- de a un ajuste (para la escalera de ajustes) ----------
def _alinear(reg):
    """Cada ajuste del respaldo lleva su texto ("que"); los respaldos viejos tenían la lista aparte."""
    for a, q in zip(reg["antes"], reg.get("que", [])):
        a.setdefault("que", q)
    reg["que"] = [a.get("que", "") for a in reg["antes"]]
    return reg

def cambiar(gid, exe, nombre, cambios):
    """Suma cambios sin tocar los que ya estaban; lo de antes se guarda solo la primera vez que se toca cada ajuste."""
    resp = _respaldos()
    reg = _alinear(resp.get(gid) or {"exe": exe, "nombre": nombre, "fecha": "", "perfilNuevo": None, "antes": [], "que": []})
    reg["fecha"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    with _Sesion() as s:
        hp = s.perfil_por_nombre(reg["perfilNuevo"]) if reg.get("perfilNuevo") else s.perfil_de(exe)
        if hp is None:
            reg["perfilNuevo"] = "TandemStacks - %s" % nombre
            hp = s.perfil_por_nombre(reg["perfilNuevo"]) or s.crear_perfil(reg["perfilNuevo"], exe)
        base = None
        for c in cambios:
            donde = (base := base or s.base()) if c["global"] else hp
            ya = next((a for a in reg["antes"] if a["id"] == c["id"]), None)
            if ya: ya["que"] = c["que"]
            else:
                valor, del_usuario = s.leer(donde, c["id"])
                reg["antes"].append({"id": c["id"], "global": c["global"], "valor": valor if del_usuario else None, "que": c["que"]})
            s.poner(donde, c["id"], c["valor"])
    reg["que"] = [a["que"] for a in reg["antes"]]
    resp[gid] = reg
    _guardar_respaldos(resp)
    paths.log("nvidia cambiado:", nombre, "; ".join(c["que"] for c in cambios))
    return reg

def restaurar(gid, ajuste):
    """Vuelve un solo ajuste a como estaba antes de TandemStacks. Si era el último, se deshace todo (y el perfil nuevo)."""
    resp = _respaldos()
    reg = resp.get(gid)
    if not reg: return False
    reg = _alinear(reg)
    a = next((x for x in reg["antes"] if x["id"] == ajuste), None)
    if not a: return False
    if len(reg["antes"]) == 1: return deshacer(gid)
    with _Sesion() as s:
        donde = s.base() if a["global"] else (s.perfil_por_nombre(reg["perfilNuevo"]) if reg.get("perfilNuevo") else s.perfil_de(reg["exe"]))
        if donde is not None:
            if a["valor"] is None: s.sacar(donde, a["id"])
            else: s.poner(donde, a["id"], a["valor"])
    reg["antes"].remove(a)
    reg["que"] = [x["que"] for x in reg["antes"]]
    resp[gid] = reg
    _guardar_respaldos(resp)
    paths.log("nvidia restaurado:", reg.get("nombre"), a.get("que"))
    return True

def valor_puesto(gid, ajuste):
    """El ajuste que TandemStacks dejó puesto (o None)."""
    reg = aplicado(gid)
    if not reg: return None
    a = next((x for x in _alinear(reg)["antes"] if x["id"] == ajuste), None)
    if not a: return None
    try:
        with _Sesion() as s:
            donde = s.base() if a["global"] else (s.perfil_por_nombre(reg["perfilNuevo"]) if reg.get("perfilNuevo") else s.perfil_de(reg["exe"]))
            return s.leer(donde, ajuste)[0] if donde is not None else None
    except Exception:
        return None
