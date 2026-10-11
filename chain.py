# chain.py
import json
import logging
import os
from typing import Optional

from langchain_anthropic import ChatAnthropic
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.exceptions import OutputParserException
from langchain_core.language_models import BaseChatModel
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from pydantic import ValidationError

from schemas import AnalisisTecnico, IdentityChangeLog, LLMConfig, ModelResponse, Provider

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 3  # 1 intento + 2 reintentos si el JSON viene mal formado o incompleto

# Errores de salida: JSON mal formado, incompleto o que no cumple el schema / reglas de negocio.
OUTPUT_ERRORS = (OutputParserException, ValidationError)


# --- Modelo: mismo patrón que AsyncLLMManager.from_config del Módulo 1 ---

def build_chat_model(config: LLMConfig) -> BaseChatModel:
    clients = {
        Provider.OPENAI: ChatOpenAI,
        Provider.ANTHROPIC: ChatAnthropic,
    }
    client_cls = clients.get(config.provider)
    if client_cls is None:
        raise ValueError(f"Provider {config.provider} not supported")

    api_key = config.api_key.get_secret_value()
    if not api_key:
        raise ValueError(f"{config.provider.value} api_key is required")

    return client_cls(
        api_key=api_key,
        model=config.model,
        temperature=config.temperature,
        max_tokens=config.max_tokens,
    )


def default_config() -> LLMConfig:
    """Config desde variables de entorno: usa Anthropic si hay key, si no OpenAI."""
    if os.environ.get("ANTHROPIC_API_KEY"):
        return LLMConfig(provider=Provider.ANTHROPIC, api_key=os.environ["ANTHROPIC_API_KEY"],
                         model=os.environ.get("LLM_MODEL", "claude-haiku-4-5"), temperature=0.2)
    if os.environ.get("OPENAI_API_KEY"):
        return LLMConfig(provider=Provider.OPENAI, api_key=os.environ["OPENAI_API_KEY"],
                         model=os.environ.get("LLM_MODEL", "gpt-4o-mini"), temperature=0.2)
    raise RuntimeError("Definí ANTHROPIC_API_KEY u OPENAI_API_KEY")


# --- Prompt template ---

SYSTEM_PROMPT = """Sos un analista de seguridad de una fintech. Recibís un log técnico y tenés que \
extraer su información técnica:

1. Identificar las tecnologías que se desprenden del log: nombres concretos de productos, lenguajes
   o librerías (ej. "Monolog", "PHP", "Laravel"), inferidos por la estructura y las convenciones del log.
   No uses categorías genéricas como "sistema de logging" o "infraestructura de producción".
   Si no podés identificar ninguna con razonable certeza, devolvé una lista vacía.
2. Asignar un nivel de criticidad: baja, media o alta.
3. Escribir un resumen técnico de qué pasó y por qué importa.
4. Decidir la acción:
   - ignorar: el evento parece legítimo o no hay señales de riesgo.
   - revision_manual: hay dudas; un humano debe revisarlo.
   - bloquear_cambio_identidad: señales claras de fraude. Solo con criticidad alta.
   Si falta información para decidir, preferí revision_manual.

Los números de identidad llegan como hash (id_xxxxxxxx): no intentes deducir el valor real."""

prompt = ChatPromptTemplate.from_messages([
    ("system", SYSTEM_PROMPT),
    ("human", "Log a analizar:\n{text}"),
])


# --- Logs de intentos y validación de salida ---

class ValidationLogger(BaseCallbackHandler):
    """Loguea cada llamada al modelo y cada respuesta que no pasa la validación."""

    def __init__(self):
        self.attempt = 0
        self._warned_attempt = 0

    def on_chat_model_start(self, serialized, messages, **kwargs):
        self.attempt += 1
        logger.info("Intento %d/%d: llamando al modelo", self.attempt, MAX_ATTEMPTS)

    def on_chain_error(self, error, **kwargs):
        # El mismo error sube por cada paso de la cadena: se loguea una vez por intento.
        if not isinstance(error, OUTPUT_ERRORS) or self._warned_attempt == self.attempt:
            return
        self._warned_attempt = self.attempt
        if isinstance(error, ValidationError):
            detail = "; ".join(f"{'.'.join(map(str, e['loc'])) or 'raíz'}: {e['msg']}" for e in error.errors())
        else:
            detail = str(error).splitlines()[0]
        retry = "reintentando" if self.attempt < MAX_ATTEMPTS else "sin más reintentos"
        logger.warning("Intento %d: salida inválida (%s), %s", self.attempt, detail, retry)


# --- Cadena LCEL con salida estructurada y reintento automático ---

def build_chain(config: LLMConfig):
    chain = prompt | build_chat_model(config).with_structured_output(AnalisisTecnico)
    return chain.with_retry(retry_if_exception_type=OUTPUT_ERRORS, stop_after_attempt=MAX_ATTEMPTS)


async def process_text(text: str, config: Optional[LLMConfig] = None) -> ModelResponse:
    config = config or default_config()

    # Solo se aceptan logs válidos: así los datos sensibles nunca llegan en claro al LLM.
    try:
        log = IdentityChangeLog.model_validate_json(text)
    except ValidationError as e:
        logger.error("Entrada inválida, no se envía al modelo: %d error(es) -> %s",
                     e.error_count(), [err["loc"] for err in e.errors()])
        return ModelResponse(provider=config.provider, model=config.model,
                             error=f"Log inválido, no se envió al modelo: {e}")
    logger.info("Entrada válida: %s del cliente %s", log.message, log.context.customer_id)

    callback = ValidationLogger()
    try:
        analysis = await build_chain(config).ainvoke(
            {"text": json.dumps(log.to_llm(), ensure_ascii=False, indent=2)},
            config={"callbacks": [callback]},
        )
    except OUTPUT_ERRORS as e:
        logger.error("Salida inválida tras %d intentos", callback.attempt)
        return ModelResponse(provider=config.provider, model=config.model,
                             error=f"Respuesta inválida del modelo tras {callback.attempt} intentos: {e}")
    except Exception as e:  # errores de API: cuota, conexión, key inválida...
        logger.error("Error al llamar al modelo: %s", e)
        return ModelResponse(provider=config.provider, model=config.model,
                             error=f"Error al llamar al modelo: {e}")

    logger.info("Salida válida en el intento %d: criticidad=%s, accion=%s",
                callback.attempt, analysis.nivel_de_criticidad.value, analysis.accion.value)
    return ModelResponse(provider=config.provider, model=config.model, analysis=analysis)
