import { ArrowRight, Braces, CircleCheck, GitBranch, ShieldCheck } from "lucide-react";
import { motion } from "framer-motion";
import { Link } from "react-router-dom";
import { ProductCard } from "../components/ProductCard";
import { products } from "../data/products";

export function LandingPage() {
  return <>
    <section className="hero page-width">
      <motion.div className="hero-copy" initial={{ opacity: 0, y: 18 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: .55 }}>
        <span className="eyebrow-pill"><i/>Merchant-side payment protection</span>
        <h1>Intelligent protection<br/><em>before every payment.</em></h1>
        <p>Merchant-side pre-authorization protection for Razorpay. Sentinel evaluates trusted behavioral history before checkout and makes a bounded ALLOW, REVIEW or BLOCK decision before a Razorpay order is created.</p>
        <div className="hero-actions"><Link className="primary-cta" to="/checkout">Try Protected Checkout <ArrowRight size={17}/></Link><Link className="secondary-cta" to="/how-it-works">See how Sentinel works</Link></div>
        <div className="trust-chips"><span><CircleCheck/>Razorpay Test Mode</span><span><GitBranch/>Causal risk scoring</span><span><Braces/>Explainable decisions</span></div>
      </motion.div>
      <motion.div className="hero-visual" initial={{ opacity: 0, scale: .96 }} animate={{ opacity: 1, scale: 1 }} transition={{ duration: .65, delay: .08 }}>
        <div className="intent-card"><span>Payment intent</span><strong>₹2,499</strong><small>Northstar Store</small></div>
        <div className="sentinel-orb"><span className="orbit one"/><span className="orbit two"/><div><ShieldCheck/><strong>Sentinel</strong><small>Precheck</small></div></div>
        <div className="decision-card"><span>Decision</span><strong>Not evaluated</strong><small>Outcome comes from the backend</small></div>
        <svg viewBox="0 0 640 420" aria-hidden="true"><path d="M145 205 C225 205 225 205 285 205 M355 205 C425 205 425 205 500 205"/></svg>
        <span className="visual-caption">A trusted decision between intent and order creation.</span>
      </motion.div>
    </section>
    <section className="store-section page-width" id="store">
      <header className="section-heading"><div><span>Northstar Store</span><h2>A believable purchase.<br/>A protected payment path.</h2></div><p>Choose a product and continue through the real Sentinel and Razorpay Test Mode flow.</p></header>
      <div className="product-grid">{products.map((product, index) => <ProductCard key={product.id} product={product} featured={index === 0}/>)}</div>
    </section>
    <section className="benefits page-width">
      <article><span>01</span><ShieldCheck/><h3>Decide before the order</h3><p>Risk is evaluated before the backend creates a Razorpay order.</p></article>
      <article><span>02</span><GitBranch/><h3>Use trusted history</h3><p>Merchant-visible verified behavior informs the next precheck.</p></article>
      <article><span>03</span><Braces/><h3>Explain every action</h3><p>Bounded decisions persist with understandable evidence.</p></article>
    </section>
  </>;
}
