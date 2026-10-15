"use client";

import { ReactNode, useId, useLayoutEffect, useRef, useState } from "react";

const MARGIN = 8;

/** Accessible tooltip: shows on hover and keyboard focus (after a short delay),
 *  linked with aria-describedby, and kept inside the viewport (shifts sideways,
 *  flips below when there is no room above). */
export default function Tip({ text, children, side = "top" }: { text: ReactNode; children: ReactNode; side?: "top" | "bottom" }) {
  const id = useId();
  const [open, setOpen] = useState(false);
  const [place, setPlace] = useState<{ dx: number; side: "top" | "bottom" }>({ dx: 0, side });
  const t = useRef<number | null>(null);
  const tipRef = useRef<HTMLSpanElement>(null);
  const show = () => { t.current = window.setTimeout(() => setOpen(true), 350); };
  const hide = () => { if (t.current) clearTimeout(t.current); setOpen(false); setPlace({ dx: 0, side }); };

  useLayoutEffect(() => {
    const el = tipRef.current;
    if (!open || !el) return;
    const r = el.getBoundingClientRect();
    let dx = 0;
    if (r.right > window.innerWidth - MARGIN) dx = window.innerWidth - MARGIN - r.right;
    if (r.left + dx < MARGIN) dx = MARGIN - r.left;
    let s = place.side;
    if (s === "top" && r.top < MARGIN) s = "bottom";
    else if (s === "bottom" && r.bottom > window.innerHeight - MARGIN) s = "top";
    if (dx !== place.dx || s !== place.side) setPlace({ dx: place.dx + dx, side: s });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  return (
    <span className="tip-wrap" onMouseEnter={show} onMouseLeave={hide} onFocus={show} onBlur={hide} aria-describedby={open ? id : undefined}
          onKeyDown={(e) => { if (e.key === "Escape") hide(); }}>
      {children}
      {open && (
        <span ref={tipRef} role="tooltip" id={id} className={`tip tip-${place.side}`}
              style={{ transform: `translateX(calc(-50% + ${place.dx}px))` }}>{text}</span>
      )}
    </span>
  );
}
