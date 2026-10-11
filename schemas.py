# schemas.py
import hashlib
from enum import Enum
from typing import Literal, Optional

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, SecretStr, model_validator


# --- Configuración del LLM ---

class Provider(str, Enum):
    OPENAI = "openai"
    ANTHROPIC = "anthropic"


class LLMConfig(BaseModel):
    provider: Provider
    api_key: SecretStr
    model: str = Field(min_length=1)
    temperature: float = Field(0.0, ge=0, le=2)  # 0 para decisiones reproducibles
    max_tokens: int = Field(500, gt=0)


# --- Entrada: log CustomerIdentityChangeAttempt ---

class IdentityChangeContext(BaseModel):
    customer_id: int
    current_identity_number: str = Field(pattern=r"^\d{6,9}$")
    requested_identity_number: str = Field(pattern=r"^\d{6,9}$")


class IdentityChangeLog(BaseModel):
    message: Literal["CustomerIdentityChangeAttempt"]
    context: IdentityChangeContext
    level: Literal[300]
    level_name: Literal["WARNING"]
    channel: str
    datetime: AwareDatetime

    def to_llm(self) -> dict:
        """Lo que se manda al LLM: misma estructura del log, pero los DNI van como hash, nunca en claro.

        `extra` queda afuera: en Monolog ahí suelen ir IP, URL o user agent, que no se validan.
        """
        def mask(v: str) -> str:
            return "id_" + hashlib.sha256(v.encode()).hexdigest()[:8]

        data = self.model_dump(mode="json")
        ctx = data["context"]
        ctx["current_identity_number"] = mask(ctx["current_identity_number"])
        ctx["requested_identity_number"] = mask(ctx["requested_identity_number"])
        return data


# --- Salida: análisis del LLM ---

class NivelCriticidad(str, Enum):
    BAJA = "baja"
    MEDIA = "media"
    ALTA = "alta"


class Accion(str, Enum):
    IGNORAR = "ignorar"
    REVISION_MANUAL = "revision_manual"
    BLOQUEAR_CAMBIO_IDENTIDAD = "bloquear_cambio_identidad"


class AnalisisTecnico(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tecnologias: list[str] = Field(description="Nombres concretos de productos, lenguajes o librerías inferibles del log (ej. Monolog, PHP). Lista vacía si no hay ninguno identificable")
    nivel_de_criticidad: NivelCriticidad
    resumen_tecnico: str = Field(min_length=10, max_length=1000, description="Qué pasó y por qué importa, en pocas oraciones")
    accion: Accion

    @model_validator(mode="after")
    def reglas_de_negocio(self):
        if self.accion == Accion.BLOQUEAR_CAMBIO_IDENTIDAD and self.nivel_de_criticidad != NivelCriticidad.ALTA:
            raise ValueError("bloquear_cambio_identidad requiere nivel_de_criticidad='alta'")
        return self


class ModelResponse(BaseModel):
    provider: Provider
    model: str
    analysis: Optional[AnalisisTecnico] = None
    error: Optional[str] = None

    @model_validator(mode="after")
    def analysis_xor_error(self):
        if (self.analysis is None) == (self.error is None):
            raise ValueError("Debe haber analysis o error, no ambos ni ninguno")
        return self
