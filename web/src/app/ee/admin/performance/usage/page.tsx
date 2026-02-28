"use client";

import { useState } from "react";
import {
  AdminDateRangeSelector,
  DateRange,
} from "@/components/dateRangeSelectors/AdminDateRangeSelector";
import { FeedbackChart } from "@/app/ee/admin/performance/usage/FeedbackChart";
import { QueryPerformanceChart } from "@/app/ee/admin/performance/usage/QueryPerformanceChart";
import { PersonaMessagesChart } from "@/app/ee/admin/performance/usage/PersonaMessagesChart";
import { OpenAIOrgAnalyticsPanel } from "@/app/ee/admin/performance/usage/OpenAIOrgAnalyticsPanel";
import { useTimeRange } from "@/app/ee/admin/performance/lib";
import { AdminPageTitle } from "@/components/admin/Title";
import UsageReports from "@/app/ee/admin/performance/usage/UsageReports";
import { ExecutiveDashboard } from "@/app/ee/admin/performance/usage/ExecutiveDashboard";
import type {
  DashboardInterval,
  DashboardUserSortBy,
} from "@/app/ee/admin/performance/usage/ExecutiveDashboard";
import Separator from "@/refresh-components/Separator";
import { useAdminPersonas } from "@/hooks/useAdminPersonas";
import { SvgActivity } from "@opal/icons";
import Text from "@/refresh-components/texts/Text";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

const INTERVAL_OPTIONS: Array<{ label: string; value: DashboardInterval }> = [
  { label: "Weekly", value: "week" },
  { label: "Monthly", value: "month" },
];

const TOP_USER_LIMIT_OPTIONS = [5, 10, 15, 20];

const USER_SORT_OPTIONS: Array<{ label: string; value: DashboardUserSortBy }> = [
  { label: "Message volume", value: "message_count" },
  { label: "Token volume", value: "token_count" },
  { label: "Recent login", value: "recent_login" },
];

export default function AnalyticsPage() {
  const [timeRange, setTimeRange] = useTimeRange();
  const [dashboardInterval, setDashboardInterval] =
    useState<DashboardInterval>("week");
  const [topUsersLimit, setTopUsersLimit] = useState(10);
  const [userSortBy, setUserSortBy] = useState<DashboardUserSortBy>("message_count");
  const { personas } = useAdminPersonas();

  function handleDateRangeChange(value: DateRange) {
    if (!value?.from || !value.to) {
      return;
    }
    setTimeRange({
      from: value.from,
      to: value.to,
      selectValue: "custom",
    });
  }

  return (
    <>
      <AdminPageTitle title="Usage Statistics" icon={SvgActivity} />

      <div className="pb-6">
        <div className="rounded-16 border border-border-02 bg-background-tint-00 p-4 md:p-5">
          <Text headingH3>Performance Snapshot</Text>
          <Text mainUiMuted text03 className="pt-1">
            Explore adoption, cost, quality, and workload trends in one place.
            Tune the controls below to change how the dashboard ranks and groups
            results.
          </Text>
        </div>

        <div className="rounded-16 border border-border-02 bg-background-neutral-00 p-4 md:p-5 mt-3">
          <Text mainUiAction>Dashboard Controls</Text>
          <div className="pt-3 grid gap-3 md:grid-cols-2 xl:grid-cols-4">
            <div className="flex flex-col gap-1">
              <Text secondaryAction text03>
                Date range
              </Text>
              <AdminDateRangeSelector value={timeRange} onValueChange={handleDateRangeChange} />
            </div>

            <div className="flex flex-col gap-1">
              <Text secondaryAction text03>
                Aggregation
              </Text>
              <Select
                value={dashboardInterval}
                onValueChange={(value) =>
                  setDashboardInterval(value as DashboardInterval)
                }
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {INTERVAL_OPTIONS.map((option) => (
                    <SelectItem key={option.value} value={option.value}>
                      {option.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="flex flex-col gap-1">
              <Text secondaryAction text03>
                Top users shown
              </Text>
              <Select
                value={String(topUsersLimit)}
                onValueChange={(value) => setTopUsersLimit(Number(value))}
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {TOP_USER_LIMIT_OPTIONS.map((option) => (
                    <SelectItem key={option} value={String(option)}>
                      Top {option}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="flex flex-col gap-1">
              <Text secondaryAction text03>
                Sort users by
              </Text>
              <Select
                value={userSortBy}
                onValueChange={(value) => setUserSortBy(value as DashboardUserSortBy)}
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {USER_SORT_OPTIONS.map((option) => (
                    <SelectItem key={option.value} value={option.value}>
                      {option.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>
        </div>
      </div>

      <OpenAIOrgAnalyticsPanel timeRange={timeRange} />
      <ExecutiveDashboard
        timeRange={timeRange}
        interval={dashboardInterval}
        topUsersLimit={topUsersLimit}
        userSortBy={userSortBy}
      />
      <QueryPerformanceChart timeRange={timeRange} />
      <FeedbackChart timeRange={timeRange} />
      <PersonaMessagesChart
        availablePersonas={personas}
        timeRange={timeRange}
      />
      <Separator />
      <UsageReports />
    </>
  );
}
