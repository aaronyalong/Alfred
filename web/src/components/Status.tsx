import type { ReactNode } from "react";

/** What a page shows while its data loads, or when loading failed. */
export function Loading({ error }: { error: Error | null }) {
  if (error) {
    return (
      <p className="notice" role="alert">
        {error.message}
      </p>
    );
  }
  return <p className="muted">Loading…</p>;
}

export function ErrorNote({ error }: { error: Error | null }) {
  if (!error) return null;
  return (
    <p className="error" role="alert">
      {error.message}
    </p>
  );
}

export function Pill({ tone, children }: { tone: "good" | "wait" | "bad"; children: ReactNode }) {
  return <span className={`pill pill-${tone}`}>{children}</span>;
}
