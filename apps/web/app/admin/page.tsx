"use client";

import { AlertTriangle, ArrowLeft, ChevronLeft, ChevronRight, Gauge, History, RefreshCw, RotateCcw, Search, ShieldCheck, Users, X } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { ApiError, getAdminOverview, resetAllQuotas } from "@/lib/api";
import type { AdminOverview } from "@/lib/types";


function formatTokens(value: number) {
  return new Intl.NumberFormat("en-AU", { notation: "compact", maximumFractionDigits: 1 }).format(value);
}

function formatDate(value: string) {
  return new Intl.DateTimeFormat("en-AU", {
    dateStyle: "medium",
    timeStyle: "short"
  }).format(new Date(value));
}

export default function AdminPage() {
  const [overview, setOverview] = useState<AdminOverview | null>(null);
  const [status, setStatus] = useState<"loading" | "ready" | "forbidden" | "anonymous" | "error">("loading");
  const [resetting, setResetting] = useState(false);
  const [confirmingReset, setConfirmingReset] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [searchInput, setSearchInput] = useState("");
  const [searchQuery, setSearchQuery] = useState("");
  const [roleFilter, setRoleFilter] = useState<"all" | "admin" | "standard">("all");
  const [page, setPage] = useState(1);

  const load = useCallback(async () => {
    setRefreshing(true);
    try {
      setOverview(await getAdminOverview({ search: searchQuery, role: roleFilter, page }));
      setStatus("ready");
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) setStatus("anonymous");
      else if (error instanceof ApiError && error.status === 403) setStatus("forbidden");
      else setStatus("error");
    } finally {
      setRefreshing(false);
    }
  }, [page, roleFilter, searchQuery]);

  useEffect(() => {
    void load();
  }, [load]);

  async function resetQuotas() {
    setResetting(true);
    setNotice(null);
    try {
      const result = await resetAllQuotas("Manual reset from administrator console");
      setNotice(`All standard-user quotas reset at ${formatDate(result.effective_at)}.`);
      setConfirmingReset(false);
      await load();
    } catch (error) {
      setNotice(error instanceof ApiError ? error.message : "Quota reset failed.");
    } finally {
      setResetting(false);
    }
  }

  if (status !== "ready" || !overview) {
    return (
      <main className="adminShell adminStateShell">
        <ShieldCheck size={24} />
        <h1>{status === "forbidden" ? "Administrator access required" : status === "anonymous" ? "Sign in required" : status === "error" ? "Administrator console unavailable" : "Loading administrator console"}</h1>
        <p>{status === "forbidden" ? "This account does not have the administrator role." : status === "anonymous" ? "Sign in to Witscraft before opening this page." : status === "error" ? "The server could not load administrative usage data." : "Checking your role and current quota period."}</p>
        <div className="adminStateActions">
          <Link className="cmdButton" href="/"><ArrowLeft size={14} /> Interactive novel</Link>
          {status === "error" && <button className="cmdButton" type="button" onClick={() => void load()}><RefreshCw size={14} /> Retry</button>}
        </div>
      </main>
    );
  }

  return (
    <main className="adminShell">
      <header className="adminHeader">
        <div>
          <span className="adminEyebrow"><ShieldCheck size={14} /> Witscraft administration</span>
          <h1>Usage governance</h1>
          <p>Review weekly AI token consumption and manage the global quota window.</p>
        </div>
        <div className="adminHeaderActions">
          <button className="plainIcon" type="button" aria-label="Refresh usage" title="Refresh usage" disabled={refreshing} onClick={() => void load()}><RefreshCw className={refreshing ? "spinIcon" : undefined} size={16} /></button>
          <Link className="cmdButton" href="/"><ArrowLeft size={14} /> Interactive novel</Link>
        </div>
      </header>

      <section className="adminMetrics" aria-label="Usage summary">
        <article><Users size={18} /><span><b>{overview.total_users}</b><small>Accounts</small></span></article>
        <article><ShieldCheck size={18} /><span><b>{overview.administrator_count}</b><small>Administrators</small></span></article>
        <article><Gauge size={18} /><span><b>{formatTokens(overview.total_used_tokens)}</b><small>Tokens this period</small></span></article>
        <article><RotateCcw size={18} /><span><b>{formatDate(overview.resets_at)}</b><small>Automatic reset</small></span></article>
      </section>

      <section className="adminQuotaPolicy">
        <div>
          <h2>Weekly standard-user quota</h2>
          <p>{overview.weekly_token_quota.toLocaleString("en-AU")} tokens per user. Administrators are exempt. Current window began {formatDate(overview.period_started_at)}.</p>
        </div>
        {!confirmingReset ? (
          <button className="cmdButton dangerAction" type="button" onClick={() => setConfirmingReset(true)}><RotateCcw size={14} /> Reset all quotas</button>
        ) : (
          <div className="adminResetConfirm">
            <AlertTriangle size={16} />
            <span><b>Reset every standard user now?</b><small>Usage history is retained; a new global quota window starts immediately.</small></span>
            <button className="cmdButton dangerAction" type="button" disabled={resetting} onClick={() => void resetQuotas()}>{resetting ? <RefreshCw className="spinIcon" size={14} /> : <RotateCcw size={14} />} Confirm reset</button>
            <button className="plainIcon adminResetCancel" type="button" aria-label="Cancel reset" title="Cancel reset" onClick={() => setConfirmingReset(false)} disabled={resetting}><X size={14} /></button>
          </div>
        )}
      </section>

      {notice && <div className="adminNotice" role="status">{notice}</div>}

      <section className="adminAuditSection">
        <header><span><History size={15} /><h2>Quota reset history</h2></span><small>Latest 10 events</small></header>
        {overview.reset_events.length ? (
          <ol className="adminAuditList">
            {overview.reset_events.map((event) => (
              <li key={event.id}>
                <time dateTime={event.effective_at}>{formatDate(event.effective_at)}</time>
                <span><b>{event.administrator_name || event.administrator_email || "Deleted administrator"}</b><small>{event.reason}</small></span>
              </li>
            ))}
          </ol>
        ) : <p className="adminEmptyState">No manual quota resets recorded.</p>}
      </section>

      <section className="adminUserSection">
        <header><h2>Account usage</h2><span>{overview.filtered_users} of {overview.total_users} accounts</span></header>
        <div className="adminUserToolbar">
          <form className="adminSearchForm" onSubmit={(event) => { event.preventDefault(); setPage(1); setSearchQuery(searchInput.trim()); }}>
            <Search size={14} />
            <input aria-label="Search accounts" placeholder="Search name or email" value={searchInput} onChange={(event) => setSearchInput(event.target.value)} maxLength={120} />
            {searchInput && <button className="plainIcon" type="button" aria-label="Clear search" title="Clear search" onClick={() => { setSearchInput(""); setSearchQuery(""); setPage(1); }}><X size={13} /></button>}
            <button className="cmdButton" type="submit">Search</button>
          </form>
          <div className="adminRoleFilter" role="group" aria-label="Filter accounts by role">
            {(["all", "admin", "standard"] as const).map((role) => (
              <button key={role} type="button" aria-pressed={roleFilter === role} onClick={() => { setRoleFilter(role); setPage(1); }}>{role === "all" ? "All" : role === "admin" ? "Administrators" : "Standard"}</button>
            ))}
          </div>
        </div>
        <div className="adminTableWrap">
          <table className="adminTable">
            <thead><tr><th>Account</th><th>Role</th><th>Usage</th><th>Tokens</th><th>Resets</th></tr></thead>
            <tbody>
              {!overview.users.length && <tr className="adminEmptyRow"><td colSpan={5}>No accounts match the current filters.</td></tr>}
              {overview.users.map((user) => (
                <tr key={user.id}>
                  <td className="adminAccountCell" data-label="Account"><b>{user.display_name}</b><small>{user.email}</small></td>
                  <td className="adminRoleCell" data-label="Role"><span className={`roleBadge ${user.is_admin ? "admin" : "standard"}`}>{user.is_admin ? "Administrator" : "Standard"}</span></td>
                  <td className="adminUsageCell" data-label="Usage">
                    {user.unlimited ? <span className="unlimitedLabel">Unlimited</span> : <div className={`adminUsage ${user.soft_limit_reached ? "warning" : ""}`}><div><span style={{ width: `${Math.min(100, user.percentage_used)}%` }} /></div><small>{user.percentage_used.toFixed(1)}%</small></div>}
                  </td>
                  <td className="adminTokenCell" data-label="Tokens"><b>{formatTokens(user.used_tokens)}</b><small>{user.limit_tokens === null ? "No limit" : `of ${formatTokens(user.limit_tokens)}`}</small></td>
                  <td className="adminResetCell" data-label="Resets">{formatDate(user.resets_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <footer className="adminPagination">
          <button className="plainIcon" type="button" aria-label="Previous page" title="Previous page" disabled={overview.page <= 1 || refreshing} onClick={() => setPage((value) => Math.max(1, value - 1))}><ChevronLeft size={15} /></button>
          <span>Page {overview.page} of {overview.total_pages}</span>
          <button className="plainIcon" type="button" aria-label="Next page" title="Next page" disabled={overview.page >= overview.total_pages || refreshing} onClick={() => setPage((value) => value + 1)}><ChevronRight size={15} /></button>
        </footer>
      </section>
    </main>
  );
}
