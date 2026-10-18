# Validación de Playlistr

Comprobaciones realizadas en el entorno de desarrollo:

| Comprobación | Resultado |
| --- | --- |
| `python -m pytest -q` | 16 pruebas aprobadas; servicios externos simulados. Una advertencia de deprecación en la dependencia de pruebas Starlette/AnyIO. |
| `node --check app/static/app.js` | Correcto. |
| `tests/browser_smoke.py` con Chromium | Flujo completo aprobado: login, conexión, sincronización, consulta de géneros, fuentes, vista previa, guardado, edición manual y logout. Sin errores JavaScript. |
| Interfaz a 1440 px y 390 px | Revisada mediante capturas; sin desbordamiento horizontal en móvil. Datos de prueba. |
| Construcción Docker | Imagen `playlistr:local` construida. Se suministró la CA confiable del proxy de este entorno mediante un secreto de BuildKit. TLS permaneció verificado. |
| Contenedor con filesystem de solo lectura | Arranca sin privilegios, con capacidades eliminadas y comprobación de salud correcta. |
| Navidrome real `deluan/navidrome:0.55.2` | Autenticación, sincronización de dos audios sintéticos, filtro por género manual y creación de playlist aprobados. Se consultó la playlist desde Navidrome para verificar sus IDs de canciones y orden. Reintentar la misma vista previa no creó otra playlist. |
| Reinicio de Playlistr | Persisten conexión, biblioteca, clasificaciones e historial. Las tareas en memoria se reinician. |
| Usuario de Unraid `99:100` | Arranque y escritura en volumen con ese UID/GID comprobados dentro de Docker. |
| Compose y plantilla XML | Configuración Compose validada y XML parseado correctamente. |
| Publicación GHCR | Workflow validado con actionlint 1.7.7; ejecución de pruebas antes de publicar, permisos de paquete limitados al job de publicación y tags para main/versiones. Imagen local reconstruida con etiquetas OCI. |
| Plantilla Unraid para GHCR | Referencia `ghcr.io/diegoshock/playlistr:latest` y XML comprobados. Instalación documentada desde Add Container, sin Compose. |

## Límites de esta validación

- La política de red del entorno impidió consultas reales a `musicbrainz.org`, `www.wikidata.org` y la página de referencia de Docker Hub. La búsqueda de géneros se probó con respuestas simuladas, incluidas identidad ambigua, géneros comunitarios, errores y alternativa de Wikidata. No se afirma que las consultas externas reales se hayan verificado.
- La integración Navidrome se verificó con géneros asignados manualmente, no con consultas externas. No se ha conectado una biblioteca personal del usuario.
- Se probó el contenedor con los permisos habituales de Unraid, pero no se dispone aquí de la interfaz de Unraid para validar la importación de la plantilla en un servidor real.
- La imagen existe localmente. La construcción local y la validación del workflow no demuestran una publicación en GHCR: debe completarse GitHub Actions y verificarse una descarga anónima después de hacer público el paquete. No se ha desplegado en el Unraid del usuario.

Para completar la validación en tu servidor, conecta tu cuenta desde la interfaz, consulta un artista conocido y compara los géneros con su fuente enlazada. Crea después una playlist pequeña y comprueba su contenido en Navidrome.
