# Mega Free Chat — Datasheet de usuario

**Versión documentada:** commit `da09a46` (rama `main`)
**Tipo de documento:** manual de usuario y referencia operativa
**Público:** persona que va a instalar y usar la aplicación en su propia máquina

---

## Índice

1. [Qué es](#1-qué-es)
2. [Qué problema resuelve](#2-qué-problema-resuelve)
3. [Qué NO es](#3-qué-no-es)
4. [Cómo funciona, en lenguaje llano](#4-cómo-funciona-en-lenguaje-llano)
5. [Requisitos](#5-requisitos)
6. [Instalación paso a paso](#6-instalación-paso-a-paso)
7. [Dependencias del proyecto](#7-dependencias-del-proyecto)
8. [Configuración](#8-configuración)
9. [Operación diaria](#9-operación-diaria)
10. [La API key: dos formas y una precedencia](#10-la-api-key-dos-formas-y-una-precedencia)
11. [La interfaz, elemento por elemento](#11-la-interfaz-elemento-por-elemento)
12. [Panel de modelos](#12-panel-de-modelos)
13. [Endpoints](#13-endpoints)
14. [Comportamiento ante fallos](#14-comportamiento-ante-fallos)
15. [Lectura del registro (log)](#15-lectura-del-registro-log)
16. [Solución de problemas](#16-solución-de-problemas)
17. [Preguntas frecuentes](#17-preguntas-frecuentes)
18. [Limitaciones](#18-limitaciones)
19. [Seguridad y privacidad](#19-seguridad-y-privacidad)
20. [Advertencias finales](#20-advertencias-finales)

---

## 1. Qué es

**Mega Free Chat** es una aplicación web que corre en tu computadora y te permite conversar con modelos de lenguaje que, en este momento, OpenRouter ofrece a **precio cero**.

No es un cliente de chat más: es una **pasarela con failover**. Tú escribes una pregunta; la aplicación mira qué modelos están en `$0`, elige uno según una regla de prioridad, le pasa la pregunta y te devuelve la respuesta a medida que se genera. Si el modelo falla o aplica un límite de velocidad, el sistema lo aparta un rato y continúa con otro.

Toda la aplicación son **cuatro archivos de código** (un servidor FastAPI, un pool de modelos, un cliente de OpenRouter y un router) más una página HTML. No hay base de datos, ni colas, ni contenedores.

| Dato | Valor |
|---|---|
| Puerto | `8000` |
| Interfaz | `http://localhost:8000` |
| Usuarios | 1 (uso personal) |
| Persistencia | Ninguna (estado en memoria) |
| Coste | `$0` mientras existan modelos gratuitos |

---

## 2. Qué problema resuelve

OpenRouter publica cientos de modelos. Algunos son gratuitos, pero:

- **No hay una lista fija.** Los modelos entran y salen de la promoción `$0` sin aviso.
- **Aplican rate limits.** Un modelo gratuito puede aceptar tres peticiones por minuto y después devolver `429`.
- **Fallan de formas distintas.** Un día el proveedor está caído, otro día el modelo fue retirado, otro día cambió el esquema de precios.
- **Elegir a mano es tedioso.** Probar modelo por modelo en una lista de decenas no es una experiencia de chat.

Mega Free Chat automatiza las cuatro cosas: **descubre**, **filtra**, **ordena** y **rota**. Tú solo escribes.

---

## 3. Qué NO es

| No es… | Explicación |
|---|---|
| Un servicio en la nube | Corre en tu máquina. Si la apagás, no hay chat. |
| Un producto multiusuario | No hay login ni separación de datos entre personas. |
| Un chat con memoria persistente | El historial vive en la pestaña del navegador y se pierde al recargar. |
| Un comparador de modelos | No puntúa calidad ni muestra varias respuestas a la vez. |
| Un modo de evadir límites | Usa tu propia clave y las rutas públicas de OpenRouter, respetando sus `429`. |
| Un generador de imágenes | Solo texto. Los modelos de audio/imagen se excluyen del pool. |

---

## 4. Cómo funciona, en lenguaje llano

Imaginá una mesa con varias personas que saben responder preguntas y que hoy trabajan gratis. Algunas hablan chino y otras no; el dueño de la mesa decidió atender primero a las que hablan chino.

1. **Cada tanto, alguien actualiza la lista** de quién está en la mesa y quién se fue (`pool`).
2. **Cuando llega una pregunta**, se llama primero a la persona de la lista que habla chino y está despierta. Si contesta, se usa esa respuesta.
3. **Si esa persona dice "estoy ocupada"** (un `429`), se la marca como no disponible por un rato y se prueba con la siguiente.
4. **La respuesta no se espera completa**: se transmite palabra por palabra a medida que la persona habla (streaming).

Eso es todo. El resto es plomería: HTTP, JSON, eventos.

**La regla de prioridad china** no significa que esos modelos sean mejores. Significa que, cuando se construyó el proyecto, eran los que ofrecían más cuota gratuita sostenida. Es una decisión de orden, visible y modificable.

---

## 5. Requisitos

### 5.1 Software

| Componente | Mínimo | Recomendado | Nota |
|---|---|---|---|
| Python | 3.10 | 3.12 | El código usa sintaxis de tipos moderna (`str \| None`). |
| pip | El incluido con Python | Última versión estable | Se usa para `pip install -r requirements.txt`. |
| Navegador | Chrome/Firefox/Edge/Safari actuales | — | Necesita `fetch` y `ReadableStream` (streaming). |
| Shell | `bash` | — | `run.sh` es un script bash. En Windows, WSL. |

### 5.2 Cuenta

Una cuenta en [OpenRouter](https://openrouter.ai) con una **API key** (`sk-or-v1-...`). Crear la cuenta y la key es gratuito. No hace falta cargar crédito para usar modelos con precio `$0`.

### 5.3 Red

- Salida a `https://openrouter.ai` por el puerto 443.
- El puerto local `8000` libre.

### 5.4 Disco y memoria

El proyecto pesa unos pocos cientos de KB sin el entorno virtual. El entorno virtual con las dependencias ronda las decenas de MB (depende de la plataforma y de la versión de `uvicorn[standard]`). En memoria, la aplicación mantiene un objeto por modelo gratuito: con decenas de modelos, es despreciable.

---

## 6. Instalación paso a paso

### 6.1 Obtener el proyecto

```bash
git clone https://github.com/wanderc137/mega-free-chat.git
cd mega-free-chat
```

(Si ya tenés la carpeta, saltá este paso.)

### 6.2 Crear el entorno virtual e instalar

Las dependencias están en `requirements.txt`.

```bash
python3 -m venv venv
source venv/bin/activate        # Linux/Mac
venv\Scripts\activate           # Windows
pip install -r requirements.txt
```

Comprobación rápida:

```bash
python -c "import fastapi, uvicorn, openai, httpx, dotenv; print('ok')"
```

### 6.3 Configurar la clave

```bash
cp .env.example .env
```

Editá `.env` y reemplazá el placeholder:

```dotenv
OPENROUTER_API_KEY=sk-or-v1-tu_clave_real
```

> Si preferís no poner la clave en el servidor, podés dejar el placeholder y configurarla desde la interfaz. Pero `run.sh` exige que la línea tenga formato de clave para arrancar; si vas por ese camino, lanzá con `uvicorn` directamente (ver 6.5).

### 6.4 Arrancar con el script

```bash
chmod +x run.sh   # solo la primera vez
./run.sh
```

Verás el arranque de Uvicorn y la línea:

```
Uvicorn running on http://0.0.0.0:8000
```

Abrí `http://localhost:8000`.

### 6.5 Arranque alternativo

```bash
source .venv/bin/activate
uvicorn server:app --host 127.0.0.1 --port 8000
```

Usá `127.0.0.1` en lugar de `0.0.0.0` si no querés que otros dispositivos de tu red puedan abrir la página.

### 6.6 Detener

`Ctrl+C` en la terminal donde corre. No queda ningún proceso en segundo plano.

---

## 7. Dependencias del proyecto

Todas están declaradas en **`requirements.txt`**. El archivo **no fija versiones** (`==`), así que pip instala la última compatible con tu Python. Esta tabla refleja lo declarado y para qué se usa cada librería:

| Librería | Versión declarada | Función en el proyecto | Dónde se usa |
|---|---|---|---|
| `fastapi` | sin pin (última estable) | Framework HTTP, validación del body con Pydantic, `StreamingResponse` | `server.py` |
| `uvicorn[standard]` | sin pin | Servidor ASGI; el extra instala `uvloop`, `httptools`, `watchfiles` | Arranque (`run.sh`, `python server.py`) |
| `openai` | sin pin | Cliente compatible con la API de OpenRouter; maneja el streaming | `src/openrouter_client.py` |
| `httpx` | sin pin | Cliente HTTP para descargar el catálogo de modelos | `src/models_pool.py` |
| `python-dotenv` | sin pin | Carga de variables desde `.env` | `server.py` |

### 7.1 Cómo instalarlas en el entorno virtual

```bash
# desde la raíz del proyecto
python3 -m venv .venv
source .venv/bin/activate        # Linux/Mac
.venv\Scripts\activate           # Windows (PowerShell: .venv\Scripts\Activate.ps1)
pip install -r requirements.txt
```

### 7.2 Verificar versiones instaladas

```bash
pip list | grep -Ei 'fastapi|uvicorn|openai|httpx|dotenv'
```

### 7.3 Reproducibilidad

Como no hay versiones fijadas, dos instalaciones en fechas distintas pueden diferir. Si necesitás congelar el entorno:

```bash
pip freeze > requirements.lock.txt
```

Y para reinstalar exactamente eso:

```bash
pip install -r requirements.lock.txt
```

### 7.4 Dependencias que NO hacen falta

| Cosa | Por qué no |
|---|---|
| Node.js / npm | La UI es HTML+CSS+JS plano, sin build. |
| Base de datos | Todo el estado es en memoria. |
| Docker | El proyecto se ejecuta con Python y un script. |
| SDK de OpenRouter | Se usa el SDK de `openai`, que es compatible. |

---

## 8. Configuración

### 8.1 Archivo `.env`

| Variable | Default | Para qué sirve | Ejemplo |
|---|---|---|---|
| `OPENROUTER_API_KEY` | — | Clave de OpenRouter usada por el servidor | `sk-or-v1-abc...` |
| `BACKOFF_SECONDS` | `300` | Segundos que un modelo queda apartado tras fallar | `600` |
| `POOL_REFRESH_SECONDS` | `21600` | Cada cuánto se vuelve a leer el catálogo | `3600` |
| `DEBUG` | `false` | Logging detallado | `true` |
| `OR_BASE_URL` | `https://openrouter.ai/api/v1` | URL base de la API (soportada, no documentada en `.env.example`) | — |

### 8.2 Qué significa cada una en la práctica

**`BACKOFF_SECONDS`.** Si un modelo devuelve un error, no se lo vuelve a intentar durante ese tiempo. Un `429` (límite de velocidad) aplica el **doble**: con el valor por defecto, 600 segundos. Subilo si querés ser conservador; bajalo si querés que los modelos se recuperen rápido.

**`POOL_REFRESH_SECONDS`.** El catálogo se cachea. Con 6 horas por defecto, la aplicación no golpea el endpoint de modelos en cada mensaje. Si estás esperando que aparezca un modelo nuevo, bajalo temporalmente.

**`DEBUG`.** Con `true`, el log incluye cada petición HTTP interna. Útil para diagnosticar; ruidoso para el uso normal.

### 8.3 Advertencia sobre el arranque

Si lanzás con `uvicorn server:app`, las variables `BACKOFF_SECONDS`, `POOL_REFRESH_SECONDS` y `OR_BASE_URL` del `.env` **pueden no aplicarse**, porque el código lee esas variables al importar los módulos y carga el `.env` después. Con `./run.sh` no hay problema: el script exporta el `.env` al entorno antes de arrancar Python.

Regla simple: **si querés que la configuración cuente, usá `run.sh`**.

### 8.4 Cambiar el puerto

```bash
PORT=8001 ./run.sh
```

O bien:

```bash
uvicorn server:app --port 8001
```

---

## 9. Operación diaria

### 9.1 Rutina típica

1. Abrir una terminal en la carpeta del proyecto.
2. `./run.sh`.
3. Abrir `http://localhost:8000`.
4. (Primera vez) Configurar la API key desde el botón de la cabecera.
5. Escribir, leer, repetir.
6. `Ctrl+C` al terminar.

### 9.2 Enviar un mensaje

- Escribí en el campo inferior.
- **Enter** envía. **Shift+Enter** hace un salto de línea.
- Mientras la respuesta se genera, el botón **Enviar** queda deshabilitado.
- El texto aparece de a poco, a medida que el modelo lo produce.

### 9.3 Conversación

- La aplicación recuerda los últimos **30 elementos** del historial (15 intercambios).
- El historial se envía con cada mensaje para dar contexto.
- Al recargar la página, el historial se pierde. No hay forma de recuperarlo.

### 9.4 Nueva conversación

Recargá la página (`F5`). No hay botón de "borrar chat"; el estado del chat vive en la pestaña.

### 9.5 Qué mirar mientras responde

- La etiqueta **modelo: …** debajo de la respuesta indica qué modelo atendió.
- En el panel izquierdo, ese modelo se resalta en verde con **EN USO**.
- La píldora de la cabecera muestra cuántos modelos gratuitos hay (`18 free`, por ejemplo) o `offline` si el backend no responde.

---

## 10. La API key: dos formas y una precedencia

### 10.1 Forma A — Desde la interfaz

1. Pulsá **API key** en la cabecera.
2. Se despliega un campo de contraseña.
3. Pegá la clave (`sk-or-v1-...`).
4. **Enter** o **Guardar**.
5. El campo se cierra y aparece `••••••` en verde.

Características:

- Se guarda en `localStorage`, bajo la clave `megaFreeChat_apiKey`.
- **Sobrevive** a cerrar el navegador y a reiniciar la computadora.
- No se muestra nunca más en claro (al reabrir el campo, aparece vacío).
- Se envía al backend en el cuerpo de cada `POST /api/chat`.

### 10.2 Forma B — Desde `.env`

```dotenv
OPENROUTER_API_KEY=sk-or-v1-tu_clave
```

- La clave queda solo del lado del servidor.
- El navegador no la transporta.
- El pool es único y conserva los cooldowns entre mensajes (más eficiente).

### 10.3 Precedencia

```
key enviada por la página   >   key del .env   >   vacío (OpenRouter rechazará)
```

Si configuraste la key en la página y además en `.env`, **gana la de la página**. Para volver a usar la del servidor, borrá la del navegador:

```javascript
// Consola del navegador (F12)
localStorage.removeItem('megaFreeChat_apiKey');
location.reload();
```

### 10.4 Cuál conviene

| Situación | Recomendación |
|---|---|
| Un solo usuario, una sola máquina | `.env` |
| Varias personas, cada una con su clave | UI |
| Scripts y automatizaciones | `.env` o `api_key` en el body |
| Equipo compartido o prestado | **Nunca** la UI con tu clave personal |

---

## 11. La interfaz, elemento por elemento

```
┌─────────────────────────────────────────────────────────────────────┐
│ Mega Free Chat  Pasarela de modelos gratuitos · OpenRouter          │
│                                  [API key]  ••••••     [18 free]    │
├──────────────────┬──────────────────────────────────────────────────┤
│ MODELOS          │  SISTEMA                                         │
│ GRATUITOS        │  Escribe un mensaje y lo enrutaré…               │
│                  │                                                  │
│ Chinos · 7       │  TÚ                                              │
│ ● Ling 3.0 Flash │  ¿Qué es un 429?                                 │
│ ● GLM-4.5 Air    │                                                  │
│ ────────────     │  IA                                              │
│ Otros · 11       │  Un 429 es un límite de velocidad…               │
│ ● Modelo X       │  modelo: inclusionai/ling-3.0-flash-fin:free     │
├──────────────────┴──────────────────────────────────────────────────┤
│ [ Escribe tu mensaje... ]                              [ Enviar ]    │
└─────────────────────────────────────────────────────────────────────┘
```

| Elemento | Función |
|---|---|
| Título y subtítulo | Identifican la app y su fuente de modelos |
| Botón **API key** | Despliega el campo para configurar la clave |
| `••••••` | Indica que hay una clave guardada |
| Píldora `N free` | Cantidad de modelos gratuitos conocidos |
| Píldora `offline` | El backend no respondió a la última consulta |
| Panel izquierdo | Lista de modelos, agrupados y con estado |
| Zona central | Conversación |
| Campo inferior | Entrada de texto, con crecimiento automático |
| Botón **Enviar** | Envía; se deshabilita mientras hay respuesta |

### 11.1 Estilo de la conversación

No hay burbujas ni tarjetas. Cada mensaje es texto sobre el fondo, precedido por una etiqueta pequeña en mayúsculas: **TÚ**, **IA**, **SISTEMA**, **ERROR**. La respuesta incluye, al final, el identificador del modelo que la generó.

### 11.2 Formato del texto

El texto se muestra **tal cual llega**. No se renderiza Markdown: si el modelo devuelve `**negrita**`, vas a ver los asteriscos; si devuelve una tabla, vas a ver las barras. Es una decisión deliberada para no interpretar HTML ajeno.

---

## 12. Panel de modelos

### 12.1 Agrupación

- **Chinos · N**: modelos clasificados como chinos. Se intentan primero.
- **Otros · N**: el resto.

### 12.2 Estados

| Punto | Etiqueta | Significado |
|---|---|---|
| Verde | `activo` | Disponible y sin fallos recientes |
| Amarillo | `cooldown` | Apartado temporalmente tras un fallo |
| Rojo | `fallo` | Acumuló fallos (estado informativo) |
| Borde verde + **EN USO** | — | Es el modelo que está respondiendo ahora |

### 12.3 Actualización

La lista se consulta cada **20 segundos**. No hay botón de refresco manual: si querés forzarlo, recargá la página.

### 12.4 Nota sobre el amarillo persistente

Un modelo puede seguir pintado en amarillo después de que su cooldown expiró; el router ya lo considera disponible. Es una diferencia entre el estado "informativo" y el estado "efectivo". No afecta el funcionamiento.

---

## 13. Endpoints

| Ruta | Método | Devuelve | Uso |
|---|---|---|---|
| `/` | GET | HTML | Interfaz de chat |
| `/api/models` | GET | JSON | Estado del pool |
| `/api/chat` | POST | `text/event-stream` | Chat con failover |
| `/static/...` | GET | Archivos | Assets estáticos |

### 13.1 `GET /api/models`

```bash
curl -s http://localhost:8000/api/models | python3 -m json.tool
```

Respuesta (recortada):

```json
{
  "updated_at": "2026-08-28T19:49:27+00:00",
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

### 13.2 `POST /api/chat`

Cuerpo:

```json
{
  "message": "Hola, ¿qué modelo sos?",
  "history": [
    {"role": "user", "content": "Hola"},
    {"role": "assistant", "content": "Hola, ¿en qué puedo ayudarte?"}
  ],
  "api_key": "sk-or-v1-opcional"
}
```

Respuesta: eventos SSE.

```
event: status
data: {"state": "routing"}

event: status
data: {"state": "streaming", "model": "inclusionai/ling-3.0-flash-fin:free"}

event: chunk
data: {"content": "Hola"}

event: done
data: {"model": "inclusionai/ling-3.0-flash-fin:free"}
```

| Evento | Significado |
|---|---|
| `status` (`routing`) | La petición fue aceptada, se está eligiendo modelo |
| `status` (`streaming`) | Un modelo aceptó; empieza el texto |
| `chunk` | Fragmento de texto a concatenar |
| `done` | Fin normal |
| `error` | Fallo; el mensaje explica qué pasó |

### 13.3 Errores HTTP

| Código | Cuándo |
|---|---|
| `422` | Body inválido: falta `message`, está vacío o supera 100 000 caracteres |
| `200` con `event: error` | El chat falló **después** de aceptar la petición |
| `500` | Excepción no controlada en el servidor |

Importante: un fallo de modelos **no** cambia el código HTTP. Hay que leer el stream para detectarlo.

---

## 14. Comportamiento ante fallos

| Situación | Qué hace la app | Qué ves |
|---|---|---|
| Un modelo devuelve `429` | Lo aparta el doble de tiempo | Nada, si otro responde; o un error si es el único |
| Un modelo devuelve `5xx` | Lo aparta el tiempo normal | Igual |
| No hay red | Error de conexión; el modelo se marca | `Error interno: ...` |
| Todos los modelos están en cooldown | No intenta ninguno | "No hay ningún modelo gratuito disponible en este momento." |
| El catálogo no se pudo descargar | Conserva el pool anterior y anota `last_error` | La lista puede estar desactualizada |
| El cliente cierra la pestaña | El stream se corta | En el log: `GeneratorExit` (normal) |
| La clave es inválida | OpenRouter rechaza | Error en el stream o en el log |

**Sobre el failover real:** el código está diseñado para saltar de modelo en modelo, pero por cómo está escrito el cliente (un generador de Python), los errores del **primer** modelo pueden no ser atrapados por el router. En la práctica, esto significa que un `429` en el primer candidato puede terminar en un mensaje de error en lugar de un salto automático. Es una limitación conocida y documentada en `docs/developer.md`; no se oculta.

---

## 15. Lectura del registro (log)

`run.sh` no redirige la salida: el log se ve en la terminal. Si lo redirigís a un archivo, `*.log` está en `.gitignore` para que no se publique.

Líneas típicas y su significado:

| Línea | Significado |
|---|---|
| `Pool actualizado: N modelos gratuitos disponibles` | Se descargó el catálogo y se filtraron N gratuitos |
| `No se pudo actualizar el pool: ...` | Falló la descarga; se conserva el pool anterior |
| `Intentando con modelo gratuito: <id>` | El router eligió ese modelo |
| `Modelo <id> con rate limit, probando siguiente` | Hubo un 429 |
| `Modelo <id> falló: ...` | Error HTTP |
| `Modelo <id> sin conexión: ...` | Error de red |
| `GeneratorExit` | El cliente cortó el stream; no es un error |
| Líneas `httpx` / `httpcore` | `DEBUG=true` activo |

Para ver solo lo importante:

```bash
grep -E 'Pool actualizado|Intentando|rate limit|falló' mega-free-chat.log | tail -20
```

---

## 16. Solución de problemas

| Síntoma | Causa | Solución |
|---|---|---|
| `ERROR: OPENROUTER_API_KEY no configurada en .env` al arrancar | Placeholder o línea mal formada | Poner la clave real; verificar que empiece con `sk-or-v1-` |
| `Address already in use` | Puerto 8000 ocupado | `PORT=8001 ./run.sh`; o cerrar el otro proceso |
| `Permission denied` al ejecutar `run.sh` | Falta permiso de ejecución | `chmod +x run.sh` |
| La página carga pero dice `offline` | El backend no responde | Verificar que el proceso siga vivo; revisar la terminal |
| "Sin modelos gratuitos ahora" | El filtro no encontró ninguno en `$0` | Esperar; revisar `last_error`; puede ser un cambio de catálogo |
| Todo devuelve `Error interno` | Clave inválida, red caída, o la limitación del generador | Revisar el log completo; probar `/api/models` |
| `401` / `User not found` | Clave revocada | Generar otra en openrouter.ai/keys |
| `402` / `Insufficient credits` | El modelo dejó de ser gratuito | Refrescar el pool (reiniciar) |
| El texto aparece de golpe | Proxy con buffering | Desactivar `proxy_buffering` o usar `curl -N` |
| `422` al llamar la API | `message` vacío o demasiado largo | Revisar el JSON |
| No se guarda la key en el navegador | `localStorage` bloqueado | Usar `.env`; revisar modo privado |
| La configuración del `.env` no cambia nada | Arranque con `uvicorn` | Usar `./run.sh` |
| `ModuleNotFoundError: fastapi` | Entorno virtual no activado | `source .venv/bin/activate` |
| La consola se llena de líneas | `DEBUG=true` | Poner `DEBUG=false` y reiniciar |

### Diagnóstico en cuatro pasos

```bash
curl -s -o /dev/null -w 'raiz: %{http_code}\n' http://localhost:8000/
curl -s http://localhost:8000/api/models | python3 -c 'import json,sys;d=json.load(sys.stdin);print("modelos:",len(d["models"]),"error:",d["last_error"])'
curl -N -s -X POST http://localhost:8000/api/chat -H 'Content-Type: application/json' -d '{"message":"ping"}' | head -6
tail -30 mega-free-chat.log 2>/dev/null || echo "sin archivo de log (salida en terminal)"
```

---

## 17. Preguntas frecuentes

**¿Es realmente gratis?**
Mientras OpenRouter tenga modelos con `pricing.prompt` y `pricing.completion` en `"0"`. Eso puede cambiar. No hay compromiso de permanencia.

**¿Necesito cargar crédito?**
No para modelos gratuitos. La cuenta debe existir y la key debe ser válida.

**¿Por qué prioriza modelos chinos?**
Porque en el momento de construir el proyecto ofrecían más cuota gratuita sostenida. Es una regla de orden, no una evaluación de calidad.

**¿Puedo elegir el modelo yo?**
No desde la interfaz. Podés cambiar el orden en el código (`src/router.py`) o apuntar el cliente a un modelo concreto.

**¿Se guardan las conversaciones?**
No. Nada se escribe en disco. El historial vive en la pestaña y se envía a OpenRouter con cada mensaje.

**¿Puedo usarlo desde el celular?**
Sí, si está en la misma red y el servidor escucha en `0.0.0.0`. Pero entonces cualquier dispositivo de la red puede usar tu clave del `.env`.

**¿Por qué a veces tarda en empezar?**
Porque el modelo tarda en producir el primer token, o porque el pool se está descargando. El indicador "Pensando..." cubre ese lapso.

**¿Puedo cambiar los colores?**
Sí: las variables CSS están al inicio de `static/index.html` (`--bg`, `--accent`, etc.).

**¿Funciona sin internet?**
No. Todo el cómputo ocurre en OpenRouter.

**¿Puedo aportar mi propia clave y que no la vea el servidor?**
No del todo: el servidor la recibe para poder llamar a OpenRouter. Lo que evitás es que quede guardada en `.env`.

---

## 18. Limitaciones

1. Los modelos gratuitos son temporales y cambian sin aviso.
2. El estado (cooldowns, contadores) se pierde al reiniciar.
3. No hay autenticación: quien llegue al puerto, usa la app.
4. No hay tests automatizados; la verificación es manual.
5. La UI no renderiza Markdown.
6. El historial se limita a 30 elementos y no persiste.
7. Con la clave puesta en la UI, cada mensaje vuelve a descargar el catálogo.
8. La app no elige modelo por calidad, solo por disponibilidad y orden.
9. Un solo proceso: no escala horizontalmente sin compartir estado.
10. Sin heartbeat SSE: algunos proxies pueden cortar respuestas lentas.

---

## 19. Seguridad y privacidad

- La clave en `localStorage` es legible por cualquier script del mismo origen. Hoy no hay scripts de terceros; mantenelo así.
- La clave viaja al backend en el cuerpo de la petición, sobre HTTP sin cifrar. En `localhost` no sale de la máquina; en red, sí.
- El servidor escucha en `0.0.0.0` por defecto. Cualquiera en tu red puede abrir la página y consumir tu cuota.
- No hay rate limiting: un vecino de red podría agotar tu cuota diaria.
- Los prompts y las respuestas se envían a OpenRouter y al proveedor del modelo. Algunos modelos gratuitos **entrenan con los datos**; no envíes información sensible.
- El repositorio excluye `.env`, `*.log` y `.venv`. Verificá antes de publicar un fork.

Recomendaciones mínimas:

1. Usá `.env` en lugar de la UI si el equipo es compartido.
2. Cambiá el host a `127.0.0.1` si no necesitás acceso desde otros dispositivos.
3. Rotá la clave si sospechás que se filtró.
4. No expongas el puerto a internet sin TLS y autenticación.

---

## 20. Advertencias finales

- **"Gratis" es una condición del mercado, no una característica del software.** El software está preparado para que el pool se vacíe; no está preparado para que alguien te garantice que no va a pasar.
- **No lo uses para trabajo crítico.** Si necesitás disponibilidad, usá un proveedor de pago con SLA.
- **Respetá los términos de OpenRouter.** La aplicación no evade límites: los registra y espera.
- **La clave es tuya y es tu responsabilidad.** No la publiques, no la pegues en capturas, no la subas al repositorio.
- **Documentación honesta > documentación optimista.** Si algo de este manual no coincide con lo que ves, gana lo que ves: abrí un issue o revisá el código, que son cuatro archivos.

---

*Documento generado para el repositorio [wanderc137/mega-free-chat](https://github.com/wanderc137/mega-free-chat). Licencia MIT.*
