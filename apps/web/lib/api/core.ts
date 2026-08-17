export function getApiBaseUrl(): string {
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

export const API_BASE_URL = getApiBaseUrl();

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

export async function requestJson<T>(url: string, init?: RequestInit): Promise<T> {
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
