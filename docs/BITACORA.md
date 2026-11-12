# Bitácora — Mega Free Chat

**Qué es este documento:** el registro de por qué el proyecto es como es. No es un changelog (para eso está `git log`) ni un manual (para eso están el README y el datasheet). Es el cuaderno de decisiones: qué se probó, qué se descartó, qué se rompió y qué se aprendió.

**Cómo leerlo:** las secciones marcadas **[observado]** se apoyan en evidencia del repositorio (commits, código, log de ejecución). Las marcadas **[reconstruido]** son la interpretación del autor al documentar, meses después; pueden tener imprecisiones de detalle, no de intención.

---

## 1. Punto de partida

La pregunta inicial no fue "hagamos un chat". Fue más incómoda:

> ¿Se puede tener una interfaz de chat usable usando **solo** lo que los proveedores regalan, sin que se caiga cuando uno de ellos decide dejar de regalar?

Tres restricciones autoimpuestas:

1. **Una sola API key.** Nada de pedirle al usuario cinco claves de cinco proveedores.
2. **Cero costo.** Si un modelo cuesta un centavo, no entra.
3. **Cero mantenimiento de listas.** Si hay que editar a mano qué modelos son gratis, el proyecto se pudre en una semana.

La tercera restricción es la que definió la arquitectura: **el pool tiene que ser dinámico**. Todo lo demás vino de ahí.

---

## 2. Línea de tiempo **[observado]**

Extraída de `git log --oneline`, todos los commits del 2026-08-28:

| Orden | Commit | Mensaje | Lectura |
|---|---|---|---|
| 1 | `381d3d1` | Mega Free Chat: pasarela web de modelos gratuitos de OpenRouter con failover y prioridad china | Nace la idea completa |
| 2 | `f129d08` | API para microcontroladores + firmware ESP8266 | Se intenta ampliar el alcance |
| 3 | `272484f` | Separar proxy de IA en repositorio propio | Se corrige el alcance |
| 4 | `5247ad0` | Lanzador dock tipo interruptor (toggle) | Se intenta mejorar la ergonomía |
| 5 | `0133d0c` | Ejecución manual en primer plano (run.sh) + quitar lanzador de dock | Se revierte la ergonomía |
| 6 | `da09a46` | Quitar launch.sh (reemplazado por run.sh): un solo ejecutable por proyecto | Se limpia el resultado |

Seis commits en un día. La forma de la curva —construir, ampliar, recortar, intentar, revertir, limpiar— es la historia real del proyecto, más que cualquier explicación posterior.

---

## 3. Decisiones y su justificación

### 3.1 OpenRouter como única fuente

**Decisión:** en lugar de integrar OpenAI, Anthropic, Google y DeepSeek por separado, se usa OpenRouter como agregador.

**Por qué:**

- Una API key, un contrato, un formato de mensajes.
- El catálogo expone el precio por modelo, que es la señal que necesita el filtro.
- Cambiar de proveedor no requiere cambiar de cliente.

**Costo aceptado:** dependencia de un intermediario. Si OpenRouter cambia su esquema o sus condiciones, el proyecto se rompe. No hay plan B implementado.

### 3.2 El SDK de OpenAI como cliente

**Decisión:** `openai.OpenAI(base_url="https://openrouter.ai/api/v1")` en lugar de un cliente HTTP propio.

**Por qué:** OpenRouter implementa el contrato de OpenAI; el SDK ya resuelve streaming, tipado, timeouts y jerarquía de excepciones. Escribir eso a mano habría sido una semana de trabajo para llegar al mismo lugar.

**Costo aceptado:** se heredan los reintentos internos del SDK y sus defaults de timeout, que no siempre son los deseados. Se descubrió al documentar que `max_retries=0` y un `timeout` explícito habrían sido mejores.

### 3.3 Filtro por precio con comparación de cadenas

**Decisión:**

```python
if pricing.get("prompt") == "0" and pricing.get("completion") == "0":
```

**Por qué:** el catálogo devuelve los precios como **strings**. Comparar contra `"0"` es literal y conservador: si el precio cambia a `"0.0000001"`, el modelo sale del pool.

**Costo aceptado:** fragilidad ante cambios de esquema. Si devolviera `0` numérico, el filtro no matchearía y el pool quedaría vacío. Se prefirió el falso negativo (perder un modelo gratis) al falso positivo (cobrar sin avisar).

### 3.4 Pool dinámico, no lista hardcodeada

**Decisión:** descargar el catálogo cada `POOL_REFRESH_SECONDS` y filtrar en runtime.

**Por qué:** una lista hardcodeada se desactualiza el mismo día. El proyecto habría nacido muerto.

**Costo aceptado:** dependencia de red en el arranque, latencia en el primer request, y la necesidad de manejar el caso "catálogo vacío".

### 3.5 Prioridad a modelos chinos

**Decisión:** ordenar con `(not is_chinese, name.lower())`.

**Por qué [reconstruido]:** en el momento de construir el proyecto, el ecosistema chino (GLM/Zhipu, Qwen, DeepSeek, MiniMax, Ling/InclusionAI) era el que ofrecía más modelos con cuota gratuita sostenida y contextos grandes. Priorizar ahí aumentaba la probabilidad de que el primer intento funcionara.

**Cómo se evita que sea un prejuicio oculto:** la regla es una constante visible (`CHINESE_PROVIDERS`, `CHINESE_KEYWORDS`), está documentada y la UI agrupa explícitamente en "Chinos" y "Otros". No se afirma que sean mejores; se afirma que se intentan primero.

### 3.6 Cooldown doble para el 429

**Decisión:** `BACKOFF_SECONDS` para errores generales, `BACKOFF_SECONDS * 2` para `429`.

**Por qué:** un `429` no es un fallo transitorio: es el proveedor diciendo "no insistas". Un `503` puede resolverse en segundos; un rate limit suele necesitar minutos. Castigar igual a ambos era optimista de más.

**Lo que faltó:** leer la cabecera `Retry-After` cuando existe. Es la fuente autoritativa y se ignoró por simplicidad. Queda anotado.

### 3.7 SSE en lugar de WebSocket

**Decisión:** `text/event-stream` sobre HTTP, consumido con `fetch` + `ReadableStream`.

**Por qué:**

- El flujo es unidireccional: el cliente manda una pregunta y recibe texto. No hay mensajes concurrentes.
- SSE es HTTP normal: pasa por proxies, no necesita handshake, se depura con `curl -N`.
- El body del POST puede llevar el historial completo, cosa que `EventSource` no permite (solo GET). Por eso se usa `fetch`, no `EventSource`.

**Costo aceptado:** sin reconexión ni `Last-Event-ID`. Si el stream se corta, se perdió el turno.

### 3.8 UI sin framework

**Decisión:** un HTML con CSS y JS embebidos, sin React, sin Vite, sin `node_modules`.

**Por qué:** la interfaz tiene tres paneles y un formulario. Un bundler habría agregado un segundo ecosistema (npm) a un proyecto que se instala con `pip`. Además, el estilo "terminal" no necesita componentes.

**Costo aceptado:** sin reactividad declarativa; el DOM se manipula a mano. Para este tamaño, es más legible que un framework.

### 3.9 La API key en el navegador

**Decisión:** campo desplegable que guarda en `localStorage` y envía la key en cada petición.

**Por qué [reconstruido]:** editar `.env` y reiniciar el servidor para probar otra clave es fricción pura. El campo resuelve el caso "quiero usar mi key ahora" sin tocar archivos.

**Costo aceptado y documentado:** la key queda en un almacén legible por JavaScript del mismo origen y viaja en cada body. Se decidió aceptarlo en una app local, y se advierte explícitamente en el README.

### 3.10 Un repositorio, una responsabilidad

**Decisión:** el commit `272484f` separó el firmware ESP8266 y la API para microcontroladores a otro repositorio.

**Por qué:** dos ciclos de vida distintos (Python/web vs C++/hardware), dos públicos, dos `README`. Tenerlos juntos obligaba a clonar un ESP8266 para leer el backend.

**Lección:** el entusiasmo por ampliar el alcance se corrigió el mismo día. Es más fácil recortar un proyecto en el commit 3 que en el commit 30.

### 3.11 Primer plano en lugar de daemon

**Decisión:** `run.sh` con `exec python server.py`, atado a la terminal. `Ctrl+C` y no queda nada.

**Por qué [reconstruido]:** se probó antes un lanzador de escritorio tipo interruptor (`5247ad0`) que arrancaba el servidor en segundo plano. El problema apareció rápido: un proceso que no ves es un proceso que olvidás. Se terminaba con dos instancias peleando por el puerto 8000 y sin saber cuál respondía.

Los commits `0133d0c` y `da09a46` son esa reversión: quitar el lanzador, quedarse con `run.sh`, y después eliminar `launch.sh` para que exista **un solo** ejecutable.

**Costo aceptado:** hay que abrir una terminal para usar la app. Es un precio bajo comparado con depurar procesos huérfanos.

---

## 4. Problemas encontrados y cómo se resolvieron

### 4.1 Falsos positivos en la clasificación china **[observado en el código]**

**Síntoma:** modelos occidentales aparecían como chinos en el panel.

**Causa:** la búsqueda de la keyword `ling` (por Ling/InclusionAI) matcheaba dentro de `inkling`, un modelo que no tiene nada que ver.

**Solución:** las keywords se convirtieron en regex con límite de palabra:

```python
CHINESE_KEYWORDS = (r"\bglm\b", r"\bqwen\b", r"\bdeepseek\b", ...)
```

**Lección:** una subcadena sin anclaje es una bomba de relojería en la clasificación de textos cortos.

### 4.2 El pool se llenaba de "modelos" que no eran modelos **[observado en el código]**

**Síntoma:** aparecían entradas que fallaban siempre al chatear.

**Causa:** el catálogo incluye alias flexibles (ids que empiezan con `~`), el router comodín `openrouter/free` y modelos de generación musical como Lyria, todos con precio `$0`.

**Solución:** `is_chat_model()` como lista negra: descarta `~*`, `openrouter/free` y cualquier id/nombre con `lyria`.

**Lección:** "gratis" y "sirve para chat" son dos filtros distintos. Confundirlos ensucia el pool.

### 4.3 Orden impredecible entre modelos **[observado en el código]**

**Síntoma:** dos ejecuciones con el mismo pool elegían modelos distintos, y los logs no eran comparables.

**Solución:** `sorted` con clave compuesta y desempate alfabético estable:

```python
key=lambda m: (not m.is_chinese, m.name.lower())
```

**Lección:** en sistemas con failover, el determinismo vale más que la variedad. Si querés variedad, agregala explícitamente (shuffle), no como efecto colateral del orden de un diccionario.

### 4.4 `DEBUG=true` y el ruido de httpx **[observado en el log]**

**Síntoma:** el log de ejecución local estaba dominado por líneas de `httpx` y `httpcore`.

**Causa:** `logging.basicConfig(level=DEBUG)` afecta a **todos** los loggers, incluidos los de las librerías.

**Estado:** no se corrigió. Se documentó que `DEBUG=true` es verboso y que para uso normal conviene `false`.

**Cómo se arreglaría:**

```python
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
```

### 4.5 `GeneratorExit` en el log **[observado]**

**Síntoma:** al cortar la lectura, aparecían líneas `GeneratorExit()` con traceback.

**Diagnóstico:** el cliente cerró la conexión y el generador del stream se cerró a mitad. Es el comportamiento normal de un generador interrumpido, no un error de la aplicación.

**Acción:** ninguna. Se documentó para que no se confunda con un fallo.

### 4.6 El failover no funciona en el primer intento **[descubierto al documentar]**

**Cómo apareció:** al escribir la sección de failover del README, el flujo no cerraba. `chat_stream` es un generador; llamarlo no ejecuta la petición; los `except` del router nunca ven el error HTTP del primer modelo.

**Evidencia:** el log local no registró ningún `429`, así que el camino de fallo no se había ejercitado. El problema se detectó por lectura del código, no por un fallo en producción.

**Estado:** **no corregido** en esta iteración (la tarea era documentar). Está registrado como deuda prioritaria en `developer.md`, con dos fixes posibles (primar el generador con `next()`, o cambiar el contrato de `chat_stream`).

**Lección:** un generador perezoso rompe el `try/except` de forma silenciosa. Si una función contiene `yield`, asumir que "llamarla" es "ejecutarla" es un error de razonamiento, no un detalle de estilo.

### 4.7 `load_dotenv()` llega tarde **[descubierto al documentar]**

**Cómo apareció:** al verificar qué variables afectaban realmente el comportamiento, el orden de `server.py` mostró que los módulos leen `os.getenv` al importarse y el `.env` se carga después.

**Consecuencia:** con `uvicorn server:app`, `BACKOFF_SECONDS`, `POOL_REFRESH_SECONDS` y `OR_BASE_URL` del `.env` se ignoran silenciosamente.

**Estado:** documentado en README, datasheet y developer. El fix (leer la configuración en runtime y pasarla al constructor) está descrito y no aplicado.

**Lección:** "funciona en mi máquina" puede significar "funciona porque `run.sh` exporta las variables". El modo de arranque es parte de la configuración.

### 4.8 Estado inconsistente entre `status` y `cooldown_until` **[observado en el código]**

**Síntoma:** un modelo se queda pintado en amarillo para siempre en la UI.

**Causa:** `is_available()` compara el reloj, pero `status` no se resetea al expirar el cooldown.

**Estado:** cosmético, documentado. El fix de dos líneas está en `developer.md`.

### 4.9 El merge del refresco congela metadatos **[observado en el código]**

**Síntoma:** un modelo cambia de nombre o de contexto y la app sigue mostrando el dato viejo.

**Causa:** el merge conserva el objeto `FreeModel` completo cuando el `id` ya existía.

**Estado:** documentado como limitación. El fix (copiar solo el estado, no el objeto) está descrito.

---

## 5. Vías descartadas y por qué

Esta sección existe para no volver a intentarlas.

| Vía descartada | Por qué se descartó |
|---|---|
| **Scraping de la web de OpenRouter** en lugar de la API | Frágil, contrario a los términos de uso, y la API pública ya expone el precio. No hay razón. |
| **Rotación de cuentas** para multiplicar la cuota gratuita | Es evadir un límite, no usar una ruta gratuita. El proyecto usa una key por usuario y respeta el `429`. |
| **Lista hardcodeada de modelos gratis** | Se desactualiza en días. Fue la primera tentación y la razón de ser del pool dinámico. |
| **WebSocket en lugar de SSE** | Complejidad de handshake y reconexión para un flujo unidireccional. SSE gana en simplicidad operativa. |
| **React/Vite/Next para la UI** | Un segundo ecosistema (npm) para tres paneles. El HTML plano es más fácil de auditar y de servir. |
| **Base de datos para el historial** | El uso previsto es una persona en una pestaña. Persistir conversaciones habría agregado esquema, migraciones y privacidad que nadie pidió. |
| **Docker** | El proyecto es un `venv` y un script. Un Dockerfile habría agregado una capa sin resolver ningún problema real. |
| **Daemon/systemd/dock toggle** | Se intentó (commit `5247ad0`) y se revirtió. Procesos en segundo plano que no ves terminan en puertos ocupados y confusión. |
| **Cliente HTTP propio en lugar del SDK** | El SDK de OpenAI ya implementa streaming y excepciones. Reimplementarlo era una semana para llegar al mismo lugar. |
| **Failover a nivel de proveedor** (dentro de OpenRouter) | OpenRouter ya enruta entre proveedores de un mismo modelo. Duplicar esa lógica desde el cliente no aporta. |
| **Prioridad por benchmark de calidad** | No hay forma barata y objetiva de medir "mejor" para todos los prompts. Se eligió una regla explícita y barata (chinos primero) en lugar de una métrica falsa. |
| **Rate limiting propio en la app** | Con un solo usuario no aporta; si se expone, el lugar correcto es el proxy. |

---

## 6. Lecciones aprendidas

Aplicables a proyectos futuros, no solo a este.

### 6.1 Sobre el alcance

1. **Recortar temprano es más barato que recortar tarde.** La separación del firmware en el commit 3 evitó meses de un repo híbrido.
2. **Un ejecutable por proyecto.** Dos scripts de arranque (`run.sh` y `launch.sh`) es una invitación a que uno quede desactualizado.
3. **El modo de ejecución es una decisión de producto.** Primer plano vs daemon no es un detalle: define cómo se depura, cómo se apaga y qué pasa cuando algo queda colgado.

### 6.2 Sobre Python

4. **Un `yield` cambia el contrato.** Una función generadora no se ejecuta al llamarla. Cualquier `try/except` alrededor de su creación es decorativo.
5. **`os.getenv` en import time es una trampa.** La configuración debe leerse cuando se construye el objeto, no cuando se importa el módulo.
6. **`logging.basicConfig(DEBUG)` enciende a todos.** Las librerías también escriben; hay que silenciarlas explícitamente.
7. **`RateLimitError` es subclase de `APIStatusError`.** El orden de los `except` cambia el comportamiento.
8. **Un `threading.Lock` no protege entre procesos.** Si algún día hay `--workers`, el estado en RAM deja de ser compartido.

### 6.3 Sobre APIs de terceros

9. **Los precios pueden venir como string.** Comparar `== "0"` es correcto solo si el esquema no cambia; hay que asumir que puede cambiar.
10. **"Gratis" no es una propiedad estable.** Cualquier producto construido sobre una promoción debe tener un camino de salida (acá: error explícito, no crash).
11. **El catálogo incluye cosas que no son modelos.** Alias, routers y generadores de audio conviven con los modelos de chat.
12. **Los reintentos del SDK pueden esconder el failover.** `max_retries=0` es un buen default para un router propio.

### 6.4 Sobre documentación

13. **Documentar obliga a leer el código de verdad.** Los bugs 4.6, 4.7, 4.8 y 4.9 se descubrieron escribiendo, no ejecutando.
14. **Lo no verificado debe declararse.** "No medí latencias" es más útil que un número inventado.
15. **Las limitaciones son parte del producto.** Un README que solo enumera virtudes se vuelve inútil en la primera crisis.

---

## 7. Estado de verificación

### Verificado **[observado]**

- `GET /` responde 200 y sirve la UI.
- `GET /api/models` responde 200 con el pool (18 modelos gratuitos el 2026-08-28).
- `POST /api/chat` responde 200 con stream SSE completo.
- El router eligió `inclusionai/ling-3.0-flash-fin:free`, coherente con la prioridad china.
- El log muestra la actualización del pool y las peticiones HTTP.
- `GeneratorExit` al cortar el stream: esperado.

### No verificado

- El salto de modelo ante un `429` real (por el problema 4.6).
- El comportamiento con más de un usuario concurrente.
- Latencias y throughput (no se midieron).
- Compatibilidad con Python 3.10 (inferida; la `.venv` es 3.12).
- Funcionamiento en Windows nativo (solo se documentó WSL).

### Cómo se verificó

Manualmente, con `curl` y el navegador. Sin tests automatizados, sin CI. Es la deuda más grande del proyecto junto con el failover.

---

## 8. Próximos pasos (si alguien retoma)

Ordenados por relación impacto/esfuerzo:

1. **Primar el generador** en `router.stream` para que el failover sea real. (~10 líneas)
2. **Cachear routers por key** para no recrear pool y cliente en cada mensaje. (~20 líneas)
3. **Leer la configuración en runtime** y eliminar el problema del orden de `load_dotenv`. (~20 líneas)
4. **Fijar `timeout` y `max_retries=0`** en el cliente. (2 líneas)
5. **Resetear `status`** en `to_dict()` cuando el cooldown expiró. (3 líneas)
6. **Preservar solo el estado** en el merge del refresco. (5 líneas)
7. **Agregar heartbeat SSE** cada 15 s. (3 líneas)
8. **Escribir tests del router** con un cliente falso. (1 archivo)
9. **Agregar `AbortController`** en la UI para cancelar respuestas. (~10 líneas)
10. **Implementar autenticación y rate limit** solo si se decide exponer el servicio.

Ninguno de estos cambios requiere rediseñar la arquitectura. Eso es, quizás, la mejor señal de que la separación en cuatro módulos fue correcta.

---

## 9. Cierre

El proyecto hace algo simple —elegir un modelo gratis y transmitir su respuesta— y lo hace con tres capas bien separadas, una UI sin dependencias y una honestidad incómoda sobre lo que no funciona.

Si tuviera que resumir la bitácora en una frase:

> La parte difícil no fue conseguir respuestas gratis; fue aceptar que "gratis" es temporal y diseñar para que el día que se termine, la app lo diga en lugar de romperse.

---

*Licencia MIT — Copyright (c) 2026 wanderc137.*
