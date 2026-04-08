# Firewall LLM Triage — Plan Index

**Source:** [`2026-04-08-firewall-llm-triage.md`](./2026-04-08-firewall-llm-triage.md) (design + analysis)

**Created:** 2026-04-08

## Phases

| # | Phase | Plan File | Status | Dependencies |
|---|-------|-----------|--------|--------------|
| 1 | Squid → mitmproxy | [plan-1-mitmproxy.md](./2026-04-08-firewall-llm-triage-plan-1-mitmproxy.md) | ⬚ Not started | — |
| 2 | Rule engine + auth | [plan-2-rule-engine.md](./2026-04-08-firewall-llm-triage-plan-2-rule-engine.md) | ⬚ Not started | Phase 1 |
| 3 | LLM evaluation + audit | [plan-3-llm-evaluation.md](./2026-04-08-firewall-llm-triage-plan-3-llm-evaluation.md) | ⬚ Not started | Phase 1, Phase 2 |

**Status legend:** ⬚ Not started · 🔨 In progress · ✅ Complete · ⏸ Blocked

## Notes

- Phases must be executed sequentially (each depends on the previous)
- Each phase plan is self-contained and can be executed independently via executing-plans or subagent-driven-development
- Phase 1 delivers functional equivalence with Squid (no new features)
- Phase 2 adds granular rules, git push blocking, and API auth
- Phase 3 adds LLM evaluation, audit log, and developer review flow
