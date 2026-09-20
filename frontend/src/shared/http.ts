export async function api<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`/api${path}`, {
    ...options,
    headers: { "Content-Type": "application/json", ...options?.headers },
  });
  const body = await response.json();
  if (!response.ok) {
    const detail =
      typeof body.detail === "string"
        ? body.detail
        : JSON.stringify(body.detail);
    throw new Error(detail || `请求失败 (${response.status})`);
  }
  return body as T;
}
