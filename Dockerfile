FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MCP_TRANSPORT=sse \
    MCP_HOST=0.0.0.0 \
    MCP_PORT=3100

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY config.py server.py check.py ./
COPY src ./src

RUN useradd --create-home --uid 10001 mcpserver
USER mcpserver

EXPOSE 3100
CMD ["python", "server.py", "--transport", "sse", "--host", "0.0.0.0", "--port", "3100"]
