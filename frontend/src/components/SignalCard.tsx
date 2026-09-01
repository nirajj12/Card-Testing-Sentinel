import { useState } from "react";
import type { LucideIcon } from "lucide-react";

export function SignalCard({ icon: Icon, title, copy, example }: { icon: LucideIcon; title: string; copy: string; example: string }) {
  const [expanded, setExpanded] = useState(false);
  return <button className={`signal-story-card ${expanded ? "expanded" : ""}`} type="button" onClick={() => setExpanded(!expanded)} aria-expanded={expanded}>
    <span className="signal-card-icon"><Icon/></span><span className="signal-card-title">{title}</span><span className="signal-card-copy">{copy}</span><span className="signal-card-example">{example}</span><span className="signal-card-hint">{expanded ? "Hide example" : "Show example"}</span>
  </button>;
}
