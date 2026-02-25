from onyx.db.models import User


# Per-user override keys stored on user.feature_overrides.
ONYX_CRAFT_ENABLED_OVERRIDE_KEY = "onyx_craft_enabled"
IMAGE_GENERATION_ENABLED_OVERRIDE_KEY = "image_generation_enabled"
DEEP_RESEARCH_ENABLED_OVERRIDE_KEY = "deep_research_enabled"


def get_feature_override(user: User, feature_key: str) -> bool | None:
    raw_value = (user.feature_overrides or {}).get(feature_key)
    return raw_value if isinstance(raw_value, bool) else None


def is_feature_enabled_with_default(
    user: User, feature_key: str, default_enabled: bool
) -> bool:
    override = get_feature_override(user, feature_key)
    if override is not None:
        return override

    return default_enabled
