"use client";

import { format } from "date-fns";
import { errorHandlingFetcher } from "@/lib/fetcher";

import { FiDownload, FiDownloadCloud } from "react-icons/fi";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import Button from "@/refresh-components/buttons/Button";
import useSWR from "swr";
import React, { useState } from "react";
import { UsageReport } from "./types";
import { ThreeDotsLoader } from "@/components/Loading";
import Link from "next/link";
import { humanReadableFormat, humanReadableFormatWithTime } from "@/lib/time";
import { ErrorCallout } from "@/components/ErrorCallout";
import { PageSelector } from "@/components/PageSelector";
import Separator from "@/refresh-components/Separator";
import { DateRangePickerValue } from "../../../../../components/dateRangeSelectors/AdminDateRangeSelector";
import Popover from "@/refresh-components/Popover";
import Calendar from "@/refresh-components/Calendar";
import { cn } from "@/lib/utils";
import { Spinner } from "@/components/Spinner";
import { SvgCalendar } from "@opal/icons";
import Text from "@/refresh-components/texts/Text";

function GenerateReportInput({
  onReportGenerated,
  isWaitingForReport,
}: {
  onReportGenerated: () => void;
  isWaitingForReport: boolean;
}) {
  const [dateRange, setDateRange] = useState<DateRangePickerValue | undefined>(
    undefined
  );
  const [isLoading, setIsLoading] = useState(false);

  const [errorOccurred, setErrorOccurred] = useState<Error | null>(null);

  const requestReport = async () => {
    setIsLoading(true);
    setErrorOccurred(null);
    try {
      let period_from: string | null = null;
      let period_to: string | null = null;

      if (dateRange?.selectValue != "allTime" && dateRange?.from) {
        period_from = dateRange?.from?.toISOString();
        period_to = dateRange?.to?.toISOString() ?? new Date().toISOString();
      }

      const res = await fetch("/api/admin/usage-report", {
        method: "POST",
        credentials: "include",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          period_from: period_from,
          period_to: period_to,
        }),
      });

      if (!res.ok) {
        throw Error(`Received an error: ${res.statusText}`);
      }

      // Trigger refresh of the reports list
      onReportGenerated();
    } catch (e) {
      setErrorOccurred(e as Error);
    } finally {
      setIsLoading(false);
    }
  };

  const today = new Date();

  const lastWeek = new Date();
  lastWeek.setDate(today.getDate() - 7);

  const lastMonth = new Date();
  lastMonth.setMonth(today.getMonth() - 1);

  const lastYear = new Date();
  lastYear.setFullYear(today.getFullYear() - 1);

  return (
    <div className="rounded-16 border border-border-02 bg-background-tint-00 p-4 md:p-5">
      <Text headingH3>Generate Usage Reports</Text>
      <Text mainUiMuted text03 className="pt-1 pb-5">
        Generate usage statistics for users in the workspace.
      </Text>
      <div className="grid gap-2 pb-3">
        <Popover>
          <Popover.Trigger asChild>
            <Button
              secondary
              className={cn(
                "w-[300px] justify-start text-left font-normal",
                !dateRange && "text-text-03"
              )}
              leftIcon={SvgCalendar}
            >
              {dateRange?.from ? (
                dateRange.to ? (
                  <>
                    {format(dateRange.from, "LLL dd, y")} -{" "}
                    {format(dateRange.to, "LLL dd, y")}
                  </>
                ) : (
                  format(dateRange.from, "LLL dd, y")
                )
              ) : (
                <span>Pick a date range</span>
              )}
            </Button>
          </Popover.Trigger>
          <Popover.Content align="start">
            <Calendar
              initialFocus
              mode="range"
              defaultMonth={dateRange?.from}
              selected={dateRange}
              onSelect={(range) =>
                range?.from &&
                setDateRange({
                  from: range.from,
                  to: range.to ?? range.from,
                  selectValue: "custom",
                })
              }
              numberOfMonths={2}
              disabled={(date) => date > new Date()}
            />
            <div className="border-t p-3">
              <Button
                tertiary
                className="w-full justify-start"
                onClick={() => {
                  setDateRange({
                    from: lastWeek,
                    to: new Date(),
                    selectValue: "lastWeek",
                  });
                }}
              >
                Last 7 days
              </Button>
              <Button
                tertiary
                className="w-full justify-start"
                onClick={() => {
                  setDateRange({
                    from: lastMonth,
                    to: new Date(),
                    selectValue: "lastMonth",
                  });
                }}
              >
                Last 30 days
              </Button>
              <Button
                tertiary
                className="w-full justify-start"
                onClick={() => {
                  setDateRange({
                    from: lastYear,
                    to: new Date(),
                    selectValue: "lastYear",
                  });
                }}
              >
                Last year
              </Button>
              <Button
                tertiary
                className="w-full justify-start"
                onClick={() => {
                  setDateRange({
                    from: new Date(1970, 0, 1),
                    to: new Date(),
                    selectValue: "allTime",
                  });
                }}
              >
                All time
              </Button>
            </div>
          </Popover.Content>
        </Popover>
      </div>
      <Button
        color={"blue"}
        leftIcon={FiDownloadCloud}
        disabled={isLoading || isWaitingForReport}
        onClick={() => requestReport()}
      >
        {isWaitingForReport ? "Generating..." : "Generate Report"}
      </Button>
      <Text secondaryBody text03 className="pt-1">
        {isWaitingForReport
          ? "A report is currently being generated. Please wait..."
          : 'Report generation runs in the background. Check the "Previous Reports" section below to download when ready.'}
      </Text>
      {errorOccurred && (
        <div className="pt-3">
          <ErrorCallout
            errorTitle="Something went wrong."
            errorMsg={errorOccurred?.toString()}
          />
        </div>
      )}
    </div>
  );
}

const USAGE_REPORT_URL = "/api/admin/usage-report";

function UsageReportsTable({
  refreshTrigger,
  isWaitingForReport,
  onNewReportDetected,
}: {
  refreshTrigger: number;
  isWaitingForReport: boolean;
  onNewReportDetected: () => void;
}) {
  const [page, setPage] = useState(1);
  const NUM_IN_PAGE = 10;
  const [previousReportCount, setPreviousReportCount] = useState<number | null>(
    null
  );

  const {
    data: usageReportsMetadata,
    error: usageReportsError,
    isLoading: usageReportsIsLoading,
    mutate,
  } = useSWR<UsageReport[]>(USAGE_REPORT_URL, errorHandlingFetcher, {
    refreshInterval: isWaitingForReport ? 3000 : 0, // Poll every 3 seconds when waiting
  });

  // Refresh when refreshTrigger changes
  React.useEffect(() => {
    if (refreshTrigger > 0) {
      mutate();
    }
  }, [refreshTrigger, mutate]);

  // Detect when a new report appears
  React.useEffect(() => {
    if (usageReportsMetadata && previousReportCount !== null) {
      if (usageReportsMetadata.length > previousReportCount) {
        onNewReportDetected();
      }
    }
    if (usageReportsMetadata) {
      setPreviousReportCount(usageReportsMetadata.length);
    }
  }, [usageReportsMetadata, previousReportCount, onNewReportDetected]);

  const paginatedReports = usageReportsMetadata
    ? usageReportsMetadata
        .slice(0)
        .reverse()
        .slice(NUM_IN_PAGE * (page - 1), NUM_IN_PAGE * page)
    : [];

  const totalPages = usageReportsMetadata
    ? Math.ceil(usageReportsMetadata.length / NUM_IN_PAGE)
    : 0;

  return (
    <div>
      <Text headingH3 className="pt-6">
        Previous Reports
      </Text>
      {usageReportsIsLoading && !isWaitingForReport ? (
        <div className="flex justify-center w-full pt-4">
          <ThreeDotsLoader />
        </div>
      ) : usageReportsError ? (
        <div className="pt-3">
          <ErrorCallout
            errorTitle="Something went wrong."
            errorMsg={(usageReportsError as Error).toString()}
          />
        </div>
      ) : (
        <div className="pt-3 rounded-16 border border-border-02 bg-background-neutral-00 p-1">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Report</TableHead>
                <TableHead>Period</TableHead>
                <TableHead>Generated By</TableHead>
                <TableHead>Time Generated</TableHead>
                <TableHead>Download</TableHead>
              </TableRow>
            </TableHeader>

            <TableBody>
              {paginatedReports.map((r) => (
                <TableRow key={r.report_name}>
                  <TableCell>
                    {r.report_name.split("_")[1]?.substring(0, 8) ||
                      r.report_name.substring(0, 8)}
                  </TableCell>
                  <TableCell>
                    {r.period_from
                      ? `${humanReadableFormat(
                          r.period_from
                        )} - ${humanReadableFormat(r.period_to!)}`
                      : "All time"}
                  </TableCell>
                  <TableCell>{r.requestor ?? "Auto generated"}</TableCell>
                  <TableCell>
                    {humanReadableFormatWithTime(r.time_created)}
                  </TableCell>
                  <TableCell>
                    <Link
                      href={`/api/admin/usage-report/${r.report_name}`}
                      className="flex justify-center"
                    >
                      <FiDownload color="primary" />
                    </Link>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
          <div className="mt-3 flex">
            <div className="mx-auto">
              <PageSelector
                totalPages={totalPages}
                currentPage={page}
                onPageChange={(newPage) => {
                  setPage(newPage);
                  window.scrollTo({
                    top: 0,
                    left: 0,
                    behavior: "smooth",
                  });
                }}
              />
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export default function UsageReports() {
  const [refreshTrigger, setRefreshTrigger] = useState(0);
  const [isWaitingForReport, setIsWaitingForReport] = useState(false);
  const [timeoutMessage, setTimeoutMessage] = useState<string | null>(null);
  const timeoutRef = React.useRef<NodeJS.Timeout | null>(null);

  const handleReportGenerated = () => {
    setRefreshTrigger((prev) => prev + 1);
    setIsWaitingForReport(true);
    setTimeoutMessage(null);

    // Clear any existing timeout
    if (timeoutRef.current) {
      clearTimeout(timeoutRef.current);
    }

    // Set a 15 second timeout
    timeoutRef.current = setTimeout(() => {
      setIsWaitingForReport(false);
      setTimeoutMessage(
        "Report generation is taking longer than expected. The report will continue generating in the background. Please check back in a few minutes."
      );
      timeoutRef.current = null;
    }, 15000);
  };

  const handleNewReportDetected = () => {
    setIsWaitingForReport(false);
    setTimeoutMessage(null);
    // Clear the timeout if report completed before timeout
    if (timeoutRef.current) {
      clearTimeout(timeoutRef.current);
      timeoutRef.current = null;
    }
  };

  // Cleanup on unmount
  React.useEffect(() => {
    return () => {
      if (timeoutRef.current) {
        clearTimeout(timeoutRef.current);
      }
    };
  }, []);

  return (
    <>
      {isWaitingForReport && <Spinner />}
      <GenerateReportInput
        onReportGenerated={handleReportGenerated}
        isWaitingForReport={isWaitingForReport}
      />
      {timeoutMessage && (
        <div className="p-4 mt-4 rounded-12 border border-status-warning-02 bg-status-warning-01">
          <Text mainUiAction className="text-status-text-warning-05">
            Report Generation In Progress
          </Text>
          <Text secondaryBody className="text-status-text-warning-05 pt-1">
            {timeoutMessage}
          </Text>
        </div>
      )}
      <Separator />
      <UsageReportsTable
        refreshTrigger={refreshTrigger}
        isWaitingForReport={isWaitingForReport}
        onNewReportDetected={handleNewReportDetected}
      />
    </>
  );
}
