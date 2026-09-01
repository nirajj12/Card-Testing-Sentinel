/* eslint-disable react-refresh/only-export-components */
import { createContext, useContext, useMemo, useState } from "react";
import type { PropsWithChildren } from "react";
import { products } from "../data/products";
import type { Product } from "../data/products";

type CartState = {
  product: Product;
  quantity: number;
  open: boolean;
  selectProduct: (product: Product) => void;
  setQuantity: (quantity: number) => void;
  setOpen: (open: boolean) => void;
};

const CartContext = createContext<CartState | null>(null);

export function CartProvider({ children }: PropsWithChildren) {
  const [product, setProduct] = useState(products[0]);
  const [quantity, setQuantityValue] = useState(1);
  const [open, setOpen] = useState(false);
  const value = useMemo<CartState>(() => ({
    product,
    quantity,
    open,
    selectProduct: (next) => { setProduct(next); setQuantityValue(1); setOpen(true); },
    setQuantity: (next) => setQuantityValue(Math.max(1, Math.min(4, next))),
    setOpen,
  }), [open, product, quantity]);
  return <CartContext.Provider value={value}>{children}</CartContext.Provider>;
}

export function useCart() {
  const value = useContext(CartContext);
  if (!value) throw new Error("useCart must be used inside CartProvider");
  return value;
}
