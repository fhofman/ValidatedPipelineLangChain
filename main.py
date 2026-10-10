# main.py
"""Mini-script de prueba: procesa un log de ejemplo.

Uso:
    ANTHROPIC_API_KEY=... python main.py
    OPENAI_API_KEY=...    python main.py
"""
import asyncio
import logging

from chain import process_text

EJEMPLO = (
    '{"message":"CustomerIdentityChangeAttempt","context":{"customer_id":5273903,'
    '"current_identity_number":"8632307","requested_identity_number":"5889543"},'
    '"level":300,"level_name":"WARNING","channel":"production",'
    '"datetime":"2026-10-08T16:10:25.120620-03:00","extra":{}}'
)


async def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    response = await process_text(EJEMPLO)
    if response.analysis:
        print(response.analysis.model_dump_json(indent=2))
    else:
        print("❌", response.error)


if __name__ == "__main__":
    asyncio.run(main())
