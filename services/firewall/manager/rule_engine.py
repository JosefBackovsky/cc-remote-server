import re
import logging

logger = logging.getLogger(__name__)


class RuleEngine:
    def __init__(self):
        self._deny_rules = []
        self._allow_rules = []

    def load(self, rules: list[dict]) -> None:
        """Load rules into memory. Pre-compile regex patterns.

        Each rule dict has: id, domain, path_pattern (optional), path_prefix (optional), action (allow/deny).
        Regex patterns longer than 200 chars are skipped with a warning.
        """
        deny_rules = []
        allow_rules = []

        for rule in rules:
            pattern = rule.get("path_pattern")
            if pattern is not None:
                if len(pattern) > 200:
                    logger.warning("Rule %s skipped: path_pattern exceeds 200 chars", rule.get("id"))
                    continue
                try:
                    compiled = re.compile(pattern)
                except re.error as e:
                    logger.warning("Rule %s skipped: invalid regex: %s", rule.get("id"), e)
                    continue
            else:
                compiled = None

            entry = {
                "domain": rule["domain"].lower(),
                "path_prefix": rule.get("path_prefix"),
                "path_pattern": compiled,
                "action": rule["action"],
            }

            if rule["action"] == "deny":
                deny_rules.append(entry)
            else:
                allow_rules.append(entry)

        self._deny_rules = deny_rules
        self._allow_rules = allow_rules

    def check(self, domain: str, path: str) -> str | None:
        """Check if a request matches any rule.

        Returns "allow", "deny", or None (no match).

        Priority:
        1. deny rules checked first (security — block always wins)
        2. allow rules checked second
        """
        domain_lower = domain.lower()

        for rule in self._deny_rules:
            if self._matches(rule, domain_lower, path):
                return "deny"

        for rule in self._allow_rules:
            if self._matches(rule, domain_lower, path):
                return "allow"

        return None

    def _matches(self, rule: dict, domain_lower: str, path: str) -> bool:
        rule_domain = rule["domain"]
        if rule_domain != "*" and rule_domain != domain_lower:
            return False

        prefix = rule.get("path_prefix")
        if prefix is not None:
            if not path.startswith(prefix):
                return False

        pattern = rule.get("path_pattern")
        if pattern is not None:
            if not pattern.search(path):
                return False

        return True
