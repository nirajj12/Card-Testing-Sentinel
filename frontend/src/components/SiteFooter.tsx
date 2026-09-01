import { ArrowUp, Github } from "lucide-react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../lib/api";
import type { SystemStatus } from "../types";
import { SentinelLogo } from "./SentinelLogo";

export function SiteFooter(){
 const [online,setOnline]=useState(false); useEffect(()=>{api.system<SystemStatus>().then(status=>setOnline(status.ready)).catch(()=>setOnline(false))},[]);
 return <footer className="site-footer"><div className="page-width footer-grid"><div className="footer-brand"><SentinelLogo/><p>Behavioural protection before Razorpay order creation.</p></div><div><strong>Explore</strong><nav aria-label="Footer navigation"><Link to="/how-it-works">How It Works</Link><Link to="/checkout">Try the Demo</Link><Link to="/results">Results</Link><a href="https://github.com/nirajj12/Card-Testing-Sentinel" target="_blank" rel="noreferrer"><Github/>GitHub</a></nav></div><div className="footer-runtime"><strong>Runtime context</strong><span><i className={online?"online":"offline"}/>{online?"Demo system online":"Demo system unavailable"}</span><span>Razorpay Test Mode</span><span>Synthetic evaluation</span></div><a className="back-top" href="#top" aria-label="Back to top"><ArrowUp/>Back to top</a><p className="footer-bottom">Built for the Razorpay AI Buildathon · Research prototype using synthetic payment scenarios · Not an official Razorpay product.</p></div></footer>;
}
