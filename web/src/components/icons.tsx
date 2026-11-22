// Inline stroke icons, drawn in the current text color unless a color is given.

const base = {
  viewBox: "0 0 24 24",
  fill: "none",
  strokeLinecap: "round",
  strokeLinejoin: "round",
} as const;

export function CheckIcon({ label, size = 20 }: { label?: string; size?: number }) {
  return (
    <svg
      {...base}
      {...a11y(label)}
      width={size}
      height={size}
      stroke="var(--good)"
      strokeWidth="2.4"
    >
      <path d="M5 12.5l4.5 4.5L19 7" />
    </svg>
  );
}

export function CrossIcon({ label, size = 20 }: { label?: string; size?: number }) {
  return (
    <svg
      {...base}
      {...a11y(label)}
      width={size}
      height={size}
      stroke="var(--bad)"
      strokeWidth="2.4"
    >
      <path d="M6 6l12 12" />
      <path d="M18 6L6 18" />
    </svg>
  );
}

export function SpinnerIcon() {
  return (
    <svg
      {...base}
      aria-hidden="true"
      className="spin"
      width="20"
      height="20"
      stroke="var(--accent)"
      strokeWidth="2.4"
    >
      <circle cx="12" cy="12" r="8" strokeDasharray="30 20" />
    </svg>
  );
}

export function PendingIcon() {
  return (
    <svg {...base} aria-hidden="true" width="20" height="20" stroke="#b7bec8" strokeWidth="2">
      <circle cx="12" cy="12" r="7" />
    </svg>
  );
}

export function UploadIcon() {
  return (
    <svg
      {...base}
      aria-hidden="true"
      width="32"
      height="32"
      stroke="var(--accent)"
      strokeWidth="1.8"
    >
      <path d="M12 16V4" />
      <path d="M7 9l5-5 5 5" />
      <path d="M4 16v3a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-3" />
    </svg>
  );
}

export function FlagIcon() {
  return (
    <svg {...base} aria-hidden="true" width="16" height="16" stroke="currentColor" strokeWidth="2">
      <path d="M5 21V4" />
      <path d="M5 4h11l-2 4 2 4H5" />
    </svg>
  );
}

/** With a label the icon is announced; without one it is decoration. */
function a11y(label: string | undefined) {
  return label
    ? ({ role: "img", "aria-label": label } as const)
    : ({ "aria-hidden": true } as const);
}
