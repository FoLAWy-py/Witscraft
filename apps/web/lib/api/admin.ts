import type {
  AdminOverview,
  QuotaPolicyUpdateResponse,
  QuotaResetResponse,
  QuotaUsage
} from "../types";
import { API_BASE_URL, requestJson } from "./core";

export async function getMyQuota(): Promise<QuotaUsage> {
  return requestJson<QuotaUsage>(`${API_BASE_URL}/api/quota/me`, { cache: "no-store" });
}

export async function getAdminOverview(options: {
  search?: string;
  role?: "all" | "admin" | "standard";
  page?: number;
  pageSize?: number;
} = {}): Promise<AdminOverview> {
  const params = new URLSearchParams({
    search: options.search ?? "",
    role: options.role ?? "all",
    page: String(options.page ?? 1),
    page_size: String(options.pageSize ?? 25)
  });
  return requestJson<AdminOverview>(`${API_BASE_URL}/api/admin/overview?${params}`, {
    cache: "no-store"
  });
}

export async function resetAllQuotas(reason: string): Promise<QuotaResetResponse> {
  return requestJson<QuotaResetResponse>(`${API_BASE_URL}/api/admin/quota/reset-all`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ reason })
  });
}

export async function updateQuotaPolicy(weeklyTokenQuota: number, reason: string): Promise<QuotaPolicyUpdateResponse> {
  return requestJson<QuotaPolicyUpdateResponse>(`${API_BASE_URL}/api/admin/quota/policy`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ weekly_token_quota: weeklyTokenQuota, reason })
  });
}
