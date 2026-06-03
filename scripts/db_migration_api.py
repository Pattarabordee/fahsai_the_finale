#!/usr/bin/env python
"""Internal admin API for applying allowlisted FahMai DB migrations.

Run with:
    uvicorn scripts.db_migration_api:app --host 127.0.0.1 --port 8081
"""

from __future__ import annotations

import hmac
import logging
import os
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, status
from pydantic import BaseModel, Field

from scripts.apply_db_migrations import MIGRATIONS, ROOT, run_migration_batch

logger = logging.getLogger(__name__)

app = FastAPI(
    title="FahMai DB Migration Admin API",
    version="1.0.0",
    description="Internal-only API for applying approved FahMai database migrations.",
)


class MigrationApplyRequest(BaseModel):
    migrations: list[str] | str = Field(
        default="schema",
        description="Use schema, full, or an ordered list of migration ids.",
    )
    dry_run: bool = Field(default=False, description="Preview migrations without connecting to the database.")
    verify: bool = Field(default=True, description="Run schema and extension verification after apply.")


def require_admin_token(authorization: Annotated[str | None, Header()] = None) -> None:
    expected_token = os.getenv("DB_MIGRATION_ADMIN_TOKEN")
    if not expected_token:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="DB_MIGRATION_ADMIN_TOKEN is not configured",
        )

    expected_header = f"Bearer {expected_token}"
    if not authorization or not hmac.compare_digest(authorization, expected_header):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid admin token")


AdminAuth = Annotated[None, Depends(require_admin_token)]


def normalize_migration_selection(selection: list[str] | str) -> str:
    if isinstance(selection, str):
        return selection
    return ",".join(selection)


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/internal/db/migrations")
def list_migrations(_: AdminAuth) -> dict[str, list[dict[str, str]]]:
    return {
        "migrations": [
            {"migration": key, "path": path.relative_to(ROOT).as_posix()}
            for key, path in MIGRATIONS.items()
        ]
    }


@app.post("/internal/db/migrations/apply")
def apply_migrations(request: MigrationApplyRequest, _: AdminAuth) -> dict:
    database_url = os.getenv("DATABASE_URL")
    if not request.dry_run and not database_url:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="DATABASE_URL is not configured",
        )

    selection = normalize_migration_selection(request.migrations)
    logger.info(
        "db migration request migrations=%s dry_run=%s verify=%s",
        selection,
        request.dry_run,
        request.verify,
    )

    try:
        return run_migration_batch(
            database_url=database_url,
            selection=selection,
            dry_run=request.dry_run,
            verify=request.verify,
            verbose=False,
        )
    except SystemExit as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Migration file is missing: {exc}",
        ) from exc
