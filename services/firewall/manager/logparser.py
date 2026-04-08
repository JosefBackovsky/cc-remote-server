import os
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ACCESS_LOG_PATH = Path(os.environ.get("ACCESS_LOG_PATH", "/data/logs/access.log"))

# Squid native log: timestamp elapsed client result_code size method url ident hierarchy content_type
LOG_PATTERN = re.compile(
    r"^\s*(\d+\.\d+)\s+\d+\s+\S+\s+TCP_DENIED/\d+\s+\d+\s+\w+\s+(\S+)"
)


def parse_blocked_domains(max_lines: int = 5000) -> list[dict]:
    """Parse last max_lines of Squid access log for TCP_DENIED entries.

    Returns list of {"domain": str, "count": int, "last_seen": str}
    sorted by count descending.
    """
    if not ACCESS_LOG_PATH.exists():
        return []

    domain_stats: defaultdict[str, dict] = defaultdict(
        lambda: {"count": 0, "last_seen": 0.0}
    )

    # Read last N lines (tail approach)
    lines = ACCESS_LOG_PATH.read_text().splitlines()
    for line in lines[-max_lines:]:
        match = LOG_PATTERN.match(line)
        if not match:
            continue
        timestamp_str, url = match.groups()
        timestamp = float(timestamp_str)

        # Extract domain from URL (CONNECT host:port or http://host/path)
        domain = _extract_domain(url)
        if not domain:
            continue

        stats = domain_stats[domain]
        stats["count"] += 1
        if timestamp > stats["last_seen"]:
            stats["last_seen"] = timestamp

    result = []
    for domain, stats in domain_stats.items():
        last_seen_dt = datetime.fromtimestamp(stats["last_seen"], tz=timezone.utc)
        result.append({
            "domain": domain,
            "count": stats["count"],
            "last_seen": last_seen_dt.isoformat(),
        })

    result.sort(key=lambda x: x["count"], reverse=True)
    return result


def _extract_domain(url: str) -> str | None:
    """Extract domain from Squid URL field.

    Handles both 'host:port' (CONNECT) and 'http://host/path' formats.
    """
    if "://" in url:
        # http://host:port/path
        without_scheme = url.split("://", 1)[1]
        host_part = without_scheme.split("/", 1)[0]
        return host_part.split(":")[0]
    elif ":" in url:
        # host:port (CONNECT)
        return url.split(":")[0]
    return url or None
