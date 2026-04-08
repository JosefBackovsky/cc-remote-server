import json
import os
import subprocess
from contextlib import asynccontextmanager

import docker
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

# PORTAL_DOMAIN env var overrides auto-detection (e.g. "cc-ts.backovsky.eu")
PORTAL_DOMAIN = os.environ.get("PORTAL_DOMAIN", "")


def get_hostname() -> str:
    """Return configured domain, or detect Tailscale hostname, or system hostname."""
    if PORTAL_DOMAIN:
        return PORTAL_DOMAIN
    try:
        result = subprocess.run(
            ["tailscale", "status", "--json"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            data = json.loads(result.stdout)
            dns_name = data.get("Self", {}).get("DNSName", "")
            if dns_name:
                return dns_name.rstrip(".")
    except (subprocess.TimeoutExpired, FileNotFoundError, json.JSONDecodeError):
        pass
    try:
        result = subprocess.run(["hostname"], capture_output=True, text=True, timeout=5)
        return result.stdout.strip()
    except Exception:
        return "localhost"


cached_hostname = None


def hostname() -> str:
    global cached_hostname
    if cached_hostname is None:
        cached_hostname = get_hostname()
    return cached_hostname


@asynccontextmanager
async def lifespan(app: FastAPI):
    hostname()  # warm cache
    yield


app = FastAPI(title="Server Portal", lifespan=lifespan)
templates = Jinja2Templates(directory="templates")


def get_services() -> dict:
    """Query Docker for running containers, group by compose project."""
    client = docker.DockerClient(base_url="unix:///var/run/docker.sock")
    containers = client.containers.list(all=True)

    projects: dict[str, list[dict]] = {}

    for c in containers:
        labels = c.labels or {}
        project = labels.get("com.docker.compose.project", "")
        service_name = labels.get("com.docker.compose.service", c.name)

        # Skip the portal itself
        if c.name == "portal":
            continue

        ports = []
        seen_ports = set()
        for container_port, host_bindings in (c.ports or {}).items():
            if host_bindings:
                for binding in host_bindings:
                    host_port = binding.get("HostPort")
                    if host_port and host_port not in seen_ports:
                        seen_ports.add(host_port)
                        proto = "https" if host_port in ("443", "9443") else "http"
                        ports.append({
                            "host_port": host_port,
                            "container_port": container_port,
                            "url": f"{proto}://{hostname()}:{host_port}",
                        })

        # Determine health status
        health = c.status  # "running", "exited", etc.
        try:
            health_status = c.attrs.get("State", {}).get("Health", {}).get("Status")
            if health_status:
                health = health_status  # "healthy", "unhealthy", "starting"
        except Exception:
            pass

        entry = {
            "name": service_name,
            "container_name": c.name,
            "status": health,
            "image": (c.image.tags[0] if c.image.tags else str(c.image.id)[:20]) if c.image else "unknown",
            "ports": sorted(ports, key=lambda p: int(p["host_port"])),
        }

        group = project if project else "_global"
        projects.setdefault(group, []).append(entry)

    # Sort services within each group
    for group in projects:
        projects[group].sort(key=lambda s: s["name"])

    # Sort groups: _global first, then alphabetically
    sorted_projects = {}
    if "_global" in projects:
        sorted_projects["_global"] = projects.pop("_global")
    for key in sorted(projects):
        sorted_projects[key] = projects[key]

    client.close()
    return sorted_projects


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    services = get_services()
    return templates.TemplateResponse("index.html", {
        "request": request,
        "hostname": hostname(),
        "projects": services,
    })


@app.get("/api/services")
async def api_services():
    return {"hostname": hostname(), "projects": get_services()}
