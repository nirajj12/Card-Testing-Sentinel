import { CheckCircle2, CreditCard, Eye, Fingerprint, Gauge, GitBranch, History, Server, ShieldCheck, XCircle } from "lucide-react";
import { useRef, useState } from "react";

type Branch = "allow" | "review" | "block";
const branches: Branch[] = ["allow", "review", "block"];
const details = {
  allow: { icon: CheckCircle2, title: "Continue to Razorpay", copy: "The backend creates a Razorpay Test order, Standard Checkout opens, and payment success is trusted only after server-side signature verification.", steps: ["Order created on the server", "Standard Checkout opens", "Signature verified by the backend", "Verified outcome can inform future checks"] },
  review: { icon: Eye, title: "Pause for merchant intervention", copy: "The attempt stops before order creation. REVIEW does not claim that Sentinel performs an OTP, CAPTCHA, 3DS challenge or manual queue.", steps: ["Merchant intervention recommended", "No Razorpay order is created", "Checkout does not open automatically", "The attempt remains explainable"] },
  block: { icon: XCircle, title: "Temporarily stop the payment path", copy: "Order creation is suppressed completely for the attempt. Razorpay is not contacted and the customer can retry later with a new check.", steps: ["Temporary block returned", "Order creation suppressed", "Checkout never opens", "No processor outcome is invented"] },
} as const;
const signals = [["Attempt velocity", "Recent attempts over short and daily windows", Gauge], ["Payment diversity", "Changes across protected card references", CreditCard], ["Decline history", "Verified prior outcomes and retry patterns", History], ["Session context", "Session changes and protected network references", Fingerprint]] as const;

export function HowItWorksPage() {
  const [active, setActive] = useState<Branch>("allow");
  const tabs = useRef<Array<HTMLButtonElement | null>>([]);
  function moveTab(event: React.KeyboardEvent, index: number) {
    let next = index;
    if (event.key === "ArrowRight") next = (index + 1) % branches.length;
    else if (event.key === "ArrowLeft") next = (index - 1 + branches.length) % branches.length;
    else if (event.key === "Home") next = 0;
    else if (event.key === "End") next = branches.length - 1;
    else return;
    event.preventDefault(); setActive(branches[next]); tabs.current[next]?.focus();
  }
  const branch = details[active]; const BranchIcon = branch.icon;
  return <main className="how-page">
    <header className="page-hero page-width"><span className="eyebrow-pill"><i/>How Sentinel works</span><h1>A clear decision point <em>before Razorpay.</em></h1><p>Sentinel sits between customer intent and order creation. It evaluates recent merchant-side behaviour, returns one bounded action, and keeps the gateway path honest.</p></header>
    <section className="shared-path page-width" aria-labelledby="shared-title"><header><span>Shared decision path</span><h2 id="shared-title">Every attempt starts the same way.</h2></header><ol><li><b>1</b><CreditCard/><strong>Customer clicks pay</strong><p>The merchant sends payment context to its backend.</p></li><li><b>2</b><Server/><strong>Sentinel precheck</strong><p>Trusted recent history becomes a compact signal set.</p></li><li><b>3</b><GitBranch/><strong>Decision policy</strong><p>ALLOW, REVIEW or TEMPORARY BLOCK is returned.</p></li></ol></section>
    <section className="branch-section page-width"><div className="branch-tabs" role="tablist" aria-label="Decision paths">{branches.map((name, index) => <button key={name} ref={(node) => { tabs.current[index] = node; }} role="tab" id={`tab-${name}`} aria-selected={active === name} aria-controls={`panel-${name}`} tabIndex={active === name ? 0 : -1} className={`${name} ${active === name ? "active" : ""}`} onClick={() => setActive(name)} onKeyDown={(event) => moveTab(event, index)}>{name === "block" ? "TEMPORARY BLOCK" : name.toUpperCase()}</button>)}</div><article className={`branch-panel ${active}`} role="tabpanel" id={`panel-${active}`} aria-labelledby={`tab-${active}`}><div className="branch-lead"><BranchIcon/><span>{active === "block" ? "TEMPORARY BLOCK" : active.toUpperCase()} path</span><h2>{branch.title}</h2><p>{branch.copy}</p></div><ol>{branch.steps.map((step, index) => <li key={step}><b>{index + 1}</b><span>{step}</span></li>)}</ol></article></section>
    <section className="section-block page-width"><header className="section-heading compact"><div><span>Signal categories</span><h2>39 categories from behaviour available at decision time.</h2></div><p>They describe patterns, not identity. Sentinel uses protected references and verified merchant history; it does not accept raw card credentials.</p></header><div className="signal-grid">{signals.map(([title, copy, Icon]) => <article key={title}><Icon/><h3>{title}</h3><p>{copy}</p></article>)}</div></section>
    <section className="comparison-section"><div className="page-width"><header><span>Responsibilities</span><h2>Sentinel and Razorpay do different jobs.</h2></header><div className="comparison-grid"><article><ShieldCheck/><h3>Sentinel</h3><ul><li>Checks risk before order creation</li><li>Returns a bounded merchant action</li><li>Stores protected references and trusted outcomes</li><li>Explains the signals behind an intervention</li></ul></article><article><CreditCard/><h3>Razorpay Test Mode</h3><ul><li>Creates the payment order after ALLOW</li><li>Collects payment credentials in Standard Checkout</li><li>Processes the test payment</li><li>Provides a signature for server verification</li></ul></article></div></div></section>
    <section className="safeguards page-width"><div><ShieldCheck/><h2>Safeguards</h2><p>Pre-authorization boundary, server-side order creation, signature verification, idempotent requests and protected identifiers.</p></div><div><Eye/><h2>Limitations</h2><p>Synthetic data, test gateway only, meaningful false positives, missed patient attacks and no claim of production fraud performance.</p></div></section>
  </main>;
}
