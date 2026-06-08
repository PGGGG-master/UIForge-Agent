#!/usr/bin/env node
/** Syntax-only Mermaid validation in Node (jsdom + mermaid.parse). */
import { readFileSync } from "node:fs";
import { JSDOM } from "jsdom";

const file = process.argv[2];
if (!file) {
  console.error("Usage: node validate-mermaid.mjs <file.mmd>");
  process.exit(2);
}

const text = readFileSync(file, "utf8");

const dom = new JSDOM("<!DOCTYPE html><html><body></body></html>", {
  url: "https://localhost/",
});
const { window } = dom;
globalThis.window = window;
globalThis.document = window.document;
globalThis.HTMLElement = window.HTMLElement;
globalThis.Node = window.Node;

const { default: mermaid } = await import("mermaid");
mermaid.initialize({ startOnLoad: false, securityLevel: "loose" });

try {
  await mermaid.parse(text);
  process.exit(0);
} catch (err) {
  const msg = err instanceof Error ? err.message : String(err);
  console.error(msg);
  process.exit(1);
}
