"""
Módulo de autenticação e autorização.
JWT decorator, verificação de admin, rate limiting.
"""
import logging
from functools import wraps

import jwt as pyjwt
from flask import request, jsonify

from config import JWT_SECRET, JWT_ALGORITHM, RATE_LIMIT_WINDOW, RATE_LIMIT_MAX, redis_client
from database import get_db_connection, release_db_connection

logger = logging.getLogger("SQLBot")


# ==============================================================================
# JWT DECORATOR
# ==============================================================================

def jwt_required(f):
    """Decorator que exige e decodifica token JWT do header Authorization."""
    @wraps(f)
    def decorated(*args, **kwargs):
        auth = request.headers.get("Authorization")
        if not auth or not auth.startswith("Bearer "):
            return jsonify({"error": "Token ausente"}), 401
        try:
            token = auth.split(" ")[1]
            payload = pyjwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM], options={"verify_sub": False})
            request.user = {
                "user_id": payload.get("sub"),
                "tenant_city_id": payload.get("tenant_city_id"),
                "roles": payload.get("roles", []),
            }
        except Exception:
            return jsonify({"error": "Token inválido"}), 401
        return f(*args, **kwargs)
    return decorated


# ==============================================================================
# HELPERS
# ==============================================================================

def rate_limit(tenant_id: str, user_id: int) -> bool:
    """Retorna True se o usuário está dentro do rate limit."""
    key = f"rate:chat:{tenant_id}:{user_id}"
    current = redis_client.incr(key)
    if current == 1:
        redis_client.expire(key, RATE_LIMIT_WINDOW)
    return current <= RATE_LIMIT_MAX


def get_user_is_admin(user_id: int) -> bool:
    """Verifica se o usuário é admin (superuser ou staff), com cache Redis de 5 min."""
    cache_key = f"user:admin:{user_id}"
    cached = redis_client.get(cache_key)
    if cached is not None:
        return cached == "1"

    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COALESCE(is_superuser, false) OR COALESCE(is_staff, false) FROM auth_user WHERE id = %s",
                (user_id,)
            )
            res = cur.fetchone()
            is_admin = bool(res[0]) if res else False
    finally:
        release_db_connection(conn)

    redis_client.setex(cache_key, 300, "1" if is_admin else "0")
    return is_admin


def get_user_name(user_id: int) -> str:
    """Busca o primeiro nome do usuário no banco."""
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT first_name FROM auth_user WHERE id = %s", (user_id,))
            res = cur.fetchone()
            return res[0] if res else "usuário"
    except Exception:
        return "usuário"
    finally:
        release_db_connection(conn)
