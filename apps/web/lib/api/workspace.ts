import type {
  CreateBranchInput,
  CreateStoryInput,
  StoryDraftSuggestion,
  StoryInterviewMessage,
  StoryInterviewResponse,
  UpdateCanonFactInput,
  UpdateCharacterInput,
  UpdateMemoryInput,
  UpdateStoryInput,
  UpdateWorldInput,
  UserPreference,
  UserPreferencesResponse,
  WorkspaceResponse
} from "../types";
import { API_BASE_URL, ApiError, StreamInterruptedError, requestJson } from "./core";

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
      interaction_mode: input.interactionMode,
      planned_chapter_count: input.plannedChapterCount,
      target_chapter_length: input.targetChapterLength,
      chapter_length_unit: input.chapterLengthUnit,
      prose_language: input.proseLanguage
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
    planned_chapter_count: number;
    target_chapter_length: number;
    chapter_length_unit: "characters" | "words";
    prose_language: string;
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
      interaction_mode: input.draft.interactionMode,
      planned_chapter_count: input.draft.plannedChapterCount,
      target_chapter_length: input.draft.targetChapterLength,
      chapter_length_unit: input.draft.chapterLengthUnit,
      prose_language: input.draft.proseLanguage
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
      interactionMode: response.draft.interaction_mode,
      plannedChapterCount: response.draft.planned_chapter_count,
      targetChapterLength: response.draft.target_chapter_length,
      chapterLengthUnit: response.draft.chapter_length_unit,
      proseLanguage: response.draft.prose_language
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
