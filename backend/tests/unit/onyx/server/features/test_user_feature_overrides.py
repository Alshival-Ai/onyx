from types import SimpleNamespace

from onyx.server.features.user_feature_overrides import get_feature_override
from onyx.server.features.user_feature_overrides import is_feature_enabled_with_default


def _user_with_overrides(overrides: dict[str, object] | None) -> SimpleNamespace:
    return SimpleNamespace(feature_overrides=overrides)


def test_get_feature_override_returns_true_false_and_none() -> None:
    user = _user_with_overrides(
        {
            "enabled_flag": True,
            "disabled_flag": False,
            "invalid_flag": "true",
        }
    )

    assert get_feature_override(user, "enabled_flag") is True
    assert get_feature_override(user, "disabled_flag") is False
    assert get_feature_override(user, "invalid_flag") is None
    assert get_feature_override(user, "missing_flag") is None


def test_is_feature_enabled_with_default_prefers_override() -> None:
    enabled_user = _user_with_overrides({"feature": True})
    disabled_user = _user_with_overrides({"feature": False})
    inherit_user = _user_with_overrides({})

    assert (
        is_feature_enabled_with_default(
            user=enabled_user, feature_key="feature", default_enabled=False
        )
        is True
    )
    assert (
        is_feature_enabled_with_default(
            user=disabled_user, feature_key="feature", default_enabled=True
        )
        is False
    )
    assert (
        is_feature_enabled_with_default(
            user=inherit_user, feature_key="feature", default_enabled=True
        )
        is True
    )
