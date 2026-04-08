import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from typing import Literal

from pydantic import BaseModel

from database import (
    init_db, create_rule, get_rule, list_rules, update_rule, delete_rule,
    import_whitelist,
    create_decision, get_decision, list_decisions, list_pending_review,
    list_escalated, update_review_status, cleanup_old_decisions,
)

logger = logging.getLogger(__name__)

MANAGER_AUTH_TOKEN = os.environ.get("MANAGER_AUTH_TOKEN", "")


async def verify_auth(request: Request):
    """Verify Bearer token for management API endpoints."""
    if not MANAGER_AUTH_TOKEN:
        return  # no token configured — dev mode, allow all
    auth = request.headers.get("Authorization", "")
    if auth != f"Bearer {MANAGER_AUTH_TOKEN}":
        raise HTTPException(status_code=401, detail="Unauthorized")


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
    await cleanup_old_decisions()  # retention cleanup on start
    yield


app = FastAPI(title="Firewall Manager", lifespan=lifespan)
templates = Jinja2Templates(directory="templates")


# --- Pydantic models ---


class RuleCreate(BaseModel):
    domain: str
    action: Literal["allow", "deny"]
    path_pattern: str | None = None
    path_prefix: str | None = None
    description: str | None = None


class RuleUpdate(BaseModel):
    domain: str | None = None
    action: Literal["allow", "deny"] | None = None
    path_pattern: str | None = None
    path_prefix: str | None = None
    description: str | None = None


# --- HTML dashboard ---


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    return templates.TemplateResponse("index.html", {
        "request": request,
        "auth_token": MANAGER_AUTH_TOKEN,
    })


# --- Rules CRUD API ---


@app.get("/api/rules", dependencies=[Depends(verify_auth)])
async def api_list_rules():
    return await list_rules()


@app.post("/api/rules", status_code=201, dependencies=[Depends(verify_auth)])
async def api_create_rule(body: RuleCreate):
    if body.path_pattern and len(body.path_pattern) > 200:
        raise HTTPException(status_code=400, detail="path_pattern exceeds 200 chars")
    rule = await create_rule(
        domain=body.domain, action=body.action,
        path_pattern=body.path_pattern, path_prefix=body.path_prefix,
        description=body.description,
    )
    return rule


@app.put("/api/rules/{rule_id}", dependencies=[Depends(verify_auth)])
async def api_update_rule(rule_id: str, body: RuleUpdate):
    if body.path_pattern and len(body.path_pattern) > 200:
        raise HTTPException(status_code=400, detail="path_pattern exceeds 200 chars")
    rule = await update_rule(rule_id, domain=body.domain, action=body.action,
                             path_pattern=body.path_pattern, path_prefix=body.path_prefix,
                             description=body.description)
    if rule is None:
        raise HTTPException(status_code=404, detail="Rule not found")
    return rule


@app.delete("/api/rules/{rule_id}", dependencies=[Depends(verify_auth)])
async def api_delete_rule(rule_id: str):
    deleted = await delete_rule(rule_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Rule not found")
    return {"deleted": True}


# --- Escalated requests ---

@app.get("/api/escalated", dependencies=[Depends(verify_auth)])
async def api_list_escalated():
    """List escalated decisions pending developer action."""
    return await list_escalated()

@app.post("/api/escalated/{decision_id}/approve", dependencies=[Depends(verify_auth)])
async def api_approve_escalated(decision_id: str):
    """Approve an escalated request — creates allow rule for the domain."""
    decision = await get_decision(decision_id)
    if decision is None:
        raise HTTPException(status_code=404, detail="Decision not found")
    if decision["decision"] != "escalate":
        raise HTTPException(status_code=400, detail="Decision is not escalated")
    # Create allow rule for this domain
    await create_rule(domain=decision["domain"], action="allow",
                      description=f"Approved from escalation {decision_id}")
    await update_review_status(decision_id, "approved")
    return {"status": "approved", "domain": decision["domain"]}

@app.post("/api/escalated/{decision_id}/deny", dependencies=[Depends(verify_auth)])
async def api_deny_escalated(decision_id: str):
    """Deny an escalated request."""
    decision = await get_decision(decision_id)
    if decision is None:
        raise HTTPException(status_code=404, detail="Decision not found")
    await update_review_status(decision_id, "denied")
    return {"status": "denied", "domain": decision["domain"]}


# --- LLM decisions ---

@app.get("/api/decisions", dependencies=[Depends(verify_auth)])
async def api_list_decisions(limit: int = 50, offset: int = 0):
    """List LLM decisions, paginated."""
    return await list_decisions(limit=limit, offset=offset)

@app.get("/api/decisions/pending-review", dependencies=[Depends(verify_auth)])
async def api_pending_review():
    """List auto-approved decisions pending developer review."""
    return await list_pending_review()

@app.post("/api/decisions/{decision_id}/review", dependencies=[Depends(verify_auth)])
async def api_review_decision(decision_id: str):
    """Mark an auto-approved decision as reviewed."""
    decision = await get_decision(decision_id)
    if decision is None:
        raise HTTPException(status_code=404, detail="Decision not found")
    result = await update_review_status(decision_id, "reviewed")
    return {"status": "reviewed", "id": decision_id}

@app.post("/api/decisions/{decision_id}/block", dependencies=[Depends(verify_auth)])
async def api_block_decision(decision_id: str):
    """Block a previously auto-approved decision — creates deny rule."""
    decision = await get_decision(decision_id)
    if decision is None:
        raise HTTPException(status_code=404, detail="Decision not found")
    # Create deny rule
    await create_rule(domain=decision["domain"], action="deny",
                      description=f"Blocked from review {decision_id}")
    await update_review_status(decision_id, "blocked")
    return {"status": "blocked", "domain": decision["domain"]}
