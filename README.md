# ValidatedPipelineLangChain

Cadena LCEL que analiza logs de Laravel/Monolog (`CustomerIdentityChangeAttempt`) y devuelve un análisis técnico validado con Pydantic.

## Archivos

- `schemas.py`: modelos Pydantic. `IdentityChangeLog` (entrada), `AnalisisTecnico` (salida: `tecnologias`, `nivel_de_criticidad`, `resumen_tecnico`, `accion`), `LLMConfig` y `ModelResponse`.
- `chain.py`: cliente `ChatOpenAI` / `ChatAnthropic`, `ChatPromptTemplate`, cadena `prompt | model.with_structured_output(AnalisisTecnico)` con `.with_retry()` y la función asíncrona `process_text()`.
- `main.py`: mini-script que procesa un log de ejemplo.
- `stress_test.py`: casos ambiguos, inválidos y con inyección de prompt.

## Flujo

1. **Validación de entrada**: el texto se valida con `IdentityChangeLog`. Si no es válido, no se envía al modelo.
2. **Datos sensibles**: los números de identidad se reemplazan por un hash antes de llegar al LLM.
3. **Salida estructurada**: el modelo responde con el schema `AnalisisTecnico`, que incluye reglas de negocio (bloquear exige criticidad alta).
4. **Reintentos**: si la salida es JSON mal formado, incompleto o inválido, se reintenta hasta 3 veces.
5. **Logs**: cada intento, cada error de validación y el resultado final quedan registrados.

## Uso

```bash
pip install -r requirements.txt
ANTHROPIC_API_KEY=... python main.py   # o OPENAI_API_KEY=...
python stress_test.py
```

Ejemplo de logs cuando el modelo se recupera:

```
INFO    chain: Entrada válida: CustomerIdentityChangeAttempt del cliente 5273903
INFO    chain: Intento 1/3: llamando al modelo
WARNING chain: Intento 1: salida inválida (raíz: Invalid JSON: EOF while parsing a list at line 1 column 26), reintentando
INFO    chain: Intento 2/3: llamando al modelo
INFO    chain: Salida válida en el intento 2: criticidad=media, accion=revision_manual
```
