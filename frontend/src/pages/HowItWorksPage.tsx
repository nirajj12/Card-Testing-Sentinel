import { Check, CreditCard, GitBranch, History, MousePointer2, ScanSearch, Server, ShieldCheck, Store, X } from "lucide-react";
import { motion } from "framer-motion";
import { useState } from "react";
import { FlowNode } from "../components/FlowNode";

type Branch = "allow" | "review" | "block";

const branchCopy = {
  allow: { title: "A verified order path", copy: "Only ALLOW reaches Razorpay. The backend creates the Test order, Standard Checkout opens, and the callback remains untrusted until the server verifies its signature." },
  review: { title: "An honest intervention boundary", copy: "REVIEW keeps its current policy meaning: merchant intervention recommended. Sentinel does not invent an OTP, CAPTCHA, 3DS or manual queue." },
  block: { title: "A path that ends before Razorpay", copy: "TEMPORARY BLOCK suppresses order creation completely. There is no Razorpay order and Checkout never opens." },
};

export function HowItWorksPage() {
  const [active, setActive] = useState<Branch>("allow");
  return <main className="architecture-page">
    <header className="architecture-hero page-width"><div><span className="eyebrow-pill"><i/>Interactive payment architecture</span><h1>The decision before<br/><em>the payment path.</em></h1></div><div><p>Sentinel sits between customer payment intent and Razorpay order creation. Select a branch to follow only the systems that participate.</p><div className="branch-switcher">{(["allow","review","block"] as Branch[]).map((branch) => <button key={branch} className={active === branch ? `active ${branch}` : ""} type="button" onClick={() => setActive(branch)}>{branch.toUpperCase()}</button>)}</div></div></header>
    <section className="flow-showcase page-width" data-active={active}>
      <div className="flow-canvas">
        <div className="flow-grid" aria-hidden="true"/>
        <svg className="flow-connectors" viewBox="0 0 1500 780" preserveAspectRatio="none" aria-hidden="true">
          <defs><marker id="arrow" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0 0L8 4L0 8Z"/></marker></defs>
          <path className="connector shared" d="M225 390 C275 390 275 390 320 390 M520 390 C565 390 565 390 610 390"/>
          <path className="connector allow" d="M800 390 C845 390 825 155 885 155 M1045 155 C1095 155 1095 155 1140 155 M1310 155 C1360 155 1370 300 1300 390 M1300 390 C1360 390 1360 620 1290 620"/>
          <path className="connector review" d="M800 390 C845 390 845 390 885 390 M1045 390 C1095 390 1095 390 1140 390"/>
          <path className="connector block" d="M800 390 C845 390 825 625 885 625 M1045 625 C1095 625 1095 625 1140 625"/>
          <path className="connector-energy allow" d="M800 390 C845 390 825 155 885 155 M1045 155 C1095 155 1095 155 1140 155 M1310 155 C1360 155 1370 300 1300 390 M1300 390 C1360 390 1360 620 1290 620"/>
          <path className="connector-energy review" d="M800 390 C845 390 845 390 885 390 M1045 390 C1095 390 1095 390 1140 390"/>
          <path className="connector-energy block" d="M800 390 C845 390 825 625 885 625 M1045 625 C1095 625 1095 625 1140 625"/>
        </svg>
        <FlowNode className="node-customer" eyebrow="Customer" title="Clicks Pay" description="The merchant checkout captures payment intent." icon={<MousePointer2/>}/>
        <FlowNode className="node-precheck" eyebrow="POST /api/precheck" title="Sentinel precheck" description="Uses only information available before the current payment outcome exists." icon={<ScanSearch/>}/>
        <FlowNode className="node-policy" eyebrow="Trusted server history" title="Risk + policy" description="A bounded operational decision is selected from model and policy evidence." icon={<GitBranch/>}/>
        <FlowNode className="node-allow" eyebrow="ALLOW" title={<>Create <b>Razorpay order</b></>} description="Created server-side only after Sentinel returns ALLOW." icon={<Server/>} branch="allow" onActivate={setActive}/>
        <FlowNode className="node-review" eyebrow="REVIEW" title="Merchant intervention" description="No automatic verification workflow is invented." icon={<Store/>} branch="review" onActivate={setActive}/>
        <FlowNode className="node-block" eyebrow="TEMPORARY BLOCK" title="Order suppressed" description="The payment path terminates before Razorpay." icon={<X/>} branch="block" onActivate={setActive}/>
        <FlowNode className="node-razorpay" eyebrow="Public key + order_id" title={<>Razorpay <b>Standard Checkout</b></>} description="The browser receives the public key and server-created order ID." icon={<CreditCard/>} branch="allow" onActivate={setActive}/>
        <FlowNode className="node-verify" eyebrow="POST /payments/verify" title="Verify signature" description="The backend verifies the Razorpay signature before trusting success." icon={<ShieldCheck/>} branch="allow" onActivate={setActive}/>
        <FlowNode className="node-history" eyebrow="Verified outcome" title="Future history" description="Trusted outcomes become features for future Sentinel prechecks." icon={<History/>} branch="allow" onActivate={setActive}/>
        <FlowNode className="node-review-end" eyebrow="Boundary" title="Order not created" description="Merchant intervention is recommended; Checkout does not open automatically." icon={<GitBranch/>} branch="review" onActivate={setActive}/>
        <FlowNode className="node-block-end" eyebrow="Hard stop" title="Checkout never opens" description="No Razorpay order exists. Retry is possible when the temporary block expires." icon={<X/>} branch="block" onActivate={setActive}/>
      </div>
      <motion.aside key={active} className={`branch-explanation ${active}`} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}><span>{active === "allow" ? <Check/> : active === "review" ? <GitBranch/> : <X/>}{active.toUpperCase()} path</span><h2>{branchCopy[active].title}</h2><p>{branchCopy[active].copy}</p></motion.aside>
    </section>
    <section className="flow-principles page-width"><article><span>01</span><strong>Intent is not an order</strong><p>The protection boundary exists before the Razorpay Orders API call.</p></article><article><span>02</span><strong>Browser success is untrusted</strong><p>The callback becomes history only after server-side signature verification.</p></article><article><span>03</span><strong>History stays causal</strong><p>The current outcome never influences the decision that preceded it.</p></article></section>
  </main>;
}
