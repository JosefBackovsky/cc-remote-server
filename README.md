# cc-remote-server

Monorepo for the cc-remote platform — isolated Claude Code sandboxes on a remote server.

## Why

Supply-chain and AI-related attacks are increasing (LiteLLM compromise, malicious packages, prompt injection leading to data exfiltration). Running an AI coding agent with full access to source code, secrets, and the internet is a security risk.

**cc-remote** isolates each project in its own sandboxed environment with minimal privileges. The core principle:

> **Claude has full freedom inside the sandbox. Security is enforced at the boundaries — input (firewall) and output (git).**

- **Firewall (input):** A Squid proxy with domain whitelist controls all outbound traffic. Its primary goal is preventing any component from exfiltrating sensitive data. New domains require explicit developer approval.
- **Git isolation (output):** Claude works with a read-only PAT — it can pull and commit, but cannot push. The developer reviews changes and pushes from outside the container. No unwanted code leaves the sandbox.
- **Per-project isolation:** Each project runs in its own Docker Compose stack with its own firewall, credentials, and network. A compromise in one project cannot affect others.

This means the developer doesn't need to restrict what Claude does *inside* the sandbox — no permission prompts, no tool restrictions. The sandbox boundaries provide the safety guarantees.

## Packages

| Package | Description |
|---------|-------------|
| [generator](./generator) | CLI tool for generating devcontainer repositories |
| [server](./server) | Remote dev server setup and orchestration (Docker, Portainer, Portal, Tailscale, TLS) |
| [services](./services) | Docker images for the platform (Portal, Firewall) |
| [setup-skill](./setup-skill) | Claude Code skill for onboarding new projects |
