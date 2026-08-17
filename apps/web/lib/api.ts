import type {
  AuthResponse,
  AuthMessageResponse,
  AuthSessionListResponse,
  AdminOverview,
  ChatResponse,
  CreateBranchInput,
  CreateStoryInput,
  StoryDraftSuggestion,
  StoryInterviewMessage,
  StoryInterviewResponse,
  LoginInput,
  ModelHealthResponse,
  ModelRoutesResponse,
  ProvidersResponse,
  QuotaResetResponse,
  QuotaUsage,
  RegisterInput,
  StoryPurpose,
  UpdateCanonFactInput,
  UpdateCharacterInput,
  UpdateMemoryInput,
  UpdateStoryInput,
  UpdateWorldInput,
  UserPreference,
  UserPreferencesResponse,
  WorkspaceResponse
} from "./types";

function getApiBaseUrl(): string {
  const configuredBaseUrl = process.env.NEXT_PUBLIC_API_BASE_URL;
  if (configuredBaseUrl) {
    if (typeof window !== "undefined") {
      return new URL(configuredBaseUrl, window.location.origin).toString().replace(/\/$/, "");
    }
    if (/^https?:\/\//.test(configuredBaseUrl)) {
      return configuredBaseUrl.replace(/\/$/, "");
    }
  }

  if (typeof window !== "undefined") {
    return `${window.location.protocol}//${window.location.hostname}:8000`;
  }

  return "http://localhost:8000";
}

const API_BASE_URL = getApiBaseUrl();
const USER_ID_KEY = "witscraft:user-id";

export class ApiError extends Error {
  constructor(message: string, public readonly status: number) {
    super(message);
    this.name = "ApiError";
  }
}

export class StreamInterruptedError extends Error {
  constructor(message = "Stream ended before completion") {
    super(message);
    this.name = "StreamInterruptedError";
  }
}

async function requestJson<T>(url: string, init?: RequestInit): Promise<T> {
  const requestInit: RequestInit = { ...init, credentials: "include" };
  if (typeof fetch === "function") {
    const response = await fetch(url, requestInit);
    if (!response.ok) {
      let message = `Request failed with status ${response.status}`;
      try {
        const payload = await response.json() as { detail?: string };
        if (payload.detail) message = payload.detail;
      } catch {
        // Keep the status-based fallback when the backend did not return JSON.
      }
      throw new ApiError(message, response.status);
    }
    if (response.status === 204) return undefined as T;
    return response.json();
  }

  return new Promise<T>((resolve, reject) => {
    const request = new XMLHttpRequest();
    request.open(requestInit.method ?? "GET", url);
    request.withCredentials = true;
    const headers = requestInit.headers;
    if (headers instanceof Headers) {
      headers.forEach((value, key) => request.setRequestHeader(key, value));
    } else if (Array.isArray(headers)) {
      headers.forEach(([key, value]) => request.setRequestHeader(key, value));
    } else if (headers) {
      Object.entries(headers).forEach(([key, value]) => request.setRequestHeader(key, String(value)));
    }
    request.onload = () => {
      if (request.status < 200 || request.status >= 300) {
        let message = `Request failed with status ${request.status}`;
        try {
          const payload = JSON.parse(request.responseText) as { detail?: string };
          if (payload.detail) message = payload.detail;
        } catch {
          // Keep the status-based fallback when the backend did not return JSON.
        }
        reject(new ApiError(message, request.status));
        return;
      }
      if (request.status === 204) {
        resolve(undefined as T);
        return;
      }
      try {
        resolve(JSON.parse(request.responseText) as T);
      } catch (error) {
        reject(error);
      }
    };
    request.onerror = () => reject(new Error("Network request failed"));
    request.send(requestInit.body as XMLHttpRequestBodyInit | null | undefined);
  });
}

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

export async function getMyQuota(storyId?: string): Promise<QuotaUsage> {
  const query = storyId ? `?story_id=${encodeURIComponent(storyId)}` : "";
  return requestJson<QuotaUsage>(`${API_BASE_URL}/api/quota/me${query}`, { cache: "no-store" });
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
  const response = await fetch(`${API_BASE_URL}/api/auth/export`, {
    credentials: "include"
  });
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

export async function getProviders(): Promise<ProvidersResponse> {
  return requestJson<ProvidersResponse>(`${API_BASE_URL}/api/providers`, {
    cache: "no-store"
  });
}

export async function testProviderModel(provider: string, model: string): Promise<ModelHealthResponse> {
  return requestJson<ModelHealthResponse>(`${API_BASE_URL}/api/providers/test`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ provider, model, max_output_tokens: 128 })
  });
}

export async function updateModelRoutes(routes: Record<StoryPurpose, string>): Promise<ModelRoutesResponse> {
  return requestJson<ModelRoutesResponse>(`${API_BASE_URL}/api/providers/routes`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ routes })
  });
}

export async function getWorkspace(storyId?: string, branchId?: string): Promise<WorkspaceResponse> {
  const url = new URL(`${API_BASE_URL}/api/workspace`);
  if (storyId) url.searchParams.set("story_id", storyId);
  if (branchId) url.searchParams.set("branch_id", branchId);
  return requestJson<WorkspaceResponse>(url.toString(), {
    cache: "no-store"
  });
}

export async function createStory(input: CreateStoryInput): Promise<WorkspaceResponse> {
  return requestJson<WorkspaceResponse>(`${API_BASE_URL}/api/workspace/stories`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      title: input.title,
      world_id: input.worldId,
      genre: input.genre,
      world_name: input.worldName,
      premise: input.premise,
      protagonist_name: input.protagonistName,
      protagonist_role: input.protagonistRole,
      tone: input.tone,
      opening_mode: input.openingMode,
      opening_text: input.openingText,
      custom_prompt: input.customPrompt,
      interaction_mode: input.interactionMode
    })
  });
}

export async function generateStoryDraft(input: CreateStoryInput): Promise<StoryDraftSuggestion> {
  type StoryDraftWire = {
    title: string;
    genre: string;
    world_name: string;
    premise: string;
    protagonist_name: string;
    protagonist_role: string;
    tone: string;
    opening_text: string;
  };
  const suggestion = await requestJson<StoryDraftWire>(`${API_BASE_URL}/api/workspace/story-draft`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      title: input.title,
      genre: input.genre,
      world_name: input.worldName,
      premise: input.premise,
      protagonist_name: input.protagonistName,
      protagonist_role: input.protagonistRole,
      tone: input.tone,
      opening_text: input.openingText
    })
  });
  return {
    title: suggestion.title,
    genre: suggestion.genre,
    worldName: suggestion.world_name,
    premise: suggestion.premise,
    protagonistName: suggestion.protagonist_name,
    protagonistRole: suggestion.protagonist_role,
    tone: suggestion.tone,
    openingText: suggestion.opening_text
  };
}

type InterviewWire = {
  assistant_message: string;
  options: string[];
  draft: {
    title: string;
    genre: string;
    world_name: string;
    premise: string;
    protagonist_name: string;
    protagonist_role: string;
    tone: string;
    opening_mode: "blank" | "custom";
    opening_text: string;
    custom_prompt: string;
    interaction_mode: "choices" | "open";
  };
  missing_fields: string[];
  ready_for_confirmation: boolean;
};

function serializeStoryInterview(input: {
  message: string;
  draft: CreateStoryInput;
  history: StoryInterviewMessage[];
}) {
  return JSON.stringify({
    message: input.message,
    history: input.history.map(({ role, content }) => ({ role, content })),
    draft: {
      title: input.draft.title,
      genre: input.draft.genre,
      world_name: input.draft.worldName,
      premise: input.draft.premise,
      protagonist_name: input.draft.protagonistName,
      protagonist_role: input.draft.protagonistRole,
      tone: input.draft.tone,
      opening_mode: input.draft.openingMode,
      opening_text: input.draft.openingText,
      custom_prompt: input.draft.customPrompt,
      interaction_mode: input.draft.interactionMode
    }
  });
}

function mapStoryInterview(response: InterviewWire): StoryInterviewResponse {
  return {
    assistantMessage: response.assistant_message,
    options: response.options ?? [],
    missingFields: response.missing_fields,
    readyForConfirmation: response.ready_for_confirmation,
    draft: {
      title: response.draft.title,
      genre: response.draft.genre,
      worldName: response.draft.world_name,
      premise: response.draft.premise,
      protagonistName: response.draft.protagonist_name,
      protagonistRole: response.draft.protagonist_role,
      tone: response.draft.tone,
      openingMode: response.draft.opening_mode,
      openingText: response.draft.opening_text,
      customPrompt: response.draft.custom_prompt,
      interactionMode: response.draft.interaction_mode
    }
  };
}

export async function continueStoryInterview(input: {
  message: string;
  draft: CreateStoryInput;
  history: StoryInterviewMessage[];
}): Promise<StoryInterviewResponse> {
  const response = await requestJson<InterviewWire>(`${API_BASE_URL}/api/workspace/story-interview`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: serializeStoryInterview(input)
  });
  return mapStoryInterview(response);
}

export async function streamStoryInterview(
  input: { message: string; draft: CreateStoryInput; history: StoryInterviewMessage[]; signal?: AbortSignal },
  handlers: { onDelta?: (content: string) => void; onReplace?: (content: string) => void; onDone?: (response: StoryInterviewResponse) => void }
): Promise<void> {
  if (typeof fetch !== "function") {
    const response = await continueStoryInterview(input);
    handlers.onDelta?.(response.assistantMessage);
    handlers.onDone?.(response);
    return;
  }

  const response = await fetch(`${API_BASE_URL}/api/workspace/story-interview/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    signal: input.signal,
    body: serializeStoryInterview(input)
  });
  if (!response.ok || !response.body) {
    throw new ApiError(`Story interview stream failed with status ${response.status}`, response.status);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let completed = false;
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const events = buffer.split("\n\n");
    buffer = events.pop() ?? "";
    for (const eventBlock of events) {
      const lines = eventBlock.split("\n");
      const eventName = lines.find((line) => line.startsWith("event: "))?.slice(7).trim();
      const dataLine = lines.find((line) => line.startsWith("data: "));
      if (!dataLine) continue;
      let payload: Record<string, unknown>;
      try {
        payload = JSON.parse(dataLine.slice(6)) as Record<string, unknown>;
      } catch {
        throw new StreamInterruptedError("Story interview returned malformed event data");
      }
      if (eventName === "delta") handlers.onDelta?.(String(payload.content ?? ""));
      if (eventName === "replace") handlers.onReplace?.(String(payload.content ?? ""));
      if (eventName === "error") throw new ApiError(String(payload.detail ?? "Story interview generation failed"), Number(payload.status ?? 502));
      if (eventName === "done") {
        completed = true;
        handlers.onDone?.(mapStoryInterview(payload.response as InterviewWire));
      }
    }
  }
  if (!completed && !input.signal?.aborted) throw new StreamInterruptedError("Story interview stream ended before completion");
}

export async function getUserPreferences(): Promise<UserPreferencesResponse> {
  type PreferencesWire = { preferences: Array<{ id: string; preference_type: string; content: string; strength: number }> };
  const response = await requestJson<PreferencesWire>(`${API_BASE_URL}/api/workspace/preferences`, { cache: "no-store" });
  return {
    preferences: response.preferences.map((item) => ({
      id: item.id,
      preferenceType: item.preference_type,
      content: item.content,
      strength: item.strength
    }))
  };
}

export async function updateUserPreferences(preferences: UserPreference[]): Promise<UserPreferencesResponse> {
  type PreferencesWire = { preferences: Array<{ id: string; preference_type: string; content: string; strength: number }> };
  const response = await requestJson<PreferencesWire>(`${API_BASE_URL}/api/workspace/preferences`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      preferences: preferences.map((item) => ({
        preference_type: item.preferenceType,
        content: item.content,
        strength: item.strength
      }))
    })
  });
  return {
    preferences: response.preferences.map((item) => ({
      id: item.id,
      preferenceType: item.preference_type,
      content: item.content,
      strength: item.strength
    }))
  };
}

export async function updateStory(storyId: string, input: UpdateStoryInput): Promise<WorkspaceResponse> {
  return requestJson<WorkspaceResponse>(`${API_BASE_URL}/api/workspace/stories/${storyId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      title: input.title,
      custom_prompt: input.customPrompt,
      interaction_mode: input.interactionMode,
      consistency_mode: input.consistencyMode
    })
  });
}

export async function deleteStory(storyId: string, activeStoryId?: string): Promise<WorkspaceResponse> {
  const url = new URL(`${API_BASE_URL}/api/workspace/stories/${storyId}`);
  if (activeStoryId) url.searchParams.set("active_story_id", activeStoryId);
  return requestJson<WorkspaceResponse>(url.toString(), {
    method: "DELETE"
  });
}

export async function createBranch(storyId: string, input: CreateBranchInput): Promise<WorkspaceResponse> {
  return requestJson<WorkspaceResponse>(`${API_BASE_URL}/api/workspace/stories/${storyId}/branches`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      name: input.name
    })
  });
}

export async function updateBranch(storyId: string, branchId: string, input: CreateBranchInput): Promise<WorkspaceResponse> {
  return requestJson<WorkspaceResponse>(`${API_BASE_URL}/api/workspace/stories/${storyId}/branches/${branchId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name: input.name })
  });
}

export async function duplicateBranch(storyId: string, branchId: string, input: CreateBranchInput): Promise<WorkspaceResponse> {
  return requestJson<WorkspaceResponse>(`${API_BASE_URL}/api/workspace/stories/${storyId}/branches/${branchId}/duplicate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name: input.name })
  });
}

export async function deleteBranch(storyId: string, branchId: string): Promise<WorkspaceResponse> {
  return requestJson<WorkspaceResponse>(`${API_BASE_URL}/api/workspace/stories/${storyId}/branches/${branchId}`, {
    method: "DELETE"
  });
}

export async function switchBranch(storyId: string, branchId: string): Promise<WorkspaceResponse> {
  return requestJson<WorkspaceResponse>(`${API_BASE_URL}/api/workspace/stories/${storyId}/branches/${branchId}/activate`, {
    method: "PATCH"
  });
}

export async function generateSessionSummary(storyId: string, branchId: string): Promise<WorkspaceResponse> {
  return requestJson<WorkspaceResponse>(`${API_BASE_URL}/api/workspace/stories/${storyId}/branches/${branchId}/summaries`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({})
  });
}

export async function downloadStoryExport(storyId: string, branchId: string, format: "markdown" | "json"): Promise<void> {
  if (typeof window === "undefined" || typeof document === "undefined" || typeof fetch !== "function") {
    throw new Error("Story export downloads require a browser runtime");
  }

  const url = new URL(`${API_BASE_URL}/api/workspace/stories/${storyId}/branches/${branchId}/export`);
  url.searchParams.set("format", format);
  const response = await fetch(url.toString(), {
    credentials: "include"
  });
  if (!response.ok) {
    throw new Error(`Export failed with status ${response.status}`);
  }

  const blob = await response.blob();
  const objectUrl = window.URL.createObjectURL(blob);
  const disposition = response.headers.get("Content-Disposition") ?? "";
  const filename = disposition.match(/filename="([^"]+)"/)?.[1] ?? `witscraft-story.${format === "markdown" ? "md" : "json"}`;
  const link = document.createElement("a");
  link.href = objectUrl;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.URL.revokeObjectURL(objectUrl);
}

export async function updateWorld(worldId: string, input: UpdateWorldInput, activeStoryId?: string): Promise<WorkspaceResponse> {
  const url = new URL(`${API_BASE_URL}/api/workspace/worlds/${worldId}`);
  if (activeStoryId) url.searchParams.set("active_story_id", activeStoryId);
  return requestJson<WorkspaceResponse>(url.toString(), {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      name: input.name,
      description: input.description,
      genre: input.genre
    })
  });
}

export async function createWorld(input: UpdateWorldInput, activeStoryId: string): Promise<WorkspaceResponse> {
  const url = new URL(`${API_BASE_URL}/api/workspace/worlds`);
  url.searchParams.set("active_story_id", activeStoryId);
  return requestJson<WorkspaceResponse>(url.toString(), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input)
  });
}

export async function selectStoryWorld(storyId: string, worldId: string): Promise<WorkspaceResponse> {
  return requestJson<WorkspaceResponse>(`${API_BASE_URL}/api/workspace/stories/${storyId}/world`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ world_id: worldId })
  });
}

export async function deleteWorld(worldId: string, activeStoryId: string): Promise<WorkspaceResponse> {
  const url = new URL(`${API_BASE_URL}/api/workspace/worlds/${worldId}`);
  url.searchParams.set("active_story_id", activeStoryId);
  return requestJson<WorkspaceResponse>(url.toString(), { method: "DELETE" });
}

export async function updateCharacter(characterId: string, input: UpdateCharacterInput, activeStoryId?: string): Promise<WorkspaceResponse> {
  const url = new URL(`${API_BASE_URL}/api/workspace/characters/${characterId}`);
  if (activeStoryId) url.searchParams.set("active_story_id", activeStoryId);
  return requestJson<WorkspaceResponse>(url.toString(), {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      name: input.name,
      role: input.role
    })
  });
}

export async function createCharacter(worldId: string, input: UpdateCharacterInput, activeStoryId: string): Promise<WorkspaceResponse> {
  const url = new URL(`${API_BASE_URL}/api/workspace/worlds/${worldId}/characters`);
  url.searchParams.set("active_story_id", activeStoryId);
  return requestJson<WorkspaceResponse>(url.toString(), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input)
  });
}

export async function deleteCharacter(characterId: string, activeStoryId: string): Promise<WorkspaceResponse> {
  const url = new URL(`${API_BASE_URL}/api/workspace/characters/${characterId}`);
  url.searchParams.set("active_story_id", activeStoryId);
  return requestJson<WorkspaceResponse>(url.toString(), { method: "DELETE" });
}

export async function updateMemoryItem(memoryId: string, input: UpdateMemoryInput, activeStoryId?: string): Promise<WorkspaceResponse> {
  const url = new URL(`${API_BASE_URL}/api/workspace/memories/${memoryId}`);
  if (activeStoryId) url.searchParams.set("active_story_id", activeStoryId);
  return requestJson<WorkspaceResponse>(url.toString(), {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      content: input.content,
      importance: input.importance
    })
  });
}

export async function updateCanonFact(factId: string, input: UpdateCanonFactInput, activeStoryId?: string): Promise<WorkspaceResponse> {
  const url = new URL(`${API_BASE_URL}/api/workspace/canon-facts/${factId}`);
  if (activeStoryId) url.searchParams.set("active_story_id", activeStoryId);
  return requestJson<WorkspaceResponse>(url.toString(), {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      content: input.content,
      importance: input.importance
    })
  });
}

export async function sendStoryMessage(input: {
  message: string;
  provider?: string;
  model?: string;
  purpose?: StoryPurpose;
  storyId?: string;
  branchId?: string;
  command?: "regenerate" | "rewrite";
  targetMessageId?: string;
  idempotencyKey?: string;
  branchVersion?: number;
}): Promise<ChatResponse> {
  return requestJson<ChatResponse>(`${API_BASE_URL}/api/chat/send`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(input.idempotencyKey ? { "Idempotency-Key": input.idempotencyKey } : {})
    },
    body: JSON.stringify({
      message: input.message,
      story_id: input.storyId,
      branch_id: input.branchId,
      provider: input.provider,
      model: input.model,
      purpose: input.purpose ?? "normal_chat",
      command: input.command,
      target_message_id: input.targetMessageId,
      idempotency_key: input.idempotencyKey,
      branch_version: input.branchVersion
    })
  });
}

export async function streamStoryMessage(
  input: {
    message: string;
    provider?: string;
    model?: string;
    purpose?: StoryPurpose;
    storyId?: string;
    branchId?: string;
    signal?: AbortSignal;
    idempotencyKey?: string;
    branchVersion?: number;
  },
  handlers: {
    onStart?: (event: Record<string, unknown>) => void;
    onDelta?: (content: string) => void;
    onReplace?: (content: string) => void;
    onDone?: (response: ChatResponse) => void;
  }
): Promise<void> {
  if (typeof fetch !== "function") {
    const response = await sendStoryMessage(input);
    handlers.onDelta?.(response.content);
    handlers.onDone?.(response);
    return;
  }

  const response = await fetch(`${API_BASE_URL}/api/chat/stream`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(input.idempotencyKey ? { "Idempotency-Key": input.idempotencyKey } : {})
    },
    credentials: "include",
    signal: input.signal,
    body: JSON.stringify({
      message: input.message,
      story_id: input.storyId,
      branch_id: input.branchId,
      provider: input.provider,
      model: input.model,
      purpose: input.purpose ?? "normal_chat",
      idempotency_key: input.idempotencyKey,
      branch_version: input.branchVersion
    })
  });
  if (!response.ok || !response.body) {
    let message = `Stream request failed with status ${response.status}`;
    try {
      const payload = await response.json() as { detail?: string };
      if (payload.detail) message = payload.detail;
    } catch {
      // Keep the status fallback when the upstream did not return JSON.
    }
    throw new ApiError(message, response.status);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let completed = false;

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const events = buffer.split("\n\n");
    buffer = events.pop() ?? "";

    for (const eventBlock of events) {
      const lines = eventBlock.split("\n");
      const eventName = lines.find((line) => line.startsWith("event: "))?.slice(7).trim();
      const dataLine = lines.find((line) => line.startsWith("data: "));
      if (!dataLine) continue;
      let payload: Record<string, unknown>;
      try {
        payload = JSON.parse(dataLine.slice(6)) as Record<string, unknown>;
      } catch {
        throw new StreamInterruptedError("Stream returned malformed event data");
      }
      if (eventName === "start") handlers.onStart?.(payload);
      if (eventName === "delta") handlers.onDelta?.(String(payload.content ?? ""));
      if (eventName === "replace") handlers.onReplace?.(String(payload.content ?? ""));
      if (eventName === "error") {
        throw new ApiError(String(payload.detail ?? "Generation failed"), Number(payload.status ?? 500));
      }
      if (eventName === "done") {
        completed = true;
        handlers.onDone?.(payload.response as ChatResponse);
      }
    }
  }
  if (!completed && !input.signal?.aborted) throw new StreamInterruptedError();
}
