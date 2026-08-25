"use client";

import {
  AlertTriangle,
  Check,
  CheckCircle2,
  CircleDashed,
  Cpu,
  Download,
  Gauge,
  GitFork,
  Globe2,
  KeyRound,
  LogOut,
  MonitorSmartphone,
  RefreshCw,
  Route,
  Settings2,
  ShieldCheck,
  Trash2,
  UserRound,
  X
} from "lucide-react";
import { useState } from "react";
import type {
  AuthSessionSummary,
  AuthUser,
  ModelOption,
  ModelRouteChange,
  ProvidersResponse,
  QuotaUsage,
  StoryPurpose,
  UserPreference
} from "@/lib/types";
import { QuotaMeter } from "./quota-meter";
import {
  modelRoleText,
  preferenceFields,
  preferenceFieldsEn,
  purposeRoutesById,
  purposeRoutesZh,
  uiText,
  type UiLanguage
} from "./workspace-config";
import { EmptyState, Panel, formatStoryUpdated } from "./workspace-ui";

export function SettingsView({
  uiLanguage,
  onUiLanguageChange,
  authUser,
  quota,
  authSessions,
  loadingAuthSessions,
  revokingSessionId,
  confirmRevokeSessionId,
  sessionError,
  exportingAccount,
  deletingAccount,
  accountActionError,
  models,
  providers,
  selectedPurpose,
  routeModels,
  routeDirty,
  savingRoutes,
  routeNotice,
  routeHistory,
  routeError,
  checkingModelId,
  modelHealthNotice,
  modelHealthError,
  userPreferences,
  preferenceDirty,
  savingPreferences,
  preferenceNotice,
  preferenceError,
  onSelectPurpose,
  onSelectRouteModel,
  onRestoreSavedRoutes,
  onUseDefaultRoutes,
  onRevertRoutes,
  onTestModel,
  onChangePreference,
  onSavePreferences,
  onRevokeSession,
  onCancelRevokeSession,
  onExportAccount,
  onDeleteAccount
}: {
  uiLanguage: UiLanguage;
  onUiLanguageChange: (language: UiLanguage) => void;
  authUser: AuthUser;
  quota: QuotaUsage | null;
  authSessions: AuthSessionSummary[];
  loadingAuthSessions: boolean;
  revokingSessionId: string | null;
  confirmRevokeSessionId: string | null;
  sessionError: string | null;
  exportingAccount: boolean;
  deletingAccount: boolean;
  accountActionError: string | null;
  models: ModelOption[];
  providers: ProvidersResponse | null;
  selectedPurpose: StoryPurpose;
  routeModels: Partial<Record<StoryPurpose, string>>;
  routeDirty: boolean;
  savingRoutes: boolean;
  routeNotice: string | null;
  routeHistory: ModelRouteChange[];
  routeError: string | null;
  checkingModelId: string | null;
  modelHealthNotice: string | null;
  modelHealthError: string | null;
  userPreferences: UserPreference[];
  preferenceDirty: boolean;
  savingPreferences: boolean;
  preferenceNotice: string | null;
  preferenceError: string | null;
  onSelectPurpose: (purpose: StoryPurpose) => void;
  onSelectRouteModel: (purpose: StoryPurpose, model: string) => void;
  onRestoreSavedRoutes: () => void;
  onUseDefaultRoutes: () => void;
  onRevertRoutes: () => void;
  onTestModel: (model: ModelOption) => void;
  onChangePreference: (preferenceType: string, content: string) => void;
  onSavePreferences: () => void;
  onRevokeSession: (authSession: AuthSessionSummary) => void;
  onCancelRevokeSession: () => void;
  onExportAccount: () => void;
  onDeleteAccount: (password: string, confirmation: string) => void;
}) {
  const [showDeleteAccount, setShowDeleteAccount] = useState(false);
  const [deletePassword, setDeletePassword] = useState("");
  const [deleteConfirmation, setDeleteConfirmation] = useState("");
  const deleteReady = deletePassword.length > 0 && deleteConfirmation === "DELETE";
  const configurableRoles = providers?.model_roles.filter((role) => role.user_configurable) ?? [];
  const embeddingRole = providers?.model_roles.find((role) => role.id === "embedding");

  return (
    <section className="settingsPage">
      <div className="settingsInner">
        <header>
          <h1>{uiText(uiLanguage, "设置", "Settings")}</h1>
          <p>{uiText(uiLanguage, "管理界面语言、账号安全、故事偏好与模型路由。", "Manage interface language, account security, story preferences, and model routing.")}</p>
        </header>

        <Panel title={uiText(uiLanguage, "界面语言", "Interface language")} icon={Globe2}>
          <p className="languageDescription">
            {uiText(uiLanguage, "只更改按钮、标签和帮助文字，不会翻译或改写小说正文。", "Changes buttons, labels, and help text only. Your story prose is never translated or rewritten.")}
          </p>
          <div className="languageToggle" role="radiogroup" aria-label={uiText(uiLanguage, "界面语言", "Interface language")}>
            <button type="button" role="radio" aria-checked={uiLanguage === "zh-CN"} className={uiLanguage === "zh-CN" ? "active" : undefined} onClick={() => onUiLanguageChange("zh-CN")}>简体中文</button>
            <button type="button" role="radio" aria-checked={uiLanguage === "en"} className={uiLanguage === "en" ? "active" : undefined} onClick={() => onUiLanguageChange("en")}>English</button>
          </div>
        </Panel>

        <Panel title={uiText(uiLanguage, "账号会话", "Account sessions")} icon={ShieldCheck} count={authSessions.length}>
          <div className="accountIdentity">
            <span><UserRound size={15} /></span>
            <span><b>{authUser.display_name}</b><small>{authUser.email}</small></span>
          </div>
          {sessionError && <div className="authError" role="alert">{sessionError}</div>}
          {loadingAuthSessions ? (
            <div className="sessionLoading"><RefreshCw size={14} className="spinIcon" /> {uiText(uiLanguage, "正在读取会话", "Loading sessions")}</div>
          ) : authSessions.length ? (
            <ul className="sessionList">
              {authSessions.map((authSession) => {
                const confirming = confirmRevokeSessionId === authSession.id;
                const revoking = revokingSessionId === authSession.id;
                return (
                  <li key={authSession.id}>
                    <MonitorSmartphone size={15} />
                    <span>
                      <b>{authSession.device_name || (authSession.current ? uiText(uiLanguage, "当前设备", "Current device") : uiText(uiLanguage, "旧版未知设备", "Legacy unknown device"))}</b>
                      <small>{authSession.current ? `${uiText(uiLanguage, "当前会话", "Current session")} · ` : ""}{authSession.ip_address || uiText(uiLanguage, "IP 未记录", "IP not recorded")} · {authSession.ip_region || uiText(uiLanguage, "地区未知", "Region unknown")}</small>
                      <small>{uiText(uiLanguage, "登录", "Signed in")} {formatStoryUpdated(authSession.created_at, uiLanguage)} · {uiText(uiLanguage, "到期", "Expires")} {formatStoryUpdated(authSession.expires_at, uiLanguage)}</small>
                    </span>
                    {confirming ? (
                      <span className="sessionActions">
                        <button className="plainIcon dangerAction" type="button" aria-label={authSession.current ? uiText(uiLanguage, "确认退出当前会话", "Confirm sign out on this device") : uiText(uiLanguage, "确认撤销会话", "Confirm session revocation")} title={uiText(uiLanguage, "再次点击确认", "Click again to confirm")} onClick={() => onRevokeSession(authSession)} disabled={revoking}>
                          {revoking ? <RefreshCw size={14} className="spinIcon" /> : <AlertTriangle size={14} />}
                        </button>
                        <button className="plainIcon" type="button" aria-label={uiText(uiLanguage, "取消撤销会话", "Cancel session revocation")} onClick={onCancelRevokeSession} disabled={revoking}><X size={14} /></button>
                      </span>
                    ) : (
                      <button className="plainIcon" type="button" aria-label={authSession.current ? uiText(uiLanguage, "退出当前会话", "Sign out this session") : uiText(uiLanguage, "撤销会话", "Revoke session")} title={authSession.current ? uiText(uiLanguage, "退出当前会话", "Sign out this session") : uiText(uiLanguage, "撤销会话", "Revoke session")} onClick={() => onRevokeSession(authSession)} disabled={Boolean(revokingSessionId)}><LogOut size={14} /></button>
                    )}
                  </li>
                );
              })}
            </ul>
          ) : <EmptyState>{uiText(uiLanguage, "没有可用的登录会话。", "No active sign-in sessions.")}</EmptyState>}
        </Panel>

        <Panel title={uiText(uiLanguage, "本周 AI 额度", "Weekly AI quota")} icon={Gauge}><QuotaMeter quota={quota} uiLanguage={uiLanguage} /></Panel>

        <Panel title={uiText(uiLanguage, "数据与账户", "Data and account")} icon={Download}>
          <div className="accountDataRow">
            <span><b>{uiText(uiLanguage, "导出全部数据", "Export all data")}</b><small>{uiText(uiLanguage, "下载账号、故事、消息、世界观、记忆、偏好与脱敏模型调用元数据。", "Download your profile, stories, messages, worlds, memories, preferences, and sanitized model-call metadata.")}</small></span>
            <button className="cmdButton" type="button" onClick={onExportAccount} disabled={exportingAccount || deletingAccount}>{exportingAccount ? <RefreshCw size={13} className="spinIcon" /> : <Download size={13} />}{uiText(uiLanguage, "导出 JSON", "Export JSON")}</button>
          </div>
          <div className="accountDangerZone">
            <span><b>{uiText(uiLanguage, "永久删除账户", "Permanently delete account")}</b><small>{uiText(uiLanguage, "删除账号、故事、消息、世界观、角色、记忆、偏好、会话与模型调用记录。此操作无法撤销。", "Deletes your account, stories, messages, worlds, characters, memories, preferences, sessions, and model-call records. This cannot be undone.")}</small></span>
            {!showDeleteAccount ? (
              <button className="cmdButton dangerAction" type="button" onClick={() => setShowDeleteAccount(true)} disabled={exportingAccount}><Trash2 size={13} /> {uiText(uiLanguage, "删除账户", "Delete account")}</button>
            ) : (
              <div className="accountDeleteForm">
                <label><span>{uiText(uiLanguage, "当前密码", "Current password")}</span><input type="password" autoComplete="current-password" maxLength={128} value={deletePassword} onChange={(event) => setDeletePassword(event.target.value)} disabled={deletingAccount} /></label>
                <label><span>{uiText(uiLanguage, "输入 DELETE 确认", "Type DELETE to confirm")}</span><input type="text" autoComplete="off" value={deleteConfirmation} onChange={(event) => setDeleteConfirmation(event.target.value)} disabled={deletingAccount} /></label>
                <div className="routingActions">
                  <button className="cmdButton dangerAction" type="button" disabled={!deleteReady || deletingAccount} onClick={() => onDeleteAccount(deletePassword, deleteConfirmation)}>{deletingAccount ? <RefreshCw size={13} className="spinIcon" /> : <Trash2 size={13} />}{uiText(uiLanguage, "永久删除", "Delete permanently")}</button>
                  <button className="cmdButton" type="button" disabled={deletingAccount} onClick={() => { setShowDeleteAccount(false); setDeletePassword(""); setDeleteConfirmation(""); }}><X size={13} /> {uiText(uiLanguage, "取消", "Cancel")}</button>
                </div>
              </div>
            )}
          </div>
          {accountActionError && <div className="authError" role="alert">{accountActionError}</div>}
        </Panel>

        <Panel title={uiText(uiLanguage, "故事偏好", "Story preferences")} icon={Settings2} action={<span className={preferenceDirty ? "statusWarn" : "statusOk"}>{preferenceDirty ? uiText(uiLanguage, "未保存", "Unsaved") : uiText(uiLanguage, "已保存", "Saved")}</span>}>
          <p className="languageDescription">{uiText(uiLanguage, "这些偏好会在每一轮正文生成时加入上下文，并受固定 token 预算保护。", "These preferences are included in the context for every prose generation within a fixed token budget.")}</p>
          <div className="preferenceGrid">
            {preferenceFields.map((field) => {
              const copy = uiLanguage === "zh-CN" ? field : preferenceFieldsEn[field.id];
              return <label key={field.id}><span>{copy.label}</span><textarea rows={2} maxLength={4000} placeholder={copy.placeholder} value={userPreferences.find((item) => item.preferenceType === field.id)?.content ?? ""} onChange={(event) => onChangePreference(field.id, event.target.value)} /></label>;
            })}
          </div>
          <div className="routingActions"><button className="cmdButton primary" type="button" onClick={onSavePreferences} disabled={!preferenceDirty || savingPreferences}>{savingPreferences ? <RefreshCw size={13} className="spinIcon" /> : <Check size={13} />}{uiText(uiLanguage, "保存偏好", "Save preferences")}</button></div>
          {preferenceNotice && <div className="routingNotice" role="status">{preferenceNotice}</div>}
          {preferenceError && <div className="authError" role="alert">{preferenceError}</div>}
        </Panel>

        <div className="providerCards">
          {(["deepinfra", "openai"] as const).map((provider) => {
            const configured = providers?.availability[provider] ?? false;
            const statusText = providers ? (configured ? uiText(uiLanguage, "已配置", "Configured") : uiText(uiLanguage, "未配置", "Not configured")) : uiText(uiLanguage, "检查中", "Checking");
            return (
              <Panel key={provider} title={provider === "deepinfra" ? "DeepInfra" : "OpenAI"} icon={Cpu} action={<span className={configured ? "statusOk" : "statusWarn"}>{configured ? <KeyRound size={13} /> : <AlertTriangle size={13} />}{statusText}</span>}>
                <div className="serverCredentialStatus"><KeyRound size={13} /><span><b>{uiText(uiLanguage, "服务器托管凭据", "Server-managed credential")}</b><small>{uiText(uiLanguage, "通过后端环境配置，浏览器无法读取或修改密钥。", "Configured on the server; the browser cannot read or modify the key.")}</small></span></div>
                <div className="modelPills">
                  {models.filter((model) => model.provider === provider).length ? models.filter((model) => model.provider === provider).map((model) => {
                    const health = providers?.model_health[model.model];
                    const checking = checkingModelId === model.model;
                    const status = !health || !health.fresh ? "unknown" : health.status;
                    const statusLabel = !health ? uiText(uiLanguage, "未检测", "Not checked") : !health.fresh ? uiText(uiLanguage, "结果已过期", "Expired") : health.status === "available" ? uiText(uiLanguage, "可用", "Available") : uiText(uiLanguage, "不可用", "Unavailable");
                    const StatusIcon = checking ? RefreshCw : status === "available" ? CheckCircle2 : status === "unavailable" ? AlertTriangle : CircleDashed;
                    return <button key={model.model} className={`modelHealthButton ${status} ${Object.values(routeModels).includes(model.model) ? "routed" : ""}`} type="button" aria-label={`${uiText(uiLanguage, "检测", "Check")} ${model.label}`} title={health?.error || `${uiText(uiLanguage, "检测", "Check")} ${model.label}`} disabled={!configured || Boolean(checkingModelId)} onClick={() => onTestModel(model)}><StatusIcon size={13} className={checking ? "spinIcon" : undefined} /><span><b>{model.label}</b><small>{checking ? uiText(uiLanguage, "检测中", "Checking") : statusLabel}{health?.checked_at ? ` · ${formatStoryUpdated(health.checked_at, uiLanguage)}` : ""}</small></span></button>;
                  }) : <EmptyState>{uiText(uiLanguage, `后端未返回 ${provider} 模型。`, `No ${provider} models returned by the server.`)}</EmptyState>}
                </div>
              </Panel>
            );
          })}
        </div>
        {modelHealthNotice && <div className="routingNotice" role="status">{modelHealthNotice}</div>}
        {modelHealthError && <div className="authError" role="alert">{modelHealthError}</div>}

        <Panel title={uiText(uiLanguage, "模型用途路由", "Purpose routing")} icon={Route} action={<span className={routeDirty || savingRoutes ? "statusWarn" : "statusOk"}>{savingRoutes ? uiText(uiLanguage, "保存中…", "Saving...") : routeDirty ? uiText(uiLanguage, "待保存", "Pending") : uiText(uiLanguage, "已保存", "Saved")}</span>}>
          <div className="routingRoleList">
            {configurableRoles.map((role) => {
              const roleText = modelRoleText[role.id];
              return <section key={role.id} className="routingRole" data-testid={`model-role-${role.id}`}><header><b>{uiLanguage === "zh-CN" ? roleText.zh : roleText.en}</b><small>{uiLanguage === "zh-CN" ? roleText.zhDescription : roleText.enDescription}</small></header><ul className="routingList">{role.purposes.map((purpose) => {
                const route = purposeRoutesById[purpose];
                return <li key={route.id} className={selectedPurpose === route.id ? "active" : undefined}><span><button type="button" onClick={() => onSelectPurpose(route.id)}><b>{uiLanguage === "zh-CN" ? purposeRoutesZh[route.id].label : route.label}</b><small>{uiLanguage === "zh-CN" ? purposeRoutesZh[route.id].description : route.description}</small></button></span><select value={routeModels[route.id] ?? providers?.purpose_defaults[route.id] ?? ""} disabled={!models.length} onChange={(event) => onSelectRouteModel(route.id, event.target.value)}>{models.length ? models.map((model) => <option key={model.model} value={model.model} disabled={providers?.model_health[model.model]?.fresh && providers.model_health[model.model].status === "unavailable"}>{model.label} ({model.provider})</option>) : <option value="">{uiText(uiLanguage, "等待后端模型列表", "Waiting for server model list")}</option>}</select></li>;
              })}</ul></section>;
            })}
            {embeddingRole?.deployment && <section className="routingRole deploymentRole" data-testid="model-role-embedding"><header><b>{uiLanguage === "zh-CN" ? modelRoleText.embedding.zh : modelRoleText.embedding.en}</b><small>{uiLanguage === "zh-CN" ? modelRoleText.embedding.zhDescription : modelRoleText.embedding.enDescription}</small></header><div className="deploymentModel"><span>{embeddingRole.deployment.model}</span><small>{embeddingRole.deployment.provider} · {embeddingRole.deployment.dimensions}d · {embeddingRole.deployment.version} · {uiText(uiLanguage, "更换模型需要受控重建索引", "model changes require controlled re-indexing")}</small></div></section>}
          </div>
          <div className="routingActions">
            <button className="cmdButton" type="button" onClick={onRestoreSavedRoutes} disabled={!routeDirty || savingRoutes}><RefreshCw size={13} /> {uiText(uiLanguage, "恢复已保存", "Restore saved")}</button>
            <button className="cmdButton" type="button" onClick={onUseDefaultRoutes} disabled={savingRoutes || !providers}><Route size={13} /> {uiText(uiLanguage, "使用默认值", "Use defaults")}</button>
            <button className="cmdButton" type="button" onClick={onRevertRoutes} disabled={savingRoutes || routeDirty || !routeHistory.length}><GitFork size={13} /> {uiText(uiLanguage, "撤销最近变更", "Undo latest change")}</button>
          </div>
          {routeHistory[0] && <div className="routingNotice">{uiText(uiLanguage, "最近变更", "Latest change")}: {routeHistory[0].action === "revert" ? uiText(uiLanguage, "撤销", "Undo") : uiText(uiLanguage, "更新", "Update")} · {formatStoryUpdated(routeHistory[0].created_at, uiLanguage)}</div>}
          {routeNotice && <div className="routingNotice" role="status">{routeNotice}</div>}
          {routeError && <div className="authError" role="alert">{routeError}</div>}
        </Panel>
      </div>
    </section>
  );
}
