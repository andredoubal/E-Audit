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

/* ---- the reconciliation dashboard's source and category marks.
   Line icons in the same 24-grid and the same weight as the rest: on a KPI card the icon says
   *what kind of thing* the figure is — a filed return, a taxpayer listing, the Authority's
   extract — so three cards carrying similar amounts are still told apart at a glance. */
export function FileReturn({ size = 16 }: { size?: number }) {
  return (
    <svg {...BASE} width={size} height={size} aria-hidden>
      <path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z" />
      <path d="M14 3v5h5" />
      <line x1="9" y1="13" x2="15" y2="13" /><line x1="9" y1="16.5" x2="13" y2="16.5" />
    </svg>
  );
}

export function Ledger({ size = 16 }: { size?: number }) {
  return (
    <svg {...BASE} width={size} height={size} aria-hidden>
      <rect x="4" y="3" width="16" height="18" rx="2" />
      <line x1="8" y1="7.5" x2="16" y2="7.5" /><line x1="8" y1="12" x2="16" y2="12" />
      <line x1="8" y1="16.5" x2="12" y2="16.5" />
    </svg>
  );
}

export function Stamp({ size = 16 }: { size?: number }) {
  return (
    <svg {...BASE} width={size} height={size} aria-hidden>
      <path d="M9 3h6l-1 6h3a2 2 0 0 1 2 2v3H5v-3a2 2 0 0 1 2-2h3z" />
      <rect x="5" y="17" width="14" height="4" rx="1" />
    </svg>
  );
}

export function Hash({ size = 16 }: { size?: number }) {
  return (
    <svg {...BASE} width={size} height={size} aria-hidden>
      <line x1="9" y1="4" x2="7.5" y2="20" /><line x1="16.5" y1="4" x2="15" y2="20" />
      <line x1="4" y1="9.5" x2="20" y2="9.5" /><line x1="4" y1="15" x2="20" y2="15" />
    </svg>
  );
}

export function Minus({ size = 16 }: { size?: number }) {
  return (
    <svg {...BASE} width={size} height={size} aria-hidden>
      <circle cx="12" cy="12" r="8.5" /><line x1="8.5" y1="12" x2="15.5" y2="12" />
    </svg>
  );
}

export function Tag({ size = 16 }: { size?: number }) {
  return (
    <svg {...BASE} width={size} height={size} aria-hidden>
      <path d="M11 3H4v7l10 10 7-7z" /><circle cx="7.7" cy="6.7" r="1.2" />
    </svg>
  );
}

export function Shield({ size = 16 }: { size?: number }) {
  return (
    <svg {...BASE} width={size} height={size} aria-hidden>
      <path d="M12 3l7 3v5.5c0 4.3-2.9 7.8-7 9.5-4.1-1.7-7-5.2-7-9.5V6z" />
    </svg>
  );
}

export function Warn({ size = 15 }: { size?: number }) {
  return (
    <svg {...BASE} width={size} height={size} aria-hidden>
      <path d="M12 4l8.5 15h-17z" />
      <line x1="12" y1="10" x2="12" y2="14" /><line x1="12" y1="16.6" x2="12" y2="16.7" />
    </svg>
  );
}

export function Info({ size = 15 }: { size?: number }) {
  return (
    <svg {...BASE} width={size} height={size} aria-hidden>
      <circle cx="12" cy="12" r="8.5" />
      <line x1="12" y1="11" x2="12" y2="16.5" /><line x1="12" y1="7.8" x2="12" y2="7.9" />
    </svg>
  );
}
