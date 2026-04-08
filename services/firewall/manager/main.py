import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from database import (
    init_db, create_request, get_request, list_requests, update_request_status,
    create_rule, list_rules, import_whitelist,
)
from whitelist import read_whitelist, add_domain, remove_domain

logger = logging.getLogger(__name__)


async def _migrate_whitelist_to_rules():
    """One-time migration: import whitelist.txt into rules table."""
    rules = await list_rules()
    if rules:
        return  # already migrated

    # Import whitelist
    whitelist_path = Path(os.environ.get("WHITELIST_PATH", "/data/whitelist.txt"))
    default_path = Path("/opt/whitelist-default.txt")

    source = whitelist_path if whitelist_path.exists() else default_path
    if source.exists():
        domains = [line.strip() for line in source.read_text().splitlines()
                   if line.strip() and not line.strip().startswith("#")]
        count = await import_whitelist(domains)
        logger.info("Migrated %d domains from %s to rules", count, source)

    # Import EXTRA_DOMAINS
    extra = os.environ.get("EXTRA_DOMAINS", "")
    if extra:
        extra_domains = [d.strip() for d in extra.split(",") if d.strip()]
        count = await import_whitelist(extra_domains)
        logger.info("Imported %d extra domains to rules", count)

    # Git push block rule
    await create_rule(domain="*", action="deny",
                      path_pattern=".*/git-receive-pack$",
                      description="Block git push (security)")
    logger.info("Added git push block rule")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    await _migrate_whitelist_to_rules()
    yield


app = FastAPI(title="Firewall Manager", lifespan=lifespan)
templates = Jinja2Templates(directory="templates")


# --- Pydantic models ---


class DomainRequest(BaseModel):
    domain: str
    reason: str


class DomainAction(BaseModel):
    domain: str


# --- HTML dashboard ---


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


# --- Claude request API ---


@app.post("/api/request")
async def submit_request(body: DomainRequest):
    """Claude submits a request to access a blocked domain."""
    result = await create_request(body.domain, body.reason)
    return {"id": result["id"], "status": result["status"]}


@app.get("/api/requests")
async def get_requests():
    """List all domain access requests."""
    return await list_requests()


@app.get("/api/requests/{request_id}")
async def get_request_detail(request_id: str):
    """Get status of a specific request (Claude polls this)."""
    result = await get_request(request_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Request not found")
    return result


@app.post("/api/requests/{request_id}/approve")
async def approve_request(request_id: str):
    """Approve a pending request — adds domain to whitelist."""
    req = await get_request(request_id)
    if req is None:
        raise HTTPException(status_code=404, detail="Request not found")
    if req["status"] != "pending":
        raise HTTPException(status_code=400, detail=f"Request is already {req['status']}")

    add_domain(req["domain"])
    result = await update_request_status(request_id, "approved")
    return {"status": "approved", "domain": req["domain"]}


@app.post("/api/requests/{request_id}/deny")
async def deny_request(request_id: str):
    """Deny a pending request."""
    req = await get_request(request_id)
    if req is None:
        raise HTTPException(status_code=404, detail="Request not found")
    if req["status"] != "pending":
        raise HTTPException(status_code=400, detail=f"Request is already {req['status']}")

    result = await update_request_status(request_id, "denied")
    return {"status": "denied", "domain": req["domain"]}


# --- Direct whitelist management ---


@app.get("/api/blocked")
async def get_blocked_domains():
    """Blocked domains — placeholder, will be replaced by LLM decisions in Phase 3."""
    return []


@app.post("/api/approve")
async def approve_domain_directly(body: DomainAction):
    """Approve a domain directly (from blocked view, without Claude request)."""
    added = add_domain(body.domain)
    return {"status": "approved", "domain": body.domain, "added": added}


@app.delete("/api/revoke")
async def revoke_domain(body: DomainAction):
    """Remove a domain from whitelist."""
    removed = remove_domain(body.domain)
    if not removed:
        raise HTTPException(status_code=404, detail="Domain not in whitelist")
    return {"status": "revoked", "domain": body.domain}


@app.get("/api/whitelist")
async def get_whitelist():
    """Current whitelist contents."""
    return read_whitelist()
