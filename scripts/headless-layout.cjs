const { spawn } = require("node:child_process");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");

const chromePath = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const targetUrl = process.argv[2] || "http://127.0.0.1:3000/";
const summaryMode = process.argv.includes("--summary");
const viewports = [
  { name: "desktop", width: 1440, height: 1000 },
  { name: "compactDesktop", width: 1291, height: 700 },
  { name: "narrow", width: 1024, height: 900 },
  { name: "tablet", width: 768, height: 1000 },
  { name: "mobile", width: 390, height: 900 }
];

let messageId = 0;

function delay(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function waitForJson(port) {
  const url = `http://127.0.0.1:${port}/json`;
  const started = Date.now();
  while (Date.now() - started < 8000) {
    try {
      const response = await fetch(url);
      if (response.ok) return await response.json();
    } catch {
      // Chrome is still booting.
    }
    await delay(120);
  }
  throw new Error(`Timed out waiting for Chrome DevTools on ${port}`);
}

function send(ws, method, params = {}) {
  const id = ++messageId;
  ws.send(JSON.stringify({ id, method, params }));
  return new Promise((resolve, reject) => {
    const onMessage = (event) => {
      const raw = typeof event.data === "string" ? event.data : event.data.toString();
      const message = JSON.parse(raw);
      if (message.id !== id) return;
      ws.removeEventListener("message", onMessage);
      if (message.error) reject(new Error(message.error.message));
      else resolve(message.result);
    };
    ws.addEventListener("message", onMessage);
  });
}

async function evaluate(ws, expression) {
  const result = await send(ws, "Runtime.evaluate", {
    expression,
    awaitPromise: true,
    returnByValue: true
  });
  if (result.exceptionDetails) {
    throw new Error(result.exceptionDetails.text || "Runtime evaluation failed");
  }
  return result.result.value;
}

async function runViewport(viewport, index) {
  const port = 9330 + index;
  const userDataDir = path.join(os.tmpdir(), `witscraft-layout-${port}`);
  fs.rmSync(userDataDir, { force: true, recursive: true });
  const chrome = spawn(chromePath, [
    "--headless=new",
    "--no-sandbox",
    "--disable-gpu",
    `--remote-debugging-port=${port}`,
    `--user-data-dir=${userDataDir}`,
    `--window-size=${viewport.width},${viewport.height}`,
    targetUrl
  ], { stdio: "ignore" });

  try {
    const targets = await waitForJson(port);
    const page = targets.find((item) => item.type === "page") || targets[0];
    const ws = new WebSocket(page.webSocketDebuggerUrl);
    await new Promise((resolve, reject) => {
      ws.addEventListener("open", resolve, { once: true });
      ws.addEventListener("error", reject, { once: true });
    });

    await send(ws, "Runtime.enable");
    await send(ws, "Page.enable");
    await send(ws, "Emulation.setDeviceMetricsOverride", {
      width: viewport.width,
      height: viewport.height,
      deviceScaleFactor: 1,
      mobile: viewport.width <= 760
    });
    await send(ws, "Page.navigate", { url: targetUrl });
    await delay(1600);

    const collect = `
      (() => {
        const rect = (el) => {
          if (!el) return null;
          const r = el.getBoundingClientRect();
          return { x: Math.round(r.x), y: Math.round(r.y), width: Math.round(r.width), height: Math.round(r.height), right: Math.round(r.right), bottom: Math.round(r.bottom) };
        };
        const q = (selector) => document.querySelector(selector);
        const panels = {
          library: q(".libraryRail"),
          stage: q(".storyStage"),
          inspector: q(".inspectorRail"),
          composer: q(".composerDock"),
          composerBox: q(".composerBox"),
          mobileTabs: q(".mobileTabs")
        };
        const overflowers = Array.from(document.querySelectorAll("body *"))
          .map((el) => {
            const r = el.getBoundingClientRect();
            return { tag: el.tagName, className: String(el.className || ""), text: (el.textContent || "").trim().slice(0, 42), left: Math.round(r.left), right: Math.round(r.right), width: Math.round(r.width), scrollWidth: el.scrollWidth, clientWidth: el.clientWidth };
          })
          .filter((item) => item.right > innerWidth + 1 || item.left < -1 || item.scrollWidth > item.clientWidth + 1)
          .sort((a, b) => Math.max(b.right - innerWidth, b.scrollWidth - b.clientWidth) - Math.max(a.right - innerWidth, a.scrollWidth - a.clientWidth))
          .slice(0, 8);
        const clipped = Array.from(document.querySelectorAll(".makePanel, .composerBox"))
          .map((el) => ({ className: String(el.className || ""), title: el.querySelector("h3")?.textContent || "", scrollHeight: el.scrollHeight, clientHeight: el.clientHeight }))
          .filter((item) => item.scrollHeight > item.clientHeight + 2)
          .slice(0, 8);
        return {
          viewport: { width: innerWidth, height: innerHeight },
          document: { scrollWidth: document.documentElement.scrollWidth, clientWidth: document.documentElement.clientWidth, bodyScrollWidth: document.body.scrollWidth },
          panels: Object.fromEntries(Object.entries(panels).map(([key, el]) => [key, { display: el ? getComputedStyle(el).display : null, transform: el ? getComputedStyle(el).transform : null, rect: rect(el) }])),
          overflowers,
          clipped
        };
      })()
    `;

    const story = await evaluate(ws, collect);
    await evaluate(ws, `(() => document.querySelector(".tabletToggles button:nth-child(2)")?.click())()`);
    await delay(200);
    const drawerInspector = await evaluate(ws, collect);
    await evaluate(ws, `(() => document.querySelector(".mobileTabs button:nth-child(3)")?.click())()`);
    await delay(200);
    const inspector = await evaluate(ws, collect);
    ws.close();
    return { ...viewport, story, drawerInspector, inspectorTab: inspector };
  } finally {
    chrome.kill("SIGTERM");
    try {
      fs.rmSync(userDataDir, { force: true, recursive: true });
    } catch {
      // Chrome may release profile files a moment after SIGTERM; leftover tmp
      // folders are harmless for this local QA helper.
    }
  }
}

(async () => {
  const results = [];
  for (let index = 0; index < viewports.length; index += 1) {
    results.push(await runViewport(viewports[index], index));
  }
  if (summaryMode) {
    const compact = results.map((result) => {
      const summarizeState = (state) => ({
        documentWidth: state.document.scrollWidth,
        viewportWidth: state.document.clientWidth,
        horizontalOverflow: state.document.scrollWidth > state.document.clientWidth + 1,
        clippedPanels: state.clipped.length,
        clippedTitles: state.clipped.map((item) => item.title || item.className),
        overflowers: state.overflowers.length
      });

      return {
        name: result.name,
        viewport: `${result.width}x${result.height}`,
        story: summarizeState(result.story),
        drawerInspector: summarizeState(result.drawerInspector),
        inspectorTab: summarizeState(result.inspectorTab)
      };
    });
    console.log(JSON.stringify(compact, null, 2));
    return;
  }
  console.log(JSON.stringify(results, null, 2));
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
