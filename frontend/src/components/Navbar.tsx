import { Menu, ShoppingBag, X } from "lucide-react";
import { useState } from "react";
import { NavLink } from "react-router-dom";
import { SentinelLogo } from "./SentinelLogo";
import { SystemStatus } from "./SystemStatus";
import { useCart } from "../state/CartContext";

const links = [["/", "Store"], ["/checkout", "Protected Checkout"], ["/how-it-works", "How it Works"], ["/evidence", "Evidence"]] as const;

export function Navbar() {
  const [mobileOpen, setMobileOpen] = useState(false);
  const cart = useCart();
  return <header className="app-nav">
    <nav className="nav-inner" aria-label="Primary navigation">
      <NavLink to="/" aria-label="Sentinel store"><SentinelLogo /></NavLink>
      <div className={`nav-links ${mobileOpen ? "is-open" : ""}`}>
        {links.map(([href, label]) => <NavLink key={href} to={href} onClick={() => setMobileOpen(false)} className={({ isActive }) => isActive ? "active" : ""}>{label}</NavLink>)}
      </div>
      <div className="nav-actions">
        <span className="test-mode"><i />Razorpay Test Mode</span>
        <SystemStatus/>
        <button className="cart-button" type="button" onClick={() => cart.setOpen(true)} aria-label="Open shopping cart"><ShoppingBag size={17}/><span>1</span></button>
        <button className="menu-button" type="button" onClick={() => setMobileOpen(!mobileOpen)} aria-label="Toggle menu">{mobileOpen ? <X/> : <Menu/>}</button>
      </div>
    </nav>
  </header>;
}
