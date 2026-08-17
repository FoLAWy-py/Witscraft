import type {
  AuthMessageResponse,
  AuthResponse,
  AuthSessionListResponse,
  LoginInput,
  RegisterInput
} from "../types";
import { API_BASE_URL, ApiError, requestJson } from "./core";

const USER_ID_KEY = "witscraft:user-id";

function getLegacyUserId(): string | undefined {
  if (typeof window === "undefined") return undefined;
  return window.localStorage.getItem(USER_ID_KEY) ?? undefined;
}

function getDeviceName(): string | undefined {
  if (typeof window === "undefined") return undefined;
  const userAgent = window.navigator.userAgent;
  const browser = /CriOS|Chrome/.test(userAgent) ? "Chrome" : /FxiOS|Firefox/.test(userAgent) ? "Firefox" : /Safari/.test(userAgent) ? "Safari" : "Browser";
  const viewport = `${window.screen.width}×${window.screen.height}`;
  const androidModel = userAgent.match(/Android[^;]*;\s*([^;)]+?)(?:\s+Build\/|\))/)?.[1]?.trim();
  const device = /iPhone/.test(userAgent)
    ? `iPhone ${viewport}`
    : /iPad/.test(userAgent)
      ? `iPad ${viewport}`
      : /Android/.test(userAgent)
        ? androidModel || `Android ${viewport}`
        : /Macintosh/.test(userAgent)
          ? `Mac ${viewport}`
          : /Windows/.test(userAgent)
            ? `Windows PC ${viewport}`
            : `Device ${viewport}`;
  return `${device} · ${browser}`;
}

export async function getCurrentUser(): Promise<AuthResponse> {
  return requestJson<AuthResponse>(`${API_BASE_URL}/api/auth/me`, { cache: "no-store" });
}

export async function login(input: LoginInput): Promise<AuthResponse> {
  return requestJson<AuthResponse>(`${API_BASE_URL}/api/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ...input, device_name: getDeviceName() })
  });
}

export async function register(input: RegisterInput): Promise<AuthResponse> {
  const response = await requestJson<AuthResponse>(`${API_BASE_URL}/api/auth/register`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      email: input.email,
      password: input.password,
      display_name: input.displayName,
      legacy_user_id: getLegacyUserId(),
      device_name: getDeviceName()
    })
  });
  if (typeof window !== "undefined") window.localStorage.removeItem(USER_ID_KEY);
  return response;
}

export async function requestEmailVerification(): Promise<AuthMessageResponse> {
  return requestJson<AuthMessageResponse>(`${API_BASE_URL}/api/auth/email-verification/request`, {
    method: "POST"
  });
}

export async function confirmEmailVerification(token: string): Promise<AuthResponse> {
  return requestJson<AuthResponse>(`${API_BASE_URL}/api/auth/email-verification/confirm`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ token })
  });
}

export async function requestPasswordReset(email: string): Promise<AuthMessageResponse> {
  return requestJson<AuthMessageResponse>(`${API_BASE_URL}/api/auth/password-reset/request`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email })
  });
}

export async function confirmPasswordReset(token: string, newPassword: string): Promise<AuthMessageResponse> {
  return requestJson<AuthMessageResponse>(`${API_BASE_URL}/api/auth/password-reset/confirm`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ token, new_password: newPassword })
  });
}

export async function logout(): Promise<void> {
  await requestJson<void>(`${API_BASE_URL}/api/auth/logout`, { method: "POST" });
}

export async function getAuthSessions(): Promise<AuthSessionListResponse> {
  return requestJson<AuthSessionListResponse>(`${API_BASE_URL}/api/auth/sessions`, {
    cache: "no-store"
  });
}

export async function revokeAuthSession(sessionId: string): Promise<void> {
  await requestJson<void>(`${API_BASE_URL}/api/auth/sessions/${sessionId}`, {
    method: "DELETE"
  });
}

export async function downloadAccountExport(): Promise<void> {
  if (typeof window === "undefined" || typeof document === "undefined" || typeof fetch !== "function") {
    throw new Error("Account export downloads require a browser runtime");
  }
  const response = await fetch(`${API_BASE_URL}/api/auth/export`, { credentials: "include" });
  if (!response.ok) {
    throw new ApiError(`Account export failed with status ${response.status}`, response.status);
  }
  const blob = await response.blob();
  const objectUrl = window.URL.createObjectURL(blob);
  const disposition = response.headers.get("Content-Disposition") ?? "";
  const filename = disposition.match(/filename="([^"]+)"/)?.[1] ?? "witscraft-account.json";
  const link = document.createElement("a");
  link.href = objectUrl;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.URL.revokeObjectURL(objectUrl);
}

export async function deleteAccount(password: string, confirmation: string): Promise<void> {
  await requestJson<void>(`${API_BASE_URL}/api/auth/account`, {
    method: "DELETE",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ password, confirmation })
  });
}
