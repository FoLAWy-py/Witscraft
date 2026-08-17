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
  const percent = quota.unlimited ? 0 : Math.min(100, quota.percentage_used);
  return (
    <div
      className={`quotaMeter ${compact ? "compact" : ""} ${quota.soft_limit_reached ? "warning" : ""}`}
    >
      <div className="quotaMeterLabel">
        <span>{quota.unlimited ? uiText(uiLanguage, "管理员不限额", "Admin unlimited") : `${quota.percentage_used.toFixed(1)}%`}</span>
      </div>
      {!quota.unlimited && (
        <div className="quotaTrack" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={percent}>
          <span style={{ width: `${percent}%` }} />
        </div>
      )}
      {!compact && quota.soft_limit_reached && !quota.unlimited && (
        <p className="quotaWarning">
          {uiText(uiLanguage, "本周使用率较高，请留意进度。", "Weekly usage is high; monitor the percentage.")}
        </p>
      )}
    </div>
  );
}
