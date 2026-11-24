export const API_BASE = import.meta.env.VITE_API_BASE_URL || "/api/v1";

export class ApiError extends Error {
  status: number;
  code?: number;

  constructor(message: string, status = 0, code?: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
  }
}

interface RequestOptions {
  method?: string;
  body?: unknown;
  headers?: Record<string, string>;
  signal?: AbortSignal;
}

function authHeaders(): Record<string, string> {
  const token = localStorage.getItem("de.token");
  return token ? { Authorization: `Bearer ${token}` } : {};
}

function handleUnauthorized(): void {
  localStorage.removeItem("de.token");
  localStorage.removeItem("de.user");
  if (!window.location.hash.startsWith("#/login")) {
    window.location.hash = "#/login";
  }
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const headers: Record<string, string> = {
    ...authHeaders(),
    ...(options.headers || {}),
  };
  if (options.body !== undefined) {
    headers["Content-Type"] = "application/json";
  }

  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      method: options.method || "GET",
      headers,
      body: options.body !== undefined ? JSON.stringify(options.body) : undefined,
      signal: options.signal,
    });
  } catch (err) {
    throw new ApiError("网络请求失败，请确认后端服务已启动", 0);
  }

  let payload: any = null;
  try {
    payload = await response.json();
  } catch {
    // ignore non-JSON responses
  }

  if (response.status === 401) {
    handleUnauthorized();
    throw new ApiError(payload?.message || "登录已过期，请重新登录", 401, payload?.code);
  }
  if (!response.ok) {
    throw new ApiError(
      payload?.message || `请求失败（${response.status}）`,
      response.status,
      payload?.code,
    );
  }
  if (payload && payload.code !== 0 && payload.code !== undefined) {
    throw new ApiError(payload.message || "请求失败", response.status, payload.code);
  }
  return (payload?.data ?? payload) as T;
}

export const api = {
  get<T>(path: string, options?: RequestOptions): Promise<T> {
    return request<T>(path, { ...options, method: "GET" });
  },
  post<T>(path: string, body?: unknown, options?: RequestOptions): Promise<T> {
    return request<T>(path, { ...options, method: "POST", body });
  },
  patch<T>(path: string, body?: unknown, options?: RequestOptions): Promise<T> {
    return request<T>(path, { ...options, method: "PATCH", body });
  },
  put<T>(path: string, body?: unknown, options?: RequestOptions): Promise<T> {
    return request<T>(path, { ...options, method: "PUT", body });
  },
  delete<T>(path: string, options?: RequestOptions): Promise<T> {
    return request<T>(path, { ...options, method: "DELETE" });
  },
  async upload<T>(
    path: string,
    file: File,
    fields?: Record<string, string | number | undefined | null>,
  ): Promise<T> {
    const form = new FormData();
    form.append("file", file);
    for (const [key, value] of Object.entries(fields || {})) {
      if (value !== undefined && value !== null && value !== "") {
        form.append(key, String(value));
      }
    }
    const response = await fetch(`${API_BASE}${path}`, {
      method: "POST",
      headers: authHeaders(),
      body: form,
    });
    const payload = await response.json().catch(() => null);
    if (response.status === 401) {
      handleUnauthorized();
      throw new ApiError(payload?.message || "登录已过期", 401, payload?.code);
    }
    if (!response.ok) {
      throw new ApiError(payload?.message || `上传失败（${response.status}）`, response.status);
    }
    if (payload && payload.code !== 0 && payload.code !== undefined) {
      throw new ApiError(payload.message || "上传失败", response.status, payload.code);
    }
    return (payload?.data ?? payload) as T;
  },
  async download(path: string, filename: string): Promise<void> {
    const response = await fetch(`${API_BASE}${path}`, { headers: authHeaders() });
    if (response.status === 401) {
      handleUnauthorized();
      throw new ApiError("登录已过期", 401);
    }
    if (!response.ok) {
      throw new ApiError(`下载失败（${response.status}）`, response.status);
    }
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = filename;
    anchor.click();
    URL.revokeObjectURL(url);
  },
};
