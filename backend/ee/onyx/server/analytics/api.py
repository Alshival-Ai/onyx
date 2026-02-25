import datetime
from collections import defaultdict
from math import ceil
from typing import List
from typing import Literal
from uuid import UUID

from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ee.onyx.db.analytics import fetch_assistant_message_analytics
from ee.onyx.db.analytics import fetch_assistant_unique_users
from ee.onyx.db.analytics import fetch_assistant_unique_users_total
from ee.onyx.db.analytics import fetch_chat_token_series
from ee.onyx.db.analytics import fetch_llm_cost_series_cents
from ee.onyx.db.analytics import fetch_llm_cost_total_cents
from ee.onyx.db.analytics import fetch_onyxbot_analytics
from ee.onyx.db.analytics import fetch_per_user_query_analytics
from ee.onyx.db.analytics import fetch_persona_message_analytics
from ee.onyx.db.analytics import fetch_persona_unique_users
from ee.onyx.db.analytics import fetch_query_analytics
from ee.onyx.db.analytics import fetch_top_user_usage
from ee.onyx.db.analytics import fetch_top_user_usage_series
from ee.onyx.db.analytics import fetch_usage_summary
from ee.onyx.db.analytics import fetch_user_last_login_map
from ee.onyx.db.analytics import user_can_view_assistant_stats
from onyx.auth.users import current_admin_user
from onyx.auth.users import current_user
from onyx.configs.constants import PUBLIC_API_TAGS
from onyx.db.engine.sql_engine import get_session
from onyx.db.models import User
from shared_configs.configs import ANALYTICS_ESTIMATED_CHAT_COST_USD_PER_1K_TOKENS

router = APIRouter(prefix="/analytics", tags=PUBLIC_API_TAGS)


_DEFAULT_LOOKBACK_DAYS = 30


class QueryAnalyticsResponse(BaseModel):
    total_queries: int
    total_likes: int
    total_dislikes: int
    date: datetime.date


@router.get("/admin/query")
def get_query_analytics(
    start: datetime.datetime | None = None,
    end: datetime.datetime | None = None,
    _: User = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> list[QueryAnalyticsResponse]:
    daily_query_usage_info = fetch_query_analytics(
        start=start
        or (
            datetime.datetime.utcnow() - datetime.timedelta(days=_DEFAULT_LOOKBACK_DAYS)
        ),  # default is 30d lookback
        end=end or datetime.datetime.utcnow(),
        db_session=db_session,
    )
    return [
        QueryAnalyticsResponse(
            total_queries=total_queries,
            total_likes=total_likes,
            total_dislikes=total_dislikes,
            date=date,
        )
        for total_queries, total_likes, total_dislikes, date in daily_query_usage_info
    ]


class UserAnalyticsResponse(BaseModel):
    total_active_users: int
    date: datetime.date


@router.get("/admin/user")
def get_user_analytics(
    start: datetime.datetime | None = None,
    end: datetime.datetime | None = None,
    _: User = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> list[UserAnalyticsResponse]:
    daily_query_usage_info_per_user = fetch_per_user_query_analytics(
        start=start
        or (
            datetime.datetime.utcnow() - datetime.timedelta(days=_DEFAULT_LOOKBACK_DAYS)
        ),  # default is 30d lookback
        end=end or datetime.datetime.utcnow(),
        db_session=db_session,
    )

    user_analytics: dict[datetime.date, int] = defaultdict(int)
    for __, ___, ____, date, _____ in daily_query_usage_info_per_user:
        user_analytics[date] += 1
    return [
        UserAnalyticsResponse(
            total_active_users=cnt,
            date=date,
        )
        for date, cnt in user_analytics.items()
    ]


class OnyxbotAnalyticsResponse(BaseModel):
    total_queries: int
    auto_resolved: int
    date: datetime.date


@router.get("/admin/onyxbot")
def get_onyxbot_analytics(
    start: datetime.datetime | None = None,
    end: datetime.datetime | None = None,
    _: User = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> list[OnyxbotAnalyticsResponse]:
    daily_onyxbot_info = fetch_onyxbot_analytics(
        start=start
        or (
            datetime.datetime.utcnow() - datetime.timedelta(days=_DEFAULT_LOOKBACK_DAYS)
        ),  # default is 30d lookback
        end=end or datetime.datetime.utcnow(),
        db_session=db_session,
    )

    resolution_results = [
        OnyxbotAnalyticsResponse(
            total_queries=total_queries,
            # If it hits negatives, something has gone wrong...
            auto_resolved=max(0, total_queries - total_negatives),
            date=date,
        )
        for total_queries, total_negatives, date in daily_onyxbot_info
    ]

    return resolution_results


class PersonaMessageAnalyticsResponse(BaseModel):
    total_messages: int
    date: datetime.date
    persona_id: int


@router.get("/admin/persona/messages")
def get_persona_messages(
    persona_id: int,
    start: datetime.datetime | None = None,
    end: datetime.datetime | None = None,
    _: User = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> list[PersonaMessageAnalyticsResponse]:
    """Fetch daily message counts for a single persona within the given time range."""
    start = start or (
        datetime.datetime.utcnow() - datetime.timedelta(days=_DEFAULT_LOOKBACK_DAYS)
    )
    end = end or datetime.datetime.utcnow()

    persona_message_counts = []
    for count, date in fetch_persona_message_analytics(
        db_session=db_session,
        persona_id=persona_id,
        start=start,
        end=end,
    ):
        persona_message_counts.append(
            PersonaMessageAnalyticsResponse(
                total_messages=count,
                date=date,
                persona_id=persona_id,
            )
        )

    return persona_message_counts


class PersonaUniqueUsersResponse(BaseModel):
    unique_users: int
    date: datetime.date
    persona_id: int


@router.get("/admin/persona/unique-users")
def get_persona_unique_users(
    persona_id: int,
    start: datetime.datetime,
    end: datetime.datetime,
    _: User = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> list[PersonaUniqueUsersResponse]:
    """Get unique users per day for a single persona."""
    unique_user_counts = []
    daily_counts = fetch_persona_unique_users(
        db_session=db_session,
        persona_id=persona_id,
        start=start,
        end=end,
    )
    for count, date in daily_counts:
        unique_user_counts.append(
            PersonaUniqueUsersResponse(
                unique_users=count,
                date=date,
                persona_id=persona_id,
            )
        )
    return unique_user_counts


class AssistantDailyUsageResponse(BaseModel):
    date: datetime.date
    total_messages: int
    total_unique_users: int


class AssistantStatsResponse(BaseModel):
    daily_stats: List[AssistantDailyUsageResponse]
    total_messages: int
    total_unique_users: int


@router.get("/assistant/{assistant_id}/stats")
def get_assistant_stats(
    assistant_id: int,
    start: datetime.datetime | None = None,
    end: datetime.datetime | None = None,
    user: User = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> AssistantStatsResponse:
    """
    Returns daily message and unique user counts for a user's assistant,
    along with the overall total messages and total distinct users.
    """
    start = start or (
        datetime.datetime.utcnow() - datetime.timedelta(days=_DEFAULT_LOOKBACK_DAYS)
    )
    end = end or datetime.datetime.utcnow()

    if not user_can_view_assistant_stats(db_session, user, assistant_id):
        raise HTTPException(
            status_code=403, detail="Not allowed to access this assistant's stats."
        )

    # Pull daily usage from the DB calls
    messages_data = fetch_assistant_message_analytics(
        db_session, assistant_id, start, end
    )
    unique_users_data = fetch_assistant_unique_users(
        db_session, assistant_id, start, end
    )

    # Map each day => (messages, unique_users).
    daily_messages_map = {date: count for count, date in messages_data}
    daily_unique_users_map = {date: count for count, date in unique_users_data}
    all_dates = set(daily_messages_map.keys()) | set(daily_unique_users_map.keys())

    # Merge both sets of metrics by date
    daily_results: list[AssistantDailyUsageResponse] = []
    for date in sorted(all_dates):
        daily_results.append(
            AssistantDailyUsageResponse(
                date=date,
                total_messages=daily_messages_map.get(date, 0),
                total_unique_users=daily_unique_users_map.get(date, 0),
            )
        )

    # Now pull a single total distinct user count across the entire time range
    total_msgs = sum(d.total_messages for d in daily_results)
    total_users = fetch_assistant_unique_users_total(
        db_session, assistant_id, start, end
    )

    return AssistantStatsResponse(
        daily_stats=daily_results,
        total_messages=total_msgs,
        total_unique_users=total_users,
    )


class CostSeriesPoint(BaseModel):
    period_start: datetime.date
    llm_cost_usd: float
    estimated_byok_cost_usd: float


class DashboardTopUser(BaseModel):
    user_id: str
    user_email: str
    message_count: int
    token_count: int
    last_login: datetime.datetime | None
    average_messages_per_week: float
    average_messages_per_month: float


class DashboardUserUsagePoint(BaseModel):
    period_start: datetime.date
    user_id: str
    user_email: str
    message_count: int


class AdminDashboardResponse(BaseModel):
    total_messages: int
    total_unique_users: int
    total_likes: int
    total_dislikes: int
    total_llm_cost_usd: float
    total_estimated_byok_cost_usd: float
    cost_series: list[CostSeriesPoint]
    top_users: list[DashboardTopUser]
    top_user_usage_series: list[DashboardUserUsagePoint]
    selected_interval: Literal["week", "month"]
    cost_note: str
    byok_estimation_note: str


@router.get("/admin/dashboard")
def get_admin_dashboard(
    start: datetime.datetime | None = None,
    end: datetime.datetime | None = None,
    interval: Literal["week", "month"] = "week",
    top_n: int = 10,
    _: User = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> AdminDashboardResponse:
    start = start or (
        datetime.datetime.utcnow() - datetime.timedelta(days=_DEFAULT_LOOKBACK_DAYS)
    )
    end = end or datetime.datetime.utcnow()

    total_messages, total_unique_users, total_likes, total_dislikes = (
        fetch_usage_summary(start=start, end=end, db_session=db_session)
    )

    llm_cost_total_cents = fetch_llm_cost_total_cents(
        start=start, end=end, db_session=db_session
    )
    llm_cost_series_cents = fetch_llm_cost_series_cents(
        start=start, end=end, db_session=db_session
    )
    chat_token_series = fetch_chat_token_series(
        start=start, end=end, db_session=db_session
    )

    llm_cost_usd_by_period: dict[datetime.date, float] = {
        period_start: (cost_cents / 100.0)
        for period_start, cost_cents in llm_cost_series_cents
    }
    estimated_chat_cost_usd_by_period: dict[datetime.date, float] = {
        period_start: (
            token_count / 1000.0 * ANALYTICS_ESTIMATED_CHAT_COST_USD_PER_1K_TOKENS
        )
        for period_start, token_count in chat_token_series
    }
    estimated_byok_cost_usd_by_period: dict[datetime.date, float] = {
        period_start: max(
            estimated_chat_cost_usd_by_period.get(period_start, 0.0)
            - llm_cost_usd_by_period.get(period_start, 0.0),
            0.0,
        )
        for period_start in set(llm_cost_usd_by_period).union(
            estimated_chat_cost_usd_by_period
        )
    }
    estimated_byok_total_usd = sum(estimated_byok_cost_usd_by_period.values())

    top_users_raw = fetch_top_user_usage(
        start=start,
        end=end,
        db_session=db_session,
        limit=max(1, min(top_n, 50)),
    )
    top_user_ids: list[UUID] = [user_id for user_id, _, _, _ in top_users_raw]
    user_last_login_map = fetch_user_last_login_map(top_user_ids, db_session)

    range_days = max(1, (end.date() - start.date()).days + 1)
    weeks_in_range = max(1, ceil(range_days / 7))
    months_in_range = max(1, ceil(range_days / 30))

    top_users = [
        DashboardTopUser(
            user_id=str(user_id),
            user_email=user_email,
            message_count=message_count,
            token_count=token_count,
            last_login=user_last_login_map.get(user_id),
            average_messages_per_week=round(message_count / weeks_in_range, 2),
            average_messages_per_month=round(message_count / months_in_range, 2),
        )
        for user_id, user_email, message_count, token_count in top_users_raw
    ]

    top_user_usage_series_raw = fetch_top_user_usage_series(
        start=start,
        end=end,
        db_session=db_session,
        user_ids=top_user_ids,
        interval=interval,
    )

    return AdminDashboardResponse(
        total_messages=total_messages,
        total_unique_users=total_unique_users,
        total_likes=total_likes,
        total_dislikes=total_dislikes,
        total_llm_cost_usd=round(llm_cost_total_cents / 100.0, 2),
        total_estimated_byok_cost_usd=round(estimated_byok_total_usd, 2),
        cost_series=[
            CostSeriesPoint(
                period_start=period_start,
                llm_cost_usd=round(llm_cost_usd_by_period.get(period_start, 0.0), 2),
                estimated_byok_cost_usd=round(
                    estimated_byok_cost_usd_by_period.get(period_start, 0.0), 2
                ),
            )
            for period_start in sorted(
                set(llm_cost_usd_by_period).union(estimated_byok_cost_usd_by_period)
            )
        ],
        top_users=top_users,
        top_user_usage_series=[
            DashboardUserUsagePoint(
                period_start=period_start,
                user_id=str(user_id),
                user_email=user_email,
                message_count=message_count,
            )
            for period_start, user_id, user_email, message_count in top_user_usage_series_raw
        ],
        selected_interval=interval,
        cost_note=(
            "AI cost is based on tracked LLM spend for Onyx-managed provider keys. "
            "Bring-your-own keys are not included in this cost figure."
        ),
        byok_estimation_note=(
            "Estimated BYOK/untracked cost is directional: it uses chat message tokens "
            f"at an assumed ${ANALYTICS_ESTIMATED_CHAT_COST_USD_PER_1K_TOKENS:.4f} "
            "per 1K tokens, minus tracked Onyx-managed cost (floored at $0)."
        ),
    )
