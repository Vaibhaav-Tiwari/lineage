"use client";

import { ReactNode, useId, useRef, useState } from "react";

/** Accessible tooltip: shows on hover and keyboard focus (after a short delay),
 *  linked with aria-describedby so screen readers announce it. */
export default function Tip({ text, children, side = "top" }: { text: ReactNode; children: ReactNode; side?: "top" | "bottom" }) {
  const id = useId();
  const [open, setOpen] = useState(false);
  const t = useRef<number | null>(null);
  const show = () => { t.current = window.setTimeout(() => setOpen(true), 350); };
  const hide = () => { if (t.current) clearTimeout(t.current); setOpen(false); };
  return (
    <span className="tip-wrap" onMouseEnter={show} onMouseLeave={hide} onFocus={show} onBlur={hide} aria-describedby={open ? id : undefined}
          onKeyDown={(e) => { if (e.key === "Escape") hide(); }}>
      {children}
      {open && <span role="tooltip" id={id} className={`tip tip-${side}`}>{text}</span>}
    </span>
  );
}
