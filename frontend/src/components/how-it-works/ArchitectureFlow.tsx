import { useState, type ElementType } from "react";
import {
  Ban, BarChart3, Check, Database, Eye, FilePlus2, History,
  Layers3, SearchCheck, ShieldCheck, ShoppingCart, SquareArrowOutUpRight,
} from "lucide-react";

export type Decision = "allow" | "review" | "block";
type NodeKey = "checkout" | "history" | "precheck" | "features" | "model" | "policy" | "create" | "open" | "review" | "block";

const details: Record<NodeKey, { title: string; label: string; body: string }> = {
  checkout: { label: "Current input", title: "Checkout Context", body: "The amount, merchant, device, session, and timing that are visible before payment starts." },
  history: { label: "Trusted input", title: "Trusted Prior History", body: "Verified outcomes and protected references from earlier attempts. The current payment result is not part of this history." },
  precheck: { label: "Preparation", title: "Sentinel Precheck", body: "Sentinel joins the current checkout with trusted earlier history before any Razorpay order is created." },
  features: { label: "Safe signals", title: "44 Causal Features", body: "These are measurable behaviour patterns—such as velocity and retry history—that genuinely exist at decision time." },
  model: { label: "Risk estimate", title: "Model v3.1", body: "The model estimates how closely the current behaviour resembles card testing. It provides a risk score; it does not block the checkout." },
  policy: { label: "Decision layer", title: "Policy v2 Action", body: "Policy v2 considers the risk score and supporting evidence, then chooses what the system should do next." },
  create: { label: "Allow outcome", title: "Create Razorpay Test Mode Order", body: "ALLOW gives the backend permission to create an order. It does not mean Razorpay has approved the payment." },
  open: { label: "Payment begins", title: "Open Standard Checkout", body: "Only after an order exists does the customer enter payment details in Razorpay Standard Checkout." },
  review: { label: "Review outcome", title: "Order Creation Suppressed", body: "REVIEW means risk is elevated but the evidence is not strong enough for BLOCK. The prototype returns HTTP 409; there is no human-review queue." },
  block: { label: "Block outcome", title: "Order Creation Suppressed", body: "BLOCK means risk and supporting evidence are strong enough to stop this attempt. No Razorpay order is created." },
};

function ArchitectureNode({ nodeKey, icon: Icon, title, subtitle, selected, onSelect, badge }: {
  nodeKey: NodeKey; icon: ElementType; title: string; subtitle: string; selected: boolean; onSelect: (key: NodeKey) => void; badge?: string;
}) {
  return <button type="button" className={`hiw-node ${selected ? "is-selected" : ""}`} onClick={() => onSelect(nodeKey)} aria-pressed={selected}>
    <span className="hiw-node-icon"><Icon aria-hidden="true" /></span>
    <span><strong>{title}</strong><small>{subtitle}</small>{badge && <b>{badge}</b>}</span>
  </button>;
}

function PolicyNode({ selected, onSelect }: { selected: boolean; onSelect: (key: NodeKey) => void }) {
  return <button type="button" className={`hiw-policy-node ${selected ? "is-selected" : ""}`} onClick={() => onSelect("policy")} aria-pressed={selected}>
    <span className="hiw-policy-inner"><ShieldCheck aria-hidden="true" /><small>Decision layer</small><strong>Policy v2 Action</strong><em>Chooses what happens next</em></span>
  </button>;
}

const options = [["allow", Check, "Allow"], ["review", Eye, "Review"], ["block", Ban, "Block"]] as const;

function DecisionSelector({ active, onChange }: { active: Decision; onChange: (value: Decision) => void }) {
  return <div className="hiw-decision-selector" role="group" aria-label="Choose a policy outcome">
    {options.map(([value, Icon, label]) => <button key={value} type="button" className={`${value} ${active === value ? "is-active" : ""}`} onClick={() => onChange(value)} aria-pressed={active === value}><Icon aria-hidden="true" />{label}</button>)}
  </div>;
}

export function ArchitectureFlow() {
  const [activePath, setActivePath] = useState<Decision>("allow");
  const [selectedNode, setSelectedNode] = useState<NodeKey>("policy");
  const detail = details[selectedNode];
  const suppressed = activePath !== "allow";
  const choosePath = (path: Decision) => { setActivePath(path); setSelectedNode(path === "allow" ? "create" : path); };

  return <section className="hiw-architecture page-width" aria-labelledby="architecture-title">
    <header className="hiw-architecture-heading compact"><div><span>Interactive architecture</span><h2 id="architecture-title">Follow one checkout</h2></div><p>Select ALLOW, REVIEW, or BLOCK to see where the checkout goes.</p></header>
    <div className={`hiw-architecture-canvas active-${activePath}`}>
      <div className="hiw-dot-field" aria-hidden="true" />

      <div className="hiw-inputs" aria-label="Information available to Sentinel">
        <ArchitectureNode nodeKey="checkout" icon={ShoppingCart} title="Current Checkout Context" subtitle="What the merchant can see now" selected={selectedNode === "checkout"} onSelect={setSelectedNode} />
        <ArchitectureNode nodeKey="history" icon={History} title="Trusted Prior History" subtitle="Verified earlier outcomes only" selected={selectedNode === "history"} onSelect={setSelectedNode} />
      </div>
      <div className="hiw-input-merge" aria-hidden="true"><i /><i /><span /></div>

      <div className="hiw-trunk">
        <ArchitectureNode nodeKey="precheck" icon={SearchCheck} title="Sentinel Precheck" subtitle="Combines the available context" selected={selectedNode === "precheck"} onSelect={setSelectedNode} />
        <i className="hiw-trunk-line l1" aria-hidden="true" />
        <ArchitectureNode nodeKey="features" icon={Layers3} title="44 Causal Features" subtitle="Safe facts available before payment" selected={selectedNode === "features"} onSelect={setSelectedNode} />
        <i className="hiw-trunk-line l2" aria-hidden="true" />
        <ArchitectureNode nodeKey="model" icon={BarChart3} title="Model v3.1" subtitle="Estimates card-testing risk" selected={selectedNode === "model"} onSelect={setSelectedNode} />
        <i className="hiw-trunk-line l3" aria-hidden="true" />
        <PolicyNode selected={selectedNode === "policy"} onSelect={setSelectedNode} />
      </div>

      <div className="hiw-branch-rail" aria-hidden="true" />
      <DecisionSelector active={activePath} onChange={choosePath} />

      <div className="hiw-outcomes">
        <div className={`hiw-decision-route allow ${activePath === "allow" ? "is-active" : "is-inactive"}`}>
          <i className="hiw-route-line" aria-hidden="true" />
          <ArchitectureNode nodeKey="create" icon={FilePlus2} title="Create Razorpay Test Mode Order" subtitle="Only after ALLOW" selected={selectedNode === "create"} onSelect={setSelectedNode} />
          <i className="hiw-route-line short" aria-hidden="true" />
          <ArchitectureNode nodeKey="open" icon={SquareArrowOutUpRight} title="Open Standard Checkout" subtitle="Payment can now begin" selected={selectedNode === "open"} onSelect={setSelectedNode} />
        </div>
        <div className={`hiw-decision-route suppress ${suppressed ? `is-active ${activePath}` : "is-inactive"}`}>
          <i className="hiw-converge-line" aria-hidden="true" />
          <ArchitectureNode nodeKey={activePath === "block" ? "block" : "review"} icon={Ban} title="Suppress Order Creation" subtitle="Razorpay is never called" badge="HTTP 409" selected={selectedNode === "review" || selectedNode === "block"} onSelect={setSelectedNode} />
          <small className="hiw-shared-outcome">REVIEW and BLOCK share this safe outcome for the current attempt.</small>
        </div>
      </div>

      <div className="hiw-detail-panel" aria-live="polite"><span>{detail.label}</span><div><strong>{detail.title}</strong><p>{detail.body}</p></div><small>Choose any card to learn more</small></div>
      <div className="hiw-truth-strip" aria-label="Architecture summary"><span><Database aria-hidden="true" />Runtime-scored</span><i /><span><ShieldCheck aria-hidden="true" />Policy-controlled</span><i /><span><Check aria-hidden="true" />Webhook-verified</span></div>
    </div>
  </section>;
}
