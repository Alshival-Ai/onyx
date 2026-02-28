"use client";

import { DateRangePickerValue } from "@/components/dateRangeSelectors/AdminDateRangeSelector";
import { getDatesList, useQueryAnalytics, useUserAnalytics } from "../lib";
import { ThreeDotsLoader } from "@/components/Loading";
import { AreaChartDisplay } from "@/components/ui/areaChart";
import CardSection from "@/components/admin/CardSection";
import Text from "@/refresh-components/texts/Text";
import { ErrorCallout } from "@/components/ErrorCallout";

export function QueryPerformanceChart({
  timeRange,
}: {
  timeRange: DateRangePickerValue;
}) {
  const {
    data: queryAnalyticsData,
    isLoading: isQueryAnalyticsLoading,
    error: queryAnalyticsError,
  } = useQueryAnalytics(timeRange);
  const {
    data: userAnalyticsData,
    isLoading: isUserAnalyticsLoading,
    error: userAnalyticsError,
  } = useUserAnalytics(timeRange);

  let chart;
  if (isQueryAnalyticsLoading || isUserAnalyticsLoading) {
    chart = (
      <div className="h-80 flex flex-col">
        <ThreeDotsLoader />
      </div>
    );
  } else if (
    !queryAnalyticsData ||
    queryAnalyticsData[0] === undefined ||
    !userAnalyticsData ||
    queryAnalyticsError ||
    userAnalyticsError
  ) {
    chart = (
      <div className="pt-4">
        <ErrorCallout
          errorTitle="Failed to load usage trends"
          errorMsg="Please refresh and try again."
        />
      </div>
    );
  } else {
    const initialDate = timeRange.from || new Date(queryAnalyticsData[0].date);
    const dateRange = getDatesList(initialDate);

    const dateToQueryAnalytics = new Map(
      queryAnalyticsData.map((queryAnalyticsEntry) => [
        queryAnalyticsEntry.date,
        queryAnalyticsEntry,
      ])
    );
    const dateToUserAnalytics = new Map(
      userAnalyticsData.map((userAnalyticsEntry) => [
        userAnalyticsEntry.date,
        userAnalyticsEntry,
      ])
    );

    chart = (
      <AreaChartDisplay
        className="mt-4"
        stacked={false}
        data={dateRange.map((dateStr) => {
          const queryAnalyticsForDate = dateToQueryAnalytics.get(dateStr);
          const userAnalyticsForDate = dateToUserAnalytics.get(dateStr);
          return {
            Day: dateStr,
            Queries: queryAnalyticsForDate?.total_queries || 0,
            "Unique Users": userAnalyticsForDate?.total_active_users || 0,
          };
        })}
        categories={["Queries", "Unique Users"]}
        index="Day"
        colors={["#1D4ED8", "#0F766E"]}
        yAxisFormatter={(number: number) =>
          new Intl.NumberFormat("en-US", {
            notation: "standard",
            maximumFractionDigits: 0,
          }).format(number)
        }
        xAxisFormatter={(dateStr: string) => {
          const date = new Date(dateStr);
          return date.toLocaleDateString("en-US", {
            month: "short",
            day: "numeric",
          });
        }}
        yAxisWidth={60}
        allowDecimals={false}
      />
    );
  }

  return (
    <CardSection className="mt-6 border-border-02 bg-background-tint-00">
      <Text headingH3>Usage</Text>
      <Text mainUiMuted text03 className="pt-1">
        Daily query volume and active users.
      </Text>
      <div className="pt-2">{chart}</div>
    </CardSection>
  );
}
