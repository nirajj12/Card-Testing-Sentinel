import { ArrowUpRight, Plus } from "lucide-react";
import { motion } from "framer-motion";
import type { Product } from "../data/products";
import { formatPrice } from "../data/products";
import { useCart } from "../state/CartContext";

export function ProductCard({ product, featured = false }: { product: Product; featured?: boolean }) {
  const cart = useCart();
  const Icon = product.icon;
  return <motion.article className={`product-card ${featured ? "featured" : ""}`} whileHover={{ y: -6 }} transition={{ duration: .22 }}>
    <div className="product-art" style={{ background: `linear-gradient(145deg, ${product.colors[0]}, ${product.colors[1]})` }}>
      <span>{product.eyebrow}</span><Icon strokeWidth={1.25}/><button type="button" onClick={() => cart.selectProduct(product)} aria-label={`Add ${product.name} to cart`}><Plus size={18}/></button>
    </div>
    <div className="product-meta"><div><h3>{product.name}</h3><p>{product.description}</p></div><strong>{formatPrice(product.price)}</strong></div>
    {featured && <button className="text-link" type="button" onClick={() => cart.selectProduct(product)}>Buy now <ArrowUpRight size={15}/></button>}
  </motion.article>;
}
