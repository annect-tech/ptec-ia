"""
Configuração centralizada da aplicação.
Carrega variáveis de ambiente e exporta constantes/clients reutilizáveis.
"""
import os
import logging
import redis
import psycopg2
from psycopg2 import pool
from dotenv import load_dotenv

# ==============================================================================
# AMBIENTE
# ==============================================================================
load_dotenv()

# Logs estruturados
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - [%(levelname)s] - %(name)s - %(message)s'
)
logger = logging.getLogger("SQLBot")

# ==============================================================================
# REDIS
# ==============================================================================
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
redis_client = redis.Redis.from_url(
    REDIS_URL,
    decode_responses=True,
    socket_connect_timeout=5,   # 5 segundos para conectar
    socket_timeout=10,          # 10 segundos para cada comando
    socket_keepalive=True,
    retry_on_timeout=True
)

# ==============================================================================
# IA / LLM
# ==============================================================================
#IA_URL = os.getenv("IA_URL")
#MODEL_NAME = "llama-4-maverick"
#IA_TIMEOUT = 45

# ==============================================================================
# BANCO DE DADOS (Connection Pool)
# ==============================================================================
DB_HOST = os.getenv("DB_HOST")
DB_PORT = os.getenv("DB_PORT")
DB_NAME = os.getenv("DB_NAME")
DB_USER = os.getenv("DB_USER")
DB_PASS = os.getenv("DB_PASS")
MIN_CONN = 1
MAX_CONN = 20

try:
    pg_pool = psycopg2.pool.ThreadedConnectionPool(
        MIN_CONN, MAX_CONN,
        host=DB_HOST, port=DB_PORT, database=DB_NAME, user=DB_USER, password=DB_PASS
    )
    logger.info("Connection Pool do PostgreSQL iniciado com sucesso.")
except Exception as e:
    logger.critical(f"Falha ao criar Pool de Conexão: {e}")
    pg_pool = None

# ==============================================================================
# JWT
# ==============================================================================
JWT_SECRET = os.getenv("JWT_SECRET", "default_secret_change_me")
JWT_ALGORITHM = "HS256"

# ==============================================================================
# RATE LIMITING
# ==============================================================================
RATE_LIMIT_WINDOW = 10  # segundos
RATE_LIMIT_MAX = 5      # requisições por janela

# ==============================================================================
# SEGURANÇA — WHITELIST DE TABELAS
# ==============================================================================
ALLOWED_TABLES = {
    "auth_user", "seletivo_userdata", "seletivo_address",
    "seletivo_guardian", "student_data_studentdata",
    "seletivo_exam", "seletivo_process",
    "seletivo_examlocal", "seletivo_examdate", "seletivo_examhour",
    "seletivo_registrationdata", "candidate_candidatedocument",
    "seletivo_academicmeritdocument", "candidate_quota",
    "faq", "tenant_city", "seletivo_allowedcity",
    "seletivo_contract", "enem_enemresult",
    "seletivo_persona", "user_profile_userprofile",
}

# ==============================================================================
# MEMÓRIA CONVERSACIONAL
# ==============================================================================
CONVERSATION_MAX_MESSAGES = 10   # últimas N mensagens no sliding window
CONVERSATION_TTL = 1800          # 30 minutos de inatividade
