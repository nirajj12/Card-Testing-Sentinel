import { Github, Menu, X } from "lucide-react";
import { useEffect, useState } from "react";
import { NavLink } from "react-router-dom";
import { SentinelLogo } from "./SentinelLogo";
import { SystemStatus } from "./SystemStatus";

const links = [["/", "Home"], ["/how-it-works", "How It Works"], ["/checkout", "Try the Demo"], ["/results", "Results"]] as const;

export function Navbar() {
  const [mobileOpen, setMobileOpen] = useState(false);
  useEffect(()=>{function close(event:KeyboardEvent){if(event.key==="Escape")setMobileOpen(false)} document.addEventListener("keydown",close);return()=>document.removeEventListener("keydown",close)},[]);
  return <header className="app-nav" id="top">
    <nav className="nav-inner" aria-label="Primary navigation">
      <NavLink to="/" aria-label="Sentinel store"><SentinelLogo /></NavLink>
      <div id="primary-links" className={`nav-links ${mobileOpen ? "is-open" : ""}`}>
        {links.map(([href, label]) => <NavLink key={href} to={href} onClick={() => setMobileOpen(false)} className={({ isActive }) => isActive ? "active" : ""}>{label}</NavLink>)}
      </div>
      <div className="nav-actions">
        <SystemStatus/>
        <a className="github-link" href="https://github.com/nirajj12/Card-Testing-Sentinel" target="_blank" rel="noreferrer"><Github size={16}/><span>GitHub</span></a>
        <button className="menu-button" type="button" onClick={() => setMobileOpen(!mobileOpen)} aria-label={mobileOpen?"Close navigation":"Open navigation"} aria-expanded={mobileOpen} aria-controls="primary-links">{mobileOpen ? <X/> : <Menu/>}</button>
      </div>
    </nav>
  </header>;
}
