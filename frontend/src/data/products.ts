import { Headphones, Keyboard, Mouse, Speaker, Usb, Watch } from "lucide-react";
import type { LucideIcon } from "lucide-react";

export type Product = {
  id: string;
  name: string;
  description: string;
  price: number;
  eyebrow: string;
  colors: [string, string];
  icon: LucideIcon;
};

export const products: Product[] = [
  { id: "northstar-air", name: "Northstar Air", description: "Wireless headphones · Midnight", price: 2499, eyebrow: "Studio sound", colors: ["#dfe8ff", "#f1f4ff"], icon: Headphones },
  { id: "pulse-keyboard", name: "Pulse Mechanical", description: "Low-profile keyboard · Graphite", price: 3299, eyebrow: "Creator desk", colors: ["#e8e1ff", "#f6f2ff"], icon: Keyboard },
  { id: "orbit-watch", name: "Orbit Watch", description: "Fitness smartwatch · Silver", price: 4999, eyebrow: "Everyday motion", colors: ["#dcf2ef", "#f0fbf9"], icon: Watch },
  { id: "mini-speaker", name: "Mini Speaker", description: "Portable audio · Cobalt", price: 1899, eyebrow: "Room-filling", colors: ["#dcecff", "#eef7ff"], icon: Speaker },
  { id: "vector-mouse", name: "Vector Mouse", description: "Wireless precision · Black", price: 1599, eyebrow: "Fast control", colors: ["#eceef3", "#f8f9fb"], icon: Mouse },
  { id: "usb-hub", name: "Six Port Hub", description: "USB-C workspace hub · Slate", price: 1299, eyebrow: "One connection", colors: ["#f0e7dc", "#fbf6ef"], icon: Usb },
];

export const formatPrice = (value: number) => `₹${value.toLocaleString("en-IN")}`;
