import datetime
import time
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

import requests

from onyx.utils.logger import setup_logger

logger = setup_logger()

_OPENAI_API_BASE_URL = "https://api.openai.com/v1"
_OPENAI_COSTS_ENDPOINT = "organization/costs"
_OPENAI_TIMEOUT_SECONDS = 45
_OPENAI_DAILY_BUCKET_WIDTH = "1d"
_OPENAI_MAX_COST_BUCKETS_PER_PAGE = 180
# OpenAI usage endpoints cap 1d bucket limit at 31.
_OPENAI_MAX_USAGE_BUCKETS_PER_PAGE = 31
_OPENAI_MAX_PAGES = 100
_OPENAI_MAX_REQUEST_ATTEMPTS = 3
_OPENAI_RETRY_BASE_DELAY_SECONDS = 1.0
_OPENAI_RETRYABLE_STATUS_CODES = {408, 429, 500, 502, 503, 504}

_OPENAI_PROJECT_IDS_PARAM = "project_ids[]"
_OPENAI_USAGE_ENDPOINT_PREFIX = "organization/usage"
_REQUEST_METRIC_CANDIDATES = (
    "num_model_requests",
    "num_requests",
    "requests",
)


@dataclass(frozen=True)
class OpenAIUsageCapabilitySpec:
    key: str
    label: str
    endpoint: str
    metric_key: str
    metric_label: str
    metric_candidates: tuple[str, ...]


@dataclass
class OpenAIUsageCapabilityAggregate:
    key: str
    label: str
    endpoint: str
    metric_key: str
    metric_label: str
    total_requests: int
    total_metric_value: float
    requests_by_day: dict[datetime.date, int]
    metric_by_day: dict[datetime.date, float]


_USAGE_CAPABILITY_SPECS: tuple[OpenAIUsageCapabilitySpec, ...] = (
    OpenAIUsageCapabilitySpec(
        key="responses_and_chat_completions",
        label="Responses and Chat Completions",
        endpoint="completions",
        metric_key="input_tokens",
        metric_label="Input Tokens",
        metric_candidates=("input_tokens",),
    ),
    OpenAIUsageCapabilitySpec(
        key="images",
        label="Images",
        endpoint="images",
        metric_key="num_images",
        metric_label="Images",
        metric_candidates=("num_images",),
    ),
    OpenAIUsageCapabilitySpec(
        key="web_searches",
        label="Web Searches",
        endpoint="web_searches",
        metric_key="num_model_requests",
        metric_label="Requests",
        metric_candidates=_REQUEST_METRIC_CANDIDATES,
    ),
    OpenAIUsageCapabilitySpec(
        key="file_searches",
        label="File Searches",
        endpoint="file_searches",
        metric_key="num_model_requests",
        metric_label="Requests",
        metric_candidates=_REQUEST_METRIC_CANDIDATES,
    ),
    OpenAIUsageCapabilitySpec(
        key="moderation",
        label="Moderation",
        endpoint="moderations",
        metric_key="input_tokens",
        metric_label="Input Tokens",
        metric_candidates=("input_tokens",),
    ),
    OpenAIUsageCapabilitySpec(
        key="embeddings",
        label="Embeddings",
        endpoint="embeddings",
        metric_key="input_tokens",
        metric_label="Input Tokens",
        metric_candidates=("input_tokens",),
    ),
    OpenAIUsageCapabilitySpec(
        key="audio_speeches",
        label="Audio Speeches",
        endpoint="audio_speeches",
        metric_key="num_characters",
        metric_label="Characters",
        metric_candidates=("num_characters",),
    ),
    OpenAIUsageCapabilitySpec(
        key="audio_transcriptions",
        label="Audio Transcriptions",
        endpoint="audio_transcriptions",
        metric_key="num_seconds",
        metric_label="Seconds",
        metric_candidates=("num_seconds",),
    ),
    OpenAIUsageCapabilitySpec(
        key="vector_stores",
        label="Vector Stores",
        endpoint="vector_stores",
        metric_key="usage_bytes",
        metric_label="Bytes",
        metric_candidates=("usage_bytes",),
    ),
    OpenAIUsageCapabilitySpec(
        key="code_interpreter_sessions",
        label="Code Interpreter Sessions",
        endpoint="code_interpreter_sessions",
        metric_key="num_sessions",
        metric_label="Sessions",
        metric_candidates=("num_sessions",),
    ),
)


def _to_unix_seconds(timestamp: datetime.datetime) -> int:
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=datetime.timezone.utc)
    else:
        timestamp = timestamp.astimezone(datetime.timezone.utc)

    return int(timestamp.timestamp())


def _normalize_openai_time_range(
    start: datetime.datetime,
    end: datetime.datetime,
) -> tuple[datetime.datetime, datetime.datetime]:
    # OpenAI usage/cost APIs can reject end_time values in the future.
    now_utc = datetime.datetime.now(datetime.timezone.utc)

    if start.tzinfo is None:
        start = start.replace(tzinfo=datetime.timezone.utc)
    else:
        start = start.astimezone(datetime.timezone.utc)

    if end.tzinfo is None:
        end = end.replace(tzinfo=datetime.timezone.utc)
    else:
        end = end.astimezone(datetime.timezone.utc)

    if end > now_utc:
        end = now_utc

    if start > end:
        start = end

    return start, end


def _bucket_start_day(bucket: dict[str, Any]) -> datetime.date | None:
    start_time = bucket.get("start_time")
    if not isinstance(start_time, (int, float)):
        return None

    return datetime.datetime.fromtimestamp(
        float(start_time), tz=datetime.timezone.utc
    ).date()


def _coerce_number(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _extract_first_numeric(
    result: dict[str, Any],
    candidate_keys: tuple[str, ...],
) -> float | None:
    for key in candidate_keys:
        candidate = _coerce_number(result.get(key))
        if candidate is not None:
            return candidate
    return None


def _build_cost_query_params(
    start: datetime.datetime,
    end: datetime.datetime,
    project_ids: list[str] | None,
) -> dict[str, Any]:
    start, end = _normalize_openai_time_range(start=start, end=end)

    start_seconds = _to_unix_seconds(start)
    end_seconds = _to_unix_seconds(end)

    params: dict[str, Any] = {
        "start_time": start_seconds,
        "bucket_width": _OPENAI_DAILY_BUCKET_WIDTH,
        "limit": _OPENAI_MAX_COST_BUCKETS_PER_PAGE,
    }

    if end_seconds >= start_seconds:
        params["end_time"] = end_seconds

    if project_ids:
        params[_OPENAI_PROJECT_IDS_PARAM] = project_ids

    return params


def _fetch_bucketed_data(
    endpoint: str,
    admin_api_key: str,
    params: dict[str, Any],
) -> list[dict[str, Any]]:
    url = f"{_OPENAI_API_BASE_URL}/{endpoint}"
    headers = {"Authorization": f"Bearer {admin_api_key}"}

    all_buckets: list[dict[str, Any]] = []
    page_cursor: str | None = None

    for _ in range(_OPENAI_MAX_PAGES):
        current_params = dict(params)
        if page_cursor:
            current_params["page"] = page_cursor

        response: requests.Response | None = None
        for attempt in range(1, _OPENAI_MAX_REQUEST_ATTEMPTS + 1):
            try:
                response = requests.get(
                    url,
                    headers=headers,
                    params=current_params,
                    timeout=_OPENAI_TIMEOUT_SECONDS,
                )
            except requests.RequestException as e:
                if (
                    isinstance(e, (requests.Timeout, requests.ConnectionError))
                    and attempt < _OPENAI_MAX_REQUEST_ATTEMPTS
                ):
                    delay_seconds = _OPENAI_RETRY_BASE_DELAY_SECONDS * attempt
                    logger.warning(
                        "OpenAI analytics request failed for '%s' (attempt %s/%s): %s. "
                        "Retrying in %.1fs.",
                        endpoint,
                        attempt,
                        _OPENAI_MAX_REQUEST_ATTEMPTS,
                        e,
                        delay_seconds,
                    )
                    time.sleep(delay_seconds)
                    continue
                raise

            if (
                response.status_code in _OPENAI_RETRYABLE_STATUS_CODES
                and attempt < _OPENAI_MAX_REQUEST_ATTEMPTS
            ):
                retry_after = response.headers.get("Retry-After")
                retry_after_seconds: float | None = None
                if retry_after:
                    try:
                        retry_after_seconds = float(retry_after)
                    except ValueError:
                        retry_after_seconds = None
                delay_seconds = retry_after_seconds or (
                    _OPENAI_RETRY_BASE_DELAY_SECONDS * attempt
                )
                logger.warning(
                    "OpenAI analytics endpoint '%s' returned status=%s "
                    "(attempt %s/%s). Retrying in %.1fs.",
                    endpoint,
                    response.status_code,
                    attempt,
                    _OPENAI_MAX_REQUEST_ATTEMPTS,
                    delay_seconds,
                )
                time.sleep(delay_seconds)
                continue

            response.raise_for_status()
            break

        if response is None:
            raise RuntimeError("OpenAI analytics request did not produce a response.")

        payload = response.json()

        data = payload.get("data")
        if not isinstance(data, list):
            logger.warning(
                "OpenAI analytics response did not include a list 'data' field."
            )
            break

        all_buckets.extend(item for item in data if isinstance(item, dict))

        has_more = bool(payload.get("has_more"))
        next_page = payload.get("next_page")
        if not has_more or not isinstance(next_page, str) or not next_page:
            break

        page_cursor = next_page
    else:
        logger.warning(
            "Reached OpenAI analytics pagination cap (%s pages).",
            _OPENAI_MAX_PAGES,
        )

    return all_buckets


def fetch_openai_cost_series_usd(
    start: datetime.datetime,
    end: datetime.datetime,
    admin_api_key: str,
    project_ids: list[str] | None = None,
) -> dict[datetime.date, float]:
    """
    Fetch daily OpenAI organization costs (USD) from the OpenAI Costs API.

    Raises:
        requests.RequestException on API/network failures.
    """
    params = _build_cost_query_params(start=start, end=end, project_ids=project_ids)
    bucketed_data = _fetch_bucketed_data(
        endpoint=_OPENAI_COSTS_ENDPOINT,
        admin_api_key=admin_api_key,
        params=params,
    )

    daily_costs_usd: defaultdict[datetime.date, float] = defaultdict(float)

    for bucket in bucketed_data:
        period_start = _bucket_start_day(bucket)
        if period_start is None:
            continue

        results = bucket.get("results")
        if not isinstance(results, list):
            continue

        for result in results:
            if not isinstance(result, dict):
                continue

            amount = result.get("amount")
            if not isinstance(amount, dict):
                continue

            value = _coerce_number(amount.get("value"))
            if value is not None:
                daily_costs_usd[period_start] += value

    return dict(daily_costs_usd)


def _build_usage_query_params(
    start: datetime.datetime,
    end: datetime.datetime,
    project_ids: list[str] | None,
) -> dict[str, Any]:
    start, end = _normalize_openai_time_range(start=start, end=end)

    start_seconds = _to_unix_seconds(start)
    end_seconds = _to_unix_seconds(end)

    params: dict[str, Any] = {
        "start_time": start_seconds,
        "bucket_width": _OPENAI_DAILY_BUCKET_WIDTH,
        "limit": _OPENAI_MAX_USAGE_BUCKETS_PER_PAGE,
    }

    if end_seconds >= start_seconds:
        params["end_time"] = end_seconds

    if project_ids:
        params[_OPENAI_PROJECT_IDS_PARAM] = project_ids

    return params


def _aggregate_usage_capability(
    spec: OpenAIUsageCapabilitySpec,
    bucketed_data: list[dict[str, Any]],
) -> OpenAIUsageCapabilityAggregate:
    requests_by_day: defaultdict[datetime.date, int] = defaultdict(int)
    metric_by_day: defaultdict[datetime.date, float] = defaultdict(float)

    for bucket in bucketed_data:
        period_start = _bucket_start_day(bucket)
        if period_start is None:
            continue

        results = bucket.get("results")
        if not isinstance(results, list):
            continue

        for result in results:
            if not isinstance(result, dict):
                continue

            request_count = _extract_first_numeric(result, _REQUEST_METRIC_CANDIDATES)
            if request_count is not None:
                requests_by_day[period_start] += int(request_count)

            metric_value = _extract_first_numeric(result, spec.metric_candidates)
            if metric_value is not None:
                metric_by_day[period_start] += metric_value

    return OpenAIUsageCapabilityAggregate(
        key=spec.key,
        label=spec.label,
        endpoint=spec.endpoint,
        metric_key=spec.metric_key,
        metric_label=spec.metric_label,
        total_requests=sum(requests_by_day.values()),
        total_metric_value=sum(metric_by_day.values()),
        requests_by_day=dict(requests_by_day),
        metric_by_day=dict(metric_by_day),
    )


def fetch_openai_usage_capabilities(
    start: datetime.datetime,
    end: datetime.datetime,
    admin_api_key: str,
    project_ids: list[str] | None = None,
) -> list[OpenAIUsageCapabilityAggregate]:
    """
    Fetch usage capabilities from OpenAI org Usage APIs.

    If a capability endpoint is unavailable, it is skipped and does not fail the
    entire analytics response. Authentication/authorization failures are raised.

    Raises:
        requests.HTTPError on auth/permission failures.
    """
    params = _build_usage_query_params(start=start, end=end, project_ids=project_ids)

    capabilities: list[OpenAIUsageCapabilityAggregate] = []
    for spec in _USAGE_CAPABILITY_SPECS:
        endpoint = f"{_OPENAI_USAGE_ENDPOINT_PREFIX}/{spec.endpoint}"
        try:
            bucketed_data = _fetch_bucketed_data(
                endpoint=endpoint,
                admin_api_key=admin_api_key,
                params=params,
            )
        except requests.HTTPError as e:
            status_code = e.response.status_code if e.response is not None else None
            if status_code in (401, 403):
                raise
            if status_code in (400, 404):
                logger.info(
                    "Skipping unsupported OpenAI usage endpoint '%s' (status=%s).",
                    endpoint,
                    status_code,
                )
                continue
            logger.warning(
                "Skipping unavailable OpenAI usage endpoint '%s' (status=%s): %s",
                endpoint,
                status_code,
                e,
            )
            continue
        except requests.RequestException as e:
            logger.warning(
                "Skipping unavailable OpenAI usage endpoint '%s' due to transport "
                "error: %s",
                endpoint,
                e,
            )
            continue

        capabilities.append(
            _aggregate_usage_capability(spec=spec, bucketed_data=bucketed_data)
        )

    return capabilities
