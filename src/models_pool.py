"""Pool de modelos gratuitos de OpenRouter.

Consulta el catálogo de OpenRouter (/api/v1/models), filtra los modelos con
pricing "0" (gratuitos) y mantiene el estado de cada uno (cooldown, fallos)
para que el router sepa cuáles están disponibles.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

import httpx

logger = logging.getLogger("mega_free_chat.pool")

BASE_URL = os.getenv("OR_BASE_URL", "https://openrouter.ai/api/v1")
REFRESH_SECONDS = int(os.getenv("POOL_REFRESH_SECONDS", "21600"))
BACKOFF_SECONDS = int(os.getenv("BACKOFF_SECONDS", "300"))


# Proveedores chinos conocidos (prefijo del id o subcadena del nombre)
CHINESE_PROVIDERS = (
    "z-ai", "zhipu", "zhipuai", "minimax", "deepseek",
    "qwen", "alibaba", "inclusionai", "moonshot", "kimi",
    "baidu", "tencent", "hunyuan", "stepfun", "01-ai", "iflytek", "xinghuo",
    "sensetime", "doubao", "baichuan", "internlm",
)

# Palabras clave en el nombre, con límite de palabra (evita falsos positivos
# como "ling" dentro de "inkling")
CHINESE_KEYWORDS = (r"\bglm\b", r"\bqwen\b", r"\bdeepseek\b", r"\bminimax\b",
                    r"\bkimi\b", r"\bhunyuan\b", r"\bdoubao\b", r"\binternlm\b",
                    r"\bbaichuan\b")


def is_chinese_model(model_id: str, name: str = "") -> bool:
    """Devuelve True si el modelo pertenece a un proveedor chino conocido."""
    import re
    haystack = f"{model_id} {name}".lower()
    for p in CHINESE_PROVIDERS:
        if p in haystack:
            return True
    low_name = name.lower()
    for kw in CHINESE_KEYWORDS:
        if re.search(kw, low_name):
            return True
    return False


def is_chat_model(model_id: str, name: str) -> bool:
    """Excluye modelos que no sirven para chat (alias, routers, audio...)."""
    mid = model_id.lower()
    mname = name.lower()
    # Alias flexibles de OpenRouter (id empieza por "~")
    if mid.startswith("~"):
        return False
    # Router comodín de OpenRouter
    if model_id == "openrouter/free":
        return False
    # Modelos de generación de audio/música (Lyria, etc.)
    if "lyria" in mid or "lyria" in mname:
        return False
    return True


@dataclass
class FreeModel:
    id: str
    name: str
    context_length: int = 0
    modalities: dict = field(default_factory=dict)
    supported_parameters: list = field(default_factory=list)
    is_chinese: bool = False

    # Estado dinámico
    status: str = "active"  # active | backoff | failed
    last_failure: str | None = None
    fail_count: int = 0
    cooldown_until: float = 0.0

    def is_available(self, now: float) -> bool:
        if self.status == "backoff" and now < self.cooldown_until:
            return False
        return True

    def mark_success(self) -> None:
        self.status = "active"
        self.fail_count = 0
        self.last_failure = None
        self.cooldown_until = 0.0

    def mark_failure(self, error: str, status_code: int | None = None) -> None:
        self.fail_count += 1
        self.last_failure = f"{status_code}: {error}" if status_code else error
        # 429 (rate limit) => backoff largo; otros errores => backoff corto
        cooldown = BACKOFF_SECONDS
        if status_code == 429:
            cooldown = BACKOFF_SECONDS * 2
        self.cooldown_until = time.time() + cooldown
        self.status = "backoff"

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "context_length": self.context_length,
            "status": self.status,
            "fail_count": self.fail_count,
            "last_failure": self.last_failure,
            "cooldown_until": self.cooldown_until,
            "is_chinese": self.is_chinese,
        }


class ModelsPool:
    """Mantiene el pool de modelos gratuitos y su estado."""

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key
        self._models: list[FreeModel] = []
        self._lock = threading.Lock()
        self._last_fetch: float = 0.0
        self._last_error: str | None = None

    def _fetch_models(self) -> list[FreeModel]:
        """Descarga el catálogo y filtra los gratuitos."""
        url = f"{BASE_URL}/models"
        headers = {"Authorization": f"Bearer {self.api_key}"}
        with httpx.Client(timeout=30) as client:
            resp = client.get(url, headers=headers)
            resp.raise_for_status()
            data = resp.json().get("data", [])

        free_models: list[FreeModel] = []
        for item in data:
            pricing = item.get("pricing") or {}
            # OpenRouter devuelve strings; "0" = gratuito
            if pricing.get("prompt") == "0" and pricing.get("completion") == "0":
                mid = item["id"]
                mname = item.get("name") or mid
                params = item.get("supported_parameters") or []
                if not is_chat_model(mid, mname):
                    continue
                free_models.append(
                    FreeModel(
                        id=mid,
                        name=mname,
                        context_length=item.get("context_length") or 0,
                        modalities=item.get("modalities") or {},
                        supported_parameters=params,
                        is_chinese=is_chinese_model(mid, mname),
                    )
                )
        return free_models

    def refresh(self, force: bool = False) -> None:
        """Actualiza el pool si ha pasado el intervalo de refresco."""
        now = time.time()
        with self._lock:
            if not force and (now - self._last_fetch) < REFRESH_SECONDS:
                return
        try:
            fetched = self._fetch_models()
            with self._lock:
                # Conservar el estado dinámico de modelos que ya conocíamos
                prev = {m.id: m for m in self._models}
                merged: list[FreeModel] = []
                for fm in fetched:
                    if fm.id in prev:
                        merged.append(prev[fm.id])
                    else:
                        merged.append(fm)
                self._models = merged
                self._last_fetch = now
                self._last_error = None
            logger.info("Pool actualizado: %d modelos gratuitos disponibles", len(self._models))
        except Exception as exc:  # noqa: BLE001
            self._last_error = str(exc)
            logger.warning("No se pudo actualizar el pool: %s", exc)

    def available_models(self) -> list[FreeModel]:
        """Modelos gratuitos sin cooldown activo."""
        self.refresh()
        now = time.time()
        with self._lock:
            return [m for m in self._models if m.is_available(now)]

    def all_models(self) -> list[FreeModel]:
        self.refresh()
        with self._lock:
            return list(self._models)

    def mark_success(self, model_id: str) -> None:
        with self._lock:
            for m in self._models:
                if m.id == model_id:
                    m.mark_success()
                    break

    def mark_failure(self, model_id: str, error: str, status_code: int | None) -> None:
        with self._lock:
            for m in self._models:
                if m.id == model_id:
                    m.mark_failure(error, status_code)
                    break

    def to_payload(self) -> dict:
        """Estado serializable para la UI."""
        return {
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "last_error": self._last_error,
            "models": [m.to_dict() for m in self.all_models()],
        }
