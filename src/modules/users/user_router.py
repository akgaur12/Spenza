"""`user_router`: authentication, password management, and profile endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status

from src.core.app_config import settings
from src.core.rate_limit import limiter
from src.core.responses import SuccessResponse
from src.modules.users.dependencies import (
    CurrentUser,
    get_device_context,
    get_user_service,
)
from src.modules.users.exceptions import InvalidRefreshTokenError
from src.modules.users.models import OTPPurpose
from src.modules.users.schemas import (
    ChangePasswordRequest,
    DeleteUserRequest,
    ForgotPasswordRequest,
    LoginRequest,
    ResendOTPRequest,
    ResetPasswordRequest,
    ResetTokenResponse,
    SignupRequest,
    TokenPair,
    UpdateProfileRequest,
    UpdateUsernameRequest,
    UserMe,
    UserProfile,
    UserPublic,
    VerifyResetOTPRequest,
    VerifySignupOTPRequest,
)
from src.modules.users.service import DeviceContext, TokenIssue, UserService

user_router = APIRouter(prefix="/api/users", tags=["users"])


# ── Cookie helpers ────────────────────────────────────────────────────────


def _set_auth_cookies(response: Response, tokens: TokenIssue) -> None:
    response.set_cookie(
        key=settings.ACCESS_TOKEN_COOKIE_NAME,
        value=tokens.access_token,
        max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        httponly=True,
        secure=settings.COOKIE_SECURE,
        samesite=settings.COOKIE_SAMESITE,
        domain=settings.COOKIE_DOMAIN,
        path=settings.COOKIE_PATH,
    )
    response.set_cookie(
        key=settings.REFRESH_TOKEN_COOKIE_NAME,
        value=tokens.refresh_token,
        max_age=settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 3600,
        httponly=True,
        secure=settings.COOKIE_SECURE,
        samesite=settings.COOKIE_SAMESITE,
        domain=settings.COOKIE_DOMAIN,
        path=settings.COOKIE_PATH,
    )


def _clear_auth_cookies(response: Response) -> None:
    response.delete_cookie(
        settings.ACCESS_TOKEN_COOKIE_NAME, domain=settings.COOKIE_DOMAIN, path=settings.COOKIE_PATH
    )
    response.delete_cookie(
        settings.REFRESH_TOKEN_COOKIE_NAME,
        domain=settings.COOKIE_DOMAIN,
        path=settings.COOKIE_PATH,
    )


# ── Signup / email verification ──────────────────────────────────────────


@user_router.post(
    "/signup",
    response_model=SuccessResponse[UserPublic],
    status_code=status.HTTP_201_CREATED,
    summary="Register a new account and send a signup OTP",
)
@limiter.limit(settings.RATE_LIMIT_AUTH)
async def signup(
    request: Request,
    data: SignupRequest,
    user_service: Annotated[UserService, Depends(get_user_service)],
) -> SuccessResponse[UserPublic]:
    user = await user_service.signup(data)
    return SuccessResponse(
        message="Account created. Check your email for a verification OTP.",
        data=UserPublic.model_validate(user),
    )


@user_router.post(
    "/verify-signup-otp",
    response_model=SuccessResponse[UserPublic],
    summary="Verify the signup OTP and activate the account",
)
@limiter.limit(settings.RATE_LIMIT_OTP)
async def verify_signup_otp(
    request: Request,
    data: VerifySignupOTPRequest,
    user_service: Annotated[UserService, Depends(get_user_service)],
) -> SuccessResponse[UserPublic]:
    user = await user_service.verify_signup_otp(data)
    return SuccessResponse(
        message="Email verified. Your account is now active.",
        data=UserPublic.model_validate(user),
    )


@user_router.post(
    "/resend-otp",
    response_model=SuccessResponse[None],
    summary="Resend the signup verification OTP",
)
@limiter.limit(settings.RATE_LIMIT_OTP)
async def resend_otp(
    request: Request,
    data: ResendOTPRequest,
    user_service: Annotated[UserService, Depends(get_user_service)],
) -> SuccessResponse[None]:
    await user_service.resend_otp(data.email, purpose=OTPPurpose.SIGNUP)
    return SuccessResponse(
        message="If an account with that email exists, a new OTP has been sent."
    )


# ── Login / tokens ────────────────────────────────────────────────────────


@user_router.post(
    "/login",
    response_model=SuccessResponse[UserPublic],
    summary="Log in and receive access/refresh tokens as HttpOnly cookies",
)
@limiter.limit(settings.RATE_LIMIT_AUTH)
async def login(
    request: Request,
    response: Response,
    data: LoginRequest,
    user_service: Annotated[UserService, Depends(get_user_service)],
    device_ctx: Annotated[DeviceContext, Depends(get_device_context)],
) -> SuccessResponse[UserPublic]:
    user = await user_service.authenticate(identifier=data.identifier, password=data.password)
    tokens = await user_service.issue_token_pair(user, device_ctx)
    _set_auth_cookies(response, tokens)
    return SuccessResponse(message="Login successful", data=UserPublic.model_validate(user))


@user_router.post(
    "/login-json",
    response_model=SuccessResponse[TokenPair],
    summary="Log in and receive access/refresh tokens in the response body (non-browser clients)",
)
@limiter.limit(settings.RATE_LIMIT_AUTH)
async def login_json(
    request: Request,
    response: Response,
    data: LoginRequest,
    user_service: Annotated[UserService, Depends(get_user_service)],
    device_ctx: Annotated[DeviceContext, Depends(get_device_context)],
) -> SuccessResponse[TokenPair]:
    user = await user_service.authenticate(identifier=data.identifier, password=data.password)
    tokens = await user_service.issue_token_pair(user, device_ctx)
    _set_auth_cookies(response, tokens)
    return SuccessResponse(
        message="Login successful",
        data=TokenPair(access_token=tokens.access_token, refresh_token=tokens.refresh_token),
    )


@user_router.post(
    "/refresh-token",
    response_model=SuccessResponse[None],
    summary="Rotate the refresh token and issue a new access token",
)
async def refresh_token(
    request: Request,
    response: Response,
    user_service: Annotated[UserService, Depends(get_user_service)],
    device_ctx: Annotated[DeviceContext, Depends(get_device_context)],
) -> SuccessResponse[None]:
    raw_refresh_token = request.cookies.get(settings.REFRESH_TOKEN_COOKIE_NAME)
    if not raw_refresh_token:
        raise InvalidRefreshTokenError(message="No refresh token cookie present")

    _, tokens = await user_service.refresh_tokens(raw_refresh_token, device_ctx)
    _set_auth_cookies(response, tokens)
    return SuccessResponse(message="Token refreshed")


@user_router.post(
    "/logout",
    response_model=SuccessResponse[None],
    summary="Log out of the current device/session",
)
async def logout(
    request: Request,
    response: Response,
    user_service: Annotated[UserService, Depends(get_user_service)],
) -> SuccessResponse[None]:
    raw_refresh_token = request.cookies.get(settings.REFRESH_TOKEN_COOKIE_NAME)
    if raw_refresh_token:
        await user_service.logout(raw_refresh_token)
    _clear_auth_cookies(response)
    return SuccessResponse(message="Logged out successfully")


@user_router.post(
    "/logout-all-devices",
    response_model=SuccessResponse[None],
    summary="Log out of every device/session for the current user",
)
async def logout_all_devices(
    response: Response,
    current_user: CurrentUser,
    user_service: Annotated[UserService, Depends(get_user_service)],
) -> SuccessResponse[None]:
    await user_service.logout_all_devices(current_user.id)
    _clear_auth_cookies(response)
    return SuccessResponse(message="Logged out of all devices")


@user_router.get(
    "/me",
    response_model=SuccessResponse[UserMe],
    summary="Get the currently authenticated user's identity",
)
async def get_me(current_user: CurrentUser) -> SuccessResponse[UserMe]:
    return SuccessResponse(message="OK", data=UserMe.model_validate(current_user))


# ── Password management ──────────────────────────────────────────────────


@user_router.post(
    "/forgot-password",
    response_model=SuccessResponse[None],
    summary="Request a password-reset OTP by email",
)
@limiter.limit(settings.RATE_LIMIT_OTP)
async def forgot_password(
    request: Request,
    data: ForgotPasswordRequest,
    user_service: Annotated[UserService, Depends(get_user_service)],
) -> SuccessResponse[None]:
    await user_service.forgot_password(data.email)
    return SuccessResponse(message="Reset OTP sent.")


@user_router.post(
    "/verify-reset-otp",
    response_model=SuccessResponse[ResetTokenResponse],
    summary="Verify the password-reset OTP and receive a one-time reset token",
)
@limiter.limit(settings.RATE_LIMIT_OTP)
async def verify_reset_otp(
    request: Request,
    data: VerifyResetOTPRequest,
    user_service: Annotated[UserService, Depends(get_user_service)],
) -> SuccessResponse[ResetTokenResponse]:
    reset_token, expires_in_minutes = await user_service.verify_reset_otp(data)
    return SuccessResponse(
        message="OTP verified",
        data=ResetTokenResponse(reset_token=reset_token, expires_in_minutes=expires_in_minutes),
    )


@user_router.post(
    "/reset-password",
    response_model=SuccessResponse[None],
    summary="Reset the password using a verified reset token; revokes all sessions",
)
async def reset_password(
    response: Response,
    data: ResetPasswordRequest,
    user_service: Annotated[UserService, Depends(get_user_service)],
) -> SuccessResponse[None]:
    await user_service.reset_password(data)
    _clear_auth_cookies(response)
    return SuccessResponse(message="Password reset successful. Please log in again.")


@user_router.post(
    "/change-password",
    response_model=SuccessResponse[None],
    summary="Change password while authenticated; revokes all sessions",
)
async def change_password(
    response: Response,
    current_user: CurrentUser,
    data: ChangePasswordRequest,
    user_service: Annotated[UserService, Depends(get_user_service)],
) -> SuccessResponse[None]:
    await user_service.change_password(current_user, data)
    _clear_auth_cookies(response)
    return SuccessResponse(message="Password changed. Please log in again.")


# ── User / profile management ────────────────────────────────────────────


@user_router.patch(
    "/update-username",
    response_model=SuccessResponse[UserPublic],
    summary="Update the current user's username",
)
async def update_username(
    current_user: CurrentUser,
    data: UpdateUsernameRequest,
    user_service: Annotated[UserService, Depends(get_user_service)],
) -> SuccessResponse[UserPublic]:
    user = await user_service.update_username(current_user, data.new_username)
    return SuccessResponse(message="Username updated", data=UserPublic.model_validate(user))


@user_router.patch(
    "/update-profile",
    response_model=SuccessResponse[UserProfile],
    summary="Update the current user's profile fields",
)
async def update_profile(
    current_user: CurrentUser,
    data: UpdateProfileRequest,
    user_service: Annotated[UserService, Depends(get_user_service)],
) -> SuccessResponse[UserProfile]:
    user = await user_service.update_profile(current_user, data)
    return SuccessResponse(message="Profile updated", data=UserProfile.model_validate(user))


@user_router.delete(
    "/delete-user",
    response_model=SuccessResponse[None],
    summary="Permanently delete the current user's account",
)
async def delete_user(
    response: Response,
    current_user: CurrentUser,
    data: DeleteUserRequest,
    user_service: Annotated[UserService, Depends(get_user_service)],
) -> SuccessResponse[None]:
    await user_service.delete_user(current_user, data.current_password)
    _clear_auth_cookies(response)
    return SuccessResponse(message="Account deleted")


@user_router.get(
    "/profile",
    response_model=SuccessResponse[UserProfile],
    summary="Get the current user's full profile",
)
async def get_profile(current_user: CurrentUser) -> SuccessResponse[UserProfile]:
    return SuccessResponse(message="OK", data=UserProfile.model_validate(current_user))
