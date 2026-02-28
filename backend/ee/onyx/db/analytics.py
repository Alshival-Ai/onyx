import datetime
from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import and_
from sqlalchemy import case
from sqlalchemy import cast
from sqlalchemy import Date
from sqlalchemy import func
from sqlalchemy import or_
from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.configs.constants import MessageType
from onyx.db.models import AccessToken
from onyx.db.models import ChatMessage
from onyx.db.models import ChatMessageFeedback
from onyx.db.models import ChatSession
from onyx.db.models import Persona
from onyx.db.models import TenantUsage
from onyx.db.models import User
from onyx.db.models import UserRole


def fetch_query_analytics(
    start: datetime.datetime,
    end: datetime.datetime,
    db_session: Session,
) -> Sequence[tuple[int, int, int, datetime.date]]:
    stmt = (
        select(
            func.count(ChatMessage.id),
            func.sum(case((ChatMessageFeedback.is_positive, 1), else_=0)),
            func.sum(
                case(
                    (ChatMessageFeedback.is_positive == False, 1), else_=0  # noqa: E712
                )
            ),
            cast(ChatMessage.time_sent, Date),
        )
        .join(
            ChatMessageFeedback,
            ChatMessageFeedback.chat_message_id == ChatMessage.id,
            isouter=True,
        )
        .where(
            ChatMessage.time_sent >= start,
        )
        .where(
            ChatMessage.time_sent <= end,
        )
        .where(ChatMessage.message_type == MessageType.ASSISTANT)
        .group_by(cast(ChatMessage.time_sent, Date))
        .order_by(cast(ChatMessage.time_sent, Date))
    )

    return db_session.execute(stmt).all()  # type: ignore


def fetch_per_user_query_analytics(
    start: datetime.datetime,
    end: datetime.datetime,
    db_session: Session,
) -> Sequence[tuple[int, int, int, datetime.date, UUID]]:
    stmt = (
        select(
            func.count(ChatMessage.id),
            func.sum(case((ChatMessageFeedback.is_positive, 1), else_=0)),
            func.sum(
                case(
                    (ChatMessageFeedback.is_positive == False, 1), else_=0  # noqa: E712
                )
            ),
            cast(ChatMessage.time_sent, Date),
            ChatSession.user_id,
        )
        .join(ChatSession, ChatSession.id == ChatMessage.chat_session_id)
        # Include chats that have no explicit feedback instead of dropping them
        .join(
            ChatMessageFeedback,
            ChatMessageFeedback.chat_message_id == ChatMessage.id,
            isouter=True,
        )
        .where(
            ChatMessage.time_sent >= start,
        )
        .where(
            ChatMessage.time_sent <= end,
        )
        .where(ChatMessage.message_type == MessageType.ASSISTANT)
        .group_by(cast(ChatMessage.time_sent, Date), ChatSession.user_id)
        .order_by(cast(ChatMessage.time_sent, Date), ChatSession.user_id)
    )

    return db_session.execute(stmt).all()  # type: ignore


def fetch_onyxbot_analytics(
    start: datetime.datetime,
    end: datetime.datetime,
    db_session: Session,
) -> Sequence[tuple[int, int, datetime.date]]:
    """Gets the:
    Date of each set of aggregated statistics
    Number of OnyxBot Queries (Chat Sessions)
    Number of instances of Negative feedback OR Needing additional help
        (only counting the last feedback)
    """
    # Get every chat session in the time range which is a Onyxbot flow
    # along with the first Assistant message which is the response to the user question.
    # Generally there should not be more than one AI message per chat session of this type
    subquery_first_ai_response = (
        db_session.query(
            ChatMessage.chat_session_id.label("chat_session_id"),
            func.min(ChatMessage.id).label("chat_message_id"),
        )
        .join(ChatSession, ChatSession.id == ChatMessage.chat_session_id)
        .where(
            ChatSession.time_created >= start,
            ChatSession.time_created <= end,
            ChatSession.onyxbot_flow.is_(True),
        )
        .where(
            ChatMessage.message_type == MessageType.ASSISTANT,
        )
        .group_by(ChatMessage.chat_session_id)
        .subquery()
    )

    # Get the chat message ids and most recent feedback for each of those chat messages,
    # not including the messages that have no feedback
    subquery_last_feedback = (
        db_session.query(
            ChatMessageFeedback.chat_message_id.label("chat_message_id"),
            func.max(ChatMessageFeedback.id).label("max_feedback_id"),
        )
        .group_by(ChatMessageFeedback.chat_message_id)
        .subquery()
    )

    results = (
        db_session.query(
            func.count(ChatSession.id).label("total_sessions"),
            # Need to explicitly specify this as False to handle the NULL case so the cases without
            # feedback aren't counted against Onyxbot
            func.sum(
                case(
                    (
                        or_(
                            ChatMessageFeedback.is_positive.is_(False),
                            ChatMessageFeedback.required_followup.is_(True),
                        ),
                        1,
                    ),
                    else_=0,
                )
            ).label("negative_answer"),
            cast(ChatSession.time_created, Date).label("session_date"),
        )
        .join(
            subquery_first_ai_response,
            ChatSession.id == subquery_first_ai_response.c.chat_session_id,
        )
        # Combine the chat sessions with latest feedback to get the latest feedback for the first AI
        # message of the chat session where the chat session is Onyxbot type and within the time
        # range specified. Left/outer join used here to ensure that if no feedback, a null is used
        # for the feedback id
        .outerjoin(
            subquery_last_feedback,
            subquery_first_ai_response.c.chat_message_id
            == subquery_last_feedback.c.chat_message_id,
        )
        # Join the actual feedback table to get the feedback info for the sums
        # Outer join because the "last feedback" may be null
        .outerjoin(
            ChatMessageFeedback,
            ChatMessageFeedback.id == subquery_last_feedback.c.max_feedback_id,
        )
        .group_by(cast(ChatSession.time_created, Date))
        .order_by(cast(ChatSession.time_created, Date))
        .all()
    )

    return [tuple(row) for row in results]


def fetch_persona_message_analytics(
    db_session: Session,
    persona_id: int,
    start: datetime.datetime,
    end: datetime.datetime,
) -> list[tuple[int, datetime.date]]:
    """Gets the daily message counts for a specific persona within the given time range."""
    query = (
        select(
            func.count(ChatMessage.id),
            cast(ChatMessage.time_sent, Date),
        )
        .join(
            ChatSession,
            ChatMessage.chat_session_id == ChatSession.id,
        )
        .where(
            ChatSession.persona_id == persona_id,
            ChatMessage.time_sent >= start,
            ChatMessage.time_sent <= end,
            ChatMessage.message_type == MessageType.ASSISTANT,
        )
        .group_by(cast(ChatMessage.time_sent, Date))
        .order_by(cast(ChatMessage.time_sent, Date))
    )

    return [tuple(row) for row in db_session.execute(query).all()]


def fetch_persona_unique_users(
    db_session: Session,
    persona_id: int,
    start: datetime.datetime,
    end: datetime.datetime,
) -> list[tuple[int, datetime.date]]:
    """Gets the daily unique user counts for a specific persona within the given time range."""
    query = (
        select(
            func.count(func.distinct(ChatSession.user_id)),
            cast(ChatMessage.time_sent, Date),
        )
        .join(
            ChatSession,
            ChatMessage.chat_session_id == ChatSession.id,
        )
        .where(
            ChatSession.persona_id == persona_id,
            ChatMessage.time_sent >= start,
            ChatMessage.time_sent <= end,
            ChatMessage.message_type == MessageType.ASSISTANT,
        )
        .group_by(cast(ChatMessage.time_sent, Date))
        .order_by(cast(ChatMessage.time_sent, Date))
    )

    return [tuple(row) for row in db_session.execute(query).all()]


def fetch_assistant_message_analytics(
    db_session: Session,
    assistant_id: int,
    start: datetime.datetime,
    end: datetime.datetime,
) -> list[tuple[int, datetime.date]]:
    """
    Gets the daily message counts for a specific assistant in the given time range.
    """
    query = (
        select(
            func.count(ChatMessage.id),
            cast(ChatMessage.time_sent, Date),
        )
        .join(
            ChatSession,
            ChatMessage.chat_session_id == ChatSession.id,
        )
        .where(
            ChatSession.persona_id == assistant_id,
            ChatMessage.time_sent >= start,
            ChatMessage.time_sent <= end,
            ChatMessage.message_type == MessageType.ASSISTANT,
        )
        .group_by(cast(ChatMessage.time_sent, Date))
        .order_by(cast(ChatMessage.time_sent, Date))
    )

    return [tuple(row) for row in db_session.execute(query).all()]


def fetch_assistant_unique_users(
    db_session: Session,
    assistant_id: int,
    start: datetime.datetime,
    end: datetime.datetime,
) -> list[tuple[int, datetime.date]]:
    """
    Gets the daily unique user counts for a specific assistant in the given time range.
    """
    query = (
        select(
            func.count(func.distinct(ChatSession.user_id)),
            cast(ChatMessage.time_sent, Date),
        )
        .join(
            ChatSession,
            ChatMessage.chat_session_id == ChatSession.id,
        )
        .where(
            ChatSession.persona_id == assistant_id,
            ChatMessage.time_sent >= start,
            ChatMessage.time_sent <= end,
            ChatMessage.message_type == MessageType.ASSISTANT,
        )
        .group_by(cast(ChatMessage.time_sent, Date))
        .order_by(cast(ChatMessage.time_sent, Date))
    )

    return [tuple(row) for row in db_session.execute(query).all()]


def fetch_assistant_unique_users_total(
    db_session: Session,
    assistant_id: int,
    start: datetime.datetime,
    end: datetime.datetime,
) -> int:
    """
    Gets the total number of distinct users who have sent or received messages from
    the specified assistant in the given time range.
    """
    query = (
        select(func.count(func.distinct(ChatSession.user_id)))
        .select_from(ChatMessage)
        .join(
            ChatSession,
            ChatMessage.chat_session_id == ChatSession.id,
        )
        .where(
            ChatSession.persona_id == assistant_id,
            ChatMessage.time_sent >= start,
            ChatMessage.time_sent <= end,
            ChatMessage.message_type == MessageType.ASSISTANT,
        )
    )

    result = db_session.execute(query).scalar()
    return result if result else 0


# Users can view assistant stats if they created the persona,
# or if they are an admin
def user_can_view_assistant_stats(
    db_session: Session, user: User, assistant_id: int
) -> bool:
    if user.role == UserRole.ADMIN:
        return True

    # Check if the user created the persona
    stmt = select(Persona).where(
        and_(Persona.id == assistant_id, Persona.user_id == user.id)
    )

    persona = db_session.execute(stmt).scalar_one_or_none()
    return persona is not None


def fetch_usage_summary(
    start: datetime.datetime,
    end: datetime.datetime,
    db_session: Session,
) -> tuple[int, int, int, int]:
    """Get summary usage metrics for the selected time range."""
    stmt = (
        select(
            func.count(ChatMessage.id),
            func.count(func.distinct(ChatSession.user_id)),
            func.coalesce(
                func.sum(case((ChatMessageFeedback.is_positive.is_(True), 1), else_=0)),
                0,
            ),
            func.coalesce(
                func.sum(case((ChatMessageFeedback.is_positive.is_(False), 1), else_=0)),
                0,
            ),
        )
        .join(ChatSession, ChatSession.id == ChatMessage.chat_session_id)
        .join(
            ChatMessageFeedback,
            ChatMessageFeedback.chat_message_id == ChatMessage.id,
            isouter=True,
        )
        .where(
            ChatMessage.time_sent >= start,
            ChatMessage.time_sent <= end,
            ChatMessage.message_type == MessageType.ASSISTANT,
            ChatSession.user_id.is_not(None),
        )
    )

    total_messages, total_unique_users, total_likes, total_dislikes = (
        db_session.execute(stmt).one()
    )
    return (
        int(total_messages or 0),
        int(total_unique_users or 0),
        int(total_likes or 0),
        int(total_dislikes or 0),
    )


def fetch_llm_cost_total_cents(
    start: datetime.datetime,
    end: datetime.datetime,
    db_session: Session,
) -> float:
    """
    Fetch tracked LLM cost (cents) from tenant_usage windows.

    Note: this is based on tracked Onyx-managed provider spend and is window-based.
    """
    stmt = select(func.coalesce(func.sum(TenantUsage.llm_cost_cents), 0.0)).where(
        TenantUsage.window_start >= start,
        TenantUsage.window_start <= end,
    )
    result = db_session.execute(stmt).scalar_one()
    return float(result or 0.0)


def fetch_llm_cost_series_cents(
    start: datetime.datetime,
    end: datetime.datetime,
    db_session: Session,
) -> list[tuple[datetime.date, float]]:
    stmt = (
        select(
            cast(TenantUsage.window_start, Date),
            func.coalesce(func.sum(TenantUsage.llm_cost_cents), 0.0),
        )
        .where(
            TenantUsage.window_start >= start,
            TenantUsage.window_start <= end,
        )
        .group_by(cast(TenantUsage.window_start, Date))
        .order_by(cast(TenantUsage.window_start, Date))
    )
    return [(date, float(cost_cents)) for date, cost_cents in db_session.execute(stmt)]


def fetch_chat_token_series(
    start: datetime.datetime,
    end: datetime.datetime,
    db_session: Session,
) -> list[tuple[datetime.date, int]]:
    """Fetch chat message token totals per day (user + assistant)."""
    stmt = (
        select(
            cast(ChatMessage.time_sent, Date),
            func.coalesce(func.sum(ChatMessage.token_count), 0),
        )
        .join(ChatSession, ChatSession.id == ChatMessage.chat_session_id)
        .where(
            ChatMessage.time_sent >= start,
            ChatMessage.time_sent <= end,
            ChatMessage.message_type.in_([MessageType.USER, MessageType.ASSISTANT]),
            ChatSession.user_id.is_not(None),
        )
        .group_by(cast(ChatMessage.time_sent, Date))
        .order_by(cast(ChatMessage.time_sent, Date))
    )
    return [
        (period_start, int(token_count or 0))
        for period_start, token_count in db_session.execute(stmt)
        if period_start is not None
    ]


def fetch_user_last_login_map(
    user_ids: list[UUID],
    db_session: Session,
) -> dict[UUID, datetime.datetime]:
    """Fetch a best-effort per-user last login timestamp.

    Primary source is auth access token creation time. In deployments that use
    Redis/JWT auth backends, access tokens may not exist in Postgres, so we
    fall back to the latest chat session creation time to avoid empty values.
    """
    if not user_ids:
        return {}

    access_token_stmt = (
        select(
            AccessToken.user_id,
            func.max(AccessToken.created_at),
        )
        .where(AccessToken.user_id.in_(user_ids))
        .group_by(AccessToken.user_id)
    )

    chat_session_stmt = (
        select(
            ChatSession.user_id,
            func.max(ChatSession.time_created),
        )
        .where(ChatSession.user_id.in_(user_ids))
        .group_by(ChatSession.user_id)
    )

    last_login_map: dict[UUID, datetime.datetime] = {
        user_id: last_login
        for user_id, last_login in db_session.execute(access_token_stmt)
        if user_id is not None and last_login is not None
    }

    for user_id, last_activity in db_session.execute(chat_session_stmt):
        if user_id is None or last_activity is None:
            continue

        existing_login = last_login_map.get(user_id)
        if existing_login is None or last_activity > existing_login:
            last_login_map[user_id] = last_activity

    return last_login_map


def fetch_top_user_usage(
    start: datetime.datetime,
    end: datetime.datetime,
    db_session: Session,
    limit: int = 10,
) -> list[tuple[UUID, str, int, int]]:
    """Fetch top users ranked by number of messages sent in the selected range."""
    message_count = func.count(ChatMessage.id).label("message_count")
    token_count = func.coalesce(func.sum(ChatMessage.token_count), 0).label("token_count")

    stmt = (
        select(
            ChatSession.user_id,
            User.email,
            message_count,
            token_count,
        )
        .join(ChatSession, ChatSession.id == ChatMessage.chat_session_id)
        .join(User, User.id == ChatSession.user_id)
        .where(
            ChatMessage.time_sent >= start,
            ChatMessage.time_sent <= end,
            ChatMessage.message_type == MessageType.USER,
            ChatSession.user_id.is_not(None),
        )
        .group_by(ChatSession.user_id, User.email)
        .order_by(message_count.desc())
        .limit(limit)
    )

    return [
        (
            user_id,
            user_email,
            int(messages or 0),
            int(tokens or 0),
        )
        for user_id, user_email, messages, tokens in db_session.execute(stmt)
        if user_id is not None and user_email is not None
    ]


def fetch_top_user_token_drivers(
    start: datetime.datetime,
    end: datetime.datetime,
    db_session: Session,
    limit: int = 10,
) -> list[tuple[UUID, str, int, int]]:
    """Fetch top users ranked by user-message token usage in the selected range."""
    message_count = func.count(ChatMessage.id).label("message_count")
    token_count = func.coalesce(func.sum(ChatMessage.token_count), 0).label("token_count")

    stmt = (
        select(
            ChatSession.user_id,
            User.email,
            message_count,
            token_count,
        )
        .join(ChatSession, ChatSession.id == ChatMessage.chat_session_id)
        .join(User, User.id == ChatSession.user_id)
        .where(
            ChatMessage.time_sent >= start,
            ChatMessage.time_sent <= end,
            ChatMessage.message_type == MessageType.USER,
            ChatSession.user_id.is_not(None),
        )
        .group_by(ChatSession.user_id, User.email)
        .order_by(token_count.desc(), message_count.desc())
        .limit(limit)
    )

    return [
        (
            user_id,
            user_email,
            int(messages or 0),
            int(tokens or 0),
        )
        for user_id, user_email, messages, tokens in db_session.execute(stmt)
        if user_id is not None and user_email is not None
    ]


def fetch_top_assistant_token_drivers(
    start: datetime.datetime,
    end: datetime.datetime,
    db_session: Session,
    limit: int = 10,
) -> list[tuple[int | None, str, int, int]]:
    """Fetch top assistants ranked by assistant-message token usage."""
    response_count = func.count(ChatMessage.id).label("response_count")
    token_count = func.coalesce(func.sum(ChatMessage.token_count), 0).label("token_count")
    assistant_name = func.coalesce(Persona.name, "Default Assistant").label(
        "assistant_name"
    )

    stmt = (
        select(
            ChatSession.persona_id,
            assistant_name,
            response_count,
            token_count,
        )
        .join(ChatSession, ChatSession.id == ChatMessage.chat_session_id)
        .join(Persona, Persona.id == ChatSession.persona_id, isouter=True)
        .where(
            ChatMessage.time_sent >= start,
            ChatMessage.time_sent <= end,
            ChatMessage.message_type == MessageType.ASSISTANT,
            ChatSession.user_id.is_not(None),
        )
        .group_by(ChatSession.persona_id, Persona.name)
        .order_by(token_count.desc(), response_count.desc())
        .limit(limit)
    )

    return [
        (
            assistant_id,
            str(name),
            int(responses or 0),
            int(tokens or 0),
        )
        for assistant_id, name, responses, tokens in db_session.execute(stmt)
        if name is not None
    ]


def fetch_top_user_usage_series(
    start: datetime.datetime,
    end: datetime.datetime,
    db_session: Session,
    user_ids: list[UUID],
    interval: str,
) -> list[tuple[datetime.date, UUID, str, int]]:
    if not user_ids:
        return []

    if interval == "month":
        period_expr = cast(func.date_trunc("month", ChatMessage.time_sent), Date)
    elif interval == "week":
        period_expr = cast(func.date_trunc("week", ChatMessage.time_sent), Date)
    else:
        period_expr = cast(ChatMessage.time_sent, Date)

    stmt = (
        select(
            period_expr,
            ChatSession.user_id,
            User.email,
            func.count(ChatMessage.id),
        )
        .join(ChatSession, ChatSession.id == ChatMessage.chat_session_id)
        .join(User, User.id == ChatSession.user_id)
        .where(
            ChatMessage.time_sent >= start,
            ChatMessage.time_sent <= end,
            ChatMessage.message_type == MessageType.USER,
            ChatSession.user_id.in_(user_ids),
        )
        .group_by(period_expr, ChatSession.user_id, User.email)
        .order_by(period_expr, func.count(ChatMessage.id).desc())
    )

    return [
        (period_start, user_id, user_email, int(message_count or 0))
        for period_start, user_id, user_email, message_count in db_session.execute(stmt)
        if period_start is not None and user_id is not None and user_email is not None
    ]
