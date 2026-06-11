# Arquitectura de Nexus

Nexus se divide en dos partes:

- **El núcleo (`core/`)**: pequeño y estable. Sabe cargar módulos, enrutar
  peticiones HTTP, servir archivos estáticos y manejar streams SSE. No conoce
  nada sobre trading ni música.
- **Los módulos (`modules/`)**: cada uno es una funcionalidad enchufable.
  El núcleo los descubre, los arranca y los expone en `/m/<slug>/`.

## Flujo de arranque

1. `./nexus` ejecuta `python3 -m core.hub`.
2. `core/hub.py` lee `config/nexus.json`.
3. `core/module_loader.py` recorre `config.modules` y, por cada módulo
   habilitado, importa `modules/<slug>/module.py` y llama a `get_module(context)`.
4. El hub llama a `start()` en cada módulo (lanzan sus hilos de fondo).
5. `core/server.py` levanta el servidor HTTP y empieza a atender.

## El contrato de un módulo

Un módulo es una subclase de `NexusModule` (ver `core/module_base.py`). Lo
mínimo es definir `slug`, `title`, `description`, `icon`. Opcionalmente:

| Método              | Para qué sirve                                              |
|---------------------|------------------------------------------------------------|
| `start()` / `stop()`| Ciclo de vida (lanzar/cerrar hilos, conexiones).           |
| `public_dir()`      | Carpeta de estáticos (por defecto `public/`).              |
| `api(subpath, q)`   | Responde `/m/<slug>/api/<subpath>` → `(status, ctype, bytes)`. |
| `sse(subpath, q)`   | Devuelve un generador para un stream SSE en vivo.          |
| `health()`          | Estado del módulo para `/health`.                          |

## Cómo crear un módulo nuevo (ejemplo: "notas")

1. Crear la carpeta y el paquete:

   ```
   modules/notas/
   ├── __init__.py
   ├── module.py
   └── public/
       └── index.html
   ```

2. En `module.py`:

   ```python
   from core.module_base import NexusModule

   class NotasModule(NexusModule):
       slug = "notas"
       title = "Notas"
       description = "Tus notas rápidas."
       icon = "📝"

       def api(self, subpath, query):
           if subpath == "ping":
               return (200, "application/json", b'{"ok": true}')
           return None

   def get_module(context):
       return NotasModule(context)
   ```

3. Habilitarlo en `config/nexus.json`:

   ```json
   "modules": {
     "notas": { "enabled": true }
   }
   ```

4. Reiniciar `./nexus`. El módulo aparece solo en el hub y en `/m/notas/`.

## Endpoints del núcleo

- `GET /` — página de inicio con las tarjetas de los módulos.
- `GET /health` — JSON con el estado del hub y de cada módulo.
- `GET /m/<slug>/...` — estáticos y API de cada módulo.
