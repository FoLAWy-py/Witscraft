import type { QuotaUsage } from "@/lib/types";

type UiLanguage = "zh-CN" | "en";

function uiText(language: UiLanguage, zh: string, en: string) {
  return language === "zh-CN" ? zh : en;
}

export function QuotaMeter({
  quota,
  uiLanguage,
  compact = false
}: {
  quota: QuotaUsage | null;
  uiLanguage: UiLanguage;
  compact?: boolean;
}) {
  if (!quota) {
    return (
      <div className={`quotaMeter ${compact ? "compact" : ""} loading`}>
        <span>{uiText(uiLanguage, "额度读取中", "Loading quota")}</span>
      </div>
    );
  }
  const resetLabel = new Intl.DateTimeFormat(uiLanguage === "zh-CN" ? "zh-CN" : "en-AU", {
    weekday: "short",
    hour: "2-digit",
    minute: "2-digit"
  }).format(new Date(quota.resets_at));
  const percent = quota.unlimited ? 0 : Math.min(100, quota.percentage_used);
  const number = new Intl.NumberFormat(uiLanguage === "zh-CN" ? "zh-CN" : "en-AU", {
    notation: compact ? "compact" : "standard",
    maximumFractionDigits: 1
  });
  const hasStoryQuota = Boolean(quota.story_id)
    && quota.story_used_tokens !== null
    && quota.story_used_tokens !== undefined;
  return (
    <div
      className={`quotaMeter ${compact ? "compact" : ""} ${quota.soft_limit_reached ? "warning" : ""}`}
      title={`${uiText(uiLanguage, "重置时间", "Resets")} ${resetLabel}`}
    >
      <div className="quotaMeterLabel">
        <span>{quota.unlimited ? uiText(uiLanguage, "管理员不限额", "Admin unlimited") : `${quota.percentage_used.toFixed(1)}%`}</span>
        {!compact && <small>{uiText(uiLanguage, "重置", "Resets")} {resetLabel}</small>}
      </div>
      {!quota.unlimited && (
        <div className="quotaTrack" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={percent}>
          <span style={{ width: `${percent}%` }} />
        </div>
      )}
      {!compact && quota.soft_limit_reached && !quota.unlimited && (
        <p className="quotaWarning">
          {uiText(uiLanguage, `已达到 ${quota.soft_limit_percentage}% 提醒线，请留意剩余额度。`, `${quota.soft_limit_percentage}% warning threshold reached. Monitor the remaining allowance.`)}
        </p>
      )}
      {!compact && (
        <div className="quotaNumbers">
          <span><b>{number.format(quota.used_tokens)}</b><small>{uiText(uiLanguage, "已用 tokens", "tokens used")}</small></span>
          <span><b>{quota.limit_tokens === null ? "∞" : number.format(quota.limit_tokens)}</b><small>{uiText(uiLanguage, "周额度", "weekly limit")}</small></span>
          <span><b>{quota.remaining_tokens === null ? "∞" : number.format(quota.remaining_tokens)}</b><small>{uiText(uiLanguage, "剩余", "remaining")}</small></span>
          {hasStoryQuota && <span><b>{number.format(quota.story_used_tokens ?? 0)}</b><small>{uiText(uiLanguage, `本小说已用 · ${(quota.story_percentage_used ?? 0).toFixed(1)}%`, `current novel · ${(quota.story_percentage_used ?? 0).toFixed(1)}%`)}</small></span>}
          {hasStoryQuota && <span><b>{quota.story_limit_tokens === null ? "∞" : number.format(quota.story_limit_tokens ?? 0)}</b><small>{uiText(uiLanguage, "小说周额度", "novel weekly limit")}</small></span>}
          {hasStoryQuota && <span><b>{quota.story_remaining_tokens === null ? "∞" : number.format(quota.story_remaining_tokens ?? 0)}</b><small>{uiText(uiLanguage, "小说剩余", "novel remaining")}</small></span>}
        </div>
      )}
    </div>
  );
}
