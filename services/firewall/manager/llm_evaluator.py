"""Azure OpenAI evaluator for firewall request classification."""

import asyncio
import json
import logging
import os

logger = logging.getLogger("firewall.llm")

AZURE_ENDPOINT = os.environ.get("AZURE_OPENAI_ENDPOINT", "")
AZURE_API_KEY = os.environ.get("AZURE_OPENAI_API_KEY", "")
AZURE_DEPLOYMENT = os.environ.get("AZURE_OPENAI_DEPLOYMENT", "gpt-5.4-mini")
AZURE_API_VERSION = os.environ.get("AZURE_OPENAI_API_VERSION", "2025-12-01-preview")
PROJECT_CONTEXT = os.environ.get("PROJECT_CONTEXT", "")
LLM_TIMEOUT = int(os.environ.get("LLM_TIMEOUT", "5"))

SYSTEM_PROMPT = """You are a security evaluator for a development sandbox firewall.
Your job is to decide if an outbound HTTP request is safe or represents
a data exfiltration risk.

APPROVE if:
- Domain is a well-known developer resource (docs, package registry, API docs)
- Request is clearly development-related (fetching dependencies, reading docs)
- No sensitive data visible in URL, headers, or body

DENY if:
- Request body contains tokens, API keys, passwords, or credentials
- Domain appears to be a data exfiltration endpoint (webhook, pastebin, file sharing)
- Domain is typosquatting a legitimate domain
- Request is git-receive-pack (push) to any host
- Request body contains high-entropy strings that could be encoded credentials

ESCALATE if:
- You're not confident in your assessment
- Domain is legitimate but request content is unusual
- Request goes to a cloud API that could be used for both legitimate and malicious purposes

Respond with JSON only: {"decision": "approve"|"deny"|"escalate", "reasoning": "..."}"""

ESCALATE_RESPONSE = {"decision": "escalate", "reasoning": "LLM evaluation unavailable"}


def _build_user_message(domain: str, url: str, method: str, headers: dict,
                        body: bytes | None, project_context: str) -> str:
    """Build the user message with request details for LLM evaluation."""
    parts = [
        f"Domain: {domain}",
        f"URL: {url}",
        f"Method: {method}",
    ]
    if project_context:
        parts.append(f"Project: {project_context}")

    # Filter sensitive headers
    safe_headers = {k: v for k, v in headers.items()
                    if k.lower() not in ("authorization", "cookie", "x-api-key")}
    if safe_headers:
        parts.append(f"Headers: {json.dumps(safe_headers, default=str)}")

    if body:
        # Truncate to ~4KB
        body_preview = body[:4096]
        try:
            body_str = body_preview.decode("utf-8", errors="replace")
        except Exception:
            body_str = repr(body_preview)
        parts.append(f"Body ({len(body)} bytes, showing first {len(body_preview)}):\n{body_str}")

    return "\n".join(parts)


def _parse_llm_response(content: str) -> dict:
    """Parse LLM response JSON. Returns escalate on any parse failure."""
    try:
        # Try to find JSON in the response
        content = content.strip()
        if content.startswith("```"):
            # Strip markdown code blocks
            lines = content.split("\n")
            content = "\n".join(lines[1:-1] if lines[-1].startswith("```") else lines[1:])
        result = json.loads(content)
        decision = result.get("decision", "").lower()
        if decision not in ("approve", "deny", "escalate"):
            logger.warning("Invalid LLM decision '%s', escalating", decision)
            return {"decision": "escalate", "reasoning": f"Invalid LLM response: {content[:200]}"}
        return {"decision": decision, "reasoning": result.get("reasoning", "")}
    except (json.JSONDecodeError, AttributeError) as e:
        logger.warning("Failed to parse LLM response: %s", e)
        return {"decision": "escalate", "reasoning": f"Failed to parse LLM response: {content[:200]}"}


async def evaluate_request(domain: str, url: str, method: str, headers: dict,
                           body: bytes | None, project_context: str | None = None) -> dict:
    """Evaluate a request using Azure OpenAI.

    Returns {"decision": "approve"|"deny"|"escalate", "reasoning": "..."}
    On timeout or error, returns escalate (safe fallback).
    """
    if not AZURE_ENDPOINT or not AZURE_API_KEY:
        logger.warning("Azure OpenAI not configured, escalating")
        return ESCALATE_RESPONSE

    try:
        from openai import AsyncAzureOpenAI
    except ImportError:
        logger.error("openai package not installed, escalating")
        return ESCALATE_RESPONSE

    user_msg = _build_user_message(domain, url, method, headers, body,
                                    project_context or PROJECT_CONTEXT)

    client = AsyncAzureOpenAI(
        azure_endpoint=AZURE_ENDPOINT,
        api_key=AZURE_API_KEY,
        api_version=AZURE_API_VERSION,
    )

    try:
        response = await asyncio.wait_for(
            client.chat.completions.create(
                model=AZURE_DEPLOYMENT,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_msg},
                ],
                temperature=0,
                max_tokens=200,
            ),
            timeout=LLM_TIMEOUT,
        )
        content = response.choices[0].message.content
        return _parse_llm_response(content)
    except asyncio.TimeoutError:
        logger.warning("LLM evaluation timed out after %ds for %s", LLM_TIMEOUT, domain)
        return {"decision": "escalate", "reasoning": f"LLM timeout ({LLM_TIMEOUT}s)"}
    except Exception as e:
        logger.error("LLM evaluation failed for %s: %s", domain, e)
        return {"decision": "escalate", "reasoning": f"LLM error: {str(e)[:200]}"}
    finally:
        await client.close()
