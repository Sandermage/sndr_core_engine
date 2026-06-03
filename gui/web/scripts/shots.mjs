// Standalone screenshot sweep — navigates the built GUI (served by the daemon)
// via hash routing and captures each section for visual review.
import { chromium } from "playwright";
import { mkdirSync } from "node:fs";

const BASE = process.env.SHOT_BASE || "http://127.0.0.1:8765";
const OUT = "/tmp/sndr-shots";
mkdirSync(OUT, { recursive: true });

const SECTIONS = [
  "launch-plan", "overview", "setup", "fleet", "hosts", "models", "configs",
  "presets", "planner", "doctor", "patches", "benchmarks", "advanced", "operations",
];

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1 });
const errors = [];
page.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });
page.on("pageerror", (e) => errors.push(`pageerror: ${e.message}`));

await page.goto(BASE + "/", { waitUntil: "domcontentloaded" });
await page.waitForTimeout(1200);

for (const s of SECTIONS) {
  await page.goto(`${BASE}/#${s}`, { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(900);
  await page.screenshot({ path: `${OUT}/${s}.png`, fullPage: false });
  console.log(`shot: ${s}`);
}

// Command palette overlay
await page.goto(`${BASE}/#overview`, { waitUntil: "domcontentloaded" });
await page.waitForTimeout(400);
await page.keyboard.press("Meta+k");
await page.waitForTimeout(400);
await page.screenshot({ path: `${OUT}/_palette.png` });
console.log("shot: _palette");

console.log(errors.length ? `CONSOLE ERRORS:\n${errors.join("\n")}` : "no console errors");
await browser.close();
