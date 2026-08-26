// Minimal jsdom bootstrap shared by the frontend module tests. This is the
// only place a DOM is constructed -- every test module imports the real
// files the FastAPI app serves at /static/*.js unmodified and exercises
// them against real elements, never a hand-rolled stand-in DOM.
import { JSDOM } from "jsdom";
import path from "node:path";
import { fileURLToPath } from "node:url";

const dom = new JSDOM("<!doctype html><html><body></body></html>");
globalThis.window = dom.window;
globalThis.document = dom.window.document;

const HERE = path.dirname(fileURLToPath(import.meta.url));
export const STATIC_DIR = path.resolve(HERE, "../../src/card_testing_sentinel/web/static");

export function el(tag = "div") {
  return document.createElement(tag);
}

export function importStatic(name) {
  return import(path.join(STATIC_DIR, name));
}
