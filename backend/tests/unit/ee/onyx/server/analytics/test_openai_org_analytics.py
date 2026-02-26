import datetime
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
import requests

from ee.onyx.server.analytics.openai_org_analytics import _build_usage_query_params
from ee.onyx.server.analytics.openai_org_analytics import fetch_openai_cost_series_usd
from ee.onyx.server.analytics.openai_org_analytics import (
    fetch_openai_usage_capabilities,
)
from ee.onyx.server.analytics.openai_org_analytics import OpenAIUsageCapabilitySpec


def _mock_response(payload: dict) -> MagicMock:
    response = MagicMock()
    response.json.return_value = payload
    response.raise_for_status.return_value = None
    return response


def test_fetch_openai_cost_series_usd_aggregates_results_per_day() -> None:
    day_one = datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)
    day_two = datetime.datetime(2026, 1, 2, tzinfo=datetime.timezone.utc)

    with patch(
        "ee.onyx.server.analytics.openai_org_analytics.requests.get"
    ) as mock_get:
        mock_get.return_value = _mock_response(
            {
                "object": "page",
                "has_more": False,
                "next_page": None,
                "data": [
                    {
                        "object": "bucket",
                        "start_time": int(day_one.timestamp()),
                        "end_time": int(day_two.timestamp()),
                        "results": [
                            {"amount": {"value": 1.25, "currency": "usd"}},
                            {"amount": {"value": 0.75, "currency": "usd"}},
                            {"amount": {"value": "0.50", "currency": "usd"}},
                        ],
                    },
                    {
                        "object": "bucket",
                        "start_time": int(day_two.timestamp()),
                        "end_time": int(day_two.timestamp()),
                        "results": [
                            {"amount": {"value": 2.50, "currency": "usd"}},
                        ],
                    },
                ],
            }
        )

        costs = fetch_openai_cost_series_usd(
            start=day_one,
            end=day_two,
            admin_api_key="sk-admin-test",
        )

    assert costs == {
        day_one.date(): 2.5,
        day_two.date(): 2.5,
    }


def test_build_usage_query_params_clamps_future_end_time() -> None:
    start = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=3)
    end = start + datetime.timedelta(days=30)

    params = _build_usage_query_params(start=start, end=end, project_ids=None)
    now_seconds = int(datetime.datetime.now(datetime.timezone.utc).timestamp())

    assert params["start_time"] <= params["end_time"]
    assert params["end_time"] <= now_seconds


def test_fetch_openai_cost_series_usd_supports_pagination() -> None:
    day_one = datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)
    day_two = datetime.datetime(2026, 1, 2, tzinfo=datetime.timezone.utc)

    first_page = _mock_response(
        {
            "object": "page",
            "has_more": True,
            "next_page": "cursor_2",
            "data": [
                {
                    "object": "bucket",
                    "start_time": int(day_one.timestamp()),
                    "end_time": int(day_two.timestamp()),
                    "results": [{"amount": {"value": 1.0, "currency": "usd"}}],
                }
            ],
        }
    )
    second_page = _mock_response(
        {
            "object": "page",
            "has_more": False,
            "next_page": None,
            "data": [
                {
                    "object": "bucket",
                    "start_time": int(day_two.timestamp()),
                    "end_time": int(day_two.timestamp()),
                    "results": [{"amount": {"value": 2.0, "currency": "usd"}}],
                }
            ],
        }
    )

    with patch(
        "ee.onyx.server.analytics.openai_org_analytics.requests.get"
    ) as mock_get:
        mock_get.side_effect = [first_page, second_page]

        costs = fetch_openai_cost_series_usd(
            start=day_one,
            end=day_two,
            admin_api_key="sk-admin-test",
        )

    assert costs == {
        day_one.date(): 1.0,
        day_two.date(): 2.0,
    }
    assert mock_get.call_count == 2

    first_call_params = mock_get.call_args_list[0].kwargs["params"]
    second_call_params = mock_get.call_args_list[1].kwargs["params"]
    assert "page" not in first_call_params
    assert second_call_params["page"] == "cursor_2"


def test_fetch_openai_cost_series_usd_passes_project_filters() -> None:
    start = datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)
    end = datetime.datetime(2026, 1, 2, tzinfo=datetime.timezone.utc)

    with patch(
        "ee.onyx.server.analytics.openai_org_analytics.requests.get"
    ) as mock_get:
        mock_get.return_value = _mock_response(
            {"object": "page", "has_more": False, "next_page": None, "data": []}
        )

        fetch_openai_cost_series_usd(
            start=start,
            end=end,
            admin_api_key="sk-admin-test",
            project_ids=["proj_1", "proj_2"],
        )

    params = mock_get.call_args.kwargs["params"]
    assert params["project_ids[]"] == ["proj_1", "proj_2"]


def test_fetch_openai_cost_series_usd_handles_non_list_data() -> None:
    start = datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)
    end = datetime.datetime(2026, 1, 2, tzinfo=datetime.timezone.utc)

    with patch(
        "ee.onyx.server.analytics.openai_org_analytics.requests.get"
    ) as mock_get:
        mock_get.return_value = _mock_response(
            {"object": "page", "has_more": False, "next_page": None, "data": {}}
        )

        costs = fetch_openai_cost_series_usd(
            start=start,
            end=end,
            admin_api_key="sk-admin-test",
        )

    assert costs == {}


def test_fetch_openai_usage_capabilities_aggregates_metrics() -> None:
    start = datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)
    end = datetime.datetime(2026, 1, 2, tzinfo=datetime.timezone.utc)

    test_spec = OpenAIUsageCapabilitySpec(
        key="responses_and_chat_completions",
        label="Responses and Chat Completions",
        endpoint="completions",
        metric_key="input_tokens",
        metric_label="Input Tokens",
        metric_candidates=("input_tokens",),
    )

    with (
        patch(
            "ee.onyx.server.analytics.openai_org_analytics._USAGE_CAPABILITY_SPECS",
            (test_spec,),
        ),
        patch(
            "ee.onyx.server.analytics.openai_org_analytics.requests.get"
        ) as mock_get,
    ):
        mock_get.return_value = _mock_response(
            {
                "object": "page",
                "has_more": False,
                "next_page": None,
                "data": [
                    {
                        "object": "bucket",
                        "start_time": int(start.timestamp()),
                        "end_time": int(end.timestamp()),
                        "results": [
                            {
                                "num_model_requests": 3,
                                "input_tokens": 1200,
                            },
                            {
                                "num_model_requests": 2,
                                "input_tokens": 800,
                            },
                        ],
                    }
                ],
            }
        )

        capabilities = fetch_openai_usage_capabilities(
            start=start,
            end=end,
            admin_api_key="sk-admin-test",
        )

    assert len(capabilities) == 1
    assert capabilities[0].key == "responses_and_chat_completions"
    assert capabilities[0].total_requests == 5
    assert capabilities[0].total_metric_value == 2000


def test_fetch_openai_usage_capabilities_skips_unsupported_endpoint() -> None:
    start = datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)
    end = datetime.datetime(2026, 1, 2, tzinfo=datetime.timezone.utc)

    test_spec = OpenAIUsageCapabilitySpec(
        key="web_searches",
        label="Web Searches",
        endpoint="web_searches",
        metric_key="num_model_requests",
        metric_label="Requests",
        metric_candidates=("num_model_requests",),
    )

    unsupported_response = MagicMock()
    unsupported_response.status_code = 404
    unsupported_error = requests.HTTPError(response=unsupported_response)

    with (
        patch(
            "ee.onyx.server.analytics.openai_org_analytics._USAGE_CAPABILITY_SPECS",
            (test_spec,),
        ),
        patch(
            "ee.onyx.server.analytics.openai_org_analytics.requests.get"
        ) as mock_get,
    ):
        mock_get.side_effect = unsupported_error

        capabilities = fetch_openai_usage_capabilities(
            start=start,
            end=end,
            admin_api_key="sk-admin-test",
        )

    assert capabilities == []


def test_fetch_openai_usage_capabilities_skips_unavailable_endpoint_and_continues() -> None:
    start = datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)
    end = datetime.datetime(2026, 1, 2, tzinfo=datetime.timezone.utc)

    unavailable_spec = OpenAIUsageCapabilitySpec(
        key="embeddings",
        label="Embeddings",
        endpoint="embeddings",
        metric_key="input_tokens",
        metric_label="Input Tokens",
        metric_candidates=("input_tokens",),
    )
    available_spec = OpenAIUsageCapabilitySpec(
        key="images",
        label="Images",
        endpoint="images",
        metric_key="num_images",
        metric_label="Images",
        metric_candidates=("num_images",),
    )

    unavailable_response = MagicMock()
    unavailable_response.status_code = 500
    unavailable_error = requests.HTTPError(response=unavailable_response)

    with (
        patch(
            "ee.onyx.server.analytics.openai_org_analytics._USAGE_CAPABILITY_SPECS",
            (unavailable_spec, available_spec),
        ),
        patch(
            "ee.onyx.server.analytics.openai_org_analytics.requests.get"
        ) as mock_get,
    ):
        mock_get.side_effect = [
            unavailable_error,
            _mock_response(
                {
                    "object": "page",
                    "has_more": False,
                    "next_page": None,
                    "data": [
                        {
                            "object": "bucket",
                            "start_time": int(start.timestamp()),
                            "end_time": int(end.timestamp()),
                            "results": [
                                {
                                    "num_model_requests": 4,
                                    "num_images": 6,
                                }
                            ],
                        }
                    ],
                }
            ),
        ]

        capabilities = fetch_openai_usage_capabilities(
            start=start,
            end=end,
            admin_api_key="sk-admin-test",
        )

    assert len(capabilities) == 1
    assert capabilities[0].key == "images"
    assert capabilities[0].total_requests == 4
    assert capabilities[0].total_metric_value == 6


def test_fetch_openai_usage_capabilities_raises_on_auth_failure() -> None:
    start = datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)
    end = datetime.datetime(2026, 1, 2, tzinfo=datetime.timezone.utc)

    test_spec = OpenAIUsageCapabilitySpec(
        key="moderation",
        label="Moderation",
        endpoint="moderations",
        metric_key="input_tokens",
        metric_label="Input Tokens",
        metric_candidates=("input_tokens",),
    )

    unauthorized_response = MagicMock()
    unauthorized_response.status_code = 401
    unauthorized_error = requests.HTTPError(response=unauthorized_response)

    with (
        patch(
            "ee.onyx.server.analytics.openai_org_analytics._USAGE_CAPABILITY_SPECS",
            (test_spec,),
        ),
        patch(
            "ee.onyx.server.analytics.openai_org_analytics.requests.get"
        ) as mock_get,
    ):
        mock_get.side_effect = unauthorized_error

        with pytest.raises(requests.HTTPError):
            fetch_openai_usage_capabilities(
                start=start,
                end=end,
                admin_api_key="sk-admin-test",
            )
