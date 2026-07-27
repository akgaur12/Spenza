"""Response schemas for the `health` module."""

from typing import Literal

from pydantic import BaseModel, ConfigDict


class ComponentHealth(BaseModel):
    """Health of a single component (the app itself, the database, ...)."""

    model_config = ConfigDict(json_schema_extra={"example": {"status": "ok", "detail": None}})

    status: Literal["ok", "error"]
    detail: str | None = None


class HealthReport(BaseModel):
    """Aggregate health across every checked component."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "status": "ok",
                "app": {"status": "ok", "detail": None},
                "database": {"status": "ok", "detail": None},
            }
        }
    )

    status: Literal["ok", "error"]
    app: ComponentHealth
    database: ComponentHealth
