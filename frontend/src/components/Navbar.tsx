import { Github, Menu, X } from "lucide-react";
import { useState } from "react";
import { NavLink } from "react-router-dom";
import { SentinelLogo } from "./SentinelLogo";
import { SystemStatus } from "./SystemStatus";

const links = [["/", "Home"], ["/how-it-works", "How It Works"], ["/checkout", "Try the Demo"], ["/results", "Results"]] as const;

export function Navbar() {
  const [mobileOpen, setMobileOpen] = useState(false);
  return <header className="app-nav">
    <nav className="nav-inner" aria-label="Primary navigation">
      <NavLink to="/" aria-label="Sentinel store"><SentinelLogo /></NavLink>
      <div className={`nav-links ${mobileOpen ? "is-open" : ""}`}>
        {links.map(([href, label]) => <NavLink key={href} to={href} onClick={() => setMobileOpen(false)} className={({ isActive }) => isActive ? "active" : ""}>{label}</NavLink>)}
      </div>
      <div className="nav-actions">
        <SystemStatus/>
        <a className="github-link" href="https://github.com/nirajj12/Card-Testing-Sentinel" target="_blank" rel="noreferrer"><Github size={16}/><span>GitHub</span></a>
        <button className="menu-button" type="button" onClick={() => setMobileOpen(!mobileOpen)} aria-label="Toggle menu">{mobileOpen ? <X/> : <Menu/>}</button>
      </div>
    </nav>
  </header>;
}
