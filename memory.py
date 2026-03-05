"""
Módulo de memória conversacional.
Sliding window de mensagens no Redis — substitui completamente o sistema de keywords.
"""
import json
import time
import logging

from config import redis_client, CONVERSATION_MAX_MESSAGES, CONVERSATION_TTL

logger = logging.getLogger("SQLBot")


def _key(user_id: int) -> str:
    """Chave Redis para o histórico do usuário."""
    return f"conv:history:{user_id}"


def add_message(user_id: int, role: str, content: str, sql: str = None, row_count: int = None):
    """
    Adiciona uma mensagem ao histórico conversacional.
    
    Args:
        user_id: ID do usuário
        role: "user" ou "assistant"
        content: Conteúdo da mensagem
        sql: SQL gerado (apenas para mensagens do assistant com ação SQL)
        row_count: Número de linhas retornadas (apenas para SQL)
    """
    key = _key(user_id)

    entry = {
        "role": role,
        "content": content,
        "timestamp": time.time(),
    }

    if sql:
        entry["sql"] = sql
    if row_count is not None:
        entry["row_count"] = row_count

    # Adiciona ao final da lista
    redis_client.rpush(key, json.dumps(entry, ensure_ascii=False))

    # Mantém apenas as últimas N mensagens (sliding window)
    redis_client.ltrim(key, -CONVERSATION_MAX_MESSAGES, -1)

    # Renova TTL a cada interação
    redis_client.expire(key, CONVERSATION_TTL)


def get_history(user_id: int) -> list:
    """
    Retorna o histórico conversacional completo do sliding window.
    Retorna lista de dicts: [{"role": ..., "content": ..., "sql": ..., ...}, ...]
    """
    key = _key(user_id)
    raw = redis_client.lrange(key, 0, -1)

    if not raw:
        return []

    return [json.loads(entry) for entry in raw]


def build_llm_messages(system_prompt: str, user_id: int, current_message: str) -> list:
    """
    Constrói a lista de mensagens para enviar ao LLM.
    
    Formato:
    [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": "mensagem antiga 1"},
        {"role": "assistant", "content": "resposta antiga 1"},
        ...
        {"role": "user", "content": current_message}
    ]
    
    O LLM recebe o histórico completo e decide NATURALMENTE se a pergunta
    é continuação ou nova busca — sem nenhuma palavra-chave.
    """
    messages = [{"role": "system", "content": system_prompt}]

    history = get_history(user_id)

    for entry in history:
        role = entry["role"]
        content = entry["content"]

        # Para mensagens do assistant que geraram SQL, incluímos o SQL no conteúdo
        # para que o LLM saiba qual query foi executada
        if role == "assistant" and entry.get("sql"):
            sql_info = entry["sql"]
            row_count = entry.get("row_count", "?")
            content = f"[SQL executado: {sql_info}] [Resultado: {row_count} linhas]\n{content}"

        messages.append({"role": role, "content": content})

    # Mensagem atual do usuário
    messages.append({"role": "user", "content": current_message})

    return messages


def clear_history(user_id: int):
    """Limpa todo o histórico conversacional do usuário."""
    redis_client.delete(_key(user_id))
    logger.info(f"🧹 Histórico conversacional limpo para user {user_id}")
