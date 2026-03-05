"""
Módulo de comunicação com o LLM — VERSÃO CORRIGIDA PARA BEDROCK.
Principais mudanças:
- System prompt é extraído do array de mensagens e passado via parâmetro `system` do LiteLLM
- Garante que o array de mensagens sempre começa com role="user"
- Prefill de resposta: envia {"role": "assistant", "content": "{"} para forçar JSON puro
- _extract_json_safely corrigido para trabalhar com prefill
"""

import json
import logging
import os
import re
import litellm
from typing import Optional, Dict, Any, List

logger = logging.getLogger("SQLBot")

MODEL_ID = "anthropic.claude-3-haiku-20240307-v1:0"
MAX_RETRIES = 2


# ==============================================================================
# UTILIDADES
# ==============================================================================

def _force_json_reminder() -> str:
    """Lembrete injetado na última mensagem do usuário em caso de retry."""
    return (
        "\n\n[LEMBRETE CRÍTICO]: Responda SOMENTE com JSON válido. "
        "Nenhum texto fora do objeto JSON. Comece com { e termine com }."
    )


def _extract_json_safely(raw: str, prefill_used: bool = False) -> Optional[Dict[str, Any]]:
    """
    Extrai JSON do retorno do modelo.
    Se prefill_used=True, o modelo retornou apenas o CONTEÚDO após o "{" inicial,
    então precisamos reconstituir o objeto completo.
    """
    if not raw:
        logger.warning("Raw response está vazio")
        return None

    raw = raw.strip()
    logger.debug(f"Raw antes do processamento (primeiros 500 chars): {raw[:500]}")

    # Se usamos prefill com "{", o modelo continuou a partir daí.
    # O retorno será algo como: '"action":"sql","sql":"..."}' (sem o { inicial)
    # Precisamos adicionar o "{" de volta.
    if prefill_used and not raw.startswith("{"):
        logger.debug("Prefill usado - adicionando '{' inicial")
        raw = "{" + raw
    
    # Verifica se o JSON está completo (tem fechamento)
    if not raw.endswith("}"):
        logger.warning(f"JSON parece incompleto (não termina com }}). Últimos 100 chars: ...{raw[-100:]}")
        # Tenta adicionar fechamento se estiver faltando
        raw = raw + "}"
    
    # CRÍTICO: Remove quebras de linha literais dentro de strings
    # JSON não aceita \n literal, precisa ser escapado
    # Estratégia: substitui quebras de linha por espaço dentro do JSON
    # Isso preserva a legibilidade do SQL mas mantém JSON válido
    raw = raw.replace('\n', ' ').replace('\r', '')
    
    logger.debug(f"Raw após ajustes (primeiros 500 chars): {raw[:500]}")

    # Remove blocos markdown ```json ... ``` caso existam
    if raw.startswith("```"):
        lines = raw.split(" ")
        lines = lines[1:] if lines[0].startswith("```") else lines
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        raw = " ".join(lines).strip()

    # Tentativa direta
    try:
        result = json.loads(raw)
        logger.debug(f"JSON parseado com sucesso: {result}")
        return result
    except json.JSONDecodeError as e:
        logger.warning(f"Erro ao parsear JSON diretamente: {e}")

    # Extrai o maior bloco { ... } encontrado
    matches = re.findall(r"\{[^{}]*\}", raw, re.DOTALL)
    logger.debug(f"Encontrados {len(matches)} blocos JSON candidatos")
    
    for idx, candidate in enumerate(reversed(matches)):
        try:
            result = json.loads(candidate)
            logger.debug(f"JSON parseado com sucesso do candidato {idx}: {result}")
            return result
        except Exception as e:
            logger.debug(f"Candidato {idx} falhou: {e}")
            continue

    logger.error("Nenhum JSON válido encontrado em nenhum método")
    return None


def _validate_schema(result: Dict[str, Any]) -> Dict[str, Any]:
    """Garante estrutura mínima válida no JSON retornado."""
    if "action" not in result:
        result["action"] = "sql" if "sql" in result else "chat"

    if result["action"] == "chat" and "response" not in result:
        result["response"] = ""

    if result["action"] == "sql" and "sql" not in result:
        raise ValueError("Action 'sql' sem campo 'sql'")

    return result


def _extract_system_prompt(messages: List[Dict[str, str]]) -> tuple[Optional[str], List[Dict[str, str]]]:
    """
    Extrai o system prompt do array de mensagens e retorna (system_prompt, mensagens_filtradas).
    Bedrock não aceita role="system" no array de mensagens.
    """
    system_prompt = None
    filtered = []
    
    for msg in messages:
        if msg.get("role") == "system":
            # Concatena múltiplos system prompts se houver
            if system_prompt:
                system_prompt += "\n\n" + msg.get("content", "")
            else:
                system_prompt = msg.get("content", "")
        else:
            filtered.append(msg)
    
    return system_prompt, filtered


# ==============================================================================
# CHAMADA BASE AO LLM — CORRIGIDA PARA BEDROCK
# ==============================================================================

def call_ai_service(
    messages: List[Dict[str, str]],
    temperature: float = 0.0
) -> Optional[str]:
    """
    Chama o LLM via Bedrock.
    Extrai automaticamente system prompts do array e garante que mensagens começam com user.
    """

    logger.info(f"Model: {MODEL_ID}")
    logger.info(f"Região AWS: {os.getenv('AWS_REGION', 'não definida')}")

    # Extrai system prompt do array
    system_prompt, filtered_messages = _extract_system_prompt(messages)
    
    # Garante que array começa com user (requerimento do Bedrock)
    if not filtered_messages or filtered_messages[0].get("role") != "user":
        logger.warning("Mensagens não começam com user, ajustando...")
        filtered_messages.insert(0, {"role": "user", "content": "Olá, preciso de ajuda."})

    logger.debug(f"System prompt extraído: {system_prompt[:100] if system_prompt else 'None'}...")
    logger.debug(f"Total de mensagens após filtro: {len(filtered_messages)}")

    try:
        response = litellm.completion(
            model=f"bedrock/{MODEL_ID}",
            messages=filtered_messages,
            system=system_prompt,  # System prompt separado (formato correto para Bedrock)
            temperature=temperature,
            max_tokens=4096,  # Aumentado para evitar truncamento
            top_p=0.95,
        )

        content = response.choices[0].message.content
        logger.info("Chamada LLM bem-sucedida.")
        logger.debug(f"RAW RESPONSE:\n{content}")
        return content

    except Exception as e:
        logger.error(f"Erro ao chamar LLM: {str(e)}")
        return None


# ==============================================================================
# ROTEAMENTO UNIFICADO COM RETRY + PREFILL
# ==============================================================================

def route_and_respond(messages: List[Dict[str, str]]) -> Optional[Dict[str, Any]]:
    """
    Envia mensagens ao LLM e garante retorno JSON válido.

    Estratégia anti-quebra de formato:
    1. Primeira tentativa: usa prefill {"role": "assistant", "content": "{"}
       para forçar o modelo a iniciar e completar um objeto JSON.
    2. Se falhar: retry adicionando lembrete no último user message + prefill novamente.
    """

    from prompts import get_assistant_prefill  # ajuste o import conforme seu projeto

    for attempt in range(MAX_RETRIES):

        current_messages = messages.copy()

        # No retry, injeta lembrete no conteúdo da última mensagem do usuário
        if attempt > 0:
            logger.warning(f"Retry {attempt} — reforçando instrução JSON")
            
            # Encontra última mensagem de usuário
            for i in range(len(current_messages) - 1, -1, -1):
                if current_messages[i].get("role") == "user":
                    current_messages[i] = {
                        "role": "user",
                        "content": current_messages[i]["content"] + _force_json_reminder()
                    }
                    break

        # Adiciona prefill: instrui o modelo a CONTINUAR a partir de "{"
        current_messages.append({
            "role": "assistant",
            "content": get_assistant_prefill()
        })
        
        logger.debug(f"Tentativa {attempt + 1}: enviando {len(current_messages)} mensagens")
        logger.debug(f"Última mensagem (prefill): {current_messages[-1]}")

        raw = call_ai_service(current_messages, temperature=0.0)

        if not raw:
            logger.warning(f"Resposta vazia (tentativa {attempt + 1})")
            continue

        logger.info(f"Raw response completo (tentativa {attempt + 1}): {raw}")

        result = _extract_json_safely(raw, prefill_used=True)

        if not result:
            logger.warning(f"Falha ao extrair JSON (tentativa {attempt + 1}). Raw: {raw[:200]}")
            continue

        try:
            result = _validate_schema(result)
            logger.info(f"JSON válido obtido: {result}")
            return result
        except Exception as e:
            logger.warning(f"Schema inválido (tentativa {attempt + 1}): {str(e)}")
            continue

    logger.error("LLM falhou em todas as tentativas.")
    return {
        "action": "chat",
        "response": "Não foi possível processar a solicitação no momento. Tente novamente."
    }


# ==============================================================================
# FORMATAÇÃO DE RESPOSTA NATURAL
# ==============================================================================

def format_response(format_prompt: str) -> str:
    """Formata dados SQL em linguagem natural usando o LLM."""
    messages = [
        {"role": "system", "content": "Responda de forma clara e objetiva em português."},
        {"role": "user",   "content": format_prompt}
    ]

    raw = call_ai_service(messages, temperature=0.3)

    if not raw:
        return "Dados encontrados, mas não foi possível formatar a resposta."

    return raw.strip()