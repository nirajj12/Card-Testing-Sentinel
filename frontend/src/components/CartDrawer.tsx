import { Minus, Plus, ShieldCheck, X } from "lucide-react";
import { AnimatePresence, motion } from "framer-motion";
import { useNavigate } from "react-router-dom";
import { formatPrice } from "../data/products";
import { useCart } from "../state/CartContext";

export function CartDrawer() {
  const cart = useCart();
  const navigate = useNavigate();
  const Icon = cart.product.icon;
  const total = cart.product.price * cart.quantity;
  return <AnimatePresence>{cart.open && <>
    <motion.button className="drawer-backdrop" aria-label="Close cart" onClick={() => cart.setOpen(false)} initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}/>
    <motion.aside className="cart-drawer" initial={{ x: "100%" }} animate={{ x: 0 }} exit={{ x: "100%" }} transition={{ type: "spring", damping: 28, stiffness: 260 }}>
      <div className="drawer-head"><div><span>Your cart</span><h2>Ready for checkout</h2></div><button type="button" onClick={() => cart.setOpen(false)} aria-label="Close cart"><X/></button></div>
      <div className="cart-product"><div style={{ background: cart.product.colors[0] }}><Icon/></div><div><strong>{cart.product.name}</strong><span>{cart.product.description}</span><b>{formatPrice(cart.product.price)}</b></div></div>
      <div className="quantity-row"><span>Quantity</span><div><button type="button" onClick={() => cart.setQuantity(cart.quantity - 1)}><Minus size={14}/></button><strong>{cart.quantity}</strong><button type="button" onClick={() => cart.setQuantity(cart.quantity + 1)}><Plus size={14}/></button></div></div>
      <dl className="cart-totals"><div><dt>Subtotal</dt><dd>{formatPrice(total)}</dd></div><div><dt>Shipping</dt><dd>Free</dd></div><div><dt>Total</dt><dd>{formatPrice(total)}</dd></div></dl>
      <button className="primary-cta full" type="button" onClick={() => { cart.setOpen(false); navigate("/checkout"); }}>Continue to secure payment <span>→</span></button>
      <p className="drawer-trust"><ShieldCheck size={16}/>Sentinel evaluates risk before any Razorpay order is created.</p>
    </motion.aside>
  </>}</AnimatePresence>;
}
