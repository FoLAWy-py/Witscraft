import type { ChatResponse, StoryPurpose } from "../types";
import { API_BASE_URL, ApiError, StreamInterruptedError, requestJson } from "./core";

type StoryMessageInput = {
  message: string;
  purpose?: StoryPurpose;
  storyId?: string;
  branchId?: string;
  command?: "regenerate" | "rewrite";
  targetMessageId?: string;
  signal?: AbortSignal;
  idempotencyKey?: string;
  branchVersion?: number;
  controlMode?: "player_action" | "continue";
};

export async function sendStoryMessage(input: StoryMessageInput): Promise<ChatResponse> {
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
      purpose: input.purpose ?? "normal_chat",
      command: input.command,
      target_message_id: input.targetMessageId,
      idempotency_key: input.idempotencyKey,
      branch_version: input.branchVersion,
      control_mode: input.controlMode ?? "player_action"
    })
  });
}

export async function streamStoryMessage(
  input: StoryMessageInput,
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
      purpose: input.purpose ?? "normal_chat",
      idempotency_key: input.idempotencyKey,
      branch_version: input.branchVersion,
      control_mode: input.controlMode ?? "player_action"
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
