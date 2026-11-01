# TasloStacks

**Todas tus bibliotecas de juegos en una sola pantalla.** Steam, Epic, EA, Xbox / Game Pass, Riot, Battle.net, Rockstar y Ubisoft, con portadas, fichas, reseñas, lo que ocupa cada juego en el disco y botones de *Instalar* / *Jugar* que abren la tienda que corresponda.

Gratis y de código abierto (licencia MIT). Hecho para Windows 10/11.

![TasloStacks](assets/logo.png)

## Qué hace

- **Detecta solo** los launchers instalados y arma la biblioteca sin que tengas que configurar nada.
- **Steam**: juegos instalados siempre; con una clave Web API (gratis, 1 minuto) también toda tu biblioteca.
- **Riot y Battle.net**: catálogo gratis (LoL, VALORANT, Overwatch 2, Hearthstone…) más lo que tengas instalado.
- **Rockstar**: los juegos de tu cuenta (los lee del launcher) y lo instalado.
- **Epic**: toda tu biblioteca (la lee del catálogo que guarda el launcher, sin pedir login).
- **EA, Xbox, Ubisoft**: lo instalado (sus bibliotecas no se pueden leer desde la PC; Ubisoft las guarda cifradas).
- Un juego que tenés en varias tiendas aparece **una sola vez**, con los logos de todas.
- Fichas (descripción, géneros, año, estudio, reseñas de Steam, Metacritic) se bajan solas y quedan en caché. Las portadas son links directos a cada tienda: la app no guarda imágenes.
- **No deja nada corriendo**: ningún launcher se abre al iniciar Windows por culpa de TasloStacks y, si abrís un juego desde acá, el launcher que se abrió se cierra cuando terminás (configurable).
- Botón para **sacar los launchers del inicio de Windows** (los deshabilita como el Administrador de tareas).
- Menú ⚙ con modo oscuro, español / inglés y desinstalar.
- Barra de discos con cuánto ocupa cada juego y aviso cuando queda poco espacio.
- Filtros por tienda (multiselección), género, instalados; búsqueda; orden por nombre, valoración, peso o año.

## Instalar

Bajá el instalador (`TasloStacks-Setup-x.y.z.exe`) desde [Releases](../../releases/latest) y seguí los pasos. No hace falta Python ni nada más.

La primera vez se abre la **configuración**: revisá los launchers detectados, pegá la clave de Steam si querés la biblioteca completa y guardá.

### Clave Web API de Steam (opcional)

1. Entrá a <https://steamcommunity.com/dev/apikey> con tu cuenta.
2. En *Nombre de dominio* poné cualquier cosa (por ejemplo `taslostacks`) y aceptá.
3. Copiá la clave en TasloStacks → ⚙ Configuración.
4. Tu perfil de Steam tiene que tener los **detalles de juegos** en público (Perfil → Editar perfil → Privacidad).

## Correr desde el código

```bash
pip install -r requirements.txt
pythonw TasloStacks.pyw
```

Armar el `.exe` y el instalador (necesita [PyInstaller](https://pyinstaller.org) e [Inno Setup 6](https://jrsoftware.org/isinfo.php)):

```powershell
.\build.ps1
```

Deja `dist\TasloStacks\` (programa) y `installer\Output\TasloStacks-Setup-<versión>.exe`.

## Dónde guarda las cosas

- Configuración: `%APPDATA%\TasloStacks\config.json`
- Portadas, caché de fichas y la página: `%LOCALAPPDATA%\TasloStacks\`

Borrar esas dos carpetas deja todo como recién instalado.

## Cómo está hecho

Python 3.12 + [pywebview](https://pywebview.flowrl.com/) (ventana con WebView2), [psutil](https://github.com/giampaolo/psutil) y [Pillow](https://python-pillow.org/). La interfaz es un HTML con CSS y JS sin frameworks. Fuentes de datos: manifiestos y registro de Windows de cada launcher, Steam Web API, Steam Store API, SteamSpy, tienda Epic (portadas). Logos de tiendas: [Simple Icons](https://simpleicons.org/).

## Contacto

Dudas, errores o ideas: abrí un [issue](../../issues).

## Licencia

[MIT](LICENSE). Los nombres y logos de las tiendas son de sus dueños.
