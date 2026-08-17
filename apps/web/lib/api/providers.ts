import type {
  ModelHealthResponse,
  ModelRoutesResponse,
  ProvidersResponse,
  StoryPurpose
} from "../types";
import { API_BASE_URL, requestJson } from "./core";

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

export async function revertModelRoutes(): Promise<ModelRoutesResponse> {
  return requestJson<ModelRoutesResponse>(`${API_BASE_URL}/api/providers/routes/revert`, {
    method: "POST"
  });
}
