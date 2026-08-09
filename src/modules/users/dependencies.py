"""FastAPI dependency providers for the `users` module."""

from typing import Annotated

from fastapi import Cookie, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession
from user_agents import parse as parse_user_agent

from src.core.app_config import settings
from src.core.database import get_db_session
from src.modules.notifications.dependencies import get_email_delivery_service
from src.modules.notifications.services.email_delivery_service import EmailDeliveryService
from src.modules.users.exceptions import AdminPrivilegesRequiredError, InvalidAccessTokenError
from src.modules.users.models import User, UserRole
from src.modules.users.service import DeviceContext, UserService


def get_user_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    email_delivery_service: Annotated[EmailDeliveryService, Depends(get_email_delivery_service)],
) -> UserService:
    return UserService(session, email_delivery_service=email_delivery_service)


def get_device_context(request: Request) -> DeviceContext:
    """Derive a human-readable device label plus IP/user-agent from the request."""
    user_agent = request.headers.get("user-agent")
    device = None
    if user_agent:
        parsed = parse_user_agent(user_agent)
        device = f"{parsed.browser.family} on {parsed.os.family}"

    client_ip = request.headers.get("x-forwarded-for", "").split(",")[0].strip() or (
        request.client.host if request.client else None
    )
    return DeviceContext(device=device, ip_address=client_ip, user_agent=user_agent)


async def get_current_user(
    user_service: Annotated[UserService, Depends(get_user_service)],
    access_token: Annotated[str | None, Cookie(alias=settings.ACCESS_TOKEN_COOKIE_NAME)] = None,
) -> User:
    """Resolve the authenticated user from the access-token cookie."""
    if not access_token:
        raise InvalidAccessTokenError(message="Not authenticated")
    return await user_service.get_user_from_access_token(access_token)


CurrentUser = Annotated[User, Depends(get_current_user)]


async def require_admin(current_user: CurrentUser) -> User:
    """Resolve the authenticated user and require the `admin` role."""
    if current_user.role != UserRole.ADMIN:
        raise AdminPrivilegesRequiredError()
    return current_user


AdminUser = Annotated[User, Depends(require_admin)]
