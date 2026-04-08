"""JSONL audit logger for forensic request logging."""

import hashlib
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger("firewall.audit")

AUDIT_LOG_PATH = Path(os.environ.get("AUDIT_LOG_PATH", "/audit/firewall.jsonl"))


class AuditLogger:
    def __init__(self, path: Path | None = None):
        self._path = path or AUDIT_LOG_PATH

    def log(self, domain: str, url: str, method: str, headers: dict,
            body: bytes | None, decision: str, reasoning: str, source: str,
            review_status: str | None = None, latency_ms: int = 0) -> None:
        """Append a single audit entry as JSONL."""
        body_bytes = body or b""
        body_sha256 = hashlib.sha256(body_bytes).hexdigest()
        body_preview = ""
        if body_bytes:
            try:
                body_preview = body_bytes[:4096].decode("utf-8", errors="replace")
            except Exception:
                body_preview = repr(body_bytes[:4096])

        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "domain": domain,
            "url": url,
            "method": method,
            "headers": {k: v for k, v in headers.items()},
            "body_sha256": body_sha256,
            "body_preview": body_preview,
            "decision": decision,
            "reasoning": reasoning,
            "source": source,
            "review_status": review_status,
            "latency_ms": latency_ms,
        }

        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._path.open("a") as f:
                f.write(json.dumps(entry, default=str) + "\n")
        except Exception as e:
            logger.error("Failed to write audit log: %s", e)
