import { type User } from "@/lib/types";
import userMutationFetcher from "@/lib/admin/users/userMutationFetcher";
import useSWRMutation from "swr/mutation";
import InputSelect from "@/refresh-components/inputs/InputSelect";

const USER_FEATURE_OVERRIDE_ENDPOINT = "/api/manage/admin/user-feature-override";

const INHERIT_VALUE = "inherit";
const ENABLED_VALUE = "enabled";
const DISABLED_VALUE = "disabled";

export type UserFeatureOverrideKey =
  | "onyx_craft_enabled"
  | "image_generation_enabled"
  | "deep_research_enabled";

interface UserFeatureOverrideDropdownProps {
  user: User;
  featureKey: UserFeatureOverrideKey;
  onSuccess: () => void;
  onError: (message: string) => void;
}

function overrideToSelectValue(override: boolean | undefined): string {
  if (override === true) {
    return ENABLED_VALUE;
  }
  if (override === false) {
    return DISABLED_VALUE;
  }
  return INHERIT_VALUE;
}

function selectValueToOverride(value: string): boolean | null {
  if (value === ENABLED_VALUE) {
    return true;
  }
  if (value === DISABLED_VALUE) {
    return false;
  }
  return null;
}

export default function UserFeatureOverrideDropdown({
  user,
  featureKey,
  onSuccess,
  onError,
}: UserFeatureOverrideDropdownProps) {
  const { trigger: setUserFeatureOverride, isMutating } = useSWRMutation(
    USER_FEATURE_OVERRIDE_ENDPOINT,
    userMutationFetcher,
    { onSuccess, onError }
  );

  const currentOverride = user.feature_overrides?.[featureKey];
  const currentValue = overrideToSelectValue(currentOverride);

  const handleChange = (value: string) => {
    if (value === currentValue) {
      return;
    }

    setUserFeatureOverride({
      user_email: user.email,
      feature_key: featureKey,
      override: selectValueToOverride(value),
    });
  };

  return (
    <InputSelect
      value={currentValue}
      onValueChange={handleChange}
      disabled={isMutating}
    >
      <InputSelect.Trigger />
      <InputSelect.Content>
        <InputSelect.Item value={INHERIT_VALUE}>
          Inherit Workspace
        </InputSelect.Item>
        <InputSelect.Item value={ENABLED_VALUE}>Enabled</InputSelect.Item>
        <InputSelect.Item value={DISABLED_VALUE}>Disabled</InputSelect.Item>
      </InputSelect.Content>
    </InputSelect>
  );
}
