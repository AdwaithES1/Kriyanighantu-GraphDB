FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1
WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .
RUN sed -i 's/\r$//' serve.sh && chmod +x serve.sh \
 && python pipeline/build_graph.py \
 && useradd --system --home /app app && chown -R app /app
USER app

EXPOSE 5000
CMD ["./serve.sh"]
