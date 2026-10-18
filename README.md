# Playlistr

**Tu biblioteca. Nuevas conexiones.** Una aplicación autohospedada para crear playlists en **Navidrome** a partir de géneros de artistas consultados en **MusicBrainz y Wikidata**, sin OpenRouter ni modelos generativos.

Interfaz en español, adaptable a móvil, con biblioteca, búsqueda de géneros, revisión de artistas, vista previa y guardado en Navidrome. Backend Python/FastAPI, SQLite y frontend HTML/CSS/JavaScript sin CDN, compilación ni dependencias de Node.

## Qué hace

- Conecta una cuenta de Navidrome mediante su API Subsonic/OpenSubsonic.
- Sincroniza álbumes y canciones, incluidos los artistas múltiples cuando el servidor los proporciona.
- Usa el MusicBrainz ID del artista si Navidrome lo conoce; en caso contrario, busca por nombre.
- Obtiene géneros con votos positivos del vocabulario de géneros de MusicBrainz. Si faltan, consulta el género `P136` de la entidad de Wikidata enlazada al artista.
- Conserva enlaces a las fuentes, fecha de consulta y votos de MusicBrainz.
- Deja las coincidencias ambiguas para revisión y permite corregir géneros manualmente.
- Filtra por uno o varios géneros, intervalo de años, exclusión de artista y cantidad de canciones; admite orden aleatorio.
- Crea en Navidrome **exactamente las canciones de la vista previa**, usando la cuenta conectada. No modifica tus archivos musicales ni playlists existentes.
- Conserva biblioteca, clasificaciones, correcciones, conexión cifrada e historial en `/data`.

**El género de un artista no es necesariamente el de todas sus canciones.** Esta aplicación no analiza audio y no promete clasificaciones infalibles. Muestra las fuentes y permite corregirlas. No usa resultados de Google: consulta APIs de datos musicales estructurados para evitar convertir fragmentos ambiguos de búsquedas en etiquetas. Las etiquetas originales de los archivos no se presentan como géneros verificados de internet.

## Instalar en Unraid, sin Docker Compose

La imagen está configurada para publicarse en **GitHub Container Registry**:

```text
ghcr.io/diegoshock/playlistr:latest
```

No necesitas Docker Compose, clonar el código ni compilar en Unraid. La descarga estará disponible cuando termine la primera publicación de GitHub Actions y el propietario establezca el paquete como **Public**. Consulta [Publicar la imagen en GHCR](#publicar-la-imagen-en-ghcr) para esos pasos iniciales; añadir un workflow no significa que la imagen ya esté publicada.

### Desde la interfaz de Unraid

1. Prepara una carpeta de datos dedicada. En la terminal de Unraid, ejecuta una sola vez:

   ```bash
   mkdir -p /mnt/user/appdata/playlistr
   chown 99:100 /mnt/user/appdata/playlistr
   chmod 700 /mnt/user/appdata/playlistr
   ```

   Si vienes de una instalación existente con otro usuario, detén primero Playlistr, respalda esa carpeta y adapta los permisos de sus archivos al UID/GID elegido. No borres ni regeneres `credentials.key`.

2. Ve a **Docker → Add Container**. Activa **Advanced View** si es necesario y configura:

   | Campo | Valor |
   | --- | --- |
   | Name | `playlistr` |
   | Repository | `ghcr.io/diegoshock/playlistr:latest` |
   | Network Type | `bridge` o la red personalizada de Navidrome |
   | WebUI | `http://[IP]:[PORT:8080]/` |
   | Extra Parameters | `--user 99:100 --security-opt=no-new-privileges --cap-drop=ALL` |
   | Puerto TCP | Contenedor `8080` → host `8088` |
   | Ruta de datos, lectura/escritura | Contenedor `/data` → host `/mnt/user/appdata/playlistr` |
   | Variable `PLAYLISTR_PASSWORD` | Tu contraseña de acceso, al menos 12 caracteres |
   | Variable `PLAYLISTR_SECURE_COOKIE` | `false` para HTTP en LAN; `true` si usas HTTPS |

   Añade puerto, ruta y variables mediante **Add another Path, Port, Variable, Label or Device**. Mantén **Privileged** desactivado. No se monta el socket de Docker.

3. Pulsa **Apply**. Unraid descargará la imagen y creará el contenedor. Abre **WebUI**, inicia sesión y conecta Navidrome en **Configuración**.
4. Para actualizar, usa **Check for Updates / Update** en Docker, conservando la ruta de datos. También puedes fijar un tag de versión publicado en lugar de `latest`.

La contraseña de Playlistr es independiente de la contraseña de Navidrome. El contenedor usa UID `99` y GID `100`, habituales en Unraid; adapta esos valores si tu servidor utiliza otros permisos.

### Plantilla de Unraid, opcional

El archivo [`unraid/playlistr.xml`](unraid/playlistr.xml) ya contiene estos campos. Puedes guardarlo como `/boot/config/plugins/dockerMan/templates-user/my-playlistr.xml` y seleccionarlo en **Docker → Add Container → Template → playlistr**. Si el repositorio es público y los cambios ya están en `main`, puedes descargarlo así:

```bash
mkdir -p /boot/config/plugins/dockerMan/templates-user
curl --fail --location --proto '=https' \
  https://raw.githubusercontent.com/diegoshock/docker-playlists/main/unraid/playlistr.xml \
  -o /boot/config/plugins/dockerMan/templates-user/my-playlistr.xml
```

No es una aplicación publicada en Community Applications: es una plantilla de usuario. También puedes configurar los mismos campos manualmente, sin descargar la plantilla.

### Conectar Navidrome

Usa la IP LAN de Unraid y el puerto publicado de Navidrome, por ejemplo `http://192.168.1.100:4533`. Si comparten una red Docker personalizada, también puedes usar `http://navidrome:4533`, donde `navidrome` es el nombre del otro contenedor en esa red. `localhost` dentro de Playlistr no apunta al contenedor de Navidrome.

En Playlistr, introduce URL, usuario y contraseña de Navidrome y pulsa **Probar conexión y guardar**, **Sincronizar biblioteca** y **Buscar géneros**.

Si el contenedor tiene `HTTP_PROXY`/`HTTPS_PROXY`, añade el nombre o IP de Navidrome a `NO_PROXY` para que el tráfico local no pase por el proxy. Si también existe `no_proxy` en minúsculas, mantenlo coherente. Ejemplo: `NO_PROXY=localhost,127.0.0.1,navidrome`.

## Publicar la imagen en GHCR

El workflow [`.github/workflows/publish.yml`](.github/workflows/publish.yml) ejecuta las pruebas y publica la imagen usando el `GITHUB_TOKEN` que GitHub Actions proporciona automáticamente, con permiso `packages: write`. **No necesitas añadir un PAT como secreto al workflow.**

- Un push a `main` actualiza `ghcr.io/diegoshock/playlistr:latest` y publica un tag `sha-<commit completo>`.
- Un tag SemVer como `v0.1.0` publica `ghcr.io/diegoshock/playlistr:0.1.0` y su tag de commit. Los tags de versión no cambian `latest`, que sigue a `main`.
- También puedes usar **Actions → Test and publish Playlistr → Run workflow**, seleccionando `main`.
- Los pull requests ejecutan pruebas, pero no publican imágenes.
- La construcción está configurada para `linux/amd64` (Unraid habitual) y `linux/arm64`.

Para la primera publicación:

1. Sube el código, incluido el workflow, a la rama `main` de este repositorio y habilita GitHub Actions si está deshabilitado.
2. Espera a que **Test and publish Playlistr** termine en verde. El resumen del job incluye el digest de la imagen y el enlace al paquete.
3. Abre [el paquete Playlistr](https://github.com/users/diegoshock/packages/container/package/playlistr), entra en **Package settings → Change visibility → Public** y confirma. **GHCR crea paquetes privados inicialmente, incluso si el repositorio es público.** Este cambio inicial permite que Unraid descargue sin un login de GitHub.
4. Comprueba la descarga desde una máquina sin sesión iniciada en GHCR:

   ```bash
   docker pull ghcr.io/diegoshock/playlistr:latest
   ```

Si el paquete ya existía y el workflow recibe `permission_denied: write_package`, vincúlalo a `diegoshock/docker-playlists` y permite acceso de Actions a ese repositorio desde los ajustes del paquete. La imagen incluye la etiqueta OCI `org.opencontainers.image.source` para asociar las publicaciones nuevas con su repositorio.

Una descarga con `denied` puede indicar que el paquete sigue privado. Un error `manifest unknown` puede indicar que el workflow aún no terminó o que no existe ese tag. Comprueba Actions y la visibilidad antes de cambiar las credenciales de Navidrome.

## Otras formas de ejecución

Docker directo, sin Compose, con la imagen publicada:

```bash
# Define PLAYLISTR_PASSWORD en el entorno de esta terminal antes de ejecutar.
docker run -d --name playlistr --restart unless-stopped \
  --user 99:100 --security-opt=no-new-privileges --cap-drop=ALL \
  -p 8088:8080 \
  -e PLAYLISTR_PASSWORD \
  -v /mnt/user/appdata/playlistr:/data \
  ghcr.io/diegoshock/playlistr:latest
```

Para desarrollo local, el repositorio conserva un Compose **opcional** que compila `playlistr:local`:

```bash
cp .env.example .env
# Edita .env y define PLAYLISTR_PASSWORD con al menos 12 caracteres.
docker compose up -d --build
```

No subas `.env` al repositorio. Ese Compose usa el volumen nombrado `playlistr-data`; `docker compose down` lo conserva y `docker compose down -v` lo elimina. La instalación de Unraid anterior usa su carpeta `appdata`, sin Compose.

## Cómo crear una playlist

1. **Sincroniza** la biblioteca. Playlistr lee la música que tu cuenta puede ver. Una sincronización fallida conserva la última biblioteca completa.
2. Pulsa **Buscar géneros**. La consulta respeta un máximo de una petición a MusicBrainz por segundo; bibliotecas grandes pueden tardar bastante. Las clasificaciones se guardan localmente y los artistas resueltos no se consultan otra vez hasta pulsar **Actualizar fuentes**.
3. En **Artistas y géneros**, revisa los artistas ambiguos o sin datos. Abre una tarjeta para ver las fuentes, elegir una identidad o escribir géneros separados por comas. Las correcciones manuales no se sobrescriben al consultar internet.
4. En **Crear playlist**, elige géneros y filtros, escribe un nombre y genera la vista previa. Sin géneros seleccionados se incluye toda la biblioteca, también canciones sin clasificar. En colaboraciones, los géneros se combinan entre sus artistas.
5. Pulsa **Guardar en Navidrome**. La vista previa dura 15 minutos. Los filtros por año excluyen las canciones sin año conocido. Repetir el guardado de la misma vista previa no crea otra playlist.

Si una escritura en Navidrome termina con un error de red, el resultado puede ser incierto. Playlistr no la repite automáticamente: comprueba primero en Navidrome si la playlist llegó a crearse.

## Configuración

| Variable | Valor predeterminado | Uso |
| --- | --- | --- |
| `PLAYLISTR_PASSWORD` | Obligatoria | Acceso a la interfaz, mínimo 12 caracteres. |
| `PLAYLISTR_DATA_DIR` | `/data` | Base de datos y clave de cifrado. |
| `PLAYLISTR_PORT` | `8088` | Puerto publicado por Compose, no el interno del contenedor. |
| `PLAYLISTR_SECURE_COOKIE` | `false` | Usa `true` si accedes exclusivamente mediante HTTPS. |
| `PLAYLISTR_USER_AGENT` | `Playlistr/0.1 (https://github.com/diegoshock/docker-playlists)` | Identificación ante las fuentes públicas; puedes añadir tu contacto. |

Destinos requeridos: tu servidor Navidrome, `https://musicbrainz.org` y `https://www.wikidata.org`. Para construir la imagen hacen falta Docker Hub y PyPI. No necesitas claves API de MusicBrainz o Wikidata. Los proveedores pueden imponer límites o no tener información de un artista.

Los nombres de artistas buscados salen hacia MusicBrainz; las consultas a Wikidata usan identificadores de entidades. No se envían audio ni contraseñas a estas fuentes. Navidrome se autentica con token y salt de Subsonic en el cuerpo de una petición POST, evitando incluirlos en las URLs. Se verifican los certificados TLS y no se siguen redirecciones con credenciales.

Si tu entorno de compilación usa un proxy corporativo con CA propia, proporciona su paquete de certificados confiable con `docker build --secret id=build_ca,src=/ruta/al/ca-bundle.pem -t playlistr:local .`. El secreto se monta solo durante la instalación; no queda en la imagen. Para certificados privados en ejecución, monta el paquete de CA completo como solo lectura y define `SSL_CERT_FILE` con esa ruta. No desactives la verificación TLS.

La contraseña de Navidrome se cifra con una clave en `/data/credentials.key`. Protege todo el volumen: quien pueda leer tanto la clave como la base de datos podrá descifrarla. Usa HTTPS para Navidrome y para el acceso a Playlistr fuera de una LAN de confianza. Detrás de un proxy inverso, conserva la cabecera `Host`, sirve Playlistr en la raíz de su dominio y activa `PLAYLISTR_SECURE_COOKIE=true`. No está diseñado para publicarse en un subdirectorio.

Playlistr administra **una biblioteca y una cuenta de Navidrome por instalación**. Cambiar de servidor o usuario limpia su caché local, correcciones e historial, pero no borra playlists del servidor. El historial local no refleja eliminaciones o ediciones hechas después desde otros clientes.

## Persistencia y mantenimiento

- Haz una copia del volumen completo con el contenedor detenido: incluye SQLite, sus archivos auxiliares y `credentials.key`.
- Las sesiones, las vistas previas y las tareas en curso están en memoria y se reinician al reiniciar el contenedor. Las clasificaciones ya confirmadas se conservan; vuelve a ejecutar la búsqueda de pendientes o la sincronización interrumpida.
- Ejecuta **un solo proceso y una sola réplica**. El límite de consultas y las sesiones se coordinan dentro de ese proceso. El Dockerfile ya usa un worker.
- No hay actualización programada de playlists, reproducción de audio, gestión de múltiples cuentas ni análisis de canciones. Las playlists se generan cuando lo solicitas y se escuchan con tu cliente Navidrome habitual.
- El endpoint `/healthz` comprueba el proceso y el acceso a SQLite. No garantiza la conectividad con Navidrome ni con las fuentes externas.

## Desarrollo y pruebas

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
export PLAYLISTR_DATA_DIR="$PWD/data"
# Define PLAYLISTR_PASSWORD antes de arrancar.
.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8080
```

En otra terminal:

```bash
.venv/bin/python -m pytest -q
node --check app/static/app.js
```

Las pruebas automatizadas usan transportes HTTP simulados y comprueban autenticación Subsonic, paginación, sincronización, preservación ante fallos, artistas múltiples, filtros, fuentes y ambigüedad de identidad, correcciones manuales, protección de credenciales y creación de playlists sin duplicados por reintentos. No requieren una biblioteca personal ni acceso a internet.

La comprobación opcional en navegador inicia una aplicación aislada con datos de prueba y verifica el flujo completo, escritorio y móvil:

```bash
.venv/bin/pip install playwright==1.62.0
.venv/bin/playwright install chromium
.venv/bin/python tests/browser_smoke.py
# Para usar Chromium ya instalado: PLAYLISTR_BROWSER_BINARY=/usr/bin/chromium
```

Las capturas de esta prueba se guardan en `/tmp/playlistr-screenshots`; contienen datos simulados y no se cargan en la aplicación normal.

Para verificar contra tu instalación, conecta Navidrome, sincroniza, consulta un artista conocido, compara su enlace de fuente y crea una playlist pequeña. Comprueba en tu cliente Navidrome que las canciones y el orden coinciden con la vista previa.
