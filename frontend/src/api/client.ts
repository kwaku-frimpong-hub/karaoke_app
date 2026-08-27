// Thin typed wrapper around fetch for the Friday Karaoke API.
// All paths are same-origin (/api/...) so the Vite dev proxy (and, later, the
// reverse proxy) forwards them to the backend.

export class ApiError extends Error {
  readonly status: number

  constructor(status: number, message: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

export interface RequestOptions {
  method?: 'GET' | 'POST' | 'PATCH' | 'DELETE'
  body?: unknown
  token?: string
}

export async function apiRequest<T>(
  path: string,
  options: RequestOptions = {},
): Promise<T> {
  const { method = 'GET', body, token } = options

  const headers: Record<string, string> = {}
  if (body !== undefined) headers['Content-Type'] = 'application/json'
  if (token) headers['Authorization'] = `Bearer ${token}`

  const response = await fetch(path, {
    method,
    headers,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  })

  if (!response.ok) {
    let message = `request failed (${response.status})`
    try {
      const data = (await response.json()) as { detail?: unknown }
      if (typeof data.detail === 'string') message = data.detail
    } catch {
      // Non-JSON error body: keep the fallback message.
    }
    throw new ApiError(response.status, message)
  }

  if (response.status === 204) {
    return undefined as T
  }
  return (await response.json()) as T
}

/** Fetch a non-JSON response body (e.g. the QR SVG) as text. */
export async function apiRequestText(
  path: string,
  options: RequestOptions = {},
): Promise<string> {
  const { method = 'GET', body, token } = options

  const headers: Record<string, string> = {}
  if (body !== undefined) headers['Content-Type'] = 'application/json'
  if (token) headers['Authorization'] = `Bearer ${token}`

  const response = await fetch(path, {
    method,
    headers,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  })

  if (!response.ok) {
    let message = `request failed (${response.status})`
    try {
      const data = (await response.json()) as { detail?: unknown }
      if (typeof data.detail === 'string') message = data.detail
    } catch {
      // Non-JSON error body: keep the fallback message.
    }
    throw new ApiError(response.status, message)
  }

  return response.text()
}
