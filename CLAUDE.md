# TasloStacks — notas para trabajar en este proyecto

App de escritorio para Windows que junta todas las bibliotecas de juegos (Steam, Epic, GOG, EA, Xbox / Game Pass, Riot, Battle.net, Rockstar, Ubisoft, Amazon Games, itch.io) en una pantalla. Open source (MIT), gratis para la comunidad. Repo: https://github.com/taslostacks/TasloStacks (cuenta GitHub `taslostacks`, mail taslostacks@gmail.com; hasta la 1.1.2 se llamaba SantiStacks en rullans/SantiStacks). Idioma del código, comentarios, UI y commits: **español rioplatense**.

Nació el 01/11/2026 como versión "para repartir" de una app personal (Santisteam), que ya se borró: **TasloStacks es la única app y es un proyecto independiente** (no depende de ninguna otra carpeta). Acá todo se detecta solo en la PC de quien lo instale.

## Cómo está armado

- `TasloStacks.pyw`: punto de entrada → `taslostacks.app.main()`.
- `taslostacks/paths.py`: carpetas y config. Config en `%APPDATA%\TasloStacks\config.json`; portadas, caché y `biblioteca.html` en `%LOCALAPPDATA%\TasloStacks`. Nada se escribe junto al programa. `ASSETS` apunta a `assets/` (o a `sys._MEIPASS/assets` dentro del exe).
- `taslostacks/detect.py`: detección de los 11 launchers (registro + rutas típicas), color, URI para abrirlos, página de descarga y nombres de sus procesos. La config puede pisar cualquier ruta (`launchers: {"Steam": {"exe": ...}}`).
- `taslostacks/steam.py`: usuario (de `loginusers.vdf`), instalados (appmanifest de todas las bibliotecas), biblioteca completa (Web API `GetOwnedGames`, necesita clave del usuario; sin clave solo instalados), fichas (`appdetails` + SteamSpy, caché 30 días en `cache/steam/<appid>.json`), y `buscar_appid()` para juegos de otras tiendas (coincidencia ≥ 0.92 y misma primera palabra; caché en `cache/busquedas.json`).
- `taslostacks/stores.py`: Epic (catálogo `catcache.bin` = biblioteca completa + manifiestos `.item` = instalados, sin DLC ni extras), EA (Programas instalados con editor Electronic Arts; lanza el exe de `DisplayIcon`), Xbox (GamingServices + `Get-AppxPackage` por PowerShell; lanza `shell:AppsFolder\...`), Riot (catálogo fijo de 5 gratis; instalado = carpeta del `product_settings.yaml`; lanza `RiotClientServices.exe --launch-product=X --launch-patchline=live`, que también instala), Battle.net (7 gratis fijos + pagos solo si están instalados, por registro `Blizzard Entertainment`; lanza `battlenet://<código>`, que solo abre la página del juego; WoW se separa en una tarjeta por versión instalada según las carpetas `_retail_`/`_classic_`/`_classic_era_`/`_anniversary_` (`WOW_VERSIONES`) y lanza con `Battle.net.exe --exec="launch WoW|WoWC"`; Era y Aniversario no tienen código conocido y abren la página), Rockstar (títulos por los `manifest_<código>_*.xml` que baja el launcher en `%LOCALAPPDATA%\Rockstar Games\Launcher` + las portadas de la cuenta en `uipackages\assets\packages\public\<id>.jpg.cache`, que se reconocen por id fijo con la tabla `ROCK_PORTADAS` (hoy GTA V, Max Payne 3 y RDR2; sumar ids a medida que aparezcan); sus `.dat` están cifrados), Ubisoft (instalados por claves `Uplay Install <id>`, lanza `uplay://launch/<id>/0`; no instalados por los íconos `data\<id>.ico` que baja Ubisoft Connect junto a `upc.exe`, reconocidos con la tabla fija `UBI_ICONOS` (12 juegos; no hay lista pública de íconos: se suman a mano cuando avisan), lanzan `uplay://`), GOG (biblioteca = `LibraryReleases` `gog_*` + `GamePieces` de `C:\ProgramData\GOG.com\Galaxy\storage\galaxy-2.0.db`, se filtran extras/goodies; instalados por `HKLM\...\WOW6432Node\GOG.com\Games`; juega con `GalaxyClient.exe /command=runGame`, instala con `goggalaxy://openGameView/gog_<id>`), Amazon Games (solo instalados: `GameInstallInfo.sqlite`; `Entitlements.sqlite` está cifrado con DPAPI y no se lee a propósito; lanza `amazon-games://play/<id>`), itch.io (`%APPDATA%\itch\dbutler.db`: `download_keys` = biblioteca, `caves` = instalados; lanza `itch://caves/<id>/launch`). Las bases SQLite se copian a la caché antes de leerlas (están en uso).
- `taslostacks/fichas.py`: **cada ficha muestra datos de SU tienda** (pedido del dueño 01/11/2026; nada se completa con Steam, salvo una excepción pedida el 07/11/2026: si Epic no tiene descripción se muestra la de Steam, aclarada, en `descSteam`; `steam_hint` es solo para portadas). Se pide solo al abrir la ficha (`Api.ficha(ids)`), con caché en `cache/fichas/<idioma>/`. Steam: horas y última vez de `userdata/<id>/config/localconfig.vdf` (o `GetOwnedGames` si hay clave) en el escaneo; logros de `appcache/stats/UserGameStats*.bin` (KeyValues binario, local) y si no, `GetPlayerAchievements` (da 403 con perfil privado). Epic: `store-content-ipv4.ak.epicgames.com/api/<loc>/content/products/<slug del título>`, válido solo si su `namespace` = el del catálogo (≈60 % aciertan; si no, lo de `catcache.bin`, cuya descripción suele ser el título y se descarta). Xbox: `displaycatalog` lookup → ProductId → `products?bigIds=` (descripción, estudio, categorías, PEGI, puntuación de la Microsoft Store). EA/Rockstar/Ubisoft: nada extra; Riot/Battle.net: catálogo fijo. "Reseñas Steam" solo en tarjetas que incluyen Steam.
- `taslostacks/covers.py`: **las portadas son links, no se descargan** (decisión del dueño 01/11/2026, para que la app no pese). Orden: incluida en `assets/covers/` (solo Riot y Battle.net, que no tienen links fijos; `file:///`) → link del catálogo de Epic → Steam: link exacto de `IStoreBrowseService/GetItems` (público, de a 100 appids; los juegos nuevos usan `<hash>/library_capsule.jpg`), y si todavía no se pidió, `library_600x900.jpg` por appid o `steam_hint` (sirve también para Rockstar/EA) → Xbox: póster de `displaycatalog.mp.microsoft.com` por PackageFamilyName (link guardado en `cache/portadas.json`). Si un link falla, la plantilla (`sinPortada`) prueba `header.jpg` de Steam y si no, nombre sobre color. El visor corre con `private_mode=False` y `storage_path=%LOCALAPPDATA%\TasloStacks\visor` para que su caché de imágenes persista. Al arrancar se borra la carpeta `covers` vieja de versiones anteriores.
- `taslostacks/watch.py`: hilo de toda la sesión que mira cada 15 s (cada 5 s con un juego abierto) si hay un juego andando, se haya lanzado desde donde sea (Steam: `HKCU\Software\Valve\Steam\RunningAppID`; otros: un proceso dentro de la carpeta de un juego instalado, sin contar ayudantes como `crash_reporter`). Cuando deja de haber juegos, si duró 30 s o más, cierra **todos los launchers abiertos** (Steam con `steam.exe -shutdown`, el resto terminate/kill con psutil); si queda otro juego andando no toca nada. Nombres genéricos (`launcher.exe`, `agent.exe`, `butler.exe`) solo cuentan si la ruta es del launcher. Regla del dueño (07/11/2026): nada corriendo al pedo.
- **Nivel:** `watch.vigilar` suma el tiempo con algún juego abierto (cualquier tienda, con TasloStacks abierta) y `Nucleo.sumar_jugado` lo guarda en `%APPDATA%\TasloStacks\nivel.json`. Arranca de cero para todos, sin recompensas por ahora. Niveles del 1 al 100: horas para el nivel n = 2190 × ((n−1)/99)^1,5 (`NIV_HORAS`, `NIV_EXP` en la plantilla), o sea el 100 a las ~2190 h, casi 3 años jugando 2 h por día. Una medalla cada 5 niveles (bronce, plata, oro, platino y leyenda en el 100); tocando el nivel se ven todas (`verMedallas()`).
- **Descargas:** `steam.descargas()` lee `BytesDownloaded`/`BytesToDownload` de los appmanifest y la página muestra una barra arriba. Por ahora solo Steam.
- `taslostacks/build.py`: inyecta `window.JUEGOS/DISCOS/TIENDAS/CONF/ESTADO/LOGO` en `assets/template.html` y escribe `biblioteca.html`. `publico()` filtra lo que ve la página (sin rutas ni comandos).
- `taslostacks/app.py`: `Nucleo` (escaneo en 2 fases: rápida sin red → fichas/portadas en 4 hilos publicando cada 8 s; vigilancia cada 12 s de manifiestos/registro para reescanear si algo se instala o desinstala; aviso de versión nueva por `api.github.com/repos/<repo>/releases/latest`, como mucho 1 vez por hora) y `Api` (lo que llama la página: `datos`, `estado`, `config`, `guardar_config`, `reescanear`, `version_nueva`, `abrir_url`, `abrir_datos`, `accion`). Ventana pywebview (WebView2), título e `AppUserModelID` "TasloStacks", ícono vía pythonnet/WinForms.
- `assets/template.html`: toda la UI (CSS + JS sin frameworks). La página no se recarga: cada 4 s pide `estado()` y si cambió `version` pide `datos()` y re-renderiza manteniendo filtros. Primer arranque (`CONF.primer_arranque`) abre la Configuración con bienvenida. Juegos repetidos entre tiendas se agrupan por nombre normalizado en una tarjeta. Filtro de tiendas multiselección; "Instalados" se combina. Logos de tiendas: SVG inline de Simple Icons (Xbox dibujado a mano).
- Estética (pedida por el dueño): industrial, naranja `#ff6a00` + blanco, sin bordes, sombras, radios 3–5 px, fuente Bahnschrift, títulos en mayúsculas con barra naranja. Logo: `assets/hacer-logo.py` → `logo.png` / `icon.ico` (cuadrado naranja con una S de bloques).

## No comprados (02/11/2026, publicado en la v1.3.4)

- Tercer grupo de la biblioteca, abajo de Instalados / No instalados: juegos de los **catálogos públicos de GOG, Steam y Xbox** que no tenés en ninguna tienda (mismo nombre normalizado = misma tarjeta, no se repite). Si está en varias tiendas, la tarjeta muestra sus logos y al tocarla se elige dónde abrirla.
- `scripts/catalogos.py` junta `catalog.gog.com/v1/catalog`, los 10.000 más jugados de Steam (SteamSpy `request=all`, 1 página por minuto) y PC Game Pass (`catalog.gamepass.com/sigls` + `displaycatalog`) → `docs/catalogo/todos.json` (`t`, `c`, `st: {GOG: [id, slug], Steam: appid, Xbox: id}`; ~14.500 juegos, 2,6 MB), publicado con la landing. Tarda ~12 min.
- Al abrir, la app rehace `biblioteca.html` si cambió la huella de la plantilla (`cache/plantilla.txt`): antes mostraba la pantalla de la versión anterior. `.github/workflows/catalogos.yml` lo rehace los lunes; **todavía no está subido**: el token de `gh` no tiene permiso `workflow` (`gh auth refresh -s workflow`).
- **Sin juegos +18 por contenido sexual** (regla del dueño, 07/11/2026): `catalogos.py` saca los que GOG marca `nsfw`/`hentai` y los que Steam marca con avisos de contenido 3 o 4 (se pregunta solo por los que SteamSpy etiqueta como dudosos; respuestas guardadas en `docs/catalogo/steam_adultos.json`). Marcado en una tienda = se va de todas. No toca la biblioteca de cada usuario: lo que compró sigue apareciendo.
- **Precios** (`taslostacks/precios.py`): solo de la página de 24 que se ve, en el país de Windows (`GetUserDefaultGeoName`). Steam: `IStoreBrowseService/GetItems` (ya viene escrito en la moneda local); GOG: `api.gog.com/products/prices?ids=`; Xbox: `displaycatalog` con `market` (sin precio = Game Pass). 6 h en memoria; la página los olvida al plegar No comprados.
- `Api.catalogo(tienda)` lo baja de la landing (caché 1 día) y `Api.ver_en_tienda` abre `goggalaxy://openGameView/<id>` (Galaxy dice Comprar o Instalar) o la web de GOG.
- No instalados y No comprados arrancan plegados y se dibujan al abrirlos, de a 24, con tarjetas "Página anterior" y "Siguiente página" y abajo el número de página (`paginado()`). Cada grupo tiene su propio buscador por nombre, adentro (`BUSCA`). El catálogo se baja recién al desplegar No comprados; portadas con `loading=lazy` (son links, no ocupan disco).
- Ubisoft: no hay catálogo usable sin claves internas de la tienda (no usarlas). Próximas candidatas con catálogo público: Steam, Xbox.

## Agregado el 01/11/2026 (publicado en la v1.1.0)

- Tarjeta por tienda: clic en la barra de tiendas abre logo grande + estado + Descargar/Abrir launcher + pasos; botón **Desvincular** (`cfg["desvinculadas"]`: oculta la tienda y sus juegos, no toca nada en la PC; se revierte desde Configuración → › de la tienda). El dueño pidió que las tarjetas de tienda NO ofrezcan desinstalar el launcher.
- Géneros en desplegable con checkboxes (Todos + multiselección, filtro OR).
- Desinstalar juegos de otras tiendas: `accion('desinstalar=<id>')` usa `g["uninstall"]` (Riot: `--uninstall-product`, Ubisoft: `uplay://uninstall/<id>`); si no hay, abre Aplicaciones instaladas de Windows.
- Menú del engranaje (arriba a la derecha): Configuración, **Modo oscuro** (`cfg["tema"]`, CSS `:root[data-tema="oscuro"]`), **Idioma** español/inglés (`cfg["idioma"]`; la UI usa el diccionario `TXT` y las guías `GUIA[idioma]` de la plantilla; cambiarlo borra la caché de fichas de Steam y reescanea), Carpeta de datos, **Desinstalar TasloStacks** (`unins000.exe` junto al exe; si no está instalado con el Setup avisa).
- **Quitar launchers del inicio de Windows** (Configuración → Inicio de Windows): `taslostacks/inicio.py` busca launchers en `Run` (HKCU y HKLM) y los deshabilita como el Administrador de tareas (`StartupApproved\Run` = `03` + FILETIME); no borra nada. Nunca toca Riot Vanguard. Las de HKLM sin permisos se informan al usuario.
- `Api.preferencia(clave, valor)` guarda tema/idioma/cerrar_launchers sin reescanear (salvo idioma).

## Armar y publicar

- Requisitos: Python 3.12, `pip install -r requirements.txt pyinstaller`, Inno Setup 6 (`%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe` o Program Files (x86)).
- `.\build.ps1` → `dist\TasloStacks\TasloStacks.exe` y `installer\Output\TasloStacks-Setup-<versión>.exe` (~16 MB). PyInstaller loguea por stderr: el script no usa `$ErrorActionPreference = "Stop"` a propósito.
- Versión: solo en `taslostacks/__init__.py` (`VERSION`); build.ps1 y el .iss la leen de ahí.
- Publicar: `git tag vX.Y.Z && git push origin vX.Y.Z && gh release create vX.Y.Z installer\Output\TasloStacks-Setup-X.Y.Z.exe --title "TasloStacks X.Y.Z" --notes "..."`. La app compara `tag_name` (sin la v) con `VERSION`.
- El instalador no está firmado: SmartScreen avisa la primera vez.

## Pilares (regla del dueño)

El proyecto tiene **4 pilares** que se mantienen **al día juntos y enlazados entre sí**:

| Pilar | Dónde | Qué tiene |
|---|---|---|
| GitHub | github.com/taslostacks/TasloStacks | código, releases, README con links a los otros 3 |
| Landing | taslostacks.github.io/TasloStacks (`docs/`) | descarga (busca el último instalador sola), botones de Discord e Instagram, link a GitHub |
| Discord | discord.gg/CKqByMZ2m | #bienvenida (links), #anuncios (versiones), soporte |
| Instagram | @taslostacks | posts de novedades, link a la landing en la bio |

Checklist en cada cambio relevante:
- **Versión nueva:** release en GitHub → confirmar que la landing ofrece la nueva → anuncio en Discord #anuncios → post o historia en Instagram.
- **Nada a Discord ni a Instagram hasta que el dueño confirme que las funciones nuevas andan** (regla del 02/11/2026). Se dejan imagen y texto listos en `instagram/` y se espera su OK.
- **Cambia un dato** (nombre, logo, link, cantidad de tiendas, tamaño del instalador, requisitos): actualizarlo en los 4.
- **Cada post o historia de Instagram también va a Discord #anuncios** (misma imagen, texto es+en, link).
- **Cada pilar enlaza a los otros 3.** Si uno no se pudo actualizar, avisarlo.
- Material de Instagram en `instagram/` (fuera de git): `hacer-posts.py` arma las imágenes.

## Decisiones tomadas (no volver a discutir)

- **La app consume lo menos posible (regla del dueño, 07/11/2026).** Nada se carga hasta que se usa y lo que se deja de ver se suelta de la memoria: los grupos se dibujan al desplegarlos y se sueltan al plegarlos; el catálogo se lee al desplegar No comprados y se libera al plegarlo; minimizada, el visor baja su memoria y se suspende (`_minimizada` en `app.py`). Toda función nueva sigue este criterio.

- **Regla principal: la app funciona 100 % sin IA.** Es una aplicación normal: nada de llamadas a modelos de IA (Claude, OpenAI, etc.) ni funciones que dependan de una. Todo sale de archivos locales, el registro de Windows y APIs públicas de las tiendas. Claude solo se usa para programarla.

- Bibliotecas **automáticas sin logins**: Steam completa solo con clave Web API del usuario (se pide en Configuración, link a steamcommunity.com/dev/apikey); **Epic completa desde `C:\ProgramData\Epic\EpicGamesLauncher\Data\Catalog\catcache.bin`** (base64 de JSON que guarda el launcher; base = `mainGameItem.id` vacío, se filtran extras por nombre con `EPIC_NO_JUEGO`; portada `DieselGameBoxTall`; la URI `com.epicgames.launcher://apps/ns%3Aitem%3Aapp?action=launch` instala o juega); Riot y Battle.net = catálogo gratis + instalados; EA/Xbox/Ubisoft = solo instalados; Rockstar = manifiestos. Se descartó integrar logins de Epic/EA (frágil, mucho trabajo).
- Formato: instalador .exe (no portable). Publicación: GitHub público con releases y aviso de versión nueva.
- **Ubisoft = instalados + los reconocidos por ícono** (01/11/2026): `%LOCALAPPDATA%\Ubisoft Game Launcher\cache\ownership\*.vdat` y `configurations.vdat` están cifrados; no leer tokens de `ConnectSecureStorage.dat`. La caché web del launcher solo tiene el catálogo de Ubisoft+ (`ownership: 0`), no la cuenta. La app lo explica en la tarjeta de Ubisoft.
- `steamcommunity.com/profiles/<id>/games?xml=1` ya no sirve para leer la biblioteca: no insistir.
- Epic GraphQL (`store.epicgames.com/graphql`) está detrás de Cloudflare: no sirve desde Python; usar el endpoint de contenido por slug.

## Pendientes / ideas

- Probar instalación limpia en otra PC (hasta ahora solo probado en la PC del dueño, Windows 11).
- El dueño todavía no cargó su clave Web API de Steam.
- La prueba en otra PC la hacen amigos del dueño; el feedback llega por Discord (#errores) o WhatsApp.
- Posibles mejoras: leer biblioteca Xbox/Epic si aparece una forma simple.
