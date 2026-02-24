# Usa uma imagem leve do Python (versão 3.10)
FROM python:3.10-slim

# Define labels para identificação da imagem
LABEL maintainer="deploy-bot"
LABEL description="PtecIA Flask Application"

# Define o diretório de trabalho dentro do container
WORKDIR /app

# Define variáveis de ambiente fixas (não secrets)
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Instala dependências mínimas do sistema (curl para o healthcheck)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Cria usuário não-root (boa prática de segurança)
RUN useradd -m -u 1000 appuser

# Copia e instala dependências primeiro (camada de cache otimizada)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir gunicorn

# CORREÇÃO AQUI:
# O script bash injeta o .env na pasta antes do build.
# O comando abaixo copia TUDO (incluindo o .env injetado).
# Removemos o 'COPY .env .' separado para evitar redundância.
COPY --chown=appuser:appuser . .

# (Opcional) Verificação rápida para garantir que o .env entrou (útil para debug no build)
RUN ls -la .env

# Troca para o usuário não-root
USER appuser

EXPOSE 5000

# Healthcheck
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:5000/ || exit 1

# Comando de execução
CMD ["gunicorn", \
     "--bind", "0.0.0.0:5000", \
     "--workers", "2", \
     "--access-logfile", "-", \
     "--error-logfile", "-", \
     "--no-control-socket", \
     "app:app"]
