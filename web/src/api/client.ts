// The typed API client. `schema.d.ts` is generated from the backend (`npm run api:types`),
// so a change to the API that the frontend doesn't follow fails the type check.
import createClient from "openapi-fetch";

import type { components, paths } from "./schema";

type Schemas = components["schemas"];
export type CourseSummary = Schemas["CourseSummary"];
export type CourseDetail = Schemas["CourseDetail"];
export type DocumentOut = Schemas["DocumentOut"];
export type DocumentPages = Schemas["DocumentPages"];
export type SetSummary = Schemas["SetSummary"];
export type SetDetail = Schemas["SetDetail"];
export type SetIn = Schemas["SetIn"];
export type SetFormat = Schemas["SetFormat"];
export type Question = SetDetail["items"][number];
export type Source = Schemas["SourceOut"];
export type Bloom = Schemas["Bloom"];
export type AttemptOut = Schemas["AttemptOut"];
export type Given = number | boolean;

// The API is served from the same origin as the page (the dev server forwards /api to it).
export const api = createClient<paths>({
  baseUrl: window.location.origin,
  // Looked up on each call, not once at startup, so tests can replace `fetch`.
  fetch: (request) => globalThis.fetch(request),
});

/** A failed request, with a message that can be shown to the user as it is. */
export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
  }
}

interface Result<T> {
  data?: T;
  error?: unknown;
  response: Response;
}

/** The response's data, or an ApiError carrying the server's explanation. */
export function unwrap<T>({ data, error, response }: Result<T>): T {
  if (response.ok) return data as T;
  throw new ApiError(errorMessage(error, response.status), response.status);
}

/** FastAPI puts a message in `detail`; for invalid input it is a list of problems. */
export function errorMessage(error: unknown, status: number): string {
  if (typeof error === "string" && error.trim()) return error;
  const detail = (error as { detail?: unknown } | undefined)?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    const messages = detail.map((d: { msg?: string }) => d.msg).filter(Boolean);
    if (messages.length) return messages.join("; ");
  }
  return status === 404 ? "Not found." : "Something went wrong. Please try again.";
}
