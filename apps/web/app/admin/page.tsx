"use client";

import { AlertTriangle, ArrowLeft, Gauge, RefreshCw, RotateCcw, ShieldCheck, Users } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { ApiError, getAdminOverview, getCurrentUser, resetAllQuotas } from "@/lib/api";
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

  const load = useCallback(async () => {
    setStatus("loading");
    try {
      const { user } = await getCurrentUser();
      if (!user.is_admin) {
        setStatus("forbidden");
        return;
      }
      setOverview(await getAdminOverview());
      setStatus("ready");
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) setStatus("anonymous");
      else if (error instanceof ApiError && error.status === 403) setStatus("forbidden");
      else setStatus("error");
    }
  }, []);

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
        <p>{status === "forbidden" ? "This account does not have the administrator role." : status === "anonymous" ? "Sign in through the Witscraft workspace before opening this page." : status === "error" ? "The server could not load administrative usage data." : "Checking your role and current quota period."}</p>
        <div className="adminStateActions">
          <Link className="cmdButton" href="/"><ArrowLeft size={14} /> Workspace</Link>
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
          <button className="plainIcon" type="button" aria-label="Refresh usage" title="Refresh usage" onClick={() => void load()}><RefreshCw size={16} /></button>
          <Link className="cmdButton" href="/"><ArrowLeft size={14} /> Workspace</Link>
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
            <button className="plainIcon" type="button" aria-label="Cancel reset" onClick={() => setConfirmingReset(false)} disabled={resetting}>×</button>
          </div>
        )}
      </section>

      {notice && <div className="adminNotice" role="status">{notice}</div>}

      <section className="adminUserSection">
        <header><h2>Account usage</h2><span>{overview.users.length} records</span></header>
        <div className="adminTableWrap">
          <table className="adminTable">
            <thead><tr><th>Account</th><th>Role</th><th>Usage</th><th>Tokens</th><th>Resets</th></tr></thead>
            <tbody>
              {overview.users.map((user) => (
                <tr key={user.id}>
                  <td><b>{user.display_name}</b><small>{user.email}</small></td>
                  <td><span className={`roleBadge ${user.is_admin ? "admin" : "standard"}`}>{user.is_admin ? "Administrator" : "Standard"}</span></td>
                  <td>
                    {user.unlimited ? <span className="unlimitedLabel">Unlimited</span> : <div className="adminUsage"><div><span style={{ width: `${Math.min(100, user.percentage_used)}%` }} /></div><small>{user.percentage_used.toFixed(1)}%</small></div>}
                  </td>
                  <td><b>{formatTokens(user.used_tokens)}</b><small>{user.limit_tokens === null ? "No limit" : `of ${formatTokens(user.limit_tokens)}`}</small></td>
                  <td>{formatDate(user.resets_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </main>
  );
}
