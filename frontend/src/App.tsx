import { AnimatePresence } from "framer-motion";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import { CartDrawer } from "./components/CartDrawer";
import { Navbar } from "./components/Navbar";
import { LandingPage } from "./pages/LandingPage";
import { CheckoutPage } from "./pages/CheckoutPage";
import { EvidencePage } from "./pages/EvidencePage";
import { HowItWorksPage } from "./pages/HowItWorksPage";
import { CartProvider } from "./state/CartContext";

export default function App() {
  return <BrowserRouter><CartProvider><Navbar/><AnimatePresence mode="wait"><Routes>
    <Route path="/" element={<LandingPage/>}/>
    <Route path="/store" element={<LandingPage/>}/>
    <Route path="/checkout" element={<CheckoutPage/>}/>
    <Route path="/how-it-works" element={<HowItWorksPage/>}/>
    <Route path="/evidence" element={<EvidencePage/>}/>
  </Routes></AnimatePresence><CartDrawer/></CartProvider></BrowserRouter>;
}
