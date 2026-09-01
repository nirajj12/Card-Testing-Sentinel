import { Github } from "lucide-react";
import { Link } from "react-router-dom";
import { SentinelLogo } from "./SentinelLogo";

export function SiteFooter() {
  return <footer className="site-footer"><div className="page-width footer-inner">
    <div><SentinelLogo/><p>A merchant-side prototype that evaluates payment risk before order creation.</p></div>
    <nav aria-label="Footer navigation"><Link to="/how-it-works">How It Works</Link><Link to="/checkout">Try the Demo</Link><Link to="/results">Results</Link><a href="https://github.com/nirajj12/Card-Testing-Sentinel" target="_blank" rel="noreferrer"><Github size={16}/>GitHub</a></nav>
    <p className="footer-note">Razorpay Test Mode only · Synthetic evaluation · Not production fraud protection</p>
  </div></footer>;
}
