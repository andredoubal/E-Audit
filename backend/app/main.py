import re

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .db import init_db
from .api.routes import router
from .llm import guidance

app = FastAPI(title="ZATCA VAT Audit Agent", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_list,
    allow_methods=["*"],
    allow_headers=["*"],
)

_CASE_PATH = re.compile(r"^/api/cases/([A-Za-z0-9][A-Za-z0-9._-]{0,29})(?:/|$)")


@app.middleware("http")
async def _case_instructions(request: Request, call_next):
    """Load the case's standing instructions once, for the whole request.

    Here rather than in each endpoint because the instruction belongs to the *case*, and every
    model call this application makes happens inside a request whose path names one. Doing it
    per-feature would mean the next AI surface someone adds silently ignores what the auditor
    wrote — and an instruction the auditor believes is in force everywhere, but is not, is worse
    than no instruction at all.

    Cheap: one indexed lookup on paths that name a case, nothing on any other route, and it is
    skipped entirely when no model is reachable, since a deterministic fallback has no prompt to
    steer.
    """
    guidance.clear()
    match = _CASE_PATH.match(request.url.path)
    if match:
        from .llm.service import availability

        enabled, _ = availability()
        if enabled:
            from sqlalchemy import select

            from .db import SessionLocal
            from .models import CaseInstruction

            try:
                with SessionLocal() as db:
                    row = db.scalar(select(CaseInstruction).where(
                        CaseInstruction.case_id == match.group(1)))
                    if row is not None and row.enabled:
                        guidance.set_for(row.text)
            except Exception:                            # noqa: BLE001
                # A steer that cannot be loaded must not take the request down with it. The
                # output is then simply un-steered, which is the behaviour before this existed.
                guidance.clear()
    try:
        return await call_next(request)
    finally:
        guidance.clear()


app.include_router(router)


@app.on_event("startup")
def _startup() -> None:
    # Demo bootstrap: ensure schemas/tables exist. Seed with `python -m app.seed.seed`.
    init_db()


@app.get("/")
def root():
    return {"service": "ZATCA VAT Audit Agent", "docs": "/docs", "api": "/api/health"}
