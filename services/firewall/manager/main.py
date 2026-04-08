import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from database import (
    init_db, create_rule, get_rule, list_rules, update_rule, delete_rule,
    import_whitelist,
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
    yield


app = FastAPI(title="Firewall Manager", lifespan=lifespan)
templates = Jinja2Templates(directory="templates")


# --- Pydantic models ---


class RuleCreate(BaseModel):
    domain: str
    action: str  # "allow" or "deny"
    path_pattern: str | None = None
    path_prefix: str | None = None
    description: str | None = None


class RuleUpdate(BaseModel):
    domain: str | None = None
    action: str | None = None
    path_pattern: str | None = None
    path_prefix: str | None = None
    description: str | None = None


# --- HTML dashboard ---


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


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
