"use client";

import { useEffect, useId, useRef, useState } from "react";

/** Search box with a listbox: results from the first character, arrow keys + Enter, Escape to close. */
export default function Combo<T>({
  label, placeholder, search, render, onPick, keyOf,
}: {
  label: string;
  placeholder: string;
  search: (q: string) => Promise<T[]>;
  render: (item: T) => React.ReactNode;
  onPick: (item: T) => void;
  keyOf: (item: T) => string;
}) {
  const id = useId();
  const [q, setQ] = useState("");
  const [items, setItems] = useState<T[]>([]);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const [searched, setSearched] = useState("");
  const seq = useRef(0);

  useEffect(() => {
    if (!q.trim()) { setItems([]); setSearched(""); return; }
    const mine = ++seq.current;
    const t = setTimeout(async () => {
      const r = await search(q).catch(() => []);
      if (mine === seq.current) { setItems(r); setActive(0); setSearched(q); setOpen(true); }
    }, 120);
    return () => clearTimeout(t);
  }, [q, search]);

  function pick(it: T) { onPick(it); setQ(""); setItems([]); setOpen(false); }

  return (
    <div className="combo">
      <label htmlFor={id} className="sr-only">{label}</label>
      <input id={id} value={q} placeholder={placeholder} autoComplete="off" role="combobox"
             aria-expanded={open} aria-controls={`${id}-list`} aria-activedescendant={open && items[active] ? `${id}-${active}` : undefined}
             onChange={(e) => { setQ(e.target.value); setOpen(true); }}
             onBlur={() => setTimeout(() => setOpen(false), 150)}
             onKeyDown={(e) => {
               if (e.key === "ArrowDown") { e.preventDefault(); setActive((a) => Math.min(a + 1, items.length - 1)); }
               if (e.key === "ArrowUp") { e.preventDefault(); setActive((a) => Math.max(a - 1, 0)); }
               if (e.key === "Enter" && items[active]) { e.preventDefault(); pick(items[active]); }
               if (e.key === "Escape") setOpen(false);
             }} />
      {open && q.trim() && (
        <ul id={`${id}-list`} role="listbox" className="combo-list">
          {items.map((it, i) => (
            <li key={keyOf(it)} id={`${id}-${i}`} role="option" aria-selected={i === active}
                onMouseDown={(e) => { e.preventDefault(); pick(it); }} onMouseEnter={() => setActive(i)}>{render(it)}</li>
          ))}
          {items.length === 0 && searched === q && <li className="combo-empty">Nothing matches “{q}”.</li>}
        </ul>
      )}
    </div>
  );
}
