"""Business logic for the `import_export` module's import side.

`preview()` never writes an expense — it parses + validates every row and
persists only a server-side `ImportSession` (see `models.py`) holding the
*already-validated* rows, returning a signed token that names that session.
`confirm()` never trusts a client-supplied payload: it decodes the token,
re-reads the session from the database, and inserts each row through
`ExpenseService.create_for_user` — the exact same path (and therefore the
exact same category/description/amount rules) as a manually created expense.
"""

import uuid
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Literal

from fastapi import UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.app_config import settings
from src.core.exceptions import AppError
from src.core.logger import get_logger
from src.core.security import (
    TokenExpiredError,
    TokenInvalidError,
    create_action_token,
    decode_action_token,
)
from src.core.timezone import local_midnight_utc
from src.modules.categories.models import Category
from src.modules.categories.repository import CategoryRepository
from src.modules.expenses.repository import ExpenseRepository
from src.modules.expenses.schemas import ExpenseCreate
from src.modules.expenses.service import ExpenseService
from src.modules.expenses.validators import validate_description
from src.modules.import_export.exceptions import (
    ImportConfirmationFailedError,
    ImportFileTooLargeError,
    ImportNoValidRowsError,
    ImportRowLimitExceededError,
    ImportSessionAlreadyConfirmedError,
    ImportSessionExpiredError,
    ImportSessionNotFoundError,
    UnsupportedFileTypeError,
)
from src.modules.import_export.import_repository import ImportSessionRepository
from src.modules.import_export.models import ImportSessionStatus
from src.modules.import_export.parsers import RawImportRow, parse_csv_rows, parse_xlsx_rows
from src.modules.import_export.schemas import (
    ImportConfirmRequest,
    ImportPreviewCategory,
    ImportPreviewResponse,
    ImportPreviewRow,
    ImportResult,
    ImportRowError,
    ImportRowErrorCode,
)
from src.modules.import_export.validators import (
    ImportValueError,
    parse_import_amount,
    parse_import_date,
    validate_import_amount,
)
from src.modules.users.models import User

logger = get_logger(__name__)

IMPORT_SESSION_PURPOSE = "import_session"

_UPLOAD_CHUNK_SIZE = 1024 * 1024


async def _read_upload_within_limit(file: UploadFile, max_bytes: int) -> bytes:
    """Reads the upload in bounded chunks, aborting as soon as the limit is
    exceeded rather than buffering an arbitrarily large file fully into
    memory first.
    """
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(_UPLOAD_CHUNK_SIZE)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise ImportFileTooLargeError(
                message=f"File exceeds the maximum allowed size of {max_bytes} bytes."
            )
        chunks.append(chunk)
    return b"".join(chunks)


class ImportService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._sessions = ImportSessionRepository(session)
        self._categories = CategoryRepository(session)
        self._expenses_repo = ExpenseRepository(session)
        self._expenses = ExpenseService(session)

    # ── Preview ──────────────────────────────────────────────────────────

    async def preview(self, user: User, file: UploadFile) -> ImportPreviewResponse:
        file_name = file.filename or "upload"
        file_type = self._resolve_file_type(file_name)
        content = await _read_upload_within_limit(file, settings.MAX_IMPORT_FILE_SIZE_BYTES)

        raw_rows = list(self._parse_rows(file_type, content))

        preview_rows: list[ImportPreviewRow] = []
        session_rows: list[dict[str, str]] = []
        for raw in raw_rows:
            preview_row, session_row = await self._validate_row(user, raw)
            preview_rows.append(preview_row)
            if session_row is not None:
                session_rows.append(session_row)

        expires_at = datetime.now(UTC) + timedelta(minutes=settings.IMPORT_SESSION_EXPIRE_MINUTES)
        import_session = self._sessions.create(
            user_id=user.id,
            file_name=file_name,
            row_count=len(session_rows),
            rows=list(session_rows),
            expires_at=expires_at,
        )
        await self._sessions.flush()

        import_token = create_action_token(
            subject=str(user.id),
            purpose=IMPORT_SESSION_PURPOSE,
            expire_minutes=settings.IMPORT_SESSION_EXPIRE_MINUTES,
            extra_claims={"session_id": str(import_session.id)},
        )

        valid_rows = len(session_rows)
        logger.info(
            "import.previewed",
            user_id=str(user.id),
            total_rows=len(raw_rows),
            valid_rows=valid_rows,
        )
        return ImportPreviewResponse(
            import_token=import_token,
            file_name=file_name,
            file_type=file_type,
            total_rows=len(raw_rows),
            valid_rows=valid_rows,
            invalid_rows=len(raw_rows) - valid_rows,
            expires_at=expires_at,
            rows=preview_rows,
        )

    def _resolve_file_type(self, file_name: str) -> Literal["csv", "xlsx"]:
        lowered = file_name.lower()
        if lowered.endswith(".csv"):
            return "csv"
        if lowered.endswith(".xlsx"):
            return "xlsx"
        raise UnsupportedFileTypeError(message="Only .csv and .xlsx files are supported.")

    def _parse_rows(
        self, file_type: Literal["csv", "xlsx"], content: bytes
    ) -> Iterator[RawImportRow]:
        parse = parse_csv_rows if file_type == "csv" else parse_xlsx_rows
        for count, row in enumerate(parse(content), start=1):
            if count > settings.MAX_IMPORT_ROWS:
                raise ImportRowLimitExceededError(
                    message=f"File contains more than {settings.MAX_IMPORT_ROWS} rows."
                )
            yield row

    async def _validate_row(
        self, user: User, raw: RawImportRow
    ) -> tuple[ImportPreviewRow, dict[str, str] | None]:
        errors: list[ImportRowError] = []

        parsed_date = self._parse_date_field(raw.date, errors)
        category_response, resolved_category = await self._parse_category_field(
            user, raw.category, errors
        )
        parsed_description = self._parse_description_field(raw.description, errors)
        parsed_amount = self._parse_amount_field(raw.amount, errors)

        spent_at: datetime | None = None
        if (
            not errors
            and parsed_date is not None
            and resolved_category is not None
            and parsed_description is not None
            and parsed_amount is not None
        ):
            spent_at = local_midnight_utc(parsed_date)
            is_duplicate = await self._expenses_repo.exists_duplicate(
                user.id,
                category_id=resolved_category.id,
                description=parsed_description,
                amount=parsed_amount,
                spent_at=spent_at,
            )
            if is_duplicate:
                errors.append(
                    ImportRowError(
                        field="duplicate",
                        code=ImportRowErrorCode.DUPLICATE_EXPENSE,
                        message="An identical expense already exists.",
                    )
                )

        is_valid = not errors
        preview_row = ImportPreviewRow(
            row_number=raw.row_number,
            date=parsed_date,
            category=category_response,
            description=parsed_description,
            amount=parsed_amount,
            valid=is_valid,
            errors=errors,
        )

        session_row: dict[str, str] | None = None
        if (
            is_valid
            and spent_at is not None
            and resolved_category is not None
            and parsed_description is not None
            and parsed_amount is not None
        ):
            session_row = {
                "category_id": str(resolved_category.id),
                "description": parsed_description,
                "amount": str(parsed_amount),
                "spent_at": spent_at.isoformat(),
            }
        return preview_row, session_row

    def _parse_date_field(self, raw_value: object, errors: list[ImportRowError]) -> date | None:
        try:
            return parse_import_date(raw_value)
        except ImportValueError as exc:
            errors.append(
                ImportRowError(field="date", code=ImportRowErrorCode.INVALID_DATE, message=str(exc))
            )
            return None

    async def _parse_category_field(
        self, user: User, raw_value: object, errors: list[ImportRowError]
    ) -> tuple[ImportPreviewCategory | None, Category | None]:
        name = "" if raw_value is None else str(raw_value).strip()
        if not name:
            errors.append(
                ImportRowError(
                    field="category",
                    code=ImportRowErrorCode.CATEGORY_NOT_FOUND,
                    message="Category is required",
                )
            )
            return None, None

        category, error = await self._resolve_category(user, name)
        if error is not None:
            errors.append(error)
            return None, None
        assert category is not None  # `error is None` guarantees this
        return ImportPreviewCategory(id=category.id, name=category.name), category

    def _parse_description_field(
        self, raw_value: object, errors: list[ImportRowError]
    ) -> str | None:
        text = "" if raw_value is None else str(raw_value)
        try:
            value = validate_description(text)
        except ValueError:
            errors.append(
                ImportRowError(
                    field="description",
                    code=ImportRowErrorCode.DESCRIPTION_REQUIRED,
                    message="Description is required",
                )
            )
            return None
        if len(value) > 255:
            errors.append(
                ImportRowError(
                    field="description",
                    code=ImportRowErrorCode.DESCRIPTION_TOO_LONG,
                    message="Description exceeds 255 characters",
                )
            )
            return None
        return value

    def _parse_amount_field(
        self, raw_value: object, errors: list[ImportRowError]
    ) -> Decimal | None:
        try:
            candidate = parse_import_amount(raw_value)
        except ImportValueError as exc:
            errors.append(
                ImportRowError(
                    field="amount", code=ImportRowErrorCode.INVALID_AMOUNT, message=str(exc)
                )
            )
            return None

        if candidate <= 0:
            errors.append(
                ImportRowError(
                    field="amount",
                    code=ImportRowErrorCode.AMOUNT_MUST_BE_POSITIVE,
                    message="Amount must be greater than zero",
                )
            )
            return None

        try:
            return validate_import_amount(candidate)
        except ImportValueError:
            errors.append(
                ImportRowError(
                    field="amount",
                    code=ImportRowErrorCode.INVALID_AMOUNT,
                    message="Amount exceeds the allowed number of digits/decimal places",
                )
            )
            return None

    async def _resolve_category(
        self, user: User, name: str
    ) -> tuple[Category | None, ImportRowError | None]:
        """System and personal categories may legitimately share a
        (case-insensitive) name — see `categories/models.py` — so both scopes
        are checked and an active match in *both* is reported as ambiguous
        rather than arbitrarily preferring one.
        """
        system_match = await self._categories.find_by_name(None, name)
        personal_match = await self._categories.find_by_name(user.id, name)

        active_candidates = [
            c for c in (system_match, personal_match) if c is not None and c.is_active
        ]
        if len(active_candidates) > 1:
            return None, ImportRowError(
                field="category",
                code=ImportRowErrorCode.CATEGORY_AMBIGUOUS,
                message=f"Category '{name}' matches more than one category.",
            )
        if len(active_candidates) == 1:
            return active_candidates[0], None

        inactive_candidates = [c for c in (system_match, personal_match) if c is not None]
        if inactive_candidates:
            return None, ImportRowError(
                field="category",
                code=ImportRowErrorCode.CATEGORY_INACTIVE,
                message=f"Category '{name}' is inactive.",
            )
        return None, ImportRowError(
            field="category",
            code=ImportRowErrorCode.CATEGORY_NOT_FOUND,
            message=f"Category '{name}' was not found.",
        )

    # ── Confirm ──────────────────────────────────────────────────────────

    async def confirm(self, user: User, data: ImportConfirmRequest) -> ImportResult:
        try:
            payload = decode_action_token(
                data.import_token, expected_purpose=IMPORT_SESSION_PURPOSE
            )
        except TokenExpiredError as exc:
            raise ImportSessionExpiredError(message=str(exc)) from exc
        except TokenInvalidError as exc:
            raise ImportSessionNotFoundError() from exc

        if payload.get("sub") != str(user.id):
            raise ImportSessionNotFoundError()

        try:
            session_id = uuid.UUID(str(payload.get("session_id")))
        except ValueError as exc:
            raise ImportSessionNotFoundError() from exc

        import_session = await self._sessions.get_by_id_for_user(session_id, user.id)
        if import_session is None:
            raise ImportSessionNotFoundError()
        if import_session.status == ImportSessionStatus.CONFIRMED:
            raise ImportSessionAlreadyConfirmedError()
        if import_session.expires_at < datetime.now(UTC):
            raise ImportSessionExpiredError()
        if not import_session.rows:
            raise ImportNoValidRowsError()

        claimed = await self._sessions.mark_confirmed_if_pending(session_id)
        if not claimed:
            raise ImportSessionAlreadyConfirmedError()

        imported_count = 0
        try:
            for row in import_session.rows:
                expense_data = ExpenseCreate(
                    category_id=uuid.UUID(row["category_id"]),
                    description=row["description"],
                    amount=Decimal(row["amount"]),
                    spent_at=datetime.fromisoformat(row["spent_at"]),
                )
                await self._expenses.create_for_user(user, expense_data)
                imported_count += 1
        except AppError as exc:
            await self._session.rollback()
            raise ImportConfirmationFailedError() from exc

        logger.info(
            "import.confirmed",
            user_id=str(user.id),
            session_id=str(session_id),
            imported_count=imported_count,
        )
        return ImportResult(status="completed", imported_count=imported_count, failed_count=0)
