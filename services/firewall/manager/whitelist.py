import os
from pathlib import Path

WHITELIST_PATH = Path(os.environ.get("WHITELIST_PATH", "/data/whitelist.txt"))


def read_whitelist() -> list[str]:
    """Read current whitelist, skipping comments and blank lines."""
    if not WHITELIST_PATH.exists():
        return []
    domains = []
    for line in WHITELIST_PATH.read_text().splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            domains.append(stripped)
    return domains


def add_domain(domain: str) -> bool:
    """Add domain to whitelist. Returns False if already present."""
    domains = read_whitelist()
    if domain in domains:
        return False
    with WHITELIST_PATH.open("a") as f:
        f.write(f"\n{domain}\n")
    return True


def remove_domain(domain: str) -> bool:
    """Remove domain from whitelist. Returns False if not found."""
    if not WHITELIST_PATH.exists():
        return False
    lines = WHITELIST_PATH.read_text().splitlines()
    new_lines = [line for line in lines if line.strip() != domain]
    if len(new_lines) == len(lines):
        return False
    WHITELIST_PATH.write_text("\n".join(new_lines) + "\n")
    return True
