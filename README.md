# Mega Free Chat

**Pasarela web que enruta cada pregunta a un modelo con precio `$0` del catálogo de OpenRouter, con failover, prioridad a modelos chinos y streaming (SSE).**

![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-ASGI-009688?logo=fastapi&logoColor=white)
![SSE](https://img.shields.io/badge/streaming-SSE-4f8cff)
![OpenRouter](https://img.shields.io/badge/router-OpenRouter-6b4fbb)
![License](https://img.shields.io/badge/license-MIT-2ecc71)
![Estado](https://img.shields.io/badge/estado-experimental-f1c40f)

> **Aviso de honestidad.** No promete IA gratis para siempre. Se apoya en una condición del mercado —que existan modelos en `$0` en OpenRouter— y eso **puede cambiar sin aviso**. Lo que sí hace es descubrir el pool en ejecución, ordenarlo por preferencia y rotar cuando un modelo se cae. Si mañana no queda ninguno en `$0`, la app sigue siendo correcta: devuelve un error explícito en lugar de inventar disponibilidad.

---

## Índice

- [Qué es](#qué-es) · [Qué no es](#qué-no-es) · [Advertencia sobre "gratis"](#advertencia-sobre-gratis)
- [Principio de funcionamiento](#principio-de-funcionamiento) · [Arquitectura](#arquitectura) · [Diagrama de conexión](#diagrama-de-conexión-y-topología)
- [Requisitos](#requisitos) · [Instalación](#instalación) · [Configuración](#configuración) · [Las dos formas de API key](#las-dos-formas-de-api-key) · [Ejecución](#ejecución)
- [Endpoints](#endpoints) · [Protocolo SSE](#protocolo-sse-de-apichat) · [Ejemplos](#ejemplos-de-uso)
- [Failover](#lógica-de-failover) · [Prioridad china](#prioridad-de-modelos-chinos) · [Interfaz web](#interfaz-web)
- [Seguridad](#seguridad) · [Rendimiento](#rendimiento-sin-números-inventados) · [Calibración](#ajuste-y-calibración)
- [Problemas](#solución-de-problemas) · [Limitaciones](#limitaciones-conocidas) · [Cómo se construyó](#cómo-se-construyó-este-proyecto)
- [Estructura](#estructura-del-repositorio) · [Documentación](#documentación-adicional) · [Referencias](#referencias) · [Licencia](#licencia)

---

## Qué es

Una aplicación web de una sola responsabilidad: **intermediar entre tu navegador y el subconjunto gratuito del catálogo de OpenRouter**.

OpenRouter agrega cientos de modelos de decenas de proveedores detrás de una API compatible con OpenAI. Algunos tienen precio cero por token, normalmente porque el proveedor promociona un modelo nuevo o porque da una cuota gratuita con límite de velocidad. La lista **no es fija**.

El proyecto hace cuatro cosas:

1. **Descubre** qué modelos están en `$0` ahora mismo.
2. **Mantiene un pool** en memoria con el estado de cada uno (activo, cooldown, fallos).
3. **Enruta** cada mensaje al primer modelo que acepte la petición, con un orden explícito.
4. **Entrega la respuesta en streaming**, sin esperar a que el modelo termine.

Alrededor hay una UI mínima —estilo terminal, sin burbujas— que muestra el pool en vivo, marca el modelo que responde y permite configurar la key sin tocar archivos.

| Aspecto | Valor |
|---|---|
| Tipo | Aplicación web local (backend + UI estática) |
| Stack | Python 3.10+ · FastAPI · Uvicorn · SDK `openai` · HTTPX |
| Transporte | HTTP + Server-Sent Events |
| Persistencia | Ninguna: estado en RAM |
| Usuarios previstos | 1, en una máquina de confianza |
| Puerto | `8000` |
| Auth de la app | No tiene (ver [Seguridad](#seguridad)) |
| Auth contra OpenRouter | API key propia `sk-or-v1-...` |
| Coste | `$0` mientras existan modelos en `$0` |

## Qué no es

| No es | Por qué importa |
|---|---|
| Un servicio multiinquilino | Sin cuentas ni aislamiento: todos usan la misma key. |
| Un producto de alta disponibilidad | El pool es volátil y el estado vive en RAM. |
| Un benchmark | No mide calidad ni latencia: solo mira el precio. |
| Un orquestador de agentes | Sin herramientas, memoria vectorial ni planificación. |
| Un bypass de límites | Usa solo las rutas públicas de OpenRouter con **tu** clave. |
| Un proxy anónimo | La petición viaja con tu key. |
| Un frontend con Markdown | Renderiza texto plano a propósito, para no introducir XSS. |

---

## Advertencia sobre "gratis"

El nombre puede inducir a error; prefiero el error contrario.

**Cómo se decide.** El catálogo devuelve `pricing` con precios **como cadenas**: `{"prompt": "0", "completion": "0"}`. El filtro es literal (`== "0"`). Si un proveedor empieza a devolver `"0.0000001"`, el modelo sale del pool solo.

**Lo que pasa en la práctica:** los gratuitos por API son casi siempre **promociones** de semanas o meses; casi todos imponen **rate limits** agresivos (de ahí el cooldown); y la composición del pool cambia. En una ejecución local del **2026-08-28** quedó en **18 modelos**; ese número es una fotografía, no una promesa. Además, algunos gratuitos se pagan con **datos**: si el proveedor entrena con tus prompts, el precio es `$0` porque el producto eres tú. Leé la ficha antes de pegar información sensible.

**Si el pool se vacía:** `/api/models` devuelve `models: []`, la UI muestra "Sin modelos gratuitos ahora" y `/api/chat` emite `error` con `No hay ningún modelo gratuito disponible en este momento.` El servidor no cae, no entra en bucle y no sustituye un modelo pago en silencio.

**Regla práctica:** usalo como capa de exploración y ahorro, no como infraestructura crítica. Si el `$0` desaparece, el mismo cliente OpenAI-compatible funciona contra modelos pagos cambiando el filtro.

---

## Principio de funcionamiento

```
 ┌────────────┐  1. GET /api/v1/models   ┌──────────────┐
 │ Mega Free  │ ───────────────────────► │  OpenRouter  │
 │   Chat     │ ◄── lista con pricing ── │   catálogo   │
 └─────┬──────┘                          └──────────────┘
       │ 2. filtra pricing == "0" → pool en memoria
       │ 3. ordena: chinos primero, luego A-Z
       ▼
   Router ── POST /chat/completions (stream=true) ──► Proveedor
       │ ◄──── 429 / 5xx / timeout ── marca cooldown y prueba el siguiente
       ▼
   SSE chunk ──► navegador (texto mientras se genera)
```

1. **Descubrimiento.** `ModelsPool.refresh()` hace `GET {OR_BASE_URL}/models` con `Authorization: Bearer <key>` y timeout de 30 s. Se cachea hasta que pasan `POOL_REFRESH_SECONDS` (6 h).
2. **Filtrado.** Solo sobreviven `pricing.prompt == "0"` **y** `pricing.completion == "0"`; después se descartan alias con `~`, `openrouter/free` y audio (Lyria).
3. **Clasificación.** Cada modelo se marca como chino o no chino.
4. **Selección.** El router pide los disponibles (sin cooldown) y los ordena por `(not is_chinese, nombre)`.
5. **Intento.** Éxito → se devuelve el stream; error → se marca el modelo y se sigue con el siguiente.
6. **Entrega.** Un `StreamingResponse` con `text/event-stream` emite `status`, `chunk`, `done` o `error`.

Lo que hace útil al diseño: el estado es **por modelo**, no global. Un `429` no invalida el sistema; invalida ese modelo un rato.

---

## Arquitectura

```
mega-free-chat/
├── server.py                  FastAPI: rutas, validación, SSE
├── src/
│   ├── models_pool.py         Catálogo, filtro $0, estado
│   ├── openrouter_client.py   Cliente OpenAI-compatible
│   └── router.py              Failover y prioridad
├── static/index.html          UI completa (sin build)
├── run.sh · requirements.txt · .env.example
└── docs/                      Datasheet, developer, referencias, bitácora, SVG
```

| Módulo | Responsabilidad |
|---|---|
| `server.py` | API, validación Pydantic, traducción a SSE, elegir router |
| `models_pool.py` | Descargar catálogo, filtrar, cooldowns, serializar |
| `openrouter_client.py` | Envolver el SDK `openai` y devolver fragmentos |
| `router.py` | Ordenar, intentar, marcar éxito/fallo, agotar con error |
| `index.html` | Chat, lectura del stream, key, panel |

La separación es intencional: **el router no sabe que existe HTTP**. Cada capa se puede probar o reemplazar por separado.

**Estado.** Cada modelo es un `FreeModel` con `id`, `name`, `context_length`, `modalities`, `supported_parameters`, `is_chinese` y estado dinámico (`status`, `fail_count`, `last_failure`, `cooldown_until`). La verdad de la disponibilidad es el método, no el campo:

```python
def is_available(self, now: float) -> bool:
    if self.status == "backoff" and now < self.cooldown_until:
        return False
    return True
```

Cuando el cooldown expira el modelo vuelve a ser candidato **aunque `status` siga en `backoff`**. La UI puede mostrarlo en amarillo un rato más; el router ya lo usa.

**Dos routers.** Al importar se crea uno global con la key del `.env`. En `POST /api/chat`, si llega `api_key`, se crean pool, cliente y router locales para esa petición. Consecuencia: **con key del navegador el cooldown no se comparte** y el catálogo se descarga en cada mensaje (~1 s observado). Con key en `.env` el pool es único y persistente mientras el proceso viva.

Los diagramas vectoriales están en [`docs/assets/`](docs/assets/): `architecture.svg`, `failover.svg`, `chat-flow.svg`.

---

## Diagrama de conexión y topología

No hay hardware: el "pinout" es la topología de red y los contratos.

```
Navegador ──HTTP──► Uvicorn/FastAPI :8000 ──HTTPS 443──► openrouter.ai
  index.html           router · pool (RAM)               /api/v1/models
  localStorage         GET /  GET /api/models            /api/v1/chat/completions
  megaFreeChat_apiKey  POST /api/chat → SSE
```

| Origen | Destino | Protocolo | Puerto | Auth |
|---|---|---|---|---|
| Navegador | `localhost:8000` | HTTP | 8000 | Ninguna (key opcional en el body) |
| FastAPI | `openrouter.ai` | HTTPS | 443 | `Authorization: Bearer <key>` |
| UI | `localStorage` | API del navegador | — | Origen local |

- **`host="0.0.0.0"`**: escucha en todas las interfaces. En una LAN, cualquiera puede abrir la página (ver [Seguridad](#seguridad)).
- **`HTTP-Referer` / `X-Title`**: cabeceras de atribución que OpenRouter usa para identificar la app.
- **`X-Accel-Buffering: no`**: evita que Nginx acumule el stream y lo entregue de golpe.

---

## Requisitos

| Componente | Versión | Nota |
|---|---|---|
| Python | **3.10+** | El código usa `str \| None` y `list[dict]` en modelos Pydantic; con 3.9 no se resuelven. La `.venv` de referencia es 3.12. |
| Navegador | Actual | Necesita `fetch` y `ReadableStream`. No hace falta Node. |
| Shell | `bash` para `run.sh` | Windows: WSL o `uvicorn` directo. |
| OpenRouter | Cuenta + key | Crear cuenta es gratis; los `$0` no descuentan crédito. |
| Red | HTTPS a `openrouter.ai:443` | Sin salida, el pool queda vacío. |
| Puerto | `8000` libre | Configurable con `PORT`. |

---

## Instalación

Las dependencias están en **`requirements.txt`**. No hay build ni assets que descargar.

```bash
git clone https://github.com/wanderc137/mega-free-chat.git
cd mega-free-chat

python3 -m venv venv
source venv/bin/activate        # Linux/Mac
venv\Scripts\activate           # Windows

pip install -r requirements.txt
```

> `run.sh` usa `.venv` por convención. Si preferís `venv`, o lo nombrás `.venv` o lanzás con `uvicorn` para no tener dos entornos.

`run.sh` (si lo usás) crea `.venv` si falta, instala dependencias si `uvicorn` no se importa, copia `.env.example` a `.env` si no existe, valida la forma de la key, exporta el `.env` y ejecuta `python server.py` con `exec` en primer plano.

| Paquete | Versión | Para qué |
|---|---|---|
| `fastapi` | sin pin | HTTP, Pydantic, `StreamingResponse` |
| `uvicorn[standard]` | sin pin | Servidor ASGI |
| `openai` | sin pin | SDK usado como cliente de OpenRouter |
| `httpx` | sin pin | Descarga del catálogo |
| `python-dotenv` | sin pin | Carga de `.env` |

**Reproducibilidad:** al no fijar versiones, dos máquinas pueden instalar versiones distintas. Para congelar: `pip freeze > requirements.lock.txt`.

---

## Configuración

Todo vive en `.env` (raíz). La plantilla es `.env.example`, versionada; el `.env` real está en `.gitignore`.

```bash
cp .env.example .env
```

```dotenv
OPENROUTER_API_KEY=sk-or-v1-...
BACKOFF_SECONDS=300
POOL_REFRESH_SECONDS=21600
DEBUG=true
```

| Variable | Default | Alcance | Descripción |
|---|---|---|---|
| `OPENROUTER_API_KEY` | `""` | Servidor | Key de respaldo. Vacía o con placeholder → warning al arrancar. |
| `BACKOFF_SECONDS` | `300` | Pool | Cooldown tras fallo. Un `429` aplica **el doble**. |
| `POOL_REFRESH_SECONDS` | `21600` | Pool | Intervalo mínimo entre descargas del catálogo. |
| `DEBUG` | `false` | Servidor | `true` → logging `DEBUG` (incluye `httpcore`, muy verboso). |
| `OR_BASE_URL` | `https://openrouter.ai/api/v1` | Cliente y pool | **Soportada pero ausente en `.env.example`**. Sirve para un proxy compatible o un mock. |

**Orden de importación (importante).** `server.py` importa los módulos **antes** de `load_dotenv()`, y esos módulos leen el entorno al importarse:

- Con **`./run.sh`**, el `.env` se exporta antes de arrancar Python → **todas** las variables tienen efecto.
- Con **`uvicorn server:app`** sin exportar, `BACKOFF_SECONDS`, `POOL_REFRESH_SECONDS` y `OR_BASE_URL` del `.env` **se ignoran**. `OPENROUTER_API_KEY` sí se lee bien.

"Cambié el cooldown y no pasa nada" es esto. Solución: `BACKOFF_SECONDS=60 POOL_REFRESH_SECONDS=600 ./run.sh`.

---

## Las dos formas de API key

Precedencia: `api_key del body` > `OPENROUTER_API_KEY del .env` > vacío (OpenRouter rechaza).

**Forma 1 — desde la interfaz.** El botón **"API key"** despliega un `<input type="password">`. Al guardar (Enter o *Guardar*), el campo se colapsa en `••••••` verde y el botón pasa a "API key configurada". La clave se guarda en `localStorage` bajo `megaFreeChat_apiKey` y **persiste entre sesiones**; `Escape` cancela. El valor nunca se rellena al reabrir (no queda visible en el DOM), el input tiene `autocomplete="off"` y la clave viaja en el **body JSON** de cada `POST /api/chat`. No hay botón de borrar: `localStorage.removeItem('megaFreeChat_apiKey')`.

- **Ventaja:** no tocás archivos ni reiniciás.
- **Coste:** cada petición reconstruye pool y cliente.

**Forma 2 — desde `.env`.** `OPENROUTER_API_KEY=sk-or-v1-tu_clave_real`. El pool es **único**, conserva cooldowns, el navegador no transporta la clave y sirve para curl o scripts sin pasar `api_key`.

| Escenario | Recomendado |
|---|---|
| Uso personal, querés olvidarte | `.env` |
| Varias personas, cada una con su key | UI |
| Scripts o curl | `.env` o `api_key` explícita |
| Instancia en red | UI, sin key de servidor |

---

## Ejecución

```bash
./run.sh          # opción A: primer plano, http://localhost:8000, Ctrl+C para detener
```

Queda en la terminal actual, sin procesos colgados. Si falta permiso: `chmod +x run.sh`.

```bash
source .venv/bin/activate
uvicorn server:app --host 0.0.0.0 --port 8000    # opción B (o python server.py)
uvicorn server:app --reload --port 8000          # opción C, desarrollo
```

En B y C recordá el detalle de importación: las variables del `.env` distintas de la key pueden no aplicarse. `--reload` reinicia el proceso al guardar y **pierde el estado del pool** en cada cambio.

Comprobar que está vivo:

```bash
curl -s http://localhost:8000/api/models | head -c 300
```

---

## Endpoints

| Ruta | Método | Respuesta | Descripción |
|---|---|---|---|
| `/` | GET | `text/html` | Sirve `static/index.html` |
| `/api/models` | GET | `application/json` | Estado completo del pool |
| `/api/chat` | POST | `text/event-stream` | Chat con failover |
| `/static/*` | GET | según archivo | Montaje de `StaticFiles` |

### `GET /api/models`

Devuelve el pool **completo**, incluidos los modelos en cooldown:

```json
{
  "updated_at": "2026-08-28T19:49:27.800000+00:00",
  "last_error": null,
  "models": [
    {
      "id": "inclusionai/ling-3.0-flash-fin:free",
      "name": "Ling 3.0 Flash (free)",
      "context_length": 131072,
      "status": "active",
      "fail_count": 0,
      "last_failure": null,
      "cooldown_until": 0.0,
      "is_chinese": true
    }
  ]
}
```

`updated_at` es el momento de la respuesta, no del último fetch. `last_error` no nulo indica que el catálogo no se pudo refrescar: el pool puede estar obsoleto pero sigue sirviendo. `cooldown_until` es epoch en segundos (`0.0` si nunca falló) y `fail_count` se resetea al primer éxito.

**Efecto secundario:** cada llamada puede disparar un `refresh()` si venció el intervalo, y entonces tarda lo que tarde el catálogo. No hay endpoint de refresco forzado.

### `POST /api/chat`

| Campo | Tipo | Obligatorio | Límites | Descripción |
|---|---|---|---|---|
| `message` | string | Sí | `1..100000` | Turno actual del usuario |
| `history` | array de objetos | No (`[]`) | Sin límite en servidor | Turnos previos en formato OpenAI |
| `api_key` | string \| null | No | — | Key para esta petición |

- El servidor **no** añade system prompt: la conversación es lo que manda el cliente.
- `history` no se valida en contenido ni longitud; la UI lo recorta a 30 elementos.
- `message` vacío o > 100 000 → **422** de FastAPI, no un evento SSE.
- **El status HTTP es 200 aunque el contenido termine en error.** Los errores viajan dentro del stream: hay que leerlo hasta el final.

---

## Protocolo SSE de `/api/chat`

Cada evento, con dos saltos de línea al final:

```
event: <nombre>
data: <json compacto, UTF-8 sin escapar>

```

| Evento | Cuándo | `data` | Consumo |
|---|---|---|---|
| `status` | Al abrir | `{"state": "routing"}` | Mostrar "pensando" |
| `status` | Un modelo aceptó | `{"state": "streaming", "model": "<id>"}` | Crear mensaje y etiquetar |
| `chunk` | Por fragmento | `{"content": "<texto>"}` | **Concatenar** |
| `done` | Fin normal | `{"model": "<id>"}` | Cerrar turno |
| `error` | Fallo | `{"message": "<detalle>"}` | Mostrar error |

```
event: status
data: {"state": "routing"}

event: status
data: {"state": "streaming", "model": "inclusionai/ling-3.0-flash-fin:free"}

event: chunk
data: {"content": "Hola"}

event: chunk
data: {"content": ", ¿en qué puedo ayudarte?"}

event: done
data: {"model": "inclusionai/ling-3.0-flash-fin:free"}
```

Errores posibles: `{"message": "No hay ningún modelo gratuito disponible en este momento."}` o `{"message": "Todos los modelos gratuitos fallaron. Detalle: modelo/a: rate limit (429) | modelo/b: HTTP 503"}`.

**Parsing:** acumulá bytes, partí por `\n\n`, guardá el último trozo como buffer, tomá `event:` y `data:` de cada bloque y hacé `JSON.parse`. Un `chunk` no equivale a palabra: puede ser un carácter o varios tokens. No asumas que `status` siempre llega.

Cabeceras: `Content-Type: text/event-stream`, `Cache-Control: no-cache`, `X-Accel-Buffering: no`, `Connection: keep-alive`.

**No tiene** `id:`/`retry:` (no se reanuda con `Last-Event-ID`), ni heartbeat (`: ping`), ni `done` garantizado si el proceso muere.

---

## Ejemplos de uso

**1. Pregunta simple (key en `.env`):**

```bash
curl -N -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "Explícame qué es un rate limit en dos frases"}'
```

`-N` desactiva el buffering de curl y deja ver los eventos de a uno.

**2. Con key explícita e historial:**

```bash
curl -N -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{
        "message": "¿Y el segundo?",
        "history": [
          {"role": "user", "content": "Nombra dos modelos de Zhipu"},
          {"role": "assistant", "content": "GLM-4.5 Air y GLM-4.6."}
        ],
        "api_key": "sk-or-v1-tu_clave"
      }'
```

**3. Inspeccionar el pool:**

```bash
# disponibles
curl -s http://localhost:8000/api/models \
  | python3 -c 'import json,sys; d=json.load(sys.stdin); print("\n".join(m["id"] for m in d["models"] if m["status"]=="active"))'
```

**4. Cliente Python que acumula la respuesta:**

```python
import json, httpx

def preguntar(texto: str, historial: list[dict] | None = None) -> str:
    partes: list[str] = []
    with httpx.stream("POST", "http://localhost:8000/api/chat",
                      json={"message": texto, "history": historial or []},
                      timeout=None) as r:
        evento = None
        for linea in r.iter_lines():
            if linea.startswith("event:"):
                evento = linea[6:].strip()
            elif linea.startswith("data:"):
                data = json.loads(linea[5:].strip())
                if evento == "chunk":
                    partes.append(data["content"])
                elif evento == "error":
                    raise RuntimeError(data["message"])
                elif evento == "done":
                    print(f"[modelo: {data['model']}]")
    return "".join(partes)

print(preguntar("Resume en una frase qué hace este proyecto."))
```

**5. Desde la LAN:** `curl -N http://<ip-de-tu-maquina>:8000/api/chat` funciona porque escucha en `0.0.0.0`. Es el motivo por el que existe la sección de seguridad. El código de la UI (`static/index.html`) es, a su vez, el ejemplo más completo de cliente JavaScript: lee el `ReadableStream` con `getReader()`, parte por `\n\n` y concatena los `chunk`.

---

## Lógica de failover

```python
available = self.pool.available_models()          # descarta cooldowns activos
if not available:
    raise RouterError("No hay ningún modelo gratuito disponible en este momento.")

candidates = sorted(available, key=lambda m: (not m.is_chinese, m.name.lower()))

for model in candidates:
    try:
        stream = self.client.chat_stream(model.id, messages)
        self.pool.mark_success(model.id)
        return model.id, stream
    except RateLimitError as exc:      ...        # 429
    except APIStatusError as exc:      ...        # status del proveedor
    except APIConnectionError as exc:  ...        # red
    except Exception as exc:           ...        # cualquier otra
```

| Excepción del SDK | `status_code` | Cooldown | `last_failure` típico |
|---|---|---|---|
| `RateLimitError` | `429` | `BACKOFF_SECONDS × 2` → **600 s** | `429: Rate limit exceeded...` |
| `APIStatusError` | el del proveedor | 300 s | `503: No available providers` |
| `APIConnectionError` | `None` | 300 s | `Connection error.` |
| `Exception` genérica | `None` | 300 s | el `str(exc)` que sea |

El doble castigo al `429` es deliberado: no es un fallo transitorio de red, es una señal de "no insistas". Un 503 puede resolverse en segundos; un 429 suele necesitar minutos.

**Cronología** con `BACKOFF_SECONDS=300`: `chino/a` recibe `429` a las 12:00 → `backoff` hasta 12:10; `chino/b` responde y queda `active`; a las 12:03 una nueva pregunta salta `chino/a`; a las 12:10:01 `is_available()` vuelve a `True` y es candidato otra vez. Un **éxito** resetea todo. El estado vive en RAM: reiniciar lo borra. El refresco del catálogo **conserva** el estado de los modelos ya conocidos (merge por `id`), así que un `429` no se olvida a las 6 horas — pero `name` y `context_length` tampoco se actualizan si el proveedor los cambia.

### El generador perezoso (limitación importante)

`OpenRouterClient.chat_stream()` es una **función generadora** (contiene `yield`). Llamarla **no ejecuta su cuerpo**: devuelve un generador. Por eso esta línea no hace todavía la petición HTTP:

```python
stream = self.client.chat_stream(model.id, messages)
```

La petición ocurre al consumir el generador, después, en `server.py`, dentro de `for fragment in stream`. Consecuencia: los `except` del router **no atrapan** los errores HTTP del primer modelo. Un `429` en el primer candidato no dispara el salto al segundo: se propaga al `except Exception` de `server.py`, que emite `Error interno: ...`. Y `mark_success` se ejecuta antes de saber si el modelo respondió.

- Si el primer modelo responde bien, todo funciona y el failover ni se nota (el caso del log local).
- Si falla, no hay reintento: el usuario ve un error.

**Arreglo** (no implementado, deuda declarada): forzar la evaluación del primer elemento dentro del `try`.

```python
gen = self.client.chat_stream(model.id, messages)
primer = next(gen)                          # aquí sí se lanza la petición
stream = itertools.chain([primer], gen)
```

Mientras no se haga, esta documentación no dice "failover robusto": dice **failover implementado con evaluación perezosa documentada**.

---

## Prioridad de modelos chinos

No es un juicio de calidad: es una **regla de orden**. `key=lambda m: (not m.is_chinese, m.name.lower())` pone `False` (chinos) antes que `True`, y dentro de cada grupo ordena alfabéticamente.

`is_chinese_model(model_id, name)` concatena `id + name`, pasa a minúsculas y aplica:

- **Proveedores (subcadena):** `z-ai`, `zhipu`, `zhipuai`, `minimax`, `deepseek`, `qwen`, `alibaba`, `inclusionai`, `moonshot`, `kimi`, `baidu`, `tencent`, `hunyuan`, `stepfun`, `01-ai`, `iflytek`, `xinghuo`, `sensetime`, `doubao`, `baichuan`, `internlm`.
- **Keywords en el nombre, con `\b`:** `glm`, `qwen`, `deepseek`, `minimax`, `kimi`, `hunyuan`, `doubao`, `internlm`, `baichuan`.

El `\b` evita falsos positivos como detectar "ling" dentro de "inkling". Fue una decisión concreta durante el desarrollo.

**Por qué existe:** en el momento de construir el proyecto, el ecosistema chino ofrecía más modelos con cuota gratuita sostenida (GLM, Qwen, DeepSeek, MiniMax, Ling), varios con contexto grande a coste cero. Priorizar ahí aumentaba la probabilidad de que el primer intento funcionara.

| Querés… | Tocá |
|---|---|
| Añadir proveedor / keyword | `CHINESE_PROVIDERS` / `CHINESE_KEYWORDS` en `models_pool.py` |
| Invertir prioridad | `key=lambda m: (m.is_chinese, ...)` en `router.py` |
| Priorizar contexto | `key=lambda m: (not m.is_chinese, -m.context_length)` |
| Desactivar | `key=lambda m: m.name.lower()` |

---

## Interfaz web

Un solo archivo con CSS y JS embebidos: sin frameworks, sin bundler.

- **Panel lateral:** grupos "Chinos · N" y "Otros · N", punto de estado por modelo (verde/amarillo/rojo), nombre, `id` y etiqueta. El que responde se resalta con borde verde y **"EN USO"**. Se refresca cada **20 s** (`setInterval`); si falla, el indicador pasa a `offline`.
- **Chat:** minimalista tipo terminal, sin burbujas. Etiquetas de rol ("TÚ", "IA", "SISTEMA", "ERROR"), `pre-wrap`, auto-scroll. El texto se inserta con `textContent`, no `innerHTML`: **sin Markdown ni HTML**, lo que elimina XSS desde la salida del modelo y limita el formato.
- **Entrada:** Enter envía, Shift+Enter salto; el textarea crece hasta 160 px; el botón se deshabilita mientras hay respuesta.
- **Historial:** en memoria, `slice(-30)` → **30 elementos** (15 intercambios), no 30 turnos. Se pierde al recargar.
- **Detalles:** `Escape` cierra el campo de key sin guardar; colores en variables CSS (`--bg`, `--panel`, `--accent`…). Falta `aria-label` en el textarea: mejora pendiente.

---

## Seguridad

Diseñado para **una persona, en su máquina, en una red de confianza**.

| Amenaza | Superficie | Estado | Mitigación |
|---|---|---|---|
| Otro equipo de la LAN usa tu key | `0.0.0.0:8000` sin auth | **Vulnerable por diseño** | Host `127.0.0.1`, firewall o proxy con auth |
| Sitio malicioso lee tus respuestas | CORS no configurado | **Mitigado** (mismo origen) | No agregar CORS permisivo |
| Robo de la key del navegador | `localStorage` | **Riesgo aceptado** | No usar en equipos compartidos; rotar |
| Key en claro en el body | HTTP local | **Riesgo aceptado** | TLS en el borde |
| Key filtrada en el repo | `.env` | **Mitigado** | `.gitignore`: `.env`, `*.env`, `!*.env.example` |
| HTML inyectado por el modelo | Render | **Mitigado** | `textContent` |
| HTML inyectado por el catálogo | Panel | **Parcial** | `escapeHtml()` en nombre e id; `status` se interpola sin escapar (enum propio) |
| Abuso de cuota | Sin rate limit | **Vulnerable si se expone** | No exponer o limitar en el proxy |
| Prompt injection | Contenido | **Fuera de alcance** | No hay herramientas ni permisos |
| Key en logs | `logging` | **Mitigado** | Se registran rutas y modelos, nunca cabeceras ni bodies |

**`localStorage`.** La key vive en el origen `http://localhost:8000` bajo `megaFreeChat_apiKey`. Persiste hasta que la borres, **es legible por cualquier JS de ese origen** (hoy no hay scripts de terceros), **no está cifrada**, es por navegador y por origen (cambiar a `127.0.0.1` es otro origen) y no se sincroniza entre dispositivos. Si te incomoda, usá `.env`: la clave del servidor nunca llega al navegador.

**`0.0.0.0`.** Significa "todas las interfaces": en una red compartida, cualquiera puede abrir la página, chatear con la key del `.env` y ver los ids. Para limitarlo: `uvicorn server:app --host 127.0.0.1 --port 8000`.

**Para exponerlo a internet** (no implementado): TLS (Caddy, Nginx, Cloudflare Tunnel), autenticación en el proxy, rate limiting, quitar la key del `.env` y exigir la de cada usuario, cabeceras de seguridad (CSP, `X-Content-Type-Options`, `Referrer-Policy`) y logs con rotación. Nada de eso está hecho, y esta documentación lo dice en lugar de insinuar lo contrario.

---

## Rendimiento (sin números inventados)

No hay benchmarks en este repositorio y no voy a inventar latencias ni throughput. Lo que sí se puede afirmar es **cómo está construido**.

| Hecho estructural | Consecuencia |
|---|---|
| Handlers `async` que llaman código **síncrono** (`httpx.Client`, iteración del SDK) | Mientras se espera al proveedor el event loop está bloqueado: con varios usuarios, las peticiones se serializan. |
| `refresh()` descarga el catálogo de forma síncrona | El primer `/api/models` (o el primero tras 6 h) tarda lo que tarde la descarga: ~1 s observado con 18 modelos. |
| Key del body → pool nuevo por petición | Se repite el catálogo y **no se comparten cooldowns**: el mayor coste evitable. |
| Failover secuencial | El peor caso es la **suma** de latencias, no el máximo. |
| Stream fragmento a fragmento | La latencia percibida es la del **primer token**, no la de la respuesta completa. |
| Un proceso, sin `--workers` | Cada worker tendría su propio pool y cooldowns. |

**Medir de verdad:**

```bash
curl -N -w '\n--- ttfb=%{time_starttransfer}s total=%{time_total}s\n' \
  -X POST http://localhost:8000/api/chat -H 'Content-Type: application/json' \
  -d '{"message":"Di hola"}'
```

Esas dos métricas —**TTFB** y **tiempo total**— son las que importan en un chat con streaming. Cualquier otra cifra acá sería inventada.

**Optimizaciones obvias (no implementadas):** compartir el pool por hash de key; cliente asíncrono; caché del catálogo en disco; primar el generador; timeout por intento; heartbeat SSE.

---

## Ajuste y calibración

No hay hardware que calibrar; se ajusta el pool.

- **Cooldown (`BACKOFF_SECONDS`):** `60` para pruebas y pools grandes; `300` (default) para uso normal; `900` si el pool es chico. Un `429` **duplica** el valor (con 300, castigo de 600).
- **Refresco (`POOL_REFRESH_SECONDS`):** `600` si esperás un modelo nuevo; `21600` (default); `86400` para instancia estable. No bajes de `300`: cada refresco es una descarga completa.
- **Historial:** `history.slice(-30)` en el cliente. Si se corta por contexto, bajalo a 10; si el modelo tiene 128k y querés charlas largas, subilo (a costa de tokens y latencia). El servidor acepta cualquier tamaño: el límite real lo pone el proveedor.
- **Longitud del mensaje:** `100000` caracteres es una defensa básica, no una regla de negocio.

Verificar que el ajuste tomó efecto:

```bash
DEBUG=true ./run.sh
curl -s http://localhost:8000/api/models > /dev/null
# log: "Pool actualizado: N modelos gratuitos disponibles"
```

Si no aparece, el intervalo no venció o falló (`No se pudo actualizar el pool: ...`).

---

## Solución de problemas

| Síntoma | Causa probable | Solución |
|---|---|---|
| `OPENROUTER_API_KEY no configurada o vacía` | `.env` con placeholder o vacío | Pegar la key real |
| `run.sh` aborta con `ERROR: OPENROUTER_API_KEY` | La regex `^OPENROUTER_API_KEY=sk-or-v1-.+` no matchea | Sin espacios ni comillas raras |
| "Sin modelos gratuitos ahora" | No hay pricing `"0"` en el catálogo | Revisar `last_error`; puede ser cambio de esquema |
| `401` / `User not found` | Key inválida o revocada | Generar otra |
| `402` / `Insufficient credits` | El modelo dejó de ser gratuito | Refrescar el pool |
| `Error interno: ...` siempre | Excepción no controlada; a menudo el generador perezoso | `DEBUG=true` y leer [limitaciones](#limitaciones-conocidas) |
| Modelo en amarillo para siempre | `status` queda en `backoff` tras expirar el cooldown | Cosmético: `is_available()` ya lo considera disponible |
| `BACKOFF_SECONDS` no tiene efecto | Arranque con `uvicorn server:app` | `./run.sh` o exportar variables |
| El texto llega de golpe | Un proxy buffereando | `X-Accel-Buffering: no` y `proxy_buffering off` |
| `Address already in use` | Otro proceso en 8000 | `PORT=8001 ./run.sh` o `lsof -i :8000` |
| `422 Unprocessable Entity` | `message` vacío o > 100000, o JSON mal formado | Revisar el body |
| UI en `offline` | Falló `/api/models` | Verificar backend |
| `GeneratorExit` en logs | El cliente cerró el stream | Normal |
| La key no se guarda | `localStorage` bloqueado | Usar `.env` |

Diagnóstico en cuatro comandos:

```bash
curl -s -o /dev/null -w '%{http_code}\n' http://localhost:8000/
curl -s http://localhost:8000/api/models | python3 -c 'import json,sys; d=json.load(sys.stdin); print(len(d["models"]), "modelos;", d["last_error"])'
curl -N -s -X POST http://localhost:8000/api/chat -H 'Content-Type: application/json' -d '{"message":"ping"}' | head -5
grep 'Intentando con modelo' mega-free-chat.log | tail -3
```

**"Funcionaba ayer y hoy no":** el modelo dejó de ser gratuito (mirá `len(models)`), se agotó la cuota diaria (`429` → cooldown → pool útil vacío), la key fue revocada, cambió el esquema del catálogo, o el `.env` cambió sin reiniciar.

---

## Limitaciones conocidas

1. **"Gratis" es temporal:** depende de promociones de terceros.
2. **El failover no atrapa errores del primer intento** (generador perezoso).
3. **Estado en RAM:** reiniciar borra cooldowns, contadores y pool.
4. **Sin autenticación ni rate limiting.**
5. **Bloqueo del event loop** por código síncrono en handlers `async`.
6. **Pool por petición** si la key viene de la UI.
7. **Precios comparados como string:** un `0` numérico dejaría el pool vacío. Conservador y frágil a la vez.
8. **Metadatos no se actualizan** al refrescar (se conserva el objeto previo por `id`).
9. **Historial sin validar en servidor.**
10. **Sin heartbeat SSE:** proxies con timeout pueden cortar antes del primer token.
11. **Sin tests automatizados** (verificación manual, descrita en la bitácora).
12. **UI sin Markdown, sin i18n y sin botón para borrar la key.**

Ninguna es un misterio: están en el código, en la bitácora y acá.

---

## Cómo se construyó este proyecto

Nació de una pregunta concreta: **¿se puede tener un chat decente usando solo lo que los proveedores regalan, sin que se rompa cuando uno se cae?**

| Commit | Qué pasó |
|---|---|
| `381d3d1` | Versión inicial: pasarela con failover y prioridad china. |
| `f129d08` | Se agregó API para microcontroladores y firmware ESP8266. |
| `272484f` | **Separación de repositorios:** este repo se quedó con la pasarela web. |
| `5247ad0` | Lanzador de escritorio tipo interruptor (dock). |
| `0133d0c` | Se reemplazó por `run.sh` en primer plano. |
| `da09a46` | Se quitó `launch.sh`: un solo ejecutable por proyecto. |

**Primer plano en lugar de daemon.** Los tres últimos commits de la tabla cuentan un retroceso consciente. Se probó un lanzador que arrancaba en segundo plano y se descartó: un proceso que no ves es un proceso que olvidás, y terminás con dos instancias peleando por el puerto 8000. `run.sh` usa `exec` y queda atado a la terminal: `Ctrl+C` y no queda nada. Menos features, menos sorpresas.

**La key en la UI.** Editar un archivo y reiniciar para probar otra key es fricción. El campo desplegable resolvió el 90 % de los casos personales; el costo —la key en cada body— se aceptó explícitamente y se documentó.

**Estilo terminal y prioridad visible.** Se descartaron burbujas y Markdown (el texto del modelo debía ser el protagonista, y de paso no se renderiza HTML ajeno); y en lugar de un `if` escondido, la prioridad china es una constante de proveedores, una lista de keywords y dos grupos en el panel.


**Verificación (2026-08-28, ejecución local):** `GET /` → 200 (sirve la UI); `GET /api/models` → 200 con **18 modelos gratuitos**; `POST /api/chat` → 200 con stream SSE completo; modelo elegido `inclusionai/ling-3.0-flash-fin:free`, coherente con la prioridad china; cierre del stream por el cliente (`GeneratorExit`, esperado). Sin tests automatizados: la verificación fue manual con `curl` y la UI, y la bitácora registra qué se probó y qué no.

---

## Estructura del repositorio

```
mega-free-chat/
├── .env.example · .gitignore · LICENSE · README.md
├── requirements.txt · run.sh · server.py
├── src/
│   ├── __init__.py
│   ├── models_pool.py        Pool, filtro $0, estado, clasificación china
│   ├── openrouter_client.py  Cliente OpenAI-compatible
│   └── router.py             Failover con prioridad
├── static/index.html         UI completa
└── docs/
    ├── datasheet.md · developer.md · REFERENCES.md · BITACORA.md
    └── assets/  architecture.svg · failover.svg · chat-flow.svg
```

No están (a propósito): `.env` (key real, ignorada), `.venv/` (reproducible), `*.log` (salida) y `__pycache__/` (bytecode).

---

## Documentación adicional

| Documento | Para quién | Contenido |
|---|---|---|
| [`docs/datasheet.md`](docs/datasheet.md) | Usuario final | Qué es, instalación, operación, endpoints, configuración, problemas |
| [`docs/developer.md`](docs/developer.md) | Desarrollador | Arquitectura, módulos, API interna, SSE, extensión, deuda técnica |
| [`docs/REFERENCES.md`](docs/REFERENCES.md) | Cualquiera | Fuentes oficiales de OpenRouter, SSE, FastAPI y SDK |
| [`docs/BITACORA.md`](docs/BITACORA.md) | Futuro yo / otros | Decisiones, descartes, lecciones |
| [`docs/assets/architecture.svg`](docs/assets/architecture.svg) | Visual | Capas, dependencias y flujo |
| [`docs/assets/failover.svg`](docs/assets/failover.svg) | Visual | Árbol de decisión y cooldowns |
| [`docs/assets/chat-flow.svg`](docs/assets/chat-flow.svg) | Visual | Secuencia navegador → FastAPI → OpenRouter |

---

## Referencias

- OpenRouter — keys: <https://openrouter.ai/keys> · docs: <https://openrouter.ai/docs>
- OpenRouter — catálogo: <https://openrouter.ai/api/v1/models> · referencia: <https://openrouter.ai/docs/api-reference/list-available-models> · límites: <https://openrouter.ai/docs/api-reference/limits>
- SSE — especificación: <https://html.spec.whatwg.org/multipage/server-sent-events.html> · guía MDN: <https://developer.mozilla.org/en-US/docs/Web/API/Server-sent_events/Using_server-sent_events> · formato: <https://developer.mozilla.org/en-US/docs/Web/API/Server-sent_events/Event-stream_format>
- FastAPI — `StreamingResponse`: <https://fastapi.tiangolo.com/advanced/custom-response/#streamingresponse> · docs: <https://fastapi.tiangolo.com/>
- Uvicorn: <https://www.uvicorn.org/> · OpenAI SDK: <https://github.com/openai/openai-python> · HTTPX: <https://www.python-httpx.org/> · python-dotenv: <https://github.com/theskumar/python-dotenv> · Pydantic: <https://docs.pydantic.dev/>

Sobre privacidad: cada proveedor declara si entrena con los datos; consultá la ficha del modelo antes de enviar información sensible.

---

## Licencia

MIT — ver [`LICENSE`](LICENSE).

```
Copyright (c) 2026 wanderc137
```

Se permite usar, copiar, modificar, fusionar, publicar, distribuir, sublicenciar y vender, con la condición de incluir el aviso de copyright y esta licencia. El software se entrega **sin garantía de ningún tipo**.

---

## Descargo final

Herramienta personal, publicada porque puede servir para aprender cómo funcionan un pool dinámico, un failover y un stream SSE. **No** es un servicio: no tiene soporte, no garantiza disponibilidad y no se responsabiliza del uso de las claves ni de los términos de los proveedores que consulta.
