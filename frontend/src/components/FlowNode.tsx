import { motion } from "framer-motion";
import type { CSSProperties, PointerEvent, ReactNode } from "react";

export function FlowNode({ className, eyebrow, title, description, icon, branch, onActivate }: { className: string; eyebrow?: string; title: ReactNode; description: string; icon?: ReactNode; branch?: "allow" | "review" | "block"; onActivate?: (branch: "allow" | "review" | "block") => void }) {
  function tilt(event: PointerEvent<HTMLButtonElement>) {
    const bounds = event.currentTarget.getBoundingClientRect();
    const x = (event.clientX - bounds.left) / bounds.width - .5;
    const y = (event.clientY - bounds.top) / bounds.height - .5;
    event.currentTarget.style.setProperty("--tilt-x", `${-y * 5}deg`);
    event.currentTarget.style.setProperty("--tilt-y", `${x * 7}deg`);
  }
  const reset = (event: PointerEvent<HTMLButtonElement>) => { event.currentTarget.style.setProperty("--tilt-x", "0deg"); event.currentTarget.style.setProperty("--tilt-y", "0deg"); };
  return <motion.button type="button" className={`flow-node ${className}`} data-branch={branch || "shared"} onPointerMove={tilt} onPointerLeave={reset} onMouseEnter={() => branch && onActivate?.(branch)} onFocus={() => branch && onActivate?.(branch)} onClick={() => branch && onActivate?.(branch)} whileHover={{ y: -5, scale: 1.015 }} transition={{ duration: .2 }} style={{ "--tilt-x": "0deg", "--tilt-y": "0deg" } as CSSProperties}>
    {eyebrow && <span className="flow-eyebrow">{eyebrow}</span>}{icon && <i className="flow-icon">{icon}</i>}<strong>{title}</strong><small>{description}</small><span className="node-tooltip">{description}</span>
  </motion.button>;
}
