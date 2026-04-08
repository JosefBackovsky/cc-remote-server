from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from database import init_db, create_request, get_request, list_requests, update_request_status
from whitelist import read_whitelist, add_domain, remove_domain
from logparser import parse_blocked_domains


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
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
    """Aggregated TCP_DENIED entries from Squid access log."""
    whitelist = set(read_whitelist())
    blocked = parse_blocked_domains()
    # Filter out domains already whitelisted
    return [entry for entry in blocked if entry["domain"] not in whitelist]


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
