"""Consistent JSON response envelopes used across every endpoint."""

from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict

T = TypeVar("T")


class SuccessResponse(BaseModel, Generic[T]):
    """Standard success envelope: `{"success": true, "message": ..., "data": ...}`."""

    model_config = ConfigDict(json_schema_extra={"example": {"success": True}})

    success: bool = True
    message: str
    data: T | None = None


class ErrorResponse(BaseModel):
    """Standard error envelope: `{"success": false, "message": ..., "error_code": ...}`."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "success": False,
                "message": "Invalid OTP",
                "error_code": "INVALID_OTP",
            }
        }
    )

    success: bool = False
    message: str
    error_code: str
    details: dict[str, object] | None = None
