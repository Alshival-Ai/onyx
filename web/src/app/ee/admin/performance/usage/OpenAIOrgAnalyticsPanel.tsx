"use client";

import { useMemo } from "react";
import CardSection from "@/components/admin/CardSection";
import { DateRangePickerValue } from "@/components/dateRangeSelectors/AdminDateRangeSelector";
import { useOpenAIOrgAnalytics } from "@/app/ee/admin/performance/lib";
import { ThreeDotsLoader } from "@/components/Loading";
import { ErrorCallout } from "@/components/ErrorCallout";
import { AreaChartDisplay } from "@/components/ui/areaChart";
import Text from "@/refresh-components/texts/Text";
import Button from "@/refresh-components/buttons/Button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

interface OpenAIOrgAnalyticsPanelProps {
  timeRange: DateRangePickerValue;
}

const currencyFormatter = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

const integerFormatter = new Intl.NumberFormat("en-US", {
  notation: "standard",
  maximumFractionDigits: 0,
});

function formatPeriodLabel(periodStart: string) {
  return new Date(periodStart).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
  });
}

function formatCapabilityMetric(value: number, metricLabel: string) {
  const roundedValue = Math.round(value);

  if (metricLabel === "Bytes") {
    return `${integerFormatter.format(roundedValue)} B`;
  }
  if (metricLabel === "Seconds") {
    return `${integerFormatter.format(roundedValue)} s`;
  }

  return integerFormatter.format(roundedValue);
}

export function OpenAIOrgAnalyticsPanel({
  timeRange,
}: OpenAIOrgAnalyticsPanelProps) {
  const { data, isLoading, error, refreshOpenAIOrgAnalytics } =
    useOpenAIOrgAnalytics(timeRange);

  const spendChartData = useMemo(() => {
    if (!data?.enabled) {
      return [];
    }

    return data.spend_series.map((point) => ({
      Period: point.period_start,
      "OpenAI Spend (USD)": point.cost_usd,
    }));
  }, [data]);

  return (
    <CardSection className="mt-6 border-border-02 bg-background-tint-00">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex flex-col">
          <Text headingH3>OpenAI Organization Analytics</Text>
          <Text mainUiMuted text03 className="pt-1">
            Live cost and capability usage from OpenAI org-level analytics APIs.
          </Text>
        </div>
        <Button size="md" secondary onClick={() => refreshOpenAIOrgAnalytics()}>
          Refresh
        </Button>
      </div>

      {isLoading ? (
        <div className="h-48 flex flex-col">
          <ThreeDotsLoader />
        </div>
      ) : null}

      {!isLoading && error ? (
        <ErrorCallout
          errorTitle="Failed to load OpenAI org analytics"
          errorMsg="Verify OPENAI_ORG_ADMIN_KEY, org permissions, and connectivity to api.openai.com."
        />
      ) : null}

      {!isLoading && data && !data.enabled ? (
        <div className="rounded-12 border border-border-02 bg-background-neutral-00 p-4">
          <Text secondaryBody text03>
            {data.note}
          </Text>
        </div>
      ) : null}

      {!isLoading && data?.enabled ? (
        <>
          <div className="grid gap-3 pt-5 md:grid-cols-3">
            <div className="rounded-12 border border-border-02 bg-background-neutral-00 p-4">
              <Text secondaryBody text03>
                Total Spend
              </Text>
              <Text headingH3 className="pt-2">
                {currencyFormatter.format(data.total_spend_usd)}
              </Text>
            </div>
            <div className="rounded-12 border border-border-02 bg-background-neutral-00 p-4">
              <Text secondaryBody text03>
                Total Tokens
              </Text>
              <Text headingH3 className="pt-2">
                {integerFormatter.format(data.total_tokens)}
              </Text>
            </div>
            <div className="rounded-12 border border-border-02 bg-background-neutral-00 p-4">
              <Text secondaryBody text03>
                Total Requests
              </Text>
              <Text headingH3 className="pt-2">
                {integerFormatter.format(data.total_requests)}
              </Text>
            </div>
          </div>

          <div className="rounded-12 border border-border-02 bg-background-neutral-00 p-3 mt-4">
            <Text mainUiAction className="pb-1">
              OpenAI Spend Over Time
            </Text>
            <Text secondaryBody text04>
              {data.note}
            </Text>
            <AreaChartDisplay
              className="mt-2"
              data={spendChartData}
              categories={["OpenAI Spend (USD)"]}
              index="Period"
              colors={["#1D4ED8"]}
              yAxisWidth={80}
              yAxisFormatter={(value: number) => currencyFormatter.format(value)}
              xAxisFormatter={(value: string) => formatPeriodLabel(value)}
              allowDecimals={false}
            />
          </div>

          <div className="rounded-12 border border-border-02 bg-background-neutral-00 p-3 mt-4">
            <Text mainUiAction className="pb-2">
              API Capabilities
            </Text>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Capability</TableHead>
                  <TableHead>Requests</TableHead>
                  <TableHead>Primary Metric</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.capabilities.map((capability) => (
                  <TableRow key={capability.key}>
                    <TableCell>{capability.label}</TableCell>
                    <TableCell>
                      {integerFormatter.format(capability.total_requests)}
                    </TableCell>
                    <TableCell>
                      {formatCapabilityMetric(
                        capability.total_metric_value,
                        capability.metric_label
                      )}{" "}
                      ({capability.metric_label})
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        </>
      ) : null}
    </CardSection>
  );
}
