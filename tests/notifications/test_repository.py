"""Unit tests for `NotificationRepository` — filtering, sort, pagination,
unread counting, and the bulk mark-all-read update.
"""

import uuid

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.modules.notifications.enums import (
    NotificationPriority,
    NotificationSortField,
    NotificationType,
    SortOrder,
)
from src.modules.notifications.repository import NotificationRepository
from src.modules.users.repository import UserRepository
from tests.conftest import RecordingEmailBackend
from tests.import_export.helpers import USER_A, login_user_a


async def _make_repo_and_user(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> tuple[AsyncSession, NotificationRepository, uuid.UUID]:
    session = db_session_factory()
    users = UserRepository(session)
    user = await users.get_by_email(USER_A["email"])
    assert user is not None
    return session, NotificationRepository(session), user.id


async def test_create_and_get_by_id_for_user(
    client: AsyncClient,
    email_backend: RecordingEmailBackend,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await login_user_a(client, email_backend)
    session, repo, user_id = await _make_repo_and_user(db_session_factory)
    async with session:
        notification = repo.create(
            user_id=user_id,
            notification_type=NotificationType.WELCOME,
            title="Welcome!",
            message="Thanks for signing up.",
            payload={"foo": "bar"},
            priority=NotificationPriority.NORMAL,
        )
        await repo.flush()
        await session.commit()
        notification_id = notification.id

    session, repo, _ = await _make_repo_and_user(db_session_factory)
    async with session:
        fetched = await repo.get_by_id_for_user(notification_id, user_id)
        assert fetched is not None
        assert fetched.title == "Welcome!"
        assert fetched.payload == {"foo": "bar"}
        assert fetched.is_read is False


async def test_get_by_id_for_user_is_none_for_another_owner(
    client: AsyncClient,
    email_backend: RecordingEmailBackend,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await login_user_a(client, email_backend)
    session, repo, user_id = await _make_repo_and_user(db_session_factory)
    async with session:
        notification = repo.create(
            user_id=user_id,
            notification_type=NotificationType.WELCOME,
            title="Welcome!",
            message="Thanks for signing up.",
            payload={},
            priority=NotificationPriority.NORMAL,
        )
        await repo.flush()
        await session.commit()
        notification_id = notification.id

    session, repo, _ = await _make_repo_and_user(db_session_factory)
    async with session:
        fetched = await repo.get_by_id_for_user(notification_id, uuid.uuid4())
        assert fetched is None


async def test_list_for_user_filters_by_is_read_type_and_priority(
    client: AsyncClient,
    email_backend: RecordingEmailBackend,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await login_user_a(client, email_backend)
    session, repo, user_id = await _make_repo_and_user(db_session_factory)
    async with session:
        unread = repo.create(
            user_id=user_id,
            notification_type=NotificationType.WELCOME,
            title="Welcome",
            message="Hi",
            payload={},
            priority=NotificationPriority.NORMAL,
        )
        read = repo.create(
            user_id=user_id,
            notification_type=NotificationType.REPORT_READY,
            title="Report ready",
            message="Your report is ready",
            payload={},
            priority=NotificationPriority.HIGH,
        )
        await repo.flush()
        read.is_read = True
        await repo.flush()
        await session.commit()
        unread_id = unread.id
        read_id = read.id

    session, repo, uid = await _make_repo_and_user(db_session_factory)
    async with session:
        items, total = await repo.list_for_user(uid, is_read=False)
        assert total == 1
        assert items[0].id == unread_id

        items, total = await repo.list_for_user(uid, is_read=True)
        assert total == 1
        assert items[0].id == read_id

        items, total = await repo.list_for_user(uid, notification_type=NotificationType.WELCOME)
        assert total == 1
        assert items[0].id == unread_id

        items, total = await repo.list_for_user(uid, priority=NotificationPriority.HIGH)
        assert total == 1
        assert items[0].id == read_id

        items, total = await repo.list_for_user(uid)
        assert total == 2


async def test_list_for_user_sorts_by_priority(
    client: AsyncClient,
    email_backend: RecordingEmailBackend,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await login_user_a(client, email_backend)
    session, repo, user_id = await _make_repo_and_user(db_session_factory)
    async with session:
        priorities = (
            NotificationPriority.LOW,
            NotificationPriority.CRITICAL,
            NotificationPriority.NORMAL,
        )
        for priority in priorities:
            repo.create(
                user_id=user_id,
                notification_type=NotificationType.SYSTEM,
                title=f"Priority {priority}",
                message="msg",
                payload={},
                priority=priority,
            )
        await repo.flush()
        await session.commit()

    session, repo, uid = await _make_repo_and_user(db_session_factory)
    async with session:
        items, _ = await repo.list_for_user(
            uid, sort_by=NotificationSortField.PRIORITY, sort_order=SortOrder.ASC
        )
        assert [i.priority for i in items] == [
            NotificationPriority.CRITICAL,
            NotificationPriority.LOW,
            NotificationPriority.NORMAL,
        ]


async def test_list_for_user_paginates(
    client: AsyncClient,
    email_backend: RecordingEmailBackend,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await login_user_a(client, email_backend)
    session, repo, user_id = await _make_repo_and_user(db_session_factory)
    async with session:
        for i in range(5):
            repo.create(
                user_id=user_id,
                notification_type=NotificationType.SYSTEM,
                title=f"Item {i}",
                message="msg",
                payload={},
                priority=NotificationPriority.NORMAL,
            )
        await repo.flush()
        await session.commit()

    session, repo, uid = await _make_repo_and_user(db_session_factory)
    async with session:
        items, total = await repo.list_for_user(uid, offset=0, limit=2)
        assert total == 5
        assert len(items) == 2

        items, total = await repo.list_for_user(uid, offset=4, limit=2)
        assert total == 5
        assert len(items) == 1


async def test_unread_count_for_user(
    client: AsyncClient,
    email_backend: RecordingEmailBackend,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await login_user_a(client, email_backend)
    session, repo, user_id = await _make_repo_and_user(db_session_factory)
    async with session:
        read = repo.create(
            user_id=user_id,
            notification_type=NotificationType.SYSTEM,
            title="Read",
            message="msg",
            payload={},
            priority=NotificationPriority.NORMAL,
        )
        repo.create(
            user_id=user_id,
            notification_type=NotificationType.SYSTEM,
            title="Unread",
            message="msg",
            payload={},
            priority=NotificationPriority.NORMAL,
        )
        await repo.flush()
        read.is_read = True
        await repo.flush()
        await session.commit()

    session, repo, uid = await _make_repo_and_user(db_session_factory)
    async with session:
        assert await repo.unread_count_for_user(uid) == 1


async def test_mark_all_read_for_user_bulk_updates_only_unread_rows(
    client: AsyncClient,
    email_backend: RecordingEmailBackend,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await login_user_a(client, email_backend)
    session, repo, user_id = await _make_repo_and_user(db_session_factory)
    async with session:
        already_read = repo.create(
            user_id=user_id,
            notification_type=NotificationType.SYSTEM,
            title="Already read",
            message="msg",
            payload={},
            priority=NotificationPriority.NORMAL,
        )
        repo.create(
            user_id=user_id,
            notification_type=NotificationType.SYSTEM,
            title="Unread 1",
            message="msg",
            payload={},
            priority=NotificationPriority.NORMAL,
        )
        repo.create(
            user_id=user_id,
            notification_type=NotificationType.SYSTEM,
            title="Unread 2",
            message="msg",
            payload={},
            priority=NotificationPriority.NORMAL,
        )
        await repo.flush()
        already_read.is_read = True
        await repo.flush()
        await session.commit()

    session, repo, uid = await _make_repo_and_user(db_session_factory)
    async with session:
        updated = await repo.mark_all_read_for_user(uid)
        assert updated == 2
        await session.commit()

    session, repo, uid = await _make_repo_and_user(db_session_factory)
    async with session:
        assert await repo.unread_count_for_user(uid) == 0


async def test_delete_removes_the_row(
    client: AsyncClient,
    email_backend: RecordingEmailBackend,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await login_user_a(client, email_backend)
    session, repo, user_id = await _make_repo_and_user(db_session_factory)
    async with session:
        notification = repo.create(
            user_id=user_id,
            notification_type=NotificationType.SYSTEM,
            title="Delete me",
            message="msg",
            payload={},
            priority=NotificationPriority.NORMAL,
        )
        await repo.flush()
        await session.commit()
        notification_id = notification.id

    session, repo, uid = await _make_repo_and_user(db_session_factory)
    async with session:
        fetched = await repo.get_by_id_for_user(notification_id, uid)
        assert fetched is not None
        await repo.delete(fetched)
        await repo.flush()
        await session.commit()

    session, repo, uid = await _make_repo_and_user(db_session_factory)
    async with session:
        assert await repo.get_by_id_for_user(notification_id, uid) is None
