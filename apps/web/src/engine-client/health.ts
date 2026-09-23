// Mirrors engine/werkbank_engine/health.py (HealthReport, camelCase JSON).

export interface DependencyStatus {
  id: string;
  name: string;
  required: boolean;
  available: boolean;
  version: string | null;
  path: string | null;
  neededFor: string;
  fix: string | null;
  detail: string | null;
}

export interface HealthReport {
  status: 'ok' | 'degraded';
  engine: { version: string; python: string; platform: string };
  dependencies: DependencyStatus[];
  hardwareEncoders: { listed: string[]; usable: string[] };
  disk: { path: string; freeBytes: number; totalBytes: number } | null;
  folders: { inbox: string; outbox: string };
  tools: number;
  checkedAt: string;
}

export class EngineHttpError extends Error {
  readonly status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

/** Calls the engine API with the bearer token. `baseUrl` is '' when the page is served by the engine. */
export async function engineFetch(
  path: string,
  token: string,
  init: RequestInit = {},
  baseUrl = '',
): Promise<Response> {
  const headers = new Headers(init.headers);
  headers.set('Authorization', `Bearer ${token}`);
  const response = await fetch(`${baseUrl}${path}`, { ...init, headers, cache: 'no-store' });
  if (!response.ok) {
    throw new EngineHttpError(response.status, `${init.method ?? 'GET'} ${path} failed with ${response.status}`);
  }
  return response;
}

export async function fetchHealth(token: string, refresh = false, signal?: AbortSignal): Promise<HealthReport> {
  const response = await engineFetch(`/api/health${refresh ? '?refresh=true' : ''}`, token, { signal });
  return (await response.json()) as HealthReport;
}

export function missingRequired(health: HealthReport): DependencyStatus[] {
  return health.dependencies.filter((d) => d.required && !d.available);
}
