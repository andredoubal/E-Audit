/** The line icons, drawn rather than typed. */
const BASE = {
  viewBox: "0 0 24 24",
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 1.6,
  strokeLinecap: "round" as const,
  strokeLinejoin: "round" as const,
};

export function Sparkles({ size = 17 }: { size?: number }) {
  return (
    <svg {...BASE} width={size} height={size} aria-hidden>
      <path d="M12 3l1.5 4.5L18 9l-4.5 1.5L12 15l-1.5-4.5L6 9l4.5-1.5z" />
      <path d="M19 3l.75 2.25L22 6l-2.25.75L19 9l-.75-2.25L16 6l2.25-.75z" />
    </svg>
  );
}

export function Sun({ size = 17 }: { size?: number }) {
  return (
    <svg {...BASE} width={size} height={size} aria-hidden>
      <circle cx="12" cy="12" r="4.5" />
      <line x1="12" y1="2" x2="12" y2="4" /><line x1="12" y1="20" x2="12" y2="22" />
      <line x1="4.93" y1="4.93" x2="6.34" y2="6.34" />
      <line x1="17.66" y1="17.66" x2="19.07" y2="19.07" />
      <line x1="2" y1="12" x2="4" y2="12" /><line x1="20" y1="12" x2="22" y2="12" />
      <line x1="4.93" y1="19.07" x2="6.34" y2="17.66" />
      <line x1="17.66" y1="6.34" x2="19.07" y2="4.93" />
    </svg>
  );
}

export function Moon({ size = 17 }: { size?: number }) {
  return (
    <svg {...BASE} width={size} height={size} aria-hidden>
      <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />
    </svg>
  );
}

export function Cases({ size = 17 }: { size?: number }) {
  return (
    <svg {...BASE} width={size} height={size} aria-hidden>
      <rect x="3" y="7" width="18" height="13" rx="2" />
      <path d="M8 7V5a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
      <line x1="3" y1="12" x2="21" y2="12" />
    </svg>
  );
}

export function Book({ size = 17 }: { size?: number }) {
  return (
    <svg {...BASE} width={size} height={size} aria-hidden>
      <path d="M4 5a2 2 0 0 1 2-2h13v16H6a2 2 0 0 0-2 2z" />
      <line x1="8" y1="8" x2="15" y2="8" /><line x1="8" y1="12" x2="15" y2="12" />
    </svg>
  );
}
