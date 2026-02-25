"use client";

import { useMemo, useState } from "react";
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

interface ExecutiveDashboardProps {
  timeRange: DateRangePickerValue;
}

interface MetricCardProps {
  title: string;
  value: string;
  subtitle?: string;
}

const COST_SERIES_COLORS = ["#1D4ED8", "#0F766E"];
const USAGE_SERIES_COLORS = ["#1D4ED8", "#0F766E", "#334155", "#0369A1", "#78350F"];

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

function MetricCard({
  title,
  value,
  subtitle,
}: MetricCardProps) {
  return (
    <div className="rounded-12 border border-border-02 bg-background-neutral-00 p-4">
      <Text secondaryBody text03>
        {title}
      </Text>
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

export function ExecutiveDashboard({ timeRange }: ExecutiveDashboardProps) {
  const [interval, setInterval] = useState<"week" | "month">("week");

  const {
    data,
    isLoading,
    error,
    refreshDashboardAnalytics,
  } = useAdminDashboardAnalytics(timeRange, interval, 10);

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

  const costChartData = useMemo(() => {
    if (!data) {
      return [];
    }

    return data.cost_series.map((point) => ({
      Period: point.period_start,
      "Tracked Onyx Cost (USD)": point.llm_cost_usd,
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

    const selectedUsers = data.top_users.slice(0, 5).map((user, index) => ({
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
  }, [data]);

  return (
    <CardSection className="mt-6 border-border-02 bg-background-tint-00">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex flex-col">
          <Text headingH3>Executive Analytics</Text>
          <Text mainUiMuted text03 className="pt-1">
            Workspace adoption, AI spending, and heavy users in one place.
          </Text>
        </div>
        <div className="flex items-center gap-2">
          <Button
            size="md"
            primary={interval === "week"}
            secondary={interval !== "week"}
            onClick={() => setInterval("week")}
          >
            Weekly
          </Button>
          <Button
            size="md"
            primary={interval === "month"}
            secondary={interval !== "month"}
            onClick={() => setInterval("month")}
          >
            Monthly
          </Button>
          <Button size="md" secondary onClick={() => refreshDashboardAnalytics()}>
            Refresh
          </Button>
        </div>
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
              subtitle="Tracked Onyx provider usage"
            />
            <MetricCard
              title="Estimated BYOK Cost"
              value={currencyFormatter.format(data.total_estimated_byok_cost_usd)}
              subtitle="Directional estimate from chat tokens"
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
                {data.cost_note}
              </Text>
              <Text secondaryBody text04 className="pt-1">
                {data.byok_estimation_note}
              </Text>
              <AreaChartDisplay
                className="mt-2"
                data={costChartData}
                categories={[
                  "Tracked Onyx Cost (USD)",
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
                Message volume by top users ({interval} buckets)
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
                  {data.top_users.length ? (
                    data.top_users.map((user, index) => (
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
