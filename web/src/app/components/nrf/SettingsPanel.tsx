"use client";

import Switch from "@/refresh-components/inputs/Switch";
import { useNRFPreferences } from "@/components/context/NRFPreferencesContext";
import Text from "@/refresh-components/texts/Text";
import { SvgX, SvgSettings, SvgSun, SvgMoon } from "@opal/icons";
import { Button } from "@opal/components";
import { cn } from "@/lib/utils";
import { useTheme } from "next-themes";

interface SettingRowProps {
  label: string;
  description?: string;
  children: React.ReactNode;
}

const SettingRow = ({ label, description, children }: SettingRowProps) => (
  <div className="flex justify-between items-center py-3">
    <div className="flex flex-col gap-0.5">
      <Text mainUiBody text04>
        {label}
      </Text>
      {description && (
        <Text secondaryBody text03>
          {description}
        </Text>
      )}
    </div>
    {children}
  </div>
);

export const SettingsPanel = ({
  settingsOpen,
  toggleSettings,
  handleUseOnyxToggle,
}: {
  settingsOpen: boolean;
  toggleSettings: () => void;
  handleUseOnyxToggle: (checked: boolean) => void;
}) => {
  const { useOnyxAsNewTab } = useNRFPreferences();
  const { theme, setTheme } = useTheme();
  const isDark = theme === "dark";

  const toggleTheme = () => {
    setTheme(isDark ? "light" : "dark");
  };

  return (
    <>
      {/* Backdrop overlay */}
      <div
        className={cn(
          "fixed inset-0 bg-mask-03 backdrop-blur-sm z-40 transition-opacity duration-300",
          settingsOpen
            ? "opacity-100 pointer-events-auto"
            : "opacity-0 pointer-events-none"
        )}
        onClick={toggleSettings}
      />

      {/* Settings panel */}
      <div
        className={cn(
          "fixed top-0 right-0 w-[25rem] h-full z-50",
          "bg-gradient-to-b from-background-tint-02 to-background-tint-01",
          "backdrop-blur-[24px] border-l border-border-01 overflow-y-auto",
          "transition-transform duration-300 ease-out",
          settingsOpen ? "translate-x-0" : "translate-x-full"
        )}
      >
        {/* Header */}
        <div className="sticky top-0 z-10 bg-gradient-to-b from-background-tint-02 to-transparent pb-4">
          <div className="flex items-center justify-between px-6 pt-6 pb-2">
            <div className="flex items-center gap-3">
              <div className="flex items-center justify-center w-10 h-10 rounded-xl bg-background-tint-02">
                <SvgSettings className="w-5 h-5 stroke-text-03" />
              </div>
              <Text headingH3 text04>
                Settings
              </Text>
            </div>
            <div className="flex items-center gap-3">
              {/* Theme Toggle */}
              <Button
                icon={isDark ? SvgMoon : SvgSun}
                onClick={toggleTheme}
                prominence="tertiary"
                tooltip={`Switch to ${isDark ? "light" : "dark"} theme`}
              />
              <Button
                icon={SvgX}
                onClick={toggleSettings}
                prominence="tertiary"
                tooltip="Close settings"
              />
            </div>
          </div>
        </div>

        <div className="px-6 pb-8 flex flex-col gap-8">
          {/* General Section */}
          <section className="flex flex-col gap-3">
            <Text secondaryAction text03 className="uppercase tracking-wider">
              General
            </Text>
            <div className="flex flex-col gap-1 bg-background-tint-01 rounded-2xl px-4">
              <SettingRow label="Use StarwoodGPT as new tab page">
                <Switch
                  checked={useOnyxAsNewTab}
                  onCheckedChange={handleUseOnyxToggle}
                />
              </SettingRow>
            </div>
          </section>
        </div>
      </div>
    </>
  );
};
