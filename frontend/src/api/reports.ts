import { api } from "./client";
import type { HistoryPoint, HistoryStats } from "./devices";

export type ReportType = "operation" | "energy" | "availability" | "changes";
export type ReportFormat = "pdf" | "csv";
export type Period = "last_day" | "last_week" | "last_month";

export type ReportParams = {
  report_type: ReportType;
  device_ids: string[];
  from: string;
  to: string;
  resolution?: "auto" | "raw" | "1h" | "1d";
  features?: string[];
};

export type ReportSeries = {
  feature: string;
  property: string;
  label: string;
  unit: string | null;
  counter: boolean;
  points: HistoryPoint[];
  stats: (HistoryStats & { delta?: number | null }) | null;
  markers: { ts: string; type: string; label: string }[];
};

export type ReportDevice = {
  id: string;
  name: string;
  model: string | null;
  location: string | null;
  availability_pct: number;
  energy_available?: boolean | null;
  series: ReportSeries[];
  offline?: { from: string; to: string; seconds: number }[];
  alerts?: { type: string; severity: string; message: string; opened_at: string; closed_at: string | null }[];
  commands?: { created_at: string; feature: string; command: string; value_before: Record<string, unknown> | null; value_after: Record<string, unknown> | null; status: string; user: string | null; acted_as_operator: boolean }[];
};

export type ReportData = {
  report_type: ReportType;
  tenant: { id: string; name: string; timezone: string; header_text: string | null };
  from: string;
  to: string;
  resolution: "raw" | "1h" | "1d";
  generated_at: string;
  devices: ReportDevice[];
  total_points: number;
};

export type ReportFile = {
  id: string;
  report_type: ReportType;
  format: ReportFormat;
  status: "pending" | "done" | "failed";
  error: string | null;
  params: ReportParams;
  size_bytes: number | null;
  filename: string;
  schedule_id: string | null;
  schedule_name: string | null;
  requested_by: string | null;
  created_at: string;
  finished_at: string | null;
  expires_at: string;
};

export type ReportSchedule = {
  id: string;
  name: string;
  report_type: ReportType;
  device_ids: string[];
  features: string[];
  period: Period;
  resolution: string;
  format: ReportFormat;
  recipients: string[];
  cron: string;
  enabled: boolean;
  last_run_at: string | null;
  created_at: string;
};

export const reportsApi = {
  preview: (tid: string, body: ReportParams) => api<ReportData>(`/tenants/${tid}/reports/preview`, { method: "POST", body }),
  requestFile: (tid: string, body: ReportParams & { format: ReportFormat }) =>
    api<{ job_id: string; file_id: string }>(`/tenants/${tid}/reports/jobs`, { method: "POST", body }),
  files: (tid: string) => api<{ results: ReportFile[] }>(`/tenants/${tid}/reports/files`),
  file: (tid: string, id: string) => api<ReportFile>(`/tenants/${tid}/reports/files/${id}`),
  deleteFile: (tid: string, id: string) => api<void>(`/tenants/${tid}/reports/files/${id}`, { method: "DELETE" }),
  downloadUrl: (tid: string, id: string) => `/api/v1/tenants/${tid}/reports/files/${id}/download`,
  schedules: (tid: string) => api<{ results: ReportSchedule[] }>(`/tenants/${tid}/report-schedules`),
  createSchedule: (tid: string, body: Omit<ReportSchedule, "id" | "last_run_at" | "created_at">) =>
    api<ReportSchedule>(`/tenants/${tid}/report-schedules`, { method: "POST", body }),
  updateSchedule: (tid: string, id: string, body: Partial<ReportSchedule>) =>
    api<ReportSchedule>(`/tenants/${tid}/report-schedules/${id}`, { method: "PATCH", body }),
  deleteSchedule: (tid: string, id: string) => api<void>(`/tenants/${tid}/report-schedules/${id}`, { method: "DELETE" }),
  runSchedule: (tid: string, id: string) => api<{ job_id: string; file_id: string }>(`/tenants/${tid}/report-schedules/${id}`, { method: "POST", body: {} }),
};
