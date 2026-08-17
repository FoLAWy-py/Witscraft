"use client";

import {
  AlertTriangle,
  ArrowRight,
  Check,
  Feather,
  Lock,
  LogOut,
  Mail,
  RefreshCw,
  Send,
  ShieldCheck,
  UserRound
} from "lucide-react";
import { useState } from "react";
import type { LoginInput, RegisterInput } from "@/lib/types";

type UiLanguage = "zh-CN" | "en";

function uiText(language: UiLanguage, zh: string, en: string) {
  return language === "zh-CN" ? zh : en;
}

export function AuthLoading({ uiLanguage, label }: { uiLanguage: UiLanguage; label?: string }) {
  return (
    <main className="authShell">
      <div className="authLoading" aria-live="polite">
        <span className="makeLogo"><Feather size={17} /></span>
        <RefreshCw size={17} className="spinIcon" />
        <span>{label ?? uiText(uiLanguage, "正在检查登录状态", "Checking sign-in status")}</span>
      </div>
    </main>
  );
}

export function WorkspaceSkeleton({ uiLanguage }: { uiLanguage: UiLanguage }) {
  const loadingLabel = uiText(uiLanguage, "正在载入互动小说", "Loading interactive novel");
  return (
    <main className="makeShell workspaceSkeleton" aria-busy="true" aria-label={loadingLabel}>
      <header className="makeTopbar">
        <div className="makeBrand"><span className="makeLogo"><Feather size={16} /></span><strong>Witscraft</strong></div>
        <div className="skeletonLine short" />
        <div className="topbarSpacer" />
        <div className="skeletonControl" />
        <div className="skeletonControl" />
      </header>
      <section className="storyWorkspace">
        <aside className="libraryRail skeletonRail">
          <div className="skeletonLine medium" />
          {[0, 1, 2].map((item) => <div className="skeletonBlock" key={item} />)}
        </aside>
        <section className="storyStage skeletonStage">
          <div className="skeletonRibbon" />
          <div className="skeletonProse">
            <div className="skeletonLine medium" />
            <div className="skeletonLine full" />
            <div className="skeletonLine full" />
            <div className="skeletonLine wide" />
            <div className="skeletonLine full" />
            <div className="skeletonLine medium" />
          </div>
          <div className="skeletonComposer" />
        </section>
        <aside className="inspectorRail skeletonRail">
          <div className="skeletonLine medium" />
          {[0, 1, 2, 3].map((item) => <div className="skeletonBlock compact" key={item} />)}
        </aside>
      </section>
      <span className="srOnly" aria-live="polite">{loadingLabel}</span>
    </main>
  );
}

export function AuthGate({
  uiLanguage,
  pending,
  error,
  notice,
  onSubmit,
  onRequestPasswordReset
}: {
  uiLanguage: UiLanguage;
  pending: boolean;
  error: string | null;
  notice: string | null;
  onSubmit: (mode: "login" | "register", input: LoginInput | RegisterInput) => void;
  onRequestPasswordReset: (email: string) => void;
}) {
  const [mode, setMode] = useState<"login" | "register" | "recovery">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [displayName, setDisplayName] = useState("");
  const canSubmit = email.trim().length >= 3
    && (mode === "recovery" || password.length >= (mode === "register" ? 12 : 1))
    && (mode !== "register" || displayName.trim().length > 0);

  return (
    <main className="authShell">
      <section className="authPanel" aria-labelledby="auth-title">
        <header className="authBrand">
          <span className="makeLogo"><Feather size={17} /></span>
          <strong>Witscraft</strong>
        </header>
        <div className="authHeading">
          <h1 id="auth-title">{mode === "login" ? uiText(uiLanguage, "登录", "Sign in") : mode === "register" ? uiText(uiLanguage, "创建账号", "Create account") : uiText(uiLanguage, "找回密码", "Reset password")}</h1>
          <p>{mode === "login" ? uiText(uiLanguage, "继续你的互动小说", "Continue your interactive novel") : mode === "register" ? uiText(uiLanguage, "开启你的私人互动小说", "Start your private interactive novel") : uiText(uiLanguage, "我们会向注册邮箱发送一次性重置链接", "We will email a one-time reset link to your registered address")}</p>
        </div>
        {mode === "recovery" ? (
          <button className="authTextButton" type="button" onClick={() => setMode("login")} disabled={pending}>
            <ArrowRight size={13} className="authBackIcon" /> {uiText(uiLanguage, "返回登录", "Back to sign in")}
          </button>
        ) : (
          <div className="authMode" role="tablist" aria-label={uiText(uiLanguage, "认证方式", "Authentication method")}>
            <button type="button" role="tab" aria-selected={mode === "login"} className={mode === "login" ? "active" : undefined} onClick={() => setMode("login")} disabled={pending}>{uiText(uiLanguage, "登录", "Sign in")}</button>
            <button type="button" role="tab" aria-selected={mode === "register"} className={mode === "register" ? "active" : undefined} onClick={() => setMode("register")} disabled={pending}>{uiText(uiLanguage, "注册", "Register")}</button>
          </div>
        )}
        <form
          className="authForm"
          onSubmit={(event) => {
            event.preventDefault();
            if (!canSubmit || pending) return;
            if (mode === "recovery") onRequestPasswordReset(email.trim());
            else if (mode === "register") onSubmit(mode, { email: email.trim(), password, displayName: displayName.trim() });
            else onSubmit(mode, { email: email.trim(), password });
          }}
        >
          {mode === "register" && (
            <label>
              <span>{uiText(uiLanguage, "显示名称", "Display name")}</span>
              <span className="authField">
                <UserRound size={15} />
                <input type="text" value={displayName} onChange={(event) => setDisplayName(event.target.value)} autoComplete="name" maxLength={120} aria-label={uiText(uiLanguage, "显示名称", "Display name")} disabled={pending} />
              </span>
            </label>
          )}
          <label>
            <span>{uiText(uiLanguage, "邮箱", "Email")}</span>
            <span className="authField">
              <Mail size={15} />
              <input type="email" value={email} onChange={(event) => setEmail(event.target.value)} autoComplete="email" aria-label={uiText(uiLanguage, "邮箱", "Email")} disabled={pending} />
            </span>
          </label>
          {mode !== "recovery" && (
            <label>
              <span>{uiText(uiLanguage, "密码", "Password")}</span>
              <span className="authField">
                <Lock size={15} />
                <input type="password" value={password} onChange={(event) => setPassword(event.target.value)} autoComplete={mode === "register" ? "new-password" : "current-password"} minLength={mode === "register" ? 12 : 1} maxLength={128} aria-label={uiText(uiLanguage, "密码", "Password")} disabled={pending} />
              </span>
              {mode === "register" && <small>{uiText(uiLanguage, "至少 12 个字符", "At least 12 characters")}</small>}
            </label>
          )}
          {mode === "login" && <button className="authTextButton authForgot" type="button" onClick={() => setMode("recovery")} disabled={pending}>{uiText(uiLanguage, "忘记密码？", "Forgot password?")}</button>}
          {error && <div className="authError" role="alert">{error}</div>}
          {notice && <div className="authNotice" role="status">{notice}</div>}
          <button className="authSubmit" type="submit" disabled={!canSubmit || pending}>
            {pending ? <RefreshCw size={15} className="spinIcon" /> : <ArrowRight size={15} />}
            {pending ? uiText(uiLanguage, "请稍候", "Please wait") : mode === "login" ? uiText(uiLanguage, "进入小说", "Enter novel") : mode === "register" ? uiText(uiLanguage, "创建账号", "Create account") : uiText(uiLanguage, "发送重置链接", "Send reset link")}
          </button>
        </form>
      </section>
    </main>
  );
}

export function EmailVerificationGate({
  uiLanguage,
  email,
  pending,
  loggingOut,
  error,
  notice,
  onResend,
  onLogout
}: {
  uiLanguage: UiLanguage;
  email: string;
  pending: boolean;
  loggingOut: boolean;
  error: string | null;
  notice: string | null;
  onResend: () => void;
  onLogout: () => void;
}) {
  return (
    <main className="authShell">
      <section className="authPanel" aria-labelledby="verification-title">
        <header className="authBrand"><span className="makeLogo"><Feather size={17} /></span><strong>Witscraft</strong></header>
        <div className="authStatusIcon"><Mail size={22} /></div>
        <div className="authHeading">
          <h1 id="verification-title">{uiText(uiLanguage, "验证你的邮箱", "Verify your email")}</h1>
          <p>{uiText(uiLanguage, "验证链接已发送到", "A verification link was sent to")} <b>{email}</b>{uiText(uiLanguage, "。完成验证后即可进入互动小说。", ". Verify it to enter your interactive novel.")}</p>
        </div>
        {error && <div className="authError" role="alert">{error}</div>}
        {notice && <div className="authNotice" role="status">{notice}</div>}
        <div className="authActions">
          <button className="authSubmit" type="button" onClick={onResend} disabled={pending || loggingOut}>
            {pending ? <RefreshCw size={15} className="spinIcon" /> : <Send size={15} />}
            {pending ? uiText(uiLanguage, "正在发送", "Sending") : uiText(uiLanguage, "重新发送验证邮件", "Resend verification email")}
          </button>
          <button className="cmdButton" type="button" onClick={onLogout} disabled={pending || loggingOut}>
            {loggingOut ? <RefreshCw size={14} className="spinIcon" /> : <LogOut size={14} />}
            {uiText(uiLanguage, "退出账号", "Sign out")}
          </button>
        </div>
      </section>
    </main>
  );
}

export function PasswordResetGate({ uiLanguage, pending, error, onSubmit, onCancel }: {
  uiLanguage: UiLanguage;
  pending: boolean;
  error: string | null;
  onSubmit: (password: string) => void;
  onCancel: () => void;
}) {
  const [password, setPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const mismatch = confirmation.length > 0 && password !== confirmation;
  const canSubmit = password.length >= 12 && password === confirmation;
  return (
    <main className="authShell">
      <section className="authPanel" aria-labelledby="reset-title">
        <header className="authBrand"><span className="makeLogo"><Feather size={17} /></span><strong>Witscraft</strong></header>
        <div className="authStatusIcon"><ShieldCheck size={22} /></div>
        <div className="authHeading">
          <h1 id="reset-title">{uiText(uiLanguage, "设置新密码", "Set a new password")}</h1>
          <p>{uiText(uiLanguage, "新密码至少需要 12 个字符，提交后所有旧登录会话都会失效。", "Use at least 12 characters. Submitting will sign out all existing sessions.")}</p>
        </div>
        <form className="authForm" onSubmit={(event) => { event.preventDefault(); if (canSubmit && !pending) onSubmit(password); }}>
          <label><span>{uiText(uiLanguage, "新密码", "New password")}</span><span className="authField"><Lock size={15} /><input type="password" autoComplete="new-password" minLength={12} maxLength={128} value={password} onChange={(event) => setPassword(event.target.value)} disabled={pending} /></span></label>
          <label><span>{uiText(uiLanguage, "确认新密码", "Confirm new password")}</span><span className="authField"><Lock size={15} /><input type="password" autoComplete="new-password" minLength={12} maxLength={128} value={confirmation} onChange={(event) => setConfirmation(event.target.value)} disabled={pending} /></span>{mismatch && <small className="fieldError">{uiText(uiLanguage, "两次输入的密码不一致", "Passwords do not match")}</small>}</label>
          {error && <div className="authError" role="alert">{error}</div>}
          <button className="authSubmit" type="submit" disabled={!canSubmit || pending}>{pending ? <RefreshCw size={15} className="spinIcon" /> : <Check size={15} />}{pending ? uiText(uiLanguage, "正在重置", "Resetting") : uiText(uiLanguage, "重置密码", "Reset password")}</button>
          <button className="authTextButton" type="button" onClick={onCancel} disabled={pending}>{uiText(uiLanguage, "返回登录", "Back to sign in")}</button>
        </form>
      </section>
    </main>
  );
}

export function WorkspaceLoadFailure({ uiLanguage, error, loading, onRetry, onLogout }: {
  uiLanguage: UiLanguage;
  error: string;
  loading: boolean;
  onRetry: () => void;
  onLogout: () => void;
}) {
  return (
    <main className="authShell">
      <section className="authPanel" aria-labelledby="workspace-error-title">
        <header className="authBrand"><span className="makeLogo"><Feather size={17} /></span><strong>Witscraft</strong></header>
        <div className="authStatusIcon"><AlertTriangle size={22} /></div>
        <div className="authHeading"><h1 id="workspace-error-title">{uiText(uiLanguage, "互动小说暂时不可用", "Interactive novel unavailable")}</h1><p>{error}</p></div>
        <div className="authActions">
          <button className="authSubmit" type="button" onClick={onRetry} disabled={loading}><RefreshCw size={15} className={loading ? "spinIcon" : undefined} />{uiText(uiLanguage, "重新读取", "Retry")}</button>
          <button className="cmdButton" type="button" onClick={onLogout}><LogOut size={14} />{uiText(uiLanguage, "退出账号", "Sign out")}</button>
        </div>
      </section>
    </main>
  );
}
