"""Local browser adapter over the same planning and execution functions."""

import asyncio
import secrets
from contextlib import asynccontextmanager
from pathlib import Path
import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, Response, JSONResponse
from fastapi.staticfiles import StaticFiles
from loguru import logger
from pydantic import BaseModel
from starlette.middleware.trustedhost import TrustedHostMiddleware
from brandprobe.config import api_key, load_config
from brandprobe.db import store
from brandprobe.engine import execute
from brandprobe.exceptions import BrandProbeError
from brandprobe.llm import catalog
from brandprobe.planning import make_plan
from brandprobe.report import csv_report, html_report, report_data
from brandprobe.schemas import Audit, AuditConfig, Plan
from brandprobe.worker import lease, recover, remaining


class Preview(BaseModel):
    config: AuditConfig
    demo: bool = True


class Approval(BaseModel):
    plan_id: str
    approved: bool = False


def create_app(root: Path) -> FastAPI:
    token = secrets.token_urlsafe(32)
    plans: dict[str, Plan] = {}
    tasks: set[asyncio.Task] = set()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        try:
            with lease(root):
                recover(root)
        except BrandProbeError:
            pass  # An active worker owns the evidence; never recover its run.
        yield
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    app = FastAPI(title="BrandProbe", lifespan=lifespan)
    app.add_middleware(
        TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "testserver"]
    )
    static = Path(__file__).parent / "static"
    app.mount("/static", StaticFiles(directory=static), name="static")

    @app.middleware("http")
    async def guard(request: Request, call_next):
        if request.method not in (
            "GET",
            "HEAD",
            "OPTIONS",
        ) and not secrets.compare_digest(
            request.headers.get("x-brandprobe-token", ""), token
        ):
            return JSONResponse(
                {"detail": "Reload this local page before submitting a run."},
                status_code=403,
            )
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Cache-Control"] = "no-store"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; frame-ancestors 'none'; base-uri 'none'"
        )
        return response

    @app.exception_handler(BrandProbeError)
    async def domain_error(request: Request, exc: BrandProbeError):
        return JSONResponse({"detail": str(exc)}, status_code=400)

    @app.exception_handler(httpx.HTTPError)
    async def network_error(request: Request, exc: httpx.HTTPError):
        return JSONResponse(
            {
                "detail": "Provider catalog unavailable. Retry the preview later; demo mode works offline."
            },
            status_code=502,
        )

    @app.get("/")
    async def index():
        return FileResponse(static / "index.html")

    @app.get("/api/setup")
    async def setup():
        return {
            "config": load_config(root / "examples/sots.toml").model_dump(mode="json"),
            "token": token,
            "key_configured": bool(api_key(root)),
            "search_key_configured": bool(api_key(root, "BRAVE_SEARCH_API_KEY")),
        }

    @app.get("/api/pilot")
    async def pilot():
        return load_config(root / "examples/sots-pilot.toml").model_dump(mode="json")

    @app.get("/api/models")
    async def models():
        async with httpx.AsyncClient(timeout=30) as client:
            return [m.model_dump(mode="json") for m in await catalog(client)]

    @app.post("/api/plans")
    async def preview(body: Preview):
        async with httpx.AsyncClient(timeout=30) as client:
            plan = await make_plan(body.config, body.demo, client)
        if len(plans) > 100:
            plans.clear()
        plans[plan.id] = plan
        return plan.model_dump(mode="json")

    async def perform(audit: Audit, approved: bool):
        try:
            await execute(
                root,
                audit.plan,
                api_key(root),
                approved=approved,
                audit=audit,
                search_key=api_key(root, "BRAVE_SEARCH_API_KEY"),
            )
        except Exception:
            audit.status = "interrupted"
            store.save(root, audit)
            logger.error(
                "Audit {} interrupted; saved available evidence. Review settings before rerunning.",
                audit.id,
            )

    @app.post("/api/runs")
    async def start(body: Approval):
        if tasks:
            raise BrandProbeError(
                "An audit is already running. Wait for it to finish before starting another."
            )
        plan = plans.get(body.plan_id)
        if plan is None:
            raise BrandProbeError("Preview this audit again before running it.")
        if plan.mode == "live" and (not body.approved or not api_key(root)):
            raise BrandProbeError(
                "Approve the live price preview and configure OPENROUTER_API_KEY first."
            )
        if plan.search_requests and not api_key(root, "BRAVE_SEARCH_API_KEY"):
            raise BrandProbeError(
                "Configure BRAVE_SEARCH_API_KEY before starting the search baseline."
            )
        from datetime import datetime, timezone

        if (
            datetime.now(timezone.utc) - datetime.fromisoformat(plan.created_at)
        ).total_seconds() > 900:
            raise BrandProbeError("Price preview expired. Create a fresh preview.")
        if plan.parent_audit_id and store.has_continuation(root, plan.parent_audit_id):
            raise BrandProbeError(
                "This audit already has a continuation. Inspect its history entry."
            )
        plans.pop(body.plan_id)
        audit = Audit(plan=plan)
        store.save(root, audit)
        task = asyncio.create_task(perform(audit, body.approved))
        tasks.add(task)
        task.add_done_callback(tasks.discard)
        return {"id": audit.id}

    @app.post("/api/runs/{audit_id}/continuation")
    async def continuation(audit_id: str):
        original = store.get(root, audit_id)
        if not original:
            raise HTTPException(404, "Audit not found.")
        if store.has_continuation(root, original.id):
            raise BrandProbeError(
                "This audit already has a continuation. Inspect its history entry."
            )
        work = remaining(original)
        if not work:
            raise BrandProbeError(
                "No never-dispatched answers remain. Uncertain requests require manual review."
            )
        config = original.plan.config.model_copy(deep=True)
        config.search.queries = []  # Never repeat search calls during generation recovery.
        config.models = list(dict.fromkeys(w.model for w in work))
        async with httpx.AsyncClient(timeout=30) as client:
            plan = await make_plan(
                config,
                original.plan.mode == "demo",
                client,
                work_items=work,
                parent_audit_id=original.id,
            )
        plans[plan.id] = plan
        return plan.model_dump(mode="json")

    @app.get("/api/runs")
    async def history():
        return [
            {
                "id": a.id,
                "brand": a.plan.config.brand.name,
                "mode": a.plan.mode,
                "status": a.status,
                "started_at": a.started_at,
                "parent_audit_id": a.plan.parent_audit_id,
                "can_continue": a.status == "interrupted"
                and a.dispatch_journal
                and any(o.status == "skipped" for o in a.observations)
                and not store.has_continuation(root, a.id),
            }
            for a in store.history(root)
        ]

    @app.get("/api/runs/{audit_id}")
    async def result(audit_id: str):
        audit = store.get(root, audit_id)
        if not audit:
            raise HTTPException(404, "Audit not found.")
        return report_data(audit)

    @app.get("/api/runs/{audit_id}/export/{kind}")
    async def export(audit_id: str, kind: str):
        audit = store.get(root, audit_id)
        if not audit:
            raise HTTPException(404, "Audit not found.")
        if kind == "html":
            return HTMLResponse(html_report(audit))
        if kind == "csv":
            return Response(
                csv_report(audit),
                media_type="text/csv",
                headers={
                    "Content-Disposition": f'attachment; filename="brandprobe-{audit.id}.csv"'
                },
            )
        if kind == "json":
            return JSONResponse(
                report_data(audit),
                headers={
                    "Content-Disposition": f'attachment; filename="brandprobe-{audit.id}.json"'
                },
            )
        raise HTTPException(404, "Choose html, csv, or json.")

    return app
