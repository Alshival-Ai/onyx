from types import SimpleNamespace
from typing import Any
from uuid import UUID
from uuid import uuid4

from onyx.feature_flags.interface import FeatureFlagProvider
from onyx.feature_flags.interface import NoOpFeatureFlagProvider
from onyx.server.features.build import utils as build_utils


class MockFeatureFlagProvider(FeatureFlagProvider):
    def __init__(self, enabled: bool) -> None:
        self._enabled = enabled

    def feature_enabled(
        self,
        flag_key: str,  # noqa: ARG002
        user_id: UUID,  # noqa: ARG002
        user_properties: dict[str, Any] | None = None,  # noqa: ARG002
    ) -> bool:
        return self._enabled


def _create_user(feature_overrides: dict[str, bool] | None = None) -> SimpleNamespace:
    return SimpleNamespace(id=uuid4(), feature_overrides=feature_overrides or {})


def test_onyx_craft_disabled_when_runtime_disabled_even_with_enable_override(
    monkeypatch,
) -> None:
    monkeypatch.setattr(build_utils, "ENABLE_CRAFT", False)
    monkeypatch.setattr(
        build_utils,
        "get_default_feature_flag_provider",
        lambda: NoOpFeatureFlagProvider(),
    )
    user = _create_user({"onyx_craft_enabled": True})

    assert build_utils.is_onyx_craft_enabled(user) is False


def test_onyx_craft_respects_disable_override_when_runtime_enabled(monkeypatch) -> None:
    monkeypatch.setattr(build_utils, "ENABLE_CRAFT", True)
    monkeypatch.setattr(
        build_utils,
        "get_default_feature_flag_provider",
        lambda: NoOpFeatureFlagProvider(),
    )
    user = _create_user({"onyx_craft_enabled": False})

    assert build_utils.is_onyx_craft_enabled(user) is False


def test_onyx_craft_enable_override_wins_over_posthog_false(monkeypatch) -> None:
    monkeypatch.setattr(
        build_utils,
        "get_default_feature_flag_provider",
        lambda: MockFeatureFlagProvider(False),
    )
    user = _create_user({"onyx_craft_enabled": True})

    assert build_utils.is_onyx_craft_enabled(user) is True


def test_onyx_craft_disable_override_wins_over_posthog_true(monkeypatch) -> None:
    monkeypatch.setattr(
        build_utils,
        "get_default_feature_flag_provider",
        lambda: MockFeatureFlagProvider(True),
    )
    user = _create_user({"onyx_craft_enabled": False})

    assert build_utils.is_onyx_craft_enabled(user) is False


def test_onyx_craft_falls_back_to_posthog_without_override(monkeypatch) -> None:
    monkeypatch.setattr(
        build_utils,
        "get_default_feature_flag_provider",
        lambda: MockFeatureFlagProvider(True),
    )
    user = _create_user({})

    assert build_utils.is_onyx_craft_enabled(user) is True
