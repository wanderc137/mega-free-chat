# Mega Free Chat — Documentación de desarrollador

**Audiencia:** quien va a leer, modificar o extender el código.
**Alcance:** arquitectura, módulos, contratos internos, deuda técnica y recetas de extensión.
**Versión documentada:** commit `da09a46`, rama `main`.

> Este documento asume que ya leíste el [README](../README.md) o el [datasheet](datasheet.md). Acá no se explica *qué hace* la app, sino *cómo está hecha* y *por qué*.

---

## Índice

1. [Mapa del código](#1-mapa-del-código)
2. [Arranque y orden de inicialización](#2-arranque-y-orden-de-inicialización)
3. [server.py — capa HTTP](#3-serverpy--capa-http)
4. [src/models_pool.py — el pool](#4-srcmodels_poolpy--el-pool)
5. [src/openrouter_client.py — el transporte](#5-srcopenrouter_clientpy--el-transporte)
6. [src/router.py — la política](#6-srcrouterpy--la-política)
7. [API interna](#7-api-interna)
8. [Contrato SSE](#8-contrato-sse)
9. [Frontend](#9-frontend)
10. [Recetas de extensión](#10-recetas-de-extensión)
11. [Deuda técnica priorizada](#11-deuda-técnica-priorizada)
12. [Trampas conocidas](#12-trampas-conocidas)
13. [Checklist de prueba manual](#13-checklist-de-prueba-manual)
14. [Convenciones](#14-convenciones)

---

## 1. Mapa del código

```
server.py                  108 líneas         Orquestación HTTP + SSE
src/models_pool.py         ~220 líneas        Catálogo + estado
src/openrouter_client.py   ~41 líneas         SDK openai → generador de texto
src/router.py              ~73 líneas         Orden + intentos
static/index.html          ~455 líneas        UI completa
run.sh                     31 líneas          Bootstrap de entorno
```

Cuatro módulos, una dirección de dependencias clara:

```
server.py
   ├── src.router.FreeModelRouter
   │        ├── src.models_pool.ModelsPool
   │        └── src.openrouter_client.OpenRouterClient
   └── src.models_pool.ModelsPool
```

`models_pool` no importa a nadie del proyecto. `openrouter_client` tampoco. `router` importa a ambos. `server` importa a todos. **No hay ciclos** y no debería haberlos: si necesitás que el pool llame al router, estás frente a un problema de diseño, no de imports.

### Qué NO existe (y conviene saber)

| Ausencia | Implicación |
|---|---|
| Base de datos | Todo el estado es RAM. Reiniciar = empezar de cero. |
| Migraciones | No aplica. |
| Capa de servicios/repositorios | Los módulos son la capa. |
| Inyección de dependencias | Se instancian objetos a mano; es suficiente para este tamaño. |
| Tests | No hay `tests/`, ni `pytest`, ni CI. Ver [checklist](#13-checklist-de-prueba-manual). |
| Docker | Se ejecuta con Python del sistema y un venv. |
| Logging estructurado | `logging` estándar con formato de texto. |

---

## 2. Arranque y orden de inicialización

`server.py` se ejecuta de arriba hacia abajo. El orden importa y explica varios comportamientos observables.

### 2.1 Secuencia real

```python
from dotenv import load_dotenv

# (1) imports de módulos del proyecto
from src.models_pool import ModelsPool
from src.openrouter_client import OpenRouterClient
from src.router import FreeModelRouter, RouterError

# (2) carga del .env
load_dotenv()

# (3) configuración derivada
API_KEY = os.getenv("OPENROUTER_API_KEY", "").strip()
DEBUG = os.getenv("DEBUG", "false").lower() == "true"
logging.basicConfig(...)
logger = logging.getLogger("mega_free_chat")

# (4) app y estáticos
app = FastAPI(title="Mega Free Chat")
app.mount("/static", StaticFiles(directory=APP_DIR / "static"), name="static")

# (5) router global (con la key del .env)
pool = ModelsPool(API_KEY)
client = OpenRouterClient(API_KEY)
router = FreeModelRouter(pool, client)
```

### 2.2 La consecuencia del orden

`models_pool.py` y `openrouter_client.py` leen `os.getenv(...)` **en el momento de importarse**, a nivel de módulo:

```python
# models_pool.py
BASE_URL = os.getenv("OR_BASE_URL", "https://openrouter.ai/api/v1")
REFRESH_SECONDS = int(os.getenv("POOL_REFRESH_SECONDS", "21600"))
BACKOFF_SECONDS = int(os.getenv("BACKOFF_SECONDS", "300"))

# openrouter_client.py
BASE_URL = os.getenv("OR_BASE_URL", "https://openrouter.ai/api/v1")
```

Como esos imports ocurren en (1) y `load_dotenv()` en (2), **las variables del `.env` no están disponibles todavía**. Resultado:

| Vía de arranque | `OPENROUTER_API_KEY` | `BACKOFF_SECONDS` | `POOL_REFRESH_SECONDS` | `OR_BASE_URL` |
|---|---|---|---|---|
| `./run.sh` (exporta el `.env` antes) | ✅ | ✅ | ✅ | ✅ |
| `uvicorn server:app` | ✅ (se lee tras `load_dotenv`) | ❌ default 300 | ❌ default 21600 | ❌ default OpenRouter |
| `python server.py` | ✅ | ❌ | ❌ | ❌ |

Si algún día se quiere arreglar sin tocar la arquitectura, hay dos caminos:

**Opción A — mover `load_dotenv()` al inicio absoluto de `server.py`** (antes de los imports del proyecto). Funciona, pero deja un import con efecto secundario y rompe si alguien importa `src.router` desde otro entrypoint.

**Opción B — leer la configuración en runtime** (la correcta):

```python
# models_pool.py
def _config() -> tuple[int, int]:
    return (int(os.getenv("BACKOFF_SECONDS", "300")),
            int(os.getenv("POOL_REFRESH_SECONDS", "21600")))
```

Y pasar esos valores al constructor de `ModelsPool`, en lugar de constantes de módulo. Es un refactor de 20 minutos y elimina la clase entera de bugs "cambié el `.env` y no pasa nada".

### 2.3 Construcción del router por petición

```python
@app.post("/api/chat")
async def chat(req: ChatRequest):
    if req.api_key:
        local_pool = ModelsPool(req.api_key)
        local_client = OpenRouterClient(req.api_key)
        active_router = FreeModelRouter(local_pool, local_client)
    else:
        active_router = router
```

Implicaciones, en orden de importancia:

1. **No hay caché por key.** Dos peticiones con la misma key crean dos pools distintos.
2. **Cada pool nuevo descarga el catálogo** en su primer `available_models()`. Es una llamada HTTP síncrona de ~1 s observada localmente.
3. **Los cooldowns no se comparten.** Un modelo que acaba de dar `429` con la key del navegador volverá a intentarse en el mensaje siguiente.
4. **El cliente `OpenAI` se recrea**, con su propio pool de conexiones `httpx`.

Un cache por hash de key resolvería 1–4:

```python
_ROUTERS: dict[str, FreeModelRouter] = {}
_LOCK = threading.Lock()

def router_for(key: str) -> FreeModelRouter:
    with _LOCK:
        r = _ROUTERS.get(key)
        if r is None:
            r = FreeModelRouter(ModelsPool(key), OpenRouterClient(key))
            _ROUTERS[key] = r
        return r
```

Falta política de expiración (una key por usuario puede crecer sin límite), pero para uso personal alcanza.

---

## 3. server.py — capa HTTP

### 3.1 Responsabilidades

- Cargar configuración y logging.
- Exponer tres rutas.
- Validar el body con Pydantic.
- Traducir el stream del router a eventos SSE.
- No decidir nada sobre modelos.

### 3.2 Modelo de entrada

```python
class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=100_000)
    history: list[dict] = Field(default_factory=list)
    api_key: str | None = None
```

| Campo | Validación | Nota de diseño |
|---|---|---|
| `message` | `1..100000` | El límite superior es defensivo, no semántico. |
| `history` | Sin validación de contenido | Se confía en el cliente; el proveedor pondrá el límite real. |
| `api_key` | Opcional, sin formato | No se valida el prefijo: una key mal formada fallará en OpenRouter con un error más informativo. |

`history` como `list[dict]` (y no `list[Message]`) es deliberado: permite pasar cualquier campo extra que el proveedor acepte (`name`, `tool_calls` en el futuro) sin migrar el modelo.

### 3.3 Serialización SSE

```python
def sse_payload(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
```

Detalles que importan:

- **`ensure_ascii=False`**: los acentos y emojis viajan como UTF-8, no como `\uXXXX`. El cliente debe decodificar como UTF-8 (la UI usa `TextDecoder`, que lo hace por defecto).
- **`json.dumps` compacto** (sin `indent`): un JSON multilínea rompería el framing de SSE, porque cada línea debe empezar con `data:`.
- **Doble `\n` final**: es el delimitador de evento del estándar.

### 3.4 Generador de eventos

La ruta construye un generador asíncrono que:

1. Emite `status: routing`.
2. Pide al router `(model_id, stream)`.
3. Emite `status: streaming` con el modelo.
4. Itera el stream y emite un `chunk` por fragmento.
5. Emite `done`.
6. Captura `RouterError` y `Exception`, emitiendo `error`.

Puntos finos:

- **El `try/except` de `RouterError` está fuera del bucle de chunks**, así que un fallo a mitad del stream cae en el `except Exception` genérico y emite `Error interno: ...`. No hay reintento a mitad de respuesta (lo cual sería incorrecto: el usuario ya vio texto parcial).
- **`RouterError` se distingue** para mostrar el detalle de los intentos sin el prefijo "Error interno".
- **No hay `finally` que emita nada**: si el cliente corta, el generador se cierra y el `GeneratorExit` aparece en el log del servidor. Es esperado.
- **No se hace `await` de nada asíncrono** dentro del bucle: la iteración del stream del SDK es síncrona. El `async def` existe porque `StreamingResponse` lo acepta, no porque haya concurrencia real.

### 3.5 Respuesta

```python
return StreamingResponse(
    event_stream(),
    media_type="text/event-stream",
    headers={
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
        "Connection": "keep-alive",
    },
)
```

`X-Accel-Buffering: no` es para Nginx; sin esa cabecera, un proxy inverso puede acumular todo el cuerpo y arruinar el streaming. `Cache-Control: no-cache` evita que un intermediario guarde la respuesta.

### 3.6 Bloque `__main__`

```python
if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
```

`0.0.0.0` es cómodo para probar desde el celular y riesgoso en redes compartidas. Está documentado en el README y en el datasheet; cambiarlo es una línea.

---

## 4. src/models_pool.py — el pool

### 4.1 Constantes de módulo

| Constante | Origen | Default | Uso |
|---|---|---|---|
| `BASE_URL` | `OR_BASE_URL` | `https://openrouter.ai/api/v1` | Endpoint del catálogo |
| `REFRESH_SECONDS` | `POOL_REFRESH_SECONDS` | `21600` | TTL del catálogo |
| `BACKOFF_SECONDS` | `BACKOFF_SECONDS` | `300` | Cooldown base |
| `CHINESE_PROVIDERS` | literal | 21 entradas | Clasificación por proveedor |
| `CHINESE_KEYWORDS` | literal | 9 regex | Clasificación por nombre |

### 4.2 Clasificación

```python
def is_chinese_model(model_id: str, name: str = "") -> bool:
    haystack = f"{model_id} {name}".lower()
    for p in CHINESE_PROVIDERS:
        if p in haystack:
            return True
    low_name = name.lower()
    for kw in CHINESE_KEYWORDS:
        if re.search(kw, low_name):
            return True
    return False
```

Decisiones:

- **Subcadena para proveedores**: `z-ai` aparece en `z-ai/glm-4.6`; `qwen` en `qwen/qwen3-...`. Barato y suficiente.
- **Regex con `\b` solo para nombres**: evita falsos positivos como `ling` dentro de `inkling`. Fue un bug real detectado durante el desarrollo y está en la bitácora.
- **`import re` dentro de la función**: no es lo ideal (se resuelve en cada llamada, aunque el módulo queda cacheado en `sys.modules`). Moverlo al tope es una mejora trivial de estilo.
- **Un solo `True` basta**: no hay puntuación ni ponderación. Si querés ranking fino, hace falta otra estructura (ver [recetas](#10-recetas-de-extensión)).

```python
def is_chat_model(model_id: str, name: str) -> bool:
    mid = model_id.lower()
    mname = name.lower()
    if mid.startswith("~"):          # alias flexibles
        return False
    if model_id == "openrouter/free":  # router comodín
        return False
    if "lyria" in mid or "lyria" in mname:  # generación musical
        return False
    return True
```

Es una **lista negra**, no blanca. Ventaja: los modelos nuevos entran solos. Riesgo: si aparece una categoría no-chat nueva (por ejemplo, embeddings), entrará al pool y fallará al intentar chatear. La alternativa —lista blanca por `architecture.modality == "text->text"`— es más correcta pero depende de que el catálogo lo declare bien. Está anotado como deuda.

### 4.3 `FreeModel`

Dataclass con dos grupos de campos: **metadatos** (del catálogo) y **estado** (mutado en runtime).

```python
@dataclass
class FreeModel:
    id: str
    name: str
    context_length: int = 0
    modalities: dict = field(default_factory=dict)
    supported_parameters: list = field(default_factory=list)
    is_chinese: bool = False

    status: str = "active"
    last_failure: str | None = None
    fail_count: int = 0
    cooldown_until: float = 0.0
```

Métodos:

| Método | Efecto |
|---|---|
| `is_available(now)` | `False` solo si `status == "backoff"` **y** `now < cooldown_until` |
| `mark_success()` | `status="active"`, `fail_count=0`, `last_failure=None`, `cooldown_until=0` |
| `mark_failure(error, status_code)` | `fail_count += 1`; cooldown base o doble si `429`; `status="backoff"` |
| `to_dict()` | Serialización para `/api/models` (incluye `cooldown_until` como epoch) |

La asimetría entre `status` y `cooldown_until` es intencional y tiene una consecuencia visible: **cuando el cooldown expira, el modelo vuelve a ser candidato aunque `status` siga en `backoff`**. La UI lo muestra amarillo un tiempo de más. Alternativas consideradas:

- Poner un timer que resetee `status` → complejidad y hilos innecesarios.
- Calcular `status` en `to_dict()` → más limpio; no se hizo por simplicidad.

Si querés arreglarlo sin tocar la lógica del router:

```python
def to_dict(self) -> dict:
    now = time.time()
    status = self.status
    if status == "backoff" and now >= self.cooldown_until:
        status = "active"
    return {..., "status": status}
```

### 4.4 `ModelsPool`

```python
class ModelsPool:
    def __init__(self, api_key: str) -> None:
        self.api_key = api_key
        self._models: list[FreeModel] = []
        self._lock = threading.Lock()
        self._last_fetch: float = 0.0
        self._last_error: str | None = None
```

| Método | Comportamiento |
|---|---|
| `_fetch_models()` | `GET {BASE_URL}/models`, timeout 30 s, filtra y construye `FreeModel`s |
| `refresh(force=False)` | Sale si `now - _last_fetch < REFRESH_SECONDS`; si no, descarga y hace merge |
| `available_models()` | `refresh()` + filtra por `is_available(time.time())` |
| `all_models()` | `refresh()` + copia de la lista |
| `mark_success(id)` | Delega en el modelo |
| `mark_failure(id, error, code)` | Delega en el modelo |
| `to_payload()` | `{updated_at, last_error, models[]}` |

#### El merge del refresco

```python
prev = {m.id: m for m in self._models}
merged = []
for fm in fetched:
    merged.append(prev.get(fm.id, fm))
self._models = merged
```

Conserva el **objeto previo completo** si el `id` ya existía. Consecuencias:

- Bien: no se pierden cooldowns ni contadores al refrescar.
- Mal: **no se actualizan `name`, `context_length`, `modalities` ni `is_chinese`**. Si un proveedor renombra un modelo o le cambia el contexto, la app sigue mostrando el dato viejo hasta reiniciar el proceso.
- Peor: si un modelo sale del catálogo, desaparece de la lista y **también su estado**. Si vuelve, entra limpio. Aceptable.

Arreglo mínimo, conservando solo el estado:

```python
old = prev.get(fm.id)
if old:
    fm.status = old.status
    fm.fail_count = old.fail_count
    fm.last_failure = old.last_failure
    fm.cooldown_until = old.cooldown_until
merged.append(fm)
```

#### Concurrencia

`threading.Lock` protege `_models`, `_last_fetch` y `_last_error`. Es suficiente para Uvicorn con un worker y varios hilos. **No** protege entre procesos: con `--workers 4` hay cuatro pools independientes, cuatro catálogos y cuatro conjuntos de cooldowns. Si alguna vez se escala así, el estado tiene que salir de RAM (Redis, por ejemplo).

`refresh()` toma el lock para chequear el TTL, **lo suelta** para hacer la descarga y lo vuelve a tomar para escribir. Eso permite dos descargas simultáneas si dos peticiones llegan a la vez con el TTL vencido. No es un problema grave (una gana), pero es un patrón "check-then-act" que un lock único alrededor de todo el método evitaría a costa de bloquear más tiempo. Está anotado.

#### Manejo de errores

```python
except Exception as exc:
    self._last_error = str(exc)
    logger.warning("No se pudo actualizar el pool: %s", exc)
```

El pool **nunca lanza por un fallo de red**: conserva la lista anterior y expone el error. Es la decisión correcta para un servicio que debe seguir respondiendo con datos viejos antes que caerse. `raise_for_status()` convierte 4xx/5xx en excepción, atrapada acá.

---

## 5. src/openrouter_client.py — el transporte

```python
class OpenRouterClient:
    def __init__(self, api_key: str) -> None:
        self.client = OpenAI(
            api_key=api_key,
            base_url=BASE_URL,
            default_headers={
                "HTTP-Referer": "http://localhost:8000",
                "X-Title": APP_NAME,
            },
        )
```

- Se usa el SDK de **OpenAI**, no un cliente específico de OpenRouter. OpenRouter implementa el mismo contrato (`/chat/completions`), así que el SDK funciona sin cambios. Ventaja: streaming, tipado y manejo de errores gratis.
- `HTTP-Referer` y `X-Title` son cabeceras de atribución que OpenRouter documenta para apps. Si desplegás en otro dominio, actualizá el referer.
- El cliente `OpenAI` instancia internamente un `httpx.Client`. Crear uno por petición (caso key del navegador) implica un pool de conexiones nuevo cada vez.

```python
def chat_stream(self, model_id: str, messages: list[dict]):
    resp = self.client.chat.completions.create(
        model=model_id,
        messages=messages,
        stream=True,
    )
    for chunk in resp:
        if chunk.choices and chunk.choices[0].delta and chunk.choices[0].delta.content:
            yield chunk.choices[0].delta.content
```

### 5.1 Por qué es un generador (y por qué eso importa)

La presencia de `yield` convierte a `chat_stream` en una **función generadora**. Llamarla **no ejecuta nada**: devuelve un objeto generador. La petición HTTP ocurre en el primer `next()`.

Esto tiene una consecuencia directa en el router, que se analiza en la sección siguiente. Es **la** trampa del proyecto.

### 5.2 Filtrado de chunks

- `chunk.choices` puede venir vacío (chunks de uso o de metadatos).
- `delta.content` puede ser `None` (chunk inicial con `role`, chunk final con `finish_reason`).
- Solo se emite texto no vacío. Los `tool_calls` y el `reasoning_content` se descartan.

Si quisieras soportar `reasoning_content` (modelos con razonamiento explícito), habría que emitir un tipo de chunk distinto y que la UI lo renderice aparte. No está implementado.

### 5.3 Errores

El SDK lanza:

| Excepción | Cuándo |
|---|---|
| `openai.RateLimitError` | HTTP 429 |
| `openai.APIStatusError` | Otros 4xx/5xx (tiene `.status_code`) |
| `openai.APIConnectionError` | DNS, TCP, TLS, timeout de conexión |
| `openai.APITimeoutError` | Timeout de lectura (subclase de `APIConnectionError`) |
| `openai.APIError` | Base de todas |

**No hay timeout configurado explícitamente** en el `OpenAI(...)`. El SDK aplica sus defaults (10 minutos para lecturas, en versiones recientes). Para un chat gratuito con proveedores lentos, conviene fijarlo:

```python
self.client = OpenAI(..., timeout=60.0, max_retries=0)
```

`max_retries=0` es importante: los reintentos internos del SDK **enmascaran** el failover y multiplican la latencia. Hoy el SDK reintenta por su cuenta en algunos errores, lo que puede hacer que un `429` tarde más de lo esperado antes de llegar al router.

---

## 6. src/router.py — la política

### 6.1 Contrato

```python
def stream(self, messages: list[dict]):
    """Devuelve (model_id, iterable_de_fragmentos) del primer modelo que responde."""
```

Devuelve una tupla, no un objeto. Simple y suficiente. Si mañana hay que devolver más metadatos (intentos, latencia), conviene una dataclass `RoutingResult`.

### 6.2 Orden

```python
candidates = sorted(available, key=lambda m: (not m.is_chinese, m.name.lower()))
```

- `not m.is_chinese` → `False` (0) para chinos, `True` (1) para el resto.
- Dentro de cada grupo, alfabético por `name`.
- `sorted` es estable: si dos modelos tienen el mismo nombre, conservan el orden del catálogo.

**No hay aleatorización.** Es una decisión: el comportamiento predecible facilita el debugging y hace que los logs sean comparables entre ejecuciones. El costo es que siempre se golpea primero al mismo modelo, lo que puede concentrar el rate limit. Una alternativa razonable sería rotar el punto de partida:

```python
import random
chinos = [m for m in available if m.is_chinese]
otros = [m for m in available if not m.is_chinese]
random.shuffle(chinos); random.shuffle(otros)
candidates = sorted(chinos, key=...) + sorted(otros, key=...)
```

### 6.3 Mapeo de excepciones

```python
except RateLimitError as exc:
    self.pool.mark_failure(model.id, str(exc), 429)
    attempts.append(f"{model.id}: rate limit (429)")
except APIStatusError as exc:
    self.pool.mark_failure(model.id, str(exc), exc.status_code)
    attempts.append(f"{model.id}: HTTP {exc.status_code}")
except APIConnectionError as exc:
    self.pool.mark_failure(model.id, str(exc), None)
    attempts.append(f"{model.id}: error de conexión")
except Exception as exc:
    self.pool.mark_failure(model.id, str(exc), None)
    attempts.append(f"{model.id}: {exc}")
```

El orden de los `except` importa: `RateLimitError` es subclase de `APIStatusError`, así que debe ir primero. `APIConnectionError` no deriva de `APIStatusError`, pero sí de `APIError`.

`attempts` acumula strings legibles que terminan en el mensaje de `RouterError`. Es un log de intentos para el usuario, no una estructura para máquina. Si un cliente quisiera reintentar selectivamente, necesitaría un JSON con códigos.

### 6.4 El problema del generador perezoso

Este es el punto más importante del documento.

```python
stream = self.client.chat_stream(model.id, messages)   # NO hace la petición
self.pool.mark_success(model.id)                        # se marca éxito sin saber si funcionó
return model.id, stream                                 # el error ocurrirá después
```

Como `chat_stream` contiene `yield`, la llamada solo construye el generador. La petición HTTP se dispara cuando `server.py` hace `for fragment in stream`. Ese `for` está **fuera** del `try` del router.

Consecuencias observables:

| Escenario | Comportamiento real |
|---|---|
| Primer modelo responde bien | Todo funciona; el failover no se nota |
| Primer modelo devuelve 429 | La excepción surge en `server.py`, se emite `error`, **no se prueba el siguiente** |
| Primer modelo devuelve 503 | Igual |
| Primer modelo tarda y luego falla | Igual, con la latencia sumada |
| `mark_success` / `mark_failure` | Se ejecutan antes de saber el resultado; el estado del pool queda incorrecto |

En el log local del 2026-08-28 no se observó ningún `429`, por lo que el camino de fallo no se ejercitó en esa ejecución. La limitación se detectó leyendo el flujo, no en producción.

**Fix recomendado (mínimo, preserva streaming):**

```python
import itertools

for model in candidates:
    try:
        gen = self.client.chat_stream(model.id, messages)
        first = next(gen)                      # aquí se lanza la petición real
        self.pool.mark_success(model.id)
        return model.id, itertools.chain([first], gen)
    except StopIteration:
        # el modelo respondió con stream vacío: se considera éxito sin texto
        self.pool.mark_success(model.id)
        return model.id, iter(())
    except RateLimitError as exc:
        ...
```

**Alternativa más limpia:** que `chat_stream` no sea generador, sino que devuelva `(primer_fragmento, resto_iterable)` o un objeto `ChatStream` con un método `__iter__` que haga la llamada en el constructor. Cualquiera de las dos hace que el `try/except` tenga sentido.

**Por qué no está arreglado:** el proyecto se documenta en el estado en que está. El fix está identificado, es pequeño y está en la lista de deuda con prioridad alta. No se aplicó porque esta documentación no modifica código.

### 6.5 `RouterError`

```python
class RouterError(Exception):
    """Error final cuando ningún modelo gratuito respondió."""
```

No lleva atributos estructurados: el detalle va en el mensaje (`"Todos los modelos gratuitos fallaron. Detalle: ..."`). Para un cliente que quiera distinguir "sin modelos" de "todos fallaron", conviene separar en dos excepciones o agregar un campo `attempts: list[dict]`.

---

## 7. API interna

### `src.models_pool`

| Firma | Devuelve | Notas |
|---|---|---|
| `is_chinese_model(model_id: str, name: str = "") -> bool` | `bool` | Subcadena de proveedor o regex de keyword |
| `is_chat_model(model_id: str, name: str) -> bool` | `bool` | Lista negra: alias `~`, `openrouter/free`, Lyria |
| `FreeModel.is_available(now: float) -> bool` | `bool` | `False` si `backoff` y `now < cooldown_until` |
| `FreeModel.mark_success() -> None` | — | Resetea estado |
| `FreeModel.mark_failure(error: str, status_code: int \| None = None) -> None` | — | Cooldown ×2 si 429 |
| `FreeModel.to_dict() -> dict` | `dict` | Payload de la UI |
| `ModelsPool(api_key: str)` | — | Estado vacío hasta el primer `refresh` |
| `ModelsPool.refresh(force: bool = False) -> None` | — | No lanza; anota `_last_error` |
| `ModelsPool.available_models() -> list[FreeModel]` | lista | Refresca si toca |
| `ModelsPool.all_models() -> list[FreeModel]` | lista | Incluye los que están en cooldown |
| `ModelsPool.mark_success(model_id: str) -> None` | — | Busca y delega |
| `ModelsPool.mark_failure(model_id: str, error: str, status_code: int \| None) -> None` | — | Busca y delega |
| `ModelsPool.to_payload() -> dict` | `dict` | `{updated_at, last_error, models}` |

### `src.openrouter_client`

| Firma | Devuelve | Notas |
|---|---|---|
| `OpenRouterClient(api_key: str)` | — | Crea `OpenAI` con `base_url` y cabeceras |
| `OpenRouterClient.chat_stream(model_id: str, messages: list[dict])` | generador de `str` | **Perezoso**: la petición ocurre al iterar |

### `src.router`

| Firma | Devuelve | Notas |
|---|---|---|
| `FreeModelRouter(pool, client)` | — | Inyección por constructor |
| `FreeModelRouter.stream(messages: list[dict])` | `(str, Iterable[str])` | Lanza `RouterError` si no hay candidatos o todos fallan |
| `RouterError` | excepción | Mensaje con el detalle de los intentos |

### `server`

| Firma | Devuelve | Notas |
|---|---|---|
| `ChatRequest` | modelo Pydantic | `message`, `history`, `api_key` |
| `sse_payload(event: str, data: dict) -> str` | `str` | Bloque SSE completo |
| `index()` | HTML | Sirve `static/index.html` |
| `get_models()` | JSON | `pool.to_payload()` |
| `chat(req: ChatRequest)` | `StreamingResponse` | SSE |

---

## 8. Contrato SSE

### 8.1 Forma del mensaje

```
event: <tipo>\n
data: <json>\n
\n
```

### 8.2 Tabla de eventos

| `event` | `data` | Cuándo | ¿Obligatorio? |
|---|---|---|---|
| `status` | `{"state": "routing"}` | Al abrir | Sí, primero |
| `status` | `{"state": "streaming", "model": "<id>"}` | Modelo aceptado | Sí, antes del primer chunk |
| `chunk` | `{"content": "<texto>"}` | Por fragmento | Puede haber 0..N |
| `done` | `{"model": "<id>"}` | Fin normal | Sí, en éxito |
| `error` | `{"message": "<texto>"}` | Fallo | Sí, en error |

### 8.3 Invariantes que un cliente puede asumir

1. El primer evento es `status: routing`.
2. Si hay texto, antes del primer `chunk` llegó `status: streaming` con el modelo.
3. Los `chunk` se concatenan en orden; no hay huecos ni reordenamiento.
4. `done` y `error` son mutuamente excluyentes y terminales.
5. El status HTTP es 200 incluso en error de aplicación.

### 8.4 Invariantes que **no** se pueden asumir

1. Que llegue `done`: el proceso puede morir, el proxy puede cortar.
2. Que haya un `chunk` por palabra.
3. Que el `model` de `done` coincida con el último `status` (en la práctica coincide).
4. Que el stream cierre con `\n\n` si el cliente corta antes.

### 8.5 Compatibilidad

El formato es SSE estándar, así que `EventSource` del navegador *podría* consumirlo — pero `EventSource` solo hace GET y no permite body, por eso la UI usa `fetch` + `ReadableStream`. Cualquier librería SSE de terceros que soporte POST sirve.

---

## 9. Frontend

### 9.1 Estructura

Un solo archivo con tres bloques: `<style>`, HTML semántico mínimo y `<script>`.

```
static/index.html
├── :root { variables de color }
├── header (título, keybox, pill de conexión)
├── .layout
│   ├── aside  → #models (panel)
│   └── main   → #chat + #inputbar
└── <script>
    ├── estado: history[], activeModel
    ├── addMsg / lastBotEl / escapeHtml
    ├── loadModels / modelCard
    ├── send (fetch + parser SSE)
    ├── gestión de la key
    └── listeners + setInterval
```

### 9.2 Estado

| Variable | Tipo | Persistencia |
|---|---|---|
| `history` | `Array<{role, content}>` | Memoria de la pestaña |
| `activeModel` | `string` | Memoria; se usa para resaltar |
| `megaFreeChat_apiKey` | `string` | `localStorage` |

`history` se recorta con `slice(-30)` al recibir `done`. Son **elementos**, no turnos: 15 pares.

### 9.3 Parser SSE

```javascript
buffer += decoder.decode(value, { stream: true });
const events = buffer.split('\n\n');
buffer = events.pop();
```

Tres detalles que suelen romperse en implementaciones caseras:

1. **`{ stream: true }`** en `TextDecoder`: sin eso, un carácter UTF-8 partido entre dos paquetes se corrompe.
2. **`buffer = events.pop()`**: el último bloque puede estar incompleto y debe conservarse para la próxima lectura.
3. **Buscar las líneas por prefijo** (`startsWith('event:')`), no por posición: el orden de las líneas no está garantizado por el estándar.

### 9.4 Renderizado seguro

- El cuerpo del mensaje se asigna con `textContent`, nunca `innerHTML`. Un modelo que devuelva `<script>` se muestra como texto.
- En el panel, `modelCard` usa `innerHTML` con plantilla, pero pasa `m.name` y `m.id` por `escapeHtml()`. El campo `m.status` se interpola sin escapar en el atributo `class` (`st-<status>`); viene de un enum controlado por el servidor, así que el riesgo es bajo, pero **no es cero** si el backend se compromete. Endurecerlo es trivial:

```javascript
const SAFE_STATUS = new Set(['active', 'backoff', 'failed']);
const st = SAFE_STATUS.has(m.status) ? m.status : 'failed';
```

### 9.5 Gestión de la key

| Acción | Efecto |
|---|---|
| Click en **API key** | Abre el campo (si estaba cerrado) o lo cierra |
| Enter / **Guardar** | `localStorage.setItem`, cierra, actualiza UI |
| Escape | Cierra sin guardar |
| `focus` en el input | El botón vuelve a decir "API key" |
| `blur` | `updateKeyUI()` restaura el texto según haya o no clave |

No hay validación de formato en el cliente: cualquier cadena se guarda. La validación real la hace OpenRouter.

### 9.6 Envío

`send()`:

1. Lee y limpia el textarea.
2. Pinta el mensaje del usuario.
3. Deshabilita el botón.
4. Muestra "Pensando...".
5. `fetch` con `{message, history, api_key}`.
6. Lee el body con `getReader()` y procesa eventos.
7. En `done`, actualiza `history`.
8. En `finally`, rehabilita el botón y enfoca el textarea.

No hay `AbortController`: si el usuario quiere cancelar, no puede (salvo recargar). Agregarlo es media hora de trabajo y una mejora de UX evidente.

### 9.7 Polling

`setInterval(loadModels, 20000)`. No se limpia nunca (la página vive hasta que se cierra). Si el backend está caído, cada 20 s hay un fetch fallido y la píldora pasa a `offline`; no hay backoff exponencial.

---

## 10. Recetas de extensión

### 10.1 Añadir un proveedor chino

```python
# src/models_pool.py
CHINESE_PROVIDERS = (
    ..., "nuevo-proveedor",
)
```

Si el nombre no contiene el id del proveedor, agregá una keyword:

```python
CHINESE_KEYWORDS = (..., r"\bnuevo-modelo\b")
```

Verificá con:

```bash
python -c "from src.models_pool import is_chinese_model as f; print(f('nuevo-proveedor/x', 'X'))"
```

### 10.2 Cambiar el criterio de orden

Todo vive en una línea de `src/router.py`:

```python
# Priorizar contexto largo dentro de los chinos
key=lambda m: (not m.is_chinese, -m.context_length)

# Alfabético puro
key=lambda m: m.name.lower()

# Los que menos fallaron primero
key=lambda m: (not m.is_chinese, m.fail_count, m.name.lower())
```

### 10.3 Soportar modelos de pago

El filtro está en `_fetch_models`:

```python
if pricing.get("prompt") == "0" and pricing.get("completion") == "0":
```

Para aceptar también los pagos, quitá la condición (y renombrá el proyecto, porque deja de ser "free"). Una variante útil es un flag:

```python
ALLOW_PAID = os.getenv("ALLOW_PAID", "false") == "true"
if ALLOW_PAID or (pricing.get("prompt") == "0" and pricing.get("completion") == "0"):
```

### 10.4 Persistir el estado del pool

`ModelsPool` es serializable casi entero. Un JSON en disco con `{id: {status, fail_count, cooldown_until}}` y carga en `__init__` alcanza. Cuidado con los `cooldown_until` absolutos: si el reloj cambió o pasó mucho tiempo, conviene guardar `cooldown_remaining` en lugar de epoch.

### 10.5 Volver asíncrono el cliente

El cambio grande, y el que más rendimiento daría:

```python
from openai import AsyncOpenAI

class AsyncOpenRouterClient:
    def __init__(self, api_key: str):
        self.client = AsyncOpenAI(api_key=api_key, base_url=BASE_URL)

    async def chat_stream(self, model_id, messages):
        resp = await self.client.chat.completions.create(
            model=model_id, messages=messages, stream=True
        )
        async for chunk in resp:
            ...
```

Requiere que `router.stream` sea `async` y que `event_stream` haga `async for`. Es un refactor de unas 50 líneas, con el beneficio de no bloquear el event loop durante la espera del proveedor.

### 10.6 Añadir heartbeat SSE

Para sobrevivir a proxies con timeout de inactividad:

```python
yield ": ping\n\n"   # comentario SSE, ignorado por los clientes
```

Cada 15 s mientras se espera el primer token. Los clientes actuales lo ignoran porque no tiene `data:`; el parser de la UI lo descarta solo (`if (!dataLine) continue`).

### 10.7 Agregar un endpoint de salud

```python
@app.get("/healthz")
def healthz():
    return {"ok": True, "models": len(pool.all_models())}
```

Útil para un proxy o un monitor. No existe hoy.

### 10.8 Tests

No hay. El punto de entrada más rentable es el router, porque es lógica pura con dos colaboradores fáciles de falsear:

```python
class FakeClient:
    def __init__(self, fail: set[str]):
        self.fail = fail
    def chat_stream(self, model_id, messages):
        if model_id in self.fail:
            raise RateLimitError(...)   # requiere construir la excepción del SDK
        return iter(["hola"])
```

Con `pytest` y `monkeypatch` sobre `time.time()` se pueden probar cooldowns sin esperar. Ese es el test que primero escribiría.

---

## 11. Deuda técnica priorizada

| # | Problema | Impacto | Esfuerzo | Prioridad |
|---|---|---|---|---|
| 1 | Failover no atrapa errores del primer intento (generador perezoso) | Alto: la feature principal no funciona en el camino de fallo | Bajo (10 líneas) | **Alta** |
| 2 | Pool/cliente por petición cuando la key viene de la UI | Medio: latencia y cooldowns perdidos | Bajo (caché por hash) | **Alta** |
| 3 | Bloqueo del event loop (sync dentro de async) | Medio: concurrencia serializada | Medio | Media |
| 4 | `status` no se resetea al expirar el cooldown | Bajo: cosmético en la UI | Bajo | Media |
| 5 | Config leída en import time | Medio: `.env` ignorado según el arranque | Bajo | Media |
| 6 | Metadatos no se actualizan en el merge | Bajo: datos viejos hasta reiniciar | Bajo | Media |
| 7 | Sin timeout explícito ni `max_retries=0` | Medio: latencias impredecibles | Bajo | Media |
| 8 | Sin tests | Alto a largo plazo | Medio | Media |
| 9 | Sin heartbeat SSE | Bajo: depende del proxy | Bajo | Baja |
| 10 | Sin `AbortController` en la UI | Bajo: UX | Bajo | Baja |
| 11 | `import re` dentro de función | Trivial | Trivial | Baja |
| 12 | Filtro de no-chat por lista negra | Bajo: puede colarse un modelo no-chat | Medio | Baja |
| 13 | Sin autenticación ni rate limit | Alto **si se expone**; nulo en local | Medio | Según despliegue |

---

## 12. Trampas conocidas

1. **`chat_stream` no hace nada hasta que se itera.** Cualquier código que lo llame y espere errores en el `try` está equivocado.
2. **`load_dotenv()` llega tarde.** Ver [§2.2](#22-la-consecuencia-del-orden).
3. **`status == "backoff"` no significa "no disponible".** La verdad está en `is_available()`.
4. **El merge conserva objetos viejos.** Un cambio de nombre en el catálogo no se ve hasta reiniciar.
5. **`RateLimitError` hereda de `APIStatusError`.** El orden de los `except` no es opcional.
6. **`StreamingResponse` con 200 en errores.** Un cliente que solo mira el status code se pierde el error.
7. **`\n\n` es el delimitador.** Un `json.dumps` con `indent` rompería todo.
8. **`ensure_ascii=False` requiere decodificar UTF-8.** `TextDecoder` sin charset explícito usa UTF-8, pero un cliente en otro lenguaje debe saberlo.
9. **`--reload` borra el pool.** Depurar cooldowns con recarga automática es una mala idea.
10. **Varios workers = varios pools.** No compartas estado en RAM si algún día usás `--workers`.
11. **`GeneratorExit` en el log no es un bug.** Es el cliente cerrando el stream.
12. **`DEBUG=true` es muy verboso.** Incluye `httpx`/`httpcore` a nivel DEBUG.

---

## 13. Checklist de prueba manual

No hay suite automatizada. Esta es la lista que se ejecutó (y se puede repetir) para validar un cambio:

### Arranque

- [ ] `./run.sh` crea `.venv` si no existe y no falla si ya existe.
- [ ] Sin `.env`, copia `.env.example` y aborta por key placeholder.
- [ ] Con key válida, Uvicorn escucha en `:8000`.
- [ ] `GET /` devuelve 200 y el HTML.

### Pool

- [ ] `GET /api/models` devuelve `models` no vacío con la red disponible.
- [ ] Todos los `pricing` del catálogo filtrado son `"0"`.
- [ ] No aparecen ids que empiecen con `~` ni `openrouter/free`.
- [ ] Los modelos chinos tienen `is_chinese: true`.
- [ ] El log muestra `Pool actualizado: N modelos gratuitos disponibles`.

### Chat

- [ ] `POST /api/chat` con `{"message":"hola"}` devuelve eventos SSE.
- [ ] El primer evento es `status: routing`.
- [ ] Llega `status: streaming` con un `model`.
- [ ] Los `chunk` se concatenan y forman una respuesta coherente.
- [ ] Llega `done` con el mismo modelo.
- [ ] `message` vacío devuelve 422.
- [ ] `message` de 100 001 caracteres devuelve 422.

### UI

- [ ] El panel muestra dos grupos con contadores.
- [ ] El modelo activo se resalta en verde con "EN USO".
- [ ] El botón de la key abre, guarda, colapsa y muestra `••••••`.
- [ ] Recargar la página conserva la key (localStorage).
- [ ] Enter envía; Shift+Enter hace salto de línea.
- [ ] El botón se deshabilita durante la respuesta.
- [ ] El texto aparece incrementalmente, no de golpe.

### Fallos

- [ ] Con una key inválida, el error se ve en el stream.
- [ ] Con la red caída, la app no se cuelga y reporta el error.
- [ ] Si todos los modelos están en cooldown, el mensaje es el esperado.
- [ ] Cerrar la pestaña a mitad del stream no rompe el servidor (`GeneratorExit` en el log).

> **Nota:** el punto "failover salta al siguiente modelo" **no se puede marcar** con el código actual, por la limitación del generador perezoso. La prueba correcta sería forzar un 429 en el primer candidato y verificar que responde el segundo; hoy fallaría. Está así documentado a propósito.

---

## 14. Convenciones

| Aspecto | Convención |
|---|---|
| Idioma del código | Docstrings y comentarios en español; nombres de API en inglés (`chat_stream`, `available_models`) |
| Tipos | Anotaciones en todas las firmas; `from __future__ import annotations` en los módulos de `src/` |
| Formato | 4 espacios, líneas ≤ 100, comillas dobles |
| Logging | `logging.getLogger("mega_free_chat.<módulo>")` |
| Errores | Excepciones específicas del SDK se atrapan en el router; el pool nunca propaga fallos de red |
| Estado | En RAM, protegido por `threading.Lock` cuando se comparte |
| Secretos | Solo por `.env` o por body; nunca en código ni en logs |
| UI | Sin frameworks, sin build, sin dependencias externas |

### Sobre la ausencia de dependencias de frontend

Es una decisión de mantenibilidad, no una limitación técnica. Cualquier persona con un editor puede abrir `static/index.html` y entenderlo. A cambio, se renuncia a reactividad, componentes y herramientas. Para una UI de tres paneles, el intercambio es favorable.

### Sobre los comentarios

El código tiene pocos comentarios y los que hay explican **por qué**, no **qué**. Ejemplo:

```python
# 429 (rate limit) => backoff largo; otros errores => backoff corto
cooldown = BACKOFF_SECONDS
if status_code == 429:
    cooldown = BACKOFF_SECONDS * 2
```

La intención es que el "qué" se lea del código. Si agregás lógica no obvia, seguí esa regla.

---

## Apéndice: diagramas

| Diagrama | Contenido |
|---|---|
| [`assets/architecture.svg`](assets/architecture.svg) | Capas, dependencias y frontera con OpenRouter |
| [`assets/failover.svg`](assets/failover.svg) | Árbol de decisión, cooldowns y estados |
| [`assets/chat-flow.svg`](assets/chat-flow.svg) | Secuencia temporal de un mensaje |

---

*Licencia MIT — Copyright (c) 2026 wanderc137. Este documento describe el código tal como está; si el código cambia, el documento debe cambiar con él.*
