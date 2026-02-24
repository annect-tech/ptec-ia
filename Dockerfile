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

# Instala dependências mínimas do sistema
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

# Copia o .env (contém variáveis sensíveis)
# Atenção: só faça isso se for ambiente de desenvolvimento ou CI específico
# Em produção → use Docker secrets, --env-file ou variáveis no compose / swarm / kubernetes
COPY --chown=appuser:appuser .env .

# Copia todo o restante do código (já com o dono correto)
COPY --chown=appuser:appuser . .

USER appuser

EXPOSE 5000

HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:5000/ || exit 1

CMD ["gunicorn", \
     "--bind", "0.0.0.0:5000", \
     "--workers", "2", \
     "--access-logfile", "-", \
     "--error-logfile", "-", \
     "--no-control-socket", \
     "app:app"]
