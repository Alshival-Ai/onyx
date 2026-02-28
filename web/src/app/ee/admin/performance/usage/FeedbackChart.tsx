import { ThreeDotsLoader } from "@/components/Loading";
import { getDatesList, useQueryAnalytics } from "../lib";

import { DateRangePickerValue } from "@/components/dateRangeSelectors/AdminDateRangeSelector";
import CardSection from "@/components/admin/CardSection";
import { AreaChartDisplay } from "@/components/ui/areaChart";
import Text from "@/refresh-components/texts/Text";
import { ErrorCallout } from "@/components/ErrorCallout";

export function FeedbackChart({
  timeRange,
}: {
  timeRange: DateRangePickerValue;
}) {
  const {
    data: queryAnalyticsData,
    isLoading: isQueryAnalyticsLoading,
    error: queryAnalyticsError,
  } = useQueryAnalytics(timeRange);

  let chart;
  if (isQueryAnalyticsLoading) {
    chart = (
      <div className="h-80 flex flex-col">
        <ThreeDotsLoader />
      </div>
    );
  } else if (
    !queryAnalyticsData ||
    queryAnalyticsData[0] === undefined ||
    queryAnalyticsError
  ) {
    chart = (
      <div className="pt-4">
        <ErrorCallout
          errorTitle="Failed to load feedback trends"
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

    chart = (
      <AreaChartDisplay
        className="mt-4"
        data={dateRange.map((dateStr) => {
          const queryAnalyticsForDate = dateToQueryAnalytics.get(dateStr);
          return {
            Day: dateStr,
            "Positive Feedback": queryAnalyticsForDate?.total_likes || 0,
            "Negative Feedback": queryAnalyticsForDate?.total_dislikes || 0,
          };
        })}
        categories={["Positive Feedback", "Negative Feedback"]}
        index="Day"
        colors={["#0F766E", "#9F1239"]}
        yAxisWidth={60}
      />
    );
  }

  return (
    <CardSection className="mt-6 border-border-02 bg-background-tint-00">
      <Text headingH3>Feedback</Text>
      <Text mainUiMuted text03 className="pt-1">
        Daily positive vs negative responses.
      </Text>
      <div className="pt-2">{chart}</div>
    </CardSection>
  );
}
