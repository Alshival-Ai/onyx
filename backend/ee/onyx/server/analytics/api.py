import datetime
from collections import defaultdict
from math import ceil
from typing import List
from typing import Literal
from uuid import UUID

import requests
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
from ee.onyx.db.analytics import fetch_top_user_token_drivers
from ee.onyx.db.analytics import fetch_top_user_usage_series
from ee.onyx.db.analytics import fetch_top_assistant_token_drivers
from ee.onyx.db.analytics import fetch_usage_summary
from ee.onyx.db.analytics import fetch_user_last_login_map
from ee.onyx.db.analytics import user_can_view_assistant_stats
from ee.onyx.server.analytics.openai_org_analytics import fetch_openai_cost_series_usd
from ee.onyx.server.analytics.openai_org_analytics import fetch_openai_usage_capabilities
from ee.onyx.server.analytics.openai_org_analytics import (
    OpenAIUsageCapabilityAggregate,
)
from onyx.auth.users import current_admin_user
from onyx.auth.users import current_user
from onyx.configs.app_configs import OPENAI_ORG_ADMIN_KEY
from onyx.configs.app_configs import OPENAI_ORG_PROJECT_IDS
from onyx.configs.constants import PUBLIC_API_TAGS
from onyx.db.engine.sql_engine import get_session
from onyx.db.models import User
from onyx.utils.logger import setup_logger
from shared_configs.configs import ANALYTICS_ESTIMATED_CHAT_COST_USD_PER_1K_TOKENS

router = APIRouter(prefix="/analytics", tags=PUBLIC_API_TAGS)
logger = setup_logger()


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


class DashboardUserCostDriver(BaseModel):
    user_id: str
    user_email: str
    message_count: int
    token_count: int
    token_share_percent: float
    estimated_cost_usd: float


class DashboardAssistantCostDriver(BaseModel):
    assistant_id: int | None
    assistant_name: str
    response_count: int
    token_count: int
    token_share_percent: float
    estimated_cost_usd: float


class DashboardCostDriverBreakdown(BaseModel):
    total_chat_tokens: int
    estimated_chat_cost_basis_usd: float
    user_drivers: list[DashboardUserCostDriver]
    assistant_drivers: list[DashboardAssistantCostDriver]
    note: str


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
    cost_driver_breakdown: DashboardCostDriverBreakdown
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
    llm_cost_note = (
        "AI cost is based on tracked LLM spend for Onyx-managed provider keys. "
        "Bring-your-own keys are not included in this cost figure."
    )
    byok_estimation_note = (
        "Estimated BYOK/untracked cost is directional: it uses chat message tokens "
        f"at an assumed ${ANALYTICS_ESTIMATED_CHAT_COST_USD_PER_1K_TOKENS:.4f} "
        "per 1K tokens, minus tracked Onyx-managed cost (floored at $0)."
    )
    using_openai_org_costs = False

    if OPENAI_ORG_ADMIN_KEY:
        try:
            llm_cost_usd_by_period = fetch_openai_cost_series_usd(
                start=start,
                end=end,
                admin_api_key=OPENAI_ORG_ADMIN_KEY,
                project_ids=OPENAI_ORG_PROJECT_IDS,
            )
            using_openai_org_costs = True

            llm_cost_note = (
                "AI cost is sourced from OpenAI Organization Costs API via "
                "OPENAI_ORG_ADMIN_KEY."
            )
            if OPENAI_ORG_PROJECT_IDS:
                llm_cost_note += " Results are filtered to configured OpenAI project IDs."
            else:
                llm_cost_note += (
                    " No OpenAI project filter is configured; results may include all "
                    "projects in the OpenAI organization."
                )

            byok_estimation_note = (
                "Estimated untracked cost is directional: it uses chat message tokens "
                f"at an assumed ${ANALYTICS_ESTIMATED_CHAT_COST_USD_PER_1K_TOKENS:.4f} "
                "per 1K tokens, minus OpenAI organization-tracked cost (floored at $0)."
            )
        except Exception as e:
            logger.warning(
                "Failed to fetch OpenAI org costs, falling back to local tracked costs: %s",
                e,
            )

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
    total_chat_tokens = sum(token_count for _, token_count in chat_token_series)
    estimated_chat_cost_basis_usd = round(
        sum(estimated_chat_cost_usd_by_period.values()),
        2,
    )

    def _token_share_percent(token_count: int) -> float:
        if total_chat_tokens <= 0:
            return 0.0
        return round((token_count / total_chat_tokens) * 100.0, 2)

    def _estimated_token_cost_usd(token_count: int) -> float:
        return round(
            token_count / 1000.0 * ANALYTICS_ESTIMATED_CHAT_COST_USD_PER_1K_TOKENS,
            2,
        )

    cost_driver_limit = max(1, min(top_n, 50))
    top_user_cost_drivers_raw = fetch_top_user_token_drivers(
        start=start,
        end=end,
        db_session=db_session,
        limit=cost_driver_limit,
    )
    top_assistant_cost_drivers_raw = fetch_top_assistant_token_drivers(
        start=start,
        end=end,
        db_session=db_session,
        limit=cost_driver_limit,
    )

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

    total_llm_cost_usd = (
        round(sum(llm_cost_usd_by_period.values()), 2)
        if using_openai_org_costs
        else round(llm_cost_total_cents / 100.0, 2)
    )
    cost_driver_note = (
        "Cost driver allocation is directional: it estimates chat cost using message "
        "token share (user + assistant tokens) at "
        f"${ANALYTICS_ESTIMATED_CHAT_COST_USD_PER_1K_TOKENS:.4f} per 1K tokens."
    )

    return AdminDashboardResponse(
        total_messages=total_messages,
        total_unique_users=total_unique_users,
        total_likes=total_likes,
        total_dislikes=total_dislikes,
        total_llm_cost_usd=total_llm_cost_usd,
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
        cost_driver_breakdown=DashboardCostDriverBreakdown(
            total_chat_tokens=total_chat_tokens,
            estimated_chat_cost_basis_usd=estimated_chat_cost_basis_usd,
            user_drivers=[
                DashboardUserCostDriver(
                    user_id=str(user_id),
                    user_email=user_email,
                    message_count=message_count,
                    token_count=token_count,
                    token_share_percent=_token_share_percent(token_count),
                    estimated_cost_usd=_estimated_token_cost_usd(token_count),
                )
                for user_id, user_email, message_count, token_count in top_user_cost_drivers_raw
            ],
            assistant_drivers=[
                DashboardAssistantCostDriver(
                    assistant_id=assistant_id,
                    assistant_name=assistant_name,
                    response_count=response_count,
                    token_count=token_count,
                    token_share_percent=_token_share_percent(token_count),
                    estimated_cost_usd=_estimated_token_cost_usd(token_count),
                )
                for assistant_id, assistant_name, response_count, token_count in top_assistant_cost_drivers_raw
            ],
            note=cost_driver_note,
        ),
        selected_interval=interval,
        cost_note=llm_cost_note,
        byok_estimation_note=byok_estimation_note,
    )


class OpenAIOrgSpendPoint(BaseModel):
    period_start: datetime.date
    cost_usd: float


class OpenAIOrgCapabilitySeriesPoint(BaseModel):
    period_start: datetime.date
    request_count: int
    metric_value: float


class OpenAIOrgCapabilityResponse(BaseModel):
    key: str
    label: str
    endpoint: str
    metric_key: str
    metric_label: str
    total_requests: int
    total_metric_value: float
    series: list[OpenAIOrgCapabilitySeriesPoint]


class OpenAIOrgAnalyticsResponse(BaseModel):
    enabled: bool
    period_start: datetime.date
    period_end: datetime.date
    total_spend_usd: float
    total_tokens: int
    total_requests: int
    spend_series: list[OpenAIOrgSpendPoint]
    capabilities: list[OpenAIOrgCapabilityResponse]
    note: str


def _build_openai_capability_response(
    capability: OpenAIUsageCapabilityAggregate,
) -> OpenAIOrgCapabilityResponse:
    all_periods = sorted(
        set(capability.requests_by_day).union(capability.metric_by_day)
    )

    return OpenAIOrgCapabilityResponse(
        key=capability.key,
        label=capability.label,
        endpoint=capability.endpoint,
        metric_key=capability.metric_key,
        metric_label=capability.metric_label,
        total_requests=capability.total_requests,
        total_metric_value=round(capability.total_metric_value, 2),
        series=[
            OpenAIOrgCapabilitySeriesPoint(
                period_start=period_start,
                request_count=capability.requests_by_day.get(period_start, 0),
                metric_value=round(capability.metric_by_day.get(period_start, 0.0), 2),
            )
            for period_start in all_periods
        ],
    )


@router.get("/admin/openai-org")
def get_openai_org_analytics(
    start: datetime.datetime | None = None,
    end: datetime.datetime | None = None,
    _: User = Depends(current_admin_user),
) -> OpenAIOrgAnalyticsResponse:
    start = start or (
        datetime.datetime.utcnow() - datetime.timedelta(days=_DEFAULT_LOOKBACK_DAYS)
    )
    end = end or datetime.datetime.utcnow()

    if not OPENAI_ORG_ADMIN_KEY:
        return OpenAIOrgAnalyticsResponse(
            enabled=False,
            period_start=start.date(),
            period_end=end.date(),
            total_spend_usd=0.0,
            total_tokens=0,
            total_requests=0,
            spend_series=[],
            capabilities=[],
            note=(
                "OpenAI org analytics is not configured. Set OPENAI_ORG_ADMIN_KEY "
                "and optionally OPENAI_ORG_PROJECT_IDS."
            ),
        )

    try:
        cost_usd_by_period = fetch_openai_cost_series_usd(
            start=start,
            end=end,
            admin_api_key=OPENAI_ORG_ADMIN_KEY,
            project_ids=OPENAI_ORG_PROJECT_IDS,
        )
        capabilities = fetch_openai_usage_capabilities(
            start=start,
            end=end,
            admin_api_key=OPENAI_ORG_ADMIN_KEY,
            project_ids=OPENAI_ORG_PROJECT_IDS,
        )
    except Exception as e:
        status_code = (
            e.response.status_code
            if isinstance(e, requests.HTTPError) and e.response is not None
            else None
        )
        if status_code in (401, 403):
            logger.warning(
                "OpenAI org analytics auth/permission failure (status=%s): %s",
                status_code,
                e,
            )
            raise HTTPException(
                status_code=502,
                detail=(
                    "Failed to fetch OpenAI org analytics. Verify "
                    "OPENAI_ORG_ADMIN_KEY has organization admin permissions."
                ),
            )

        logger.warning(
            "Failed to fetch OpenAI org analytics due to network/API issue, "
            "returning disabled state: %s",
            e,
        )
        return OpenAIOrgAnalyticsResponse(
            enabled=False,
            period_start=start.date(),
            period_end=end.date(),
            total_spend_usd=0.0,
            total_tokens=0,
            total_requests=0,
            spend_series=[],
            capabilities=[],
            note=(
                "OpenAI org analytics is temporarily unavailable due to an OpenAI "
                "API/network timeout. Retry in a minute; if it persists, verify "
                "connectivity to api.openai.com."
            ),
        )

    capability_responses = [
        _build_openai_capability_response(capability) for capability in capabilities
    ]
    total_requests = sum(capability.total_requests for capability in capabilities)

    completion_capability = next(
        (
            capability
            for capability in capabilities
            if capability.key == "responses_and_chat_completions"
        ),
        None,
    )
    total_tokens = (
        int(round(completion_capability.total_metric_value))
        if completion_capability is not None
        else 0
    )

    note = "Data is sourced from OpenAI Organization costs/usage APIs."
    if OPENAI_ORG_PROJECT_IDS:
        note += " Results are filtered to configured project IDs."
    else:
        note += " No project filter is configured (all org projects may be included)."
    if not capabilities:
        note += (
            " Usage capability endpoints were unavailable for this request, so "
            "capability metrics are not shown."
        )

    return OpenAIOrgAnalyticsResponse(
        enabled=True,
        period_start=start.date(),
        period_end=end.date(),
        total_spend_usd=round(sum(cost_usd_by_period.values()), 2),
        total_tokens=total_tokens,
        total_requests=total_requests,
        spend_series=[
            OpenAIOrgSpendPoint(period_start=period_start, cost_usd=round(cost_usd, 2))
            for period_start, cost_usd in sorted(cost_usd_by_period.items())
        ],
        capabilities=capability_responses,
        note=note,
    )
