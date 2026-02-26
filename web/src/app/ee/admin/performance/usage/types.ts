import { Feedback, SessionType } from "@/lib/types";

export interface QueryAnalytics {
  total_queries: number;
  total_likes: number;
  total_dislikes: number;
  date: string;
}

export interface UserAnalytics {
  total_active_users: number;
  date: string;
}

export interface OnyxBotAnalytics {
  total_queries: number;
  auto_resolved: number;
  date: string;
}

export interface DashboardCostSeriesPoint {
  period_start: string;
  llm_cost_usd: number;
  estimated_byok_cost_usd: number;
}

export interface DashboardTopUser {
  user_id: string;
  user_email: string;
  message_count: number;
  token_count: number;
  last_login: string | null;
  average_messages_per_week: number;
  average_messages_per_month: number;
}

export interface DashboardUserUsagePoint {
  period_start: string;
  user_id: string;
  user_email: string;
  message_count: number;
}

export interface AdminDashboardAnalytics {
  total_messages: number;
  total_unique_users: number;
  total_likes: number;
  total_dislikes: number;
  total_llm_cost_usd: number;
  total_estimated_byok_cost_usd: number;
  cost_series: DashboardCostSeriesPoint[];
  top_users: DashboardTopUser[];
  top_user_usage_series: DashboardUserUsagePoint[];
  selected_interval: "week" | "month";
  cost_note: string;
  byok_estimation_note: string;
}

export interface OpenAIOrgSpendPoint {
  period_start: string;
  cost_usd: number;
}

export interface OpenAIOrgCapabilitySeriesPoint {
  period_start: string;
  request_count: number;
  metric_value: number;
}

export interface OpenAIOrgCapability {
  key: string;
  label: string;
  endpoint: string;
  metric_key: string;
  metric_label: string;
  total_requests: number;
  total_metric_value: number;
  series: OpenAIOrgCapabilitySeriesPoint[];
}

export interface OpenAIOrgAnalytics {
  enabled: boolean;
  period_start: string;
  period_end: string;
  total_spend_usd: number;
  total_tokens: number;
  total_requests: number;
  spend_series: OpenAIOrgSpendPoint[];
  capabilities: OpenAIOrgCapability[];
  note: string;
}

export interface AbridgedSearchDoc {
  document_id: string;
  semantic_identifier: string;
  link: string | null;
}

export interface MessageSnapshot {
  id: number;
  message: string;
  message_type: "user" | "assistant";
  documents: AbridgedSearchDoc[];
  feedback_type: Feedback | null;
  feedback_text: string | null;
  time_created: string;
}

export interface ChatSessionSnapshot {
  id: number;
  user_email: string | null;
  name: string | null;
  messages: MessageSnapshot[];
  assistant_id: number | null;
  assistant_name: string | null;
  time_created: string;
  flow_type: SessionType;
}

export interface ChatSessionMinimal {
  id: number;
  user_email: string | null;
  name: string | null;
  first_user_message: string;
  first_ai_message: string;
  assistant_id: number | null;
  assistant_name: string | null;
  time_created: string;
  feedback_type: Feedback | "mixed" | null;
  flow_type: SessionType;
  conversation_length: number;
}

export interface UsageReport {
  report_name: string;
  requestor: string | null;
  time_created: string;
  period_from: string | null;
  period_to: string | null;
}
