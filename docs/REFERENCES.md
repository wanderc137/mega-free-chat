# Referencias — Mega Free Chat

**Propósito:** reunir las fuentes que sostienen las decisiones técnicas del proyecto, con el motivo por el que cada una es relevante. No es una bibliografía decorativa: cada enlace se usó (o se debió usar) para construir, depurar o documentar algo concreto.

**Fecha de recopilación:** agosto de 2026. Las URLs de documentación cambian; si un enlace devuelve 404, buscá el título del recurso en el sitio oficial.

---

## 1. OpenRouter

| Recurso | URL | Para qué se usó |
|---|---|---|
| Portal / gestión de claves | <https://openrouter.ai/keys> | Crear y revocar la API key `sk-or-v1-...` |
| Documentación general | <https://openrouter.ai/docs> | Contrato de la API compatible con OpenAI, cabeceras de atribución |
| Catálogo de modelos (JSON) | <https://openrouter.ai/api/v1/models> | Endpoint que consume `ModelsPool._fetch_models()` |
| Referencia: listar modelos | <https://openrouter.ai/docs/api-reference/list-available-models> | Campos `id`, `name`, `context_length`, `pricing`, `supported_parameters` |
| Límites y rate limits | <https://openrouter.ai/docs/api-reference/limits> | Interpretación del `429` y de las cuotas gratuitas |
| Enrutamiento de proveedores | <https://openrouter.ai/docs/features/provider-routing> | Contexto de por qué un mismo modelo puede fallar de formas distintas |

### Qué se toma de cada una

- **Del catálogo:** el objeto `pricing` con `prompt` y `completion` como **cadenas**. El filtro `== "0"` depende de ese detalle; si OpenRouter cambia el tipo, el pool queda vacío.
- **De los límites:** que un `429` no es un error transitorio de red, sino una señal de cuota. De ahí el cooldown doble.
- **Del enrutamiento:** que un `id` de modelo no es un servidor único; detrás puede haber varios proveedores con disponibilidad distinta.

> **Nota de verificación:** el esquema exacto (`pricing` como string) se comprobó contra una respuesta real del catálogo durante el desarrollo. No se asume que sea eterno: está anotado como fragilidad conocida en el README y en la bitácora.

---

## 2. Server-Sent Events (SSE)

| Recurso | URL | Para qué se usó |
|---|---|---|
| Especificación WHATWG | <https://html.spec.whatwg.org/multipage/server-sent-events.html> | Formato `event:` / `data:` y delimitador `\n\n` |
| Guía MDN — uso | <https://developer.mozilla.org/en-US/docs/Web/API/Server-sent_events/Using_server-sent_events> | Conceptos de stream unidireccional y reconexión |
| Referencia MDN — formato | <https://developer.mozilla.org/en-US/docs/Web/API/Server-sent_events/Event-stream_format> | Campos `id`, `retry`, comentarios (`:`) |
| `EventSource` (MDN) | <https://developer.mozilla.org/en-US/docs/Web/API/EventSource> | Por qué **no** se usa: solo admite GET y sin body |

### Decisiones derivadas

1. **Se usa SSE y no WebSocket** porque el flujo es unidireccional (servidor → cliente) y el transporte es HTTP normal: no hace falta handshake ni framing binario.
2. **Se usa `fetch` + `ReadableStream` y no `EventSource`** porque el mensaje del usuario viaja en un `POST` con body JSON. `EventSource` no permite body.
3. **No se implementan `id:` ni `retry:`** porque no hay reanudación: si el stream se corta, el turno se perdió. Agregarlos sin lógica de reanudación sería decorativo.
4. **No hay heartbeat** (comentarios `: ping`). Es una mejora pendiente para proxies con timeout de inactividad.

### Lectura recomendada del estándar

- La sección de **parsing** explica por qué el cliente debe acumular y partir por una línea en blanco: los paquetes TCP no respetan los límites de evento.
- La sección de **reconnection** explica el `Last-Event-ID`, que este proyecto no usa.

---

## 3. FastAPI y Starlette

| Recurso | URL | Para qué se usó |
|---|---|---|
| `StreamingResponse` | <https://fastapi.tiangolo.com/advanced/custom-response/#streamingresponse> | Envolver el generador de eventos |
| Respuestas personalizadas | <https://fastapi.tiangolo.com/advanced/custom-response/> | Cabeceras y media type |
| Dependencias y ciclo de vida | <https://fastapi.tiangolo.com/advanced/events/> | Contexto de por qué el estado vive en el proceso |
| Documentación general | <https://fastapi.tiangolo.com/> | Validación con Pydantic, rutas |
| Starlette — responses | <https://www.starlette.io/responses/> | Comportamiento real de `StreamingResponse` (Starlette es la base) |
| Starlette — static files | <https://www.starlette.io/staticfiles/> | Montaje de `/static` |

### Puntos finos aprendidos

- `StreamingResponse` acepta generadores síncronos y asíncronos. Un generador síncrono se ejecuta en un hilo del pool, no en el event loop; eso **mitiga parcialmente** el bloqueo, pero no lo elimina cuando la espera está dentro de la iteración.
- Las cabeceras de la respuesta se envían **antes** del primer chunk. Por eso no se puede cambiar el status code a mitad del stream: de ahí que los errores viajen como eventos.
- `X-Accel-Buffering: no` es una convención de Nginx, no un estándar. Otros proxies tienen sus propias directivas.

---

## 4. SDK de OpenAI (usado como cliente de OpenRouter)

| Recurso | URL | Para qué se usó |
|---|---|---|
| Repositorio | <https://github.com/openai/openai-python> | Comportamiento de `chat.completions.create(stream=True)` |
| Referencia de la librería | <https://platform.openai.com/docs/api-reference> | Formato de `messages`, `delta.content` |
| Manejo de errores | <https://github.com/openai/openai-python#handling-errors> | Jerarquía `APIError` → `APIStatusError` → `RateLimitError` |
| Timeouts y reintentos | <https://github.com/openai/openai-python#timeouts> | `timeout`, `max_retries` (no configurados en el proyecto) |

### Lo que se aprendió

- El SDK **reintenta por su cuenta** algunos errores. Sin `max_retries=0`, un `429` puede tardar más de lo esperado antes de llegar al router.
- `RateLimitError` hereda de `APIStatusError`; el orden de los `except` importa.
- El objeto devuelto por `stream=True` es un iterador que hay que consumir; no es una lista.
- `base_url` permite apuntar a cualquier API compatible, que es exactamente lo que hace OpenRouter.

> **Advertencia de versión:** el proyecto no fija la versión de `openai`. Cambios de comportamiento entre versiones (timeouts por defecto, reintentos, tipos de excepción) pueden afectar el router. Si algo se rompe tras un `pip install -U`, revisá el changelog del SDK antes que el código del proyecto.

---

## 5. HTTPX

| Recurso | URL | Para qué se usó |
|---|---|---|
| Documentación | <https://www.python-httpx.org/> | `Client.get`, timeouts |
| Timeouts | <https://www.python-httpx.org/advanced/timeouts/> | `timeout=30` en el catálogo |
| Errores | <https://www.python-httpx.org/exceptions/> | Qué lanza `raise_for_status()` |

Se usa el cliente **síncrono** en `models_pool.py` porque el pool se diseñó como un objeto simple, sin `async`. Es una de las razones del bloqueo del event loop descrito en el README.

---

## 6. Pydantic y python-dotenv

| Recurso | URL | Para qué se usó |
|---|---|---|
| Pydantic — modelos | <https://docs.pydantic.dev/latest/concepts/models/> | `ChatRequest` |
| Pydantic — campos | <https://docs.pydantic.dev/latest/concepts/fields/> | `Field(..., min_length=1, max_length=100_000)` |
| python-dotenv | <https://github.com/theskumar/python-dotenv> | `load_dotenv()` y `os.getenv` |
| python-dotenv — variables | <https://saurabh-kumar.com/python-dotenv/> | Precedencia entre `.env` y entorno real |

### Detalle importante

`load_dotenv()` **no sobreescribe** variables ya presentes en el entorno por defecto. Eso permite hacer:

```bash
BACKOFF_SECONDS=60 ./run.sh
```

y que el valor de la shell gane sobre el del archivo. Es el comportamiento deseado para pruebas puntuales.

---

## 7. Uvicorn

| Recurso | URL | Para qué se usó |
|---|---|---|
| Documentación | <https://www.uvicorn.org/> | Arranque, `--host`, `--port`, `--reload` |
| Configuración | <https://www.uvicorn.org/settings/> | Workers, loop, timeouts |
| Despliegue | <https://www.uvicorn.org/deployment/> | Por qué un solo worker importa para el estado en RAM |

`uvicorn[standard]` agrega `uvloop` (loop más rápido), `httptools` (parser), `watchfiles` (recarga) y `websockets`. El proyecto no usa WebSockets, pero el extra viene junto y no molesta.

---

## 8. Conceptos externos que informan el diseño

| Concepto | Fuente de referencia | Cómo se aplica |
|---|---|---|
| Circuit breaker | <https://martinfowler.com/bliki/CircuitBreaker.html> | El cooldown es un circuit breaker por modelo, sin estado "half-open" explícito |
| Retry con backoff | <https://aws.amazon.com/builders-library/timeouts-retries-and-backoff-with-jitter/> | Inspiración para el doble castigo del `429` |
| Failover | <https://en.wikipedia.org/wiki/Failover> | Cambio de recurso ante fallo; acá el recurso es un modelo |
| Rate limiting (429) | <https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/429> | Semántica del código y de `Retry-After` (no se lee) |
| `localStorage` y seguridad | <https://developer.mozilla.org/en-US/docs/Web/API/Window/localStorage> | Persistencia de la key y sus límites |
| Same-origin policy | <https://developer.mozilla.org/en-US/docs/Web/Security/Same-origin_policy> | Por qué la UI no necesita CORS |
| Server-sent events vs WebSockets | <https://developer.mozilla.org/en-US/docs/Web/API/Server-sent_events/Using_server-sent_events> | Elección de transporte |

### Sobre `Retry-After`

El estándar HTTP permite que un `429` incluya la cabecera `Retry-After` con los segundos a esperar. **El proyecto no la lee**: usa un valor fijo (`BACKOFF_SECONDS`). Es una mejora obvia y de bajo costo:

```python
retry_after = exc.response.headers.get("retry-after")
cooldown = int(retry_after) if retry_after and retry_after.isdigit() else BACKOFF_SECONDS
```

No está implementado. Se documenta para que la omisión sea una decisión visible y no un olvido.

---

## 9. Herramientas usadas durante el desarrollo

| Herramienta | Uso |
|---|---|
| `curl` | Probar endpoints y streaming (`-N` para no bufferear) |
| `python3 -m json.tool` | Formatear la respuesta del catálogo |
| Navegador con DevTools | Inspeccionar `localStorage`, red y eventos SSE |
| `logging` de Python | Diagnóstico del pool y del router |
| `git log` | Reconstruir la línea de tiempo del proyecto |

No se usaron frameworks de test, linters configurados ni CI. Es una limitación reconocida, no una virtud.

---

## 10. Cómo verificar una referencia

Si vas a modificar el proyecto y necesitás confirmar un comportamiento:

1. **Contra el catálogo real:** `curl -s https://openrouter.ai/api/v1/models | python3 -m json.tool | less` y buscá `pricing`.
2. **Contra el estándar:** la especificación WHATWG de SSE es corta y resuelve el 90 % de las dudas de framing.
3. **Contra el SDK instalado:** `python -c "import openai; print(openai.__version__)"` y después `inspect.getsource` de la clase de excepción.
4. **Contra el propio proyecto:** `grep -rn "BACKOFF_SECONDS" .` suele responder más rápido que cualquier documentación externa.

---

## 11. Lo que no se pudo verificar

Por honestidad, estas cosas **no** están respaldadas por una fuente o una medición en este repositorio:

| Afirmación | Estado |
|---|---|
| "El failover salta al siguiente modelo ante un 429" | **No verificado en ejecución.** El código lo intenta; la evaluación perezosa del generador lo impide en el primer intento. Ver `developer.md` §6.4. |
| "El pool tiene 18 modelos" | Verificado una vez, el 2026-08-28. Es una fotografía, no una constante. |
| "El catálogo pesa ~1 MB" | Observación local, dependiente del catálogo del momento. |
| "La latencia del primer token es X" | No medido. El README evita cifras. |
| "Funciona con Python 3.10" | Inferido por la sintaxis usada; la `.venv` de referencia es 3.12. |

Documentar lo no verificado es parte del trabajo. Un lector que confía en una afirmación sin respaldo toma peores decisiones que uno que sabe qué falta.

---

*Licencia MIT — Copyright (c) 2026 wanderc137.*
