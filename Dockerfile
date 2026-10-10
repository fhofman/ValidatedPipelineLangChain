FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY *.py .

# Sin usuario root
RUN useradd --create-home app
USER app

# Por defecto corre el ejemplo; para la prueba de estrés: docker run ... python stress_test.py
CMD ["python", "main.py"]
