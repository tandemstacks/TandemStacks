# TandemStacks

**Todas tus bibliotecas de juegos en una sola pantalla.** Steam, Epic, GOG, EA, Xbox / Game Pass, Riot, Battle.net, Rockstar, Ubisoft, Amazon Games, itch.io y Google Play Juegos, con portadas, fichas, reseñas, lo que ocupa cada juego en el disco y botones de *Instalar* / *Jugar* que abren la tienda que corresponda.

Gratis y de código abierto (licencia MIT). Hecho para Windows 10/11.

**Página y descarga: https://tandemstacks.github.io/TandemStacks/**

Comunidad: [Discord](https://discord.gg/CKqByMZ2m) · [Instagram @tandemstacks](https://www.instagram.com/tandemstacks/)

![TandemStacks](assets/logo.png)

## Qué hace

- **Detecta solo** los launchers instalados y arma la biblioteca sin que tengas que configurar nada.
- **Steam**: juegos instalados siempre; con una clave Web API (gratis, 1 minuto) también toda tu biblioteca.
- **Riot y Battle.net**: catálogo gratis (LoL, VALORANT, Overwatch 2, Hearthstone…) más lo que tengas instalado.
- **Rockstar**: los juegos de tu cuenta (los lee del launcher) y lo instalado.
- **Epic**: toda tu biblioteca (la lee del catálogo que guarda el launcher, sin pedir login).
- **GOG e itch.io**: toda tu biblioteca (la leen de la base que guardan GOG Galaxy y la app de itch) y lo instalado.
- **EA, Xbox, Ubisoft, Amazon Games y Google Play Juegos**: lo instalado (sus bibliotecas no se pueden leer desde la PC; Ubisoft, Amazon y Google Play las guardan cifradas). De Xbox también se ven los juegos comprados en la Microsoft Store.
- Un juego que tenés en varias tiendas aparece **una sola vez**, con los logos de todas.
- Fichas (descripción, géneros, año, estudio, porcentaje de reseñas de la comunidad de Steam) se bajan solas y quedan en caché. Las portadas son links directos a cada tienda: la app no guarda imágenes.
- **No deja nada corriendo**: ningún launcher se abre al iniciar Windows por culpa de TandemStacks y, cuando terminás de jugar, se cierran todos los launchers abiertos, mientras TandemStacks esté abierto (configurable).
- Botón para **sacar los launchers del inicio de Windows** (los deshabilita como el Administrador de tareas).
- Menú ⚙ con modo oscuro, español / inglés y desinstalar.
- Barra de discos con cuánto ocupa cada juego (con miniaturas y un gráfico de torta) y aviso cuando queda poco espacio.
- Cada grupo (Instalados, No instalados, No comprados) tiene sus propios filtros: tiendas, géneros, orden y un buscador.
- **No comprados**: juegos de 8 tiendas (Steam, GOG, Xbox Game Pass, itch.io, Ubisoft, EA, Battle.net y Rockstar) que no tenés, con el **precio de cada tienda en tu moneda** y un interruptor para ver solo los que están **en oferta**. Sin juegos +18 por contenido sexual.
- **Nivel** del 1 al 100 según las horas que jugás con TandemStacks abierta, con una **medalla cada 5 niveles**, y barra de progreso de las descargas de Steam.
- **Pulso**: mide cada partida (FPS, 1 % más lento, tirones, placa, procesador, RAM, disco, red y ping), te dice **por qué hubo tirones** (disco cargando, procesador al tope, memoria de video llena, descargas…) y si algo está **mal configurado** (V-Sync, ventana, FPS de más). Guarda un historial de hasta 200 partidas por juego para comparar. Todo queda en tu PC.
- **Mejorar rendimiento paso a paso**: según lo que midió Pulso, te propone un cambio por partida (con NVIDIA lo aplica solo, con respaldo para deshacer) y compara si mejoró. Son reglas fijas, sin IA.
- **Relojes en vivo** de procesador, RAM, placa de video, disco y red; tocando cada uno se ve una gráfica grande con qué es cada línea y cuándo preocuparse.
- **Descargas en vivo** de Steam y Epic (con porcentaje, pausa y botón para cancelar) y de las demás tiendas por velocidad; el juego que se baja se va llenando de color en su tarjeta.
- **Cerrar tiendas** desde el menú ⚙, y los accesos directos que dejan las tiendas en el escritorio van a la papelera (configurable).
- Consume poco: lo que no está a la vista no se carga, y minimizada casi no usa memoria ni procesador.

## Instalar

Bajá el instalador (`TandemStacks-Setup-x.y.z.exe`) desde [Releases](../../releases/latest) y seguí los pasos. No hace falta Python ni nada más.

La primera vez se abre la **configuración**: revisá los launchers detectados, pegá la clave de Steam si querés la biblioteca completa y guardá.

### Clave Web API de Steam (opcional)

1. Entrá a <https://steamcommunity.com/dev/apikey> con tu cuenta.
2. En *Nombre de dominio* poné cualquier cosa (por ejemplo `tandemstacks`) y aceptá.
3. Copiá la clave en TandemStacks → ⚙ Configuración.
4. Tu perfil de Steam tiene que tener los **detalles de juegos** en público (Perfil → Editar perfil → Privacidad).

## Correr desde el código

```bash
pip install -r requirements.txt
pythonw TandemStacks.pyw
```

Armar el `.exe` y el instalador (necesita [PyInstaller](https://pyinstaller.org) e [Inno Setup 6](https://jrsoftware.org/isinfo.php)):

```powershell
.\build.ps1
```

Deja `dist\TandemStacks\` (programa) y `installer\Output\TandemStacks-Setup-<versión>.exe`.

## Dónde guarda las cosas

- Configuración: `%APPDATA%\TandemStacks\config.json`
- Portadas, caché de fichas y la página: `%LOCALAPPDATA%\TandemStacks\`

Borrar esas dos carpetas deja todo como recién instalado.

## Cómo está hecho

Python 3.12 + [pywebview](https://pywebview.flowrl.com/) (ventana con WebView2), [psutil](https://github.com/giampaolo/psutil) y [Pillow](https://python-pillow.org/). La interfaz es un HTML con CSS y JS sin frameworks. Fuentes de datos: manifiestos y registro de Windows de cada launcher, Steam Web API, Steam Store API, SteamSpy, tienda Epic (portadas). Logos de tiendas: [Simple Icons](https://simpleicons.org/).

## Donaciones

TandemStacks es sin fines de lucro y hoy no recibe plata. **Estamos buscando patrocinios** u otras formas de generar ingresos que nos permitan hacer donaciones, y **todo lo que entre se dona** a lugares que la comunidad propone y elige por votación en Discord. **Por ahora son de Montevideo (Uruguay)**, por logística: así podemos conocer de cerca el lugar que eligió la gente y dar garantías de a dónde va el dinero. La comunidad puede ser de cualquier país. Cada donación se publica con su monto y su comprobante.

## Contacto

- Correo: **tandemstacks@gmail.com** (patrocinios, marcas y propuestas)

Dudas, errores o ideas: abrí un [issue](../../issues).

## Aviso

TandemStacks no es un producto oficial de ninguna tienda ni está respaldado por ellas. Los nombres y logos de las tiendas y de los juegos son de sus dueños.

## Licencia

[MIT](LICENSE). Los nombres y logos de las tiendas son de sus dueños.
