# Firewall — TODO

## Firewall Manager — automatic approval via LLM

Currently the developer must manually approve every domain access request. Add an auto-approval layer where an LLM (Sonnet 4.6) evaluates requests and automatically approves/denies based on context.

The LLM evaluates:
- Whether the domain makes sense for the stated reason (e.g. `docs.python.org` for "need asyncio docs" → OK)
- Whether there's a risk of sensitive data exfiltration (e.g. request for an unknown webhook endpoint → deny)
- Whether the domain is suspicious (typosquatting, known malicious)

- [ ] Design prompt for evaluating requests (domain + reason + project context)
- [ ] Integrate Claude API (Sonnet 4.6) into Firewall Manager
- [ ] Define policy: auto-approve / auto-deny / escalate to developer
- [ ] Log LLM decisions for audit trail
