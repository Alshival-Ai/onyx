"use client";

import { useMemo } from "react";
import { DateRangePickerValue } from "@/components/dateRangeSelectors/AdminDateRangeSelector";
import CardSection from "@/components/admin/CardSection";
import { useAdminDashboardAnalytics } from "../lib";
import { ThreeDotsLoader } from "@/components/Loading";
import { ErrorCallout } from "@/components/ErrorCallout";
import { AreaChartDisplay } from "@/components/ui/areaChart";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import Button from "@/refresh-components/buttons/Button";
import Text from "@/refresh-components/texts/Text";
import { humanReadableFormatWithTime, timeAgo } from "@/lib/time";
import type { DashboardTopUser } from "@/app/ee/admin/performance/usage/types";
import SimpleTooltip from "@/refresh-components/SimpleTooltip";

interface ExecutiveDashboardProps {
  timeRange: DateRangePickerValue;
  interval: DashboardInterval;
  topUsersLimit: number;
  userSortBy: DashboardUserSortBy;
}

export type DashboardInterval = "week" | "month";
export type DashboardUserSortBy =
  | "message_count"
  | "token_count"
  | "recent_login";

interface MetricCardProps {
  title: string;
  value: string;
  subtitle?: string;
  titleTooltip?: string;
}

const COST_SERIES_COLORS = ["#1D4ED8", "#0F766E"];
const USAGE_SERIES_COLORS = [
  "#1D4ED8",
  "#0F766E",
  "#334155",
  "#0369A1",
  "#78350F",
  "#7C3AED",
  "#0E7490",
  "#B45309",
];

const USER_SORT_LABEL: Record<DashboardUserSortBy, string> = {
  message_count: "message volume",
  token_count: "token volume",
  recent_login: "recent login",
};

const integerFormatter = new Intl.NumberFormat("en-US", {
  notation: "standard",
  maximumFractionDigits: 0,
});

const decimalFormatter = new Intl.NumberFormat("en-US", {
  notation: "standard",
  minimumFractionDigits: 1,
  maximumFractionDigits: 2,
});

const currencyFormatter = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

function applyBrandingCopy(text: string): string {
  return text.replace(/\bonyx\b/gi, "StarwoodGPT");
}

function formatPeriodLabel(periodStart: string, interval: "week" | "month") {
  const date = new Date(periodStart);
  const formatOptions: Intl.DateTimeFormatOptions = {
    month: "short",
  };

  if (interval === "week") {
    formatOptions.day = "numeric";
  } else {
    formatOptions.year = "2-digit";
  }

  return date.toLocaleDateString("en-US", formatOptions);
}

function formatLastLogin(lastLogin: string | null): string {
  if (!lastLogin) {
    return "No login recorded";
  }

  const relative = timeAgo(lastLogin);
  if (!relative) {
    return humanReadableFormatWithTime(lastLogin);
  }

  return `${humanReadableFormatWithTime(lastLogin)} (${relative})`;
}

function sortTopUsers(
  users: DashboardTopUser[],
  userSortBy: DashboardUserSortBy
): DashboardTopUser[] {
  const sortedUsers = [...users];
  if (userSortBy === "message_count") {
    sortedUsers.sort((left, right) => right.message_count - left.message_count);
    return sortedUsers;
  }

  if (userSortBy === "token_count") {
    sortedUsers.sort((left, right) => right.token_count - left.token_count);
    return sortedUsers;
  }

  sortedUsers.sort((left, right) => {
    if (!left.last_login && !right.last_login) {
      return 0;
    }
    if (!left.last_login) {
      return 1;
    }
    if (!right.last_login) {
      return -1;
    }
    return new Date(right.last_login).getTime() - new Date(left.last_login).getTime();
  });
  return sortedUsers;
}

function MetricCard({
  title,
  value,
  subtitle,
  titleTooltip,
}: MetricCardProps) {
  return (
    <div className="rounded-12 border border-border-02 bg-background-neutral-00 p-4">
      <div className="flex items-center gap-1">
        <Text secondaryBody text03>
          {title}
        </Text>
        {titleTooltip ? (
          <SimpleTooltip tooltip={titleTooltip} side="top">
            <span className="inline-flex h-4 min-w-4 items-center justify-center rounded-full border border-border-03 px-1 cursor-help">
              <Text as="span" secondaryMono text03>
                ?
              </Text>
            </span>
          </SimpleTooltip>
        ) : null}
      </div>
      <Text headingH3 className="pt-2">
        {value}
      </Text>
      {subtitle ? (
        <Text secondaryBody text04 className="pt-1">
          {subtitle}
        </Text>
      ) : null}
    </div>
  );
}

export function ExecutiveDashboard({
  timeRange,
  interval,
  topUsersLimit,
  userSortBy,
}: ExecutiveDashboardProps) {
  const {
    data,
    isLoading,
    error,
    refreshDashboardAnalytics,
  } = useAdminDashboardAnalytics(timeRange, interval, topUsersLimit);

  const positiveFeedbackRate = useMemo(() => {
    if (!data) {
      return null;
    }

    const totalFeedback = data.total_likes + data.total_dislikes;
    if (totalFeedback <= 0) {
      return null;
    }

    return (data.total_likes / totalFeedback) * 100;
  }, [data]);

  const sortedTopUsers = useMemo(() => {
    if (!data?.top_users.length) {
      return [];
    }
    return sortTopUsers(data.top_users, userSortBy);
  }, [data, userSortBy]);

  const costChartData = useMemo(() => {
    if (!data) {
      return [];
    }

    return data.cost_series.map((point) => ({
      Period: point.period_start,
      "Tracked StarwoodGPT Cost (USD)": point.llm_cost_usd,
      "Estimated BYOK Cost (USD)": point.estimated_byok_cost_usd,
    }));
  }, [data]);

  const topUsageChart = useMemo(() => {
    if (!data?.top_users.length || !data.top_user_usage_series.length) {
      return {
        categories: [] as string[],
        rows: [] as Record<string, string | number>[],
      };
    }

    const selectedUsers = sortedTopUsers
      .slice(0, Math.min(sortedTopUsers.length, USAGE_SERIES_COLORS.length))
      .map((user, index) => ({
        id: user.user_id,
        label: `${index + 1}. ${user.user_email}`,
      }));

    const userIdToCategory = new Map(
      selectedUsers.map((selectedUser) => [selectedUser.id, selectedUser.label])
    );

    const rowsByPeriod = new Map<string, Record<string, string | number>>();

    for (const point of data.top_user_usage_series) {
      const category = userIdToCategory.get(point.user_id);
      if (!category) {
        continue;
      }

      const currentRow = rowsByPeriod.get(point.period_start) ?? {
        Period: point.period_start,
      };

      currentRow[category] = point.message_count;
      rowsByPeriod.set(point.period_start, currentRow);
    }

    const categories = selectedUsers.map((selectedUser) => selectedUser.label);

    const rows = Array.from(rowsByPeriod.entries())
      .sort(
        ([leftPeriod], [rightPeriod]) =>
          new Date(leftPeriod).getTime() - new Date(rightPeriod).getTime()
      )
      .map(([, row]) => {
        const normalized = { ...row };
        for (const category of categories) {
          if (normalized[category] === undefined) {
            normalized[category] = 0;
          }
        }
        return normalized;
      });

    return { categories, rows };
  }, [data, sortedTopUsers]);

  return (
    <CardSection className="mt-6 border-border-02 bg-background-tint-00">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex flex-col">
          <Text headingH3>Executive Analytics</Text>
          <Text mainUiMuted text03 className="pt-1">
            Workspace adoption, AI spending, and heavy users in one place.
          </Text>
          <Text secondaryBody text03 className="pt-1">
            {interval === "week" ? "Weekly" : "Monthly"} cadence • Top{" "}
            {topUsersLimit} users • Sorted by {USER_SORT_LABEL[userSortBy]}.
          </Text>
        </div>
        <Button size="md" secondary onClick={() => refreshDashboardAnalytics()}>
          Refresh
        </Button>
      </div>

      {isLoading ? (
        <div className="h-64 flex flex-col">
          <ThreeDotsLoader />
        </div>
      ) : null}

      {!isLoading && (error || !data) ? (
        <ErrorCallout
          errorTitle="Failed to load executive analytics"
          errorMsg="Please refresh and try again."
        />
      ) : null}

      {!isLoading && data ? (
        <>
          <div className="grid gap-3 pt-5 md:grid-cols-2 xl:grid-cols-5">
            <MetricCard
              title="Tracked AI Cost"
              value={currencyFormatter.format(data.total_llm_cost_usd)}
              subtitle="Tracked StarwoodGPT provider usage"
            />
            <MetricCard
              title="Estimated BYOK Cost"
              value={currencyFormatter.format(data.total_estimated_byok_cost_usd)}
              subtitle="Directional estimate from chat tokens"
              titleTooltip="BYOK means Bring Your Own Key. If your team uses its own model/API keys instead of StarwoodGPT-managed keys, this is the estimated spend for that usage."
            />
            <MetricCard
              title="Assistant Messages"
              value={integerFormatter.format(data.total_messages)}
              subtitle="Responses generated in range"
            />
            <MetricCard
              title="Active Users"
              value={integerFormatter.format(data.total_unique_users)}
              subtitle="Unique users with activity"
            />
            <MetricCard
              title="Positive Feedback"
              value={
                positiveFeedbackRate == null
                  ? "No feedback"
                  : `${positiveFeedbackRate.toFixed(1)}%`
              }
              subtitle={`${integerFormatter.format(data.total_likes)} up / ${integerFormatter.format(data.total_dislikes)} down`}
            />
          </div>

          <div className="grid gap-4 pt-5 xl:grid-cols-2">
            <div className="rounded-12 border border-border-02 bg-background-neutral-00 p-3">
              <Text mainUiAction className="pb-1">
                AI Cost Over Time
              </Text>
              <Text secondaryBody text04>
                {applyBrandingCopy(data.cost_note)}
              </Text>
              <Text secondaryBody text04 className="pt-1">
                {applyBrandingCopy(data.byok_estimation_note)}
              </Text>
              <AreaChartDisplay
                className="mt-2"
                data={costChartData}
                categories={[
                  "Tracked StarwoodGPT Cost (USD)",
                  "Estimated BYOK Cost (USD)",
                ]}
                index="Period"
                colors={COST_SERIES_COLORS}
                yAxisWidth={80}
                yAxisFormatter={(value: number) => currencyFormatter.format(value)}
                xAxisFormatter={(value: string) => formatPeriodLabel(value, interval)}
                allowDecimals={false}
              />
            </div>

            <div className="rounded-12 border border-border-02 bg-background-neutral-00 p-3">
              <Text mainUiAction className="pb-1">
                Top Users Activity
              </Text>
              <Text secondaryBody text04>
                Message volume by top-ranked users ({interval} buckets), ordered by{" "}
                {USER_SORT_LABEL[userSortBy]}.
              </Text>

              {topUsageChart.rows.length > 0 && topUsageChart.categories.length > 0 ? (
                <AreaChartDisplay
                  className="mt-2"
                  data={topUsageChart.rows}
                  categories={topUsageChart.categories}
                  index="Period"
                  colors={USAGE_SERIES_COLORS}
                  stacked={false}
                  yAxisWidth={70}
                  allowDecimals={false}
                  yAxisFormatter={(value: number) => integerFormatter.format(value)}
                  xAxisFormatter={(value: string) =>
                    formatPeriodLabel(value, interval)
                  }
                />
              ) : (
                <div className="h-[350px] flex items-center justify-center rounded-12 border border-border-02 bg-background-tint-00">
                  <Text mainUiMuted text03>
                    No top user trend data in this range.
                  </Text>
                </div>
              )}
            </div>
          </div>

          <div className="pt-5">
            <Text mainUiAction className="pb-1">
              Cost Driver Breakdown
            </Text>
            <Text secondaryBody text04>
              {applyBrandingCopy(data.cost_driver_breakdown.note)}
            </Text>
            <div className="grid gap-3 pt-3 md:grid-cols-2">
              <MetricCard
                title="Chat Tokens in Range"
                value={integerFormatter.format(
                  data.cost_driver_breakdown.total_chat_tokens
                )}
              />
              <MetricCard
                title="Estimated Chat Cost Basis"
                value={currencyFormatter.format(
                  data.cost_driver_breakdown.estimated_chat_cost_basis_usd
                )}
                subtitle="Directional token-based estimate"
              />
            </div>

            <div className="grid gap-4 pt-4 xl:grid-cols-2">
              <div className="rounded-12 border border-border-02 bg-background-neutral-00 p-1">
                <Text mainUiAction className="px-2 pb-2 pt-2">
                  Top User Cost Drivers
                </Text>
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>User</TableHead>
                      <TableHead>Tokens</TableHead>
                      <TableHead>Token Share</TableHead>
                      <TableHead>Estimated Cost</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {data.cost_driver_breakdown.user_drivers.length ? (
                      data.cost_driver_breakdown.user_drivers.map((driver) => (
                        <TableRow key={driver.user_id}>
                          <TableCell>{driver.user_email}</TableCell>
                          <TableCell>
                            {integerFormatter.format(driver.token_count)}
                          </TableCell>
                          <TableCell>
                            {decimalFormatter.format(driver.token_share_percent)}%
                          </TableCell>
                          <TableCell>
                            {currencyFormatter.format(driver.estimated_cost_usd)}
                          </TableCell>
                        </TableRow>
                      ))
                    ) : (
                      <TableRow noHover>
                        <TableCell colSpan={4} className="text-center">
                          <Text mainUiMuted text03>
                            No user cost-driver data in this range.
                          </Text>
                        </TableCell>
                      </TableRow>
                    )}
                  </TableBody>
                </Table>
              </div>

              <div className="rounded-12 border border-border-02 bg-background-neutral-00 p-1">
                <Text mainUiAction className="px-2 pb-2 pt-2">
                  Top Assistant Cost Drivers
                </Text>
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Assistant</TableHead>
                      <TableHead>Tokens</TableHead>
                      <TableHead>Token Share</TableHead>
                      <TableHead>Estimated Cost</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {data.cost_driver_breakdown.assistant_drivers.length ? (
                      data.cost_driver_breakdown.assistant_drivers.map((driver) => (
                        <TableRow
                          key={`${driver.assistant_id ?? "default"}-${driver.assistant_name}`}
                        >
                          <TableCell>{driver.assistant_name}</TableCell>
                          <TableCell>
                            {integerFormatter.format(driver.token_count)}
                          </TableCell>
                          <TableCell>
                            {decimalFormatter.format(driver.token_share_percent)}%
                          </TableCell>
                          <TableCell>
                            {currencyFormatter.format(driver.estimated_cost_usd)}
                          </TableCell>
                        </TableRow>
                      ))
                    ) : (
                      <TableRow noHover>
                        <TableCell colSpan={4} className="text-center">
                          <Text mainUiMuted text03>
                            No assistant cost-driver data in this range.
                          </Text>
                        </TableCell>
                      </TableRow>
                    )}
                  </TableBody>
                </Table>
              </div>
            </div>
          </div>

          <div className="pt-5">
            <Text mainUiAction className="pb-2">
              Top Users
            </Text>
            <div className="rounded-12 border border-border-02 bg-background-neutral-00 p-1">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>#</TableHead>
                    <TableHead>User</TableHead>
                    <TableHead>Messages</TableHead>
                    <TableHead>Tokens</TableHead>
                    <TableHead>Avg / Week</TableHead>
                    <TableHead>Avg / Month</TableHead>
                    <TableHead>Last Login</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {sortedTopUsers.length ? (
                    sortedTopUsers.map((user, index) => (
                      <TableRow key={user.user_id}>
                        <TableCell>{index + 1}</TableCell>
                        <TableCell>{user.user_email}</TableCell>
                        <TableCell>
                          {integerFormatter.format(user.message_count)}
                        </TableCell>
                        <TableCell>{integerFormatter.format(user.token_count)}</TableCell>
                        <TableCell>
                          {decimalFormatter.format(user.average_messages_per_week)}
                        </TableCell>
                        <TableCell>
                          {decimalFormatter.format(user.average_messages_per_month)}
                        </TableCell>
                        <TableCell>{formatLastLogin(user.last_login)}</TableCell>
                      </TableRow>
                    ))
                  ) : (
                    <TableRow noHover>
                      <TableCell colSpan={7} className="text-center">
                        <Text mainUiMuted text03>
                          No user activity in this date range.
                        </Text>
                      </TableCell>
                    </TableRow>
                  )}
                </TableBody>
              </Table>
            </div>
          </div>
        </>
      ) : null}
    </CardSection>
  );
}
