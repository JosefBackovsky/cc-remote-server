# Firewall — TODO

## Firewall Manager — automatické schvalování přes LLM

Aktuálně developer musí ručně schvalovat každou žádost o přístup k doméně. Přidat auto-approval vrstvu, kde LLM (Sonnet 4.6) vyhodnotí žádost a automaticky schválí/zamítne na základě kontextu.

LLM posoudí:
- Zda doména dává smysl pro uvedený důvod (např. `docs.python.org` pro "need asyncio docs" → OK)
- Zda nehrozí exfiltrace citlivých dat (např. požadavek na neznámý webhook endpoint → zamítnout)
- Zda doména není podezřelá (typosquatting, known malicious)

- [ ] Navrhnout prompt pro vyhodnocování žádostí (doména + reason + kontext projektu)
- [ ] Integrace s Claude API (Sonnet 4.6) ve Firewall Manageru
- [ ] Definovat politiku: auto-approve / auto-deny / escalate na developera
- [ ] Logging rozhodnutí LLM pro audit trail
