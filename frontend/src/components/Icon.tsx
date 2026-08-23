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

export function Cases({ size = 13 }: { size?: number }) {
  return (
    <svg {...BASE} strokeWidth={1.8} width={size} height={size} aria-hidden>
      <rect x="3" y="7" width="18" height="13" rx="2" />
      <path d="M8 7V5.5A1.5 1.5 0 0 1 9.5 4h5A1.5 1.5 0 0 1 16 5.5V7" />
    </svg>
  );
}

/** The three lines of a standing instruction. */
export function Lines({ size = 13 }: { size?: number }) {
  return (
    <svg {...BASE} strokeWidth={1.8} width={size} height={size} aria-hidden>
      <line x1="5" y1="7" x2="19" y2="7" /><line x1="5" y1="12" x2="19" y2="12" />
      <line x1="5" y1="17" x2="13" y2="17" />
    </svg>
  );
}

/** A four-point star — the assistant, everywhere it appears. */
export function Star({ size = 14 }: { size?: number }) {
  return (
    <svg {...BASE} strokeWidth={1.7} width={size} height={size} aria-hidden>
      <path d="M12 4l1.7 5.3L19 11l-5.3 1.7L12 18l-1.7-5.3L5 11l5.3-1.7z" />
    </svg>
  );
}

/** A table — the ZATCA extract, which is a grid of invoices and nothing else. */
export function Table({ size = 16 }: { size?: number }) {
  return (
    <svg {...BASE} width={size} height={size} aria-hidden>
      <rect x="4" y="4" width="16" height="16" rx="2" />
      <line x1="4" y1="9.5" x2="20" y2="9.5" /><line x1="9.5" y1="9.5" x2="9.5" y2="20" />
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
