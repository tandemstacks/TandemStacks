# SantiStacks — notas para trabajar en este proyecto

App de escritorio para Windows que junta todas las bibliotecas de juegos (Steam, Epic, EA, Xbox / Game Pass, Riot, Battle.net, Rockstar, Ubisoft) en una pantalla. Open source (MIT), gratis para la comunidad. Repo: https://github.com/rullans/SantiStacks (dueño: `rullans`). Idioma del código, comentarios, UI y commits: **español rioplatense**.

Nació el 01/11/2026 como versión "para repartir" de una app personal (Santisteam, en `Proyectos IA\things IA\Chequeo PC`), que sigue existiendo aparte con la lista de juegos cargada a mano. **Este repo no comparte código con aquella**: acá todo se detecta solo en la PC de quien lo instale.

## Cómo está armado

- `SantiStacks.pyw`: punto de entrada → `santistacks.app.main()`.
- `santistacks/paths.py`: carpetas y config. Config en `%APPDATA%\SantiStacks\config.json`; portadas, caché y `biblioteca.html` en `%LOCALAPPDATA%\SantiStacks`. Nada se escribe junto al programa. `ASSETS` apunta a `assets/` (o a `sys._MEIPASS/assets` dentro del exe).
- `santistacks/detect.py`: detección de los 8 launchers (registro + rutas típicas), color, URI para abrirlos, página de descarga y nombres de sus procesos. La config puede pisar cualquier ruta (`launchers: {"Steam": {"exe": ...}}`).
- `santistacks/steam.py`: usuario (de `loginusers.vdf`), instalados (appmanifest de todas las bibliotecas), biblioteca completa (Web API `GetOwnedGames`, necesita clave del usuario; sin clave solo instalados), fichas (`appdetails` + SteamSpy, caché 30 días en `cache/steam/<appid>.json`), y `buscar_appid()` para juegos de otras tiendas (coincidencia ≥ 0.92 y misma primera palabra; caché en `cache/busquedas.json`).
- `santistacks/stores.py`: Epic (catálogo `catcache.bin` = biblioteca completa + manifiestos `.item` = instalados, sin DLC ni extras), EA (Programas instalados con editor Electronic Arts; lanza el exe de `DisplayIcon`), Xbox (GamingServices + `Get-AppxPackage` por PowerShell; lanza `shell:AppsFolder\...`), Riot (catálogo fijo de 5 gratis; instalado = carpeta del `product_settings.yaml`; lanza `RiotClientServices.exe --launch-product=X --launch-patchline=live`, que también instala), Battle.net (7 gratis fijos + pagos solo si están instalados, por registro `Blizzard Entertainment`; lanza `battlenet://<código>`), Rockstar (títulos por los `manifest_<código>_*.xml` que baja el launcher en `%LOCALAPPDATA%\Rockstar Games\Launcher`; sus `.dat` están cifrados), Ubisoft (claves `Uplay Install <id>`; lanza `uplay://launch/<id>/0`).
- `santistacks/covers.py`: **las portadas son links, no se descargan** (decisión del dueño 01/11/2026, para que la app no pese). Orden: incluida en `assets/covers/` (solo Riot y Battle.net, que no tienen links fijos; `file:///`) → link del catálogo de Epic → Steam: link exacto de `IStoreBrowseService/GetItems` (público, de a 100 appids; los juegos nuevos usan `<hash>/library_capsule.jpg`), y si todavía no se pidió, `library_600x900.jpg` por appid o `steam_hint` (sirve también para Rockstar/EA) → Xbox: póster de `displaycatalog.mp.microsoft.com` por PackageFamilyName (link guardado en `cache/portadas.json`). Si un link falla, la plantilla (`sinPortada`) prueba `header.jpg` de Steam y si no, nombre sobre color. El visor corre con `private_mode=False` y `storage_path=%LOCALAPPDATA%\SantiStacks\visor` para que su caché de imágenes persista. Al arrancar se borra la carpeta `covers` vieja de versiones anteriores.
- `santistacks/watch.py`: al lanzar un juego anota qué launchers estaban abiertos; detecta fin del juego (Steam: `HKCU\Software\Valve\Steam\RunningAppID`; otros: ningún proceso dentro de la carpeta del juego) y cierra **solo los launchers que abrió ese lanzamiento** (Steam con `steam.exe -shutdown`, el resto terminate/kill con psutil). Si el juego no arranca en 4 min no toca nada. Regla del dueño: nada corriendo al pedo.
- `santistacks/build.py`: inyecta `window.JUEGOS/DISCOS/TIENDAS/CONF/ESTADO/LOGO` en `assets/template.html` y escribe `biblioteca.html`. `publico()` filtra lo que ve la página (sin rutas ni comandos).
- `santistacks/app.py`: `Nucleo` (escaneo en 2 fases: rápida sin red → fichas/portadas en 4 hilos publicando cada 8 s; vigilancia cada 12 s de manifiestos/registro para reescanear si algo se instala o desinstala; aviso de versión nueva por `api.github.com/repos/<repo>/releases/latest`, 1 vez por día) y `Api` (lo que llama la página: `datos`, `estado`, `config`, `guardar_config`, `reescanear`, `version_nueva`, `abrir_url`, `abrir_datos`, `accion`). Ventana pywebview (WebView2), título e `AppUserModelID` "SantiStacks", ícono vía pythonnet/WinForms.
- `assets/template.html`: toda la UI (CSS + JS sin frameworks). La página no se recarga: cada 4 s pide `estado()` y si cambió `version` pide `datos()` y re-renderiza manteniendo filtros. Primer arranque (`CONF.primer_arranque`) abre la Configuración con bienvenida. Juegos repetidos entre tiendas se agrupan por nombre normalizado en una tarjeta. Filtro de tiendas multiselección; "Instalados" se combina. Logos de tiendas: SVG inline de Simple Icons (Xbox dibujado a mano).
- Estética (pedida por el dueño): industrial, naranja `#ff6a00` + blanco, sin bordes, sombras, radios 3–5 px, fuente Bahnschrift, títulos en mayúsculas con barra naranja. Logo: `assets/hacer-logo.py` → `logo.png` / `icon.ico` (cuadrado naranja con una S de bloques).

## Agregado el 01/11/2026 (después de la v1.0.0, sin publicar todavía)

- Tarjeta por tienda: clic en la barra de tiendas abre logo grande + estado + Descargar/Abrir launcher + pasos; botón **Desvincular** (`cfg["desvinculadas"]`: oculta la tienda y sus juegos, no toca nada en la PC; se revierte desde Configuración → › de la tienda). El dueño pidió que las tarjetas de tienda NO ofrezcan desinstalar el launcher.
- Géneros en desplegable con checkboxes (Todos + multiselección, filtro OR).
- Desinstalar juegos de otras tiendas: `accion('desinstalar=<id>')` usa `g["uninstall"]` (Riot: `--uninstall-product`, Ubisoft: `uplay://uninstall/<id>`); si no hay, abre Aplicaciones instaladas de Windows.
- Menú del engranaje (arriba a la derecha): Configuración, **Modo oscuro** (`cfg["tema"]`, CSS `:root[data-tema="oscuro"]`), **Idioma** español/inglés (`cfg["idioma"]`; la UI usa el diccionario `TXT` y las guías `GUIA[idioma]` de la plantilla; cambiarlo borra la caché de fichas de Steam y reescanea), Carpeta de datos, **Desinstalar SantiStacks** (`unins000.exe` junto al exe; si no está instalado con el Setup avisa).
- **Quitar launchers del inicio de Windows** (Configuración → Inicio de Windows): `santistacks/inicio.py` busca launchers en `Run` (HKCU y HKLM) y los deshabilita como el Administrador de tareas (`StartupApproved\Run` = `03` + FILETIME); no borra nada. Nunca toca Riot Vanguard. Las de HKLM sin permisos se informan al usuario.
- `Api.preferencia(clave, valor)` guarda tema/idioma/cerrar_launchers sin reescanear (salvo idioma).

## Armar y publicar

- Requisitos: Python 3.12, `pip install -r requirements.txt pyinstaller`, Inno Setup 6 (`%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe` o Program Files (x86)).
- `.\build.ps1` → `dist\SantiStacks\SantiStacks.exe` y `installer\Output\SantiStacks-Setup-<versión>.exe` (~26 MB). PyInstaller loguea por stderr: el script no usa `$ErrorActionPreference = "Stop"` a propósito.
- Versión: solo en `santistacks/__init__.py` (`VERSION`); build.ps1 y el .iss la leen de ahí.
- Publicar: `git tag vX.Y.Z && git push origin vX.Y.Z && gh release create vX.Y.Z installer\Output\SantiStacks-Setup-X.Y.Z.exe --title "SantiStacks X.Y.Z" --notes "..."`. La app compara `tag_name` (sin la v) con `VERSION`.
- El instalador no está firmado: SmartScreen avisa la primera vez.

## Decisiones tomadas (no volver a discutir)

- Bibliotecas **automáticas sin logins**: Steam completa solo con clave Web API del usuario (se pide en Configuración, link a steamcommunity.com/dev/apikey); **Epic completa desde `C:\ProgramData\Epic\EpicGamesLauncher\Data\Catalog\catcache.bin`** (base64 de JSON que guarda el launcher; base = `mainGameItem.id` vacío, se filtran extras por nombre con `EPIC_NO_JUEGO`; portada `DieselGameBoxTall`; la URI `com.epicgames.launcher://apps/ns%3Aitem%3Aapp?action=launch` instala o juega); Riot y Battle.net = catálogo gratis + instalados; EA/Xbox/Ubisoft = solo instalados; Rockstar = manifiestos. Se descartó integrar logins de Epic/EA (frágil, mucho trabajo).
- Formato: instalador .exe (no portable). Publicación: GitHub público con releases y aviso de versión nueva.
- **Ubisoft = solo instalados, a propósito** (decisión del dueño 01/11/2026): `%LOCALAPPDATA%\Ubisoft Game Launcher\cache\ownership\*.vdat` y `configurations.vdat` están cifrados; no leer tokens de `ConnectSecureStorage.dat`. La app lo explica en la tarjeta de Ubisoft y cuando se filtra una tienda con 0 juegos.
- `steamcommunity.com/profiles/<id>/games?xml=1` ya no sirve para leer la biblioteca: no insistir.
- Epic GraphQL (`store.epicgames.com/graphql`) está detrás de Cloudflare: no sirve desde Python; usar el endpoint de contenido por slug.

## Pendientes / ideas

- Probar instalación limpia en otra PC (hasta ahora solo probado en la PC del dueño, Windows 11).
- El dueño todavía no cargó su clave Web API de Steam.
- Idioma de la UI: hoy solo español; `cfg["idioma"]` solo afecta las fichas de Steam.
- Posibles mejoras: portadas para juegos de Xbox sin Steam (hoy solo Minecraft incluida), leer biblioteca Xbox/Epic si aparece una forma simple, tema oscuro opcional.
