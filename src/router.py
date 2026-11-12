"""Router de failover dinámico entre modelos gratuitos.

Recibe los mensajes, itera el pool de modelos gratuitos y prueba cada uno
hasta encontrar uno que responda. En caso de fallo, marca el modelo en
cooldown y continúa con el siguiente.
"""

from __future__ import annotations

import logging
import time

from openai import APIConnectionError, APIStatusError, RateLimitError

from .models_pool import ModelsPool
from .openrouter_client import OpenRouterClient

logger = logging.getLogger("mega_free_chat.router")


class RouterError(Exception):
    """Error final cuando ningún modelo gratuito respondió."""


class FreeModelRouter:
    def __init__(self, pool: ModelsPool, client: OpenRouterClient) -> None:
        self.pool = pool
        self.client = client

    def stream(self, messages: list[dict]):
        """Itera el pool y devuelve (model_id, iterable) del primer modelo que responde.

        Devuelve el modelo elegido y un generador de fragmentos. Si todos
        fallan, levanta RouterError con el detalle de cada intento.
        """
        available = self.pool.available_models()
        if not available:
            raise RouterError("No hay ningún modelo gratuito disponible en este momento.")

        attempts: list[str] = []
        # Prioridad: primero los modelos chinos, luego el resto. Dentro de cada
        # grupo, orden estable por nombre para un comportamiento predecible.
        candidates = sorted(
            available,
            key=lambda m: (not m.is_chinese, m.name.lower()),
        )

        for model in candidates:
            try:
                logger.info("Intentando con modelo gratuito: %s", model.id)
                stream = self.client.chat_stream(model.id, messages)
                # Verificar que realmente arranca (evita modelos muertos)
                self.pool.mark_success(model.id)
                self._stream = model.id
                return model.id, stream
            except RateLimitError as exc:
                self.pool.mark_failure(model.id, str(exc), 429)
                attempts.append(f"{model.id}: rate limit (429)")
                logger.warning("Modelo %s con rate limit, probando siguiente", model.id)
            except APIStatusError as exc:
                self.pool.mark_failure(model.id, str(exc), exc.status_code)
                attempts.append(f"{model.id}: HTTP {exc.status_code}")
                logger.warning("Modelo %s falló: %s", model.id, exc)
            except APIConnectionError as exc:
                self.pool.mark_failure(model.id, str(exc), None)
                attempts.append(f"{model.id}: error de conexión")
                logger.warning("Modelo %s sin conexión: %s", model.id, exc)
            except Exception as exc:  # noqa: BLE001
                self.pool.mark_failure(model.id, str(exc), None)
                attempts.append(f"{model.id}: {exc}")
                logger.warning("Modelo %s error inesperado: %s", model.id, exc)

        raise RouterError("Todos los modelos gratuitos fallaron. Detalle: " + " | ".join(attempts))
