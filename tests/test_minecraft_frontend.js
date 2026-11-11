const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const appSource = fs.readFileSync(path.join(__dirname, "../static/app.js"), "utf8");

class Element {
  constructor(selector = "") {
    this.selector = selector;
    this.id = selector;
    this.textContent = "";
    if (selector === "#minecraft-test-banner") this.textContent = "DEVELOPMENT TEST DATA · SIMULATED, NOT LIVE GAME STATE";
    this.hidden = false;
    this.value = selector === "#volume-control" ? "75" : "";
    this.checked = selector === "#voice-toggle";
    this.disabled = false;
    this.children = [];
    this.listeners = {};
    this.style = {};
    this.scrollHeight = 0;
    this.className = "";
    this.files = [];
    this.clickCount = 0;
    this.videoWidth = 1280;
    this.videoHeight = 720;
    this.classList = {
      add() {},
      remove() {},
      toggle() {},
    };
  }

  addEventListener(name, callback) {
    (this.listeners[name] ||= []).push(callback);
  }

  append(...children) { this.children.push(...children); }
  replaceChildren(...children) { this.children = children; }
  click() { this.clickCount += 1; }
  play() { return Promise.resolve(); }
  getContext() { return { drawImage() {} }; }
  toBlob(callback, type) { callback(new Blob(["fixture capture"], { type })); }
  remove() {}
  focus() {}
  setAttribute() {}
  dispatch(name) { return Promise.all((this.listeners[name] || []).map((callback) => callback({ target: this }))); }
}

function createHarness({ announcements = false, muted = false, speaking = false, devMode = false, visionMode = false } = {}) {
  const selectors = [
    "#message-list", "#chat-form", "#message-input", "#talk-button", "#status-title", "#status-subtitle",
    "#mic-indicator", "#mic-label", "#voice-toggle", "#volume-control", "#voice-select", "#speed-control",
    "#volume-value", "#speed-value", "#orb-wrap", "#connection-label", "#clear-button", ".send-button",
    ".connection", "#copy-session-id", "#minecraft-announcements", "#minecraft-connection", "#minecraft-player",
    "#minecraft-health", "#minecraft-hunger", "#minecraft-coordinates", "#minecraft-biome", "#minecraft-dimension",
    "#minecraft-game-mode", "#minecraft-held-item", "#minecraft-xp", "#minecraft-updated-at", "#welcome-card",
    "#minecraft-test-banner", "#minecraft-test-controls", "#minecraft-test-toggle",
    "#vision-enabled", "#vision-share-screen", "#vision-analyze", "#vision-file", "#vision-auto-enabled",
    "#vision-interval", "#vision-status", "#vision-analysis-status", "#vision-last-captured", "#vision-analysis",
  ];
  const elements = Object.fromEntries(selectors.map((selector) => [selector, new Element(selector)]));
  const storage = new Map([
    ["jarvis-session-id", "123e4567-e89b-12d3-a456-426614174000"],
    ["jarvis-minecraft-announcements", String(announcements)],
    ["jarvis-voice-enabled", String(!muted)],
  ]);
  let eventSource;
  let recognition;
  const timers = [];
  const utterances = [];
  const devUpdates = [];
  const devClears = [];
  const intervals = [];
  const screenshotRequests = [];
  let displayShareRequests = 0;
  const speechSynthesis = {
    speaking,
    pending: false,
    getVoices: () => [],
    cancel() {},
    speak(utterance) { utterances.push(utterance); },
    addEventListener() {},
  };
  class EventSourceMock {
    constructor(url) {
      this.url = url;
      this.readyState = 0;
      eventSource = this;
    }
    close() { this.readyState = 2; }
  }
  class SpeechRecognitionMock {
    constructor() { recognition = this; }
    start() { this.onstart?.(); }
    stop() { this.onend?.(); }
  }
  const document = {
    body: new Element("body"),
    querySelector: (selector) => elements[selector] || null,
    createElement: (tag) => new Element(tag),
  };
  const mediaDevices = {
    async getDisplayMedia() {
      displayShareRequests += 1;
      const track = { stop() {}, addEventListener() {} };
      return { getTracks: () => [track], getVideoTracks: () => [track] };
    },
  };
  class FormDataMock {
    constructor() { this.entries = []; }
    append(...entry) { this.entries.push(entry); }
  }
  const fetch = async (url) => {
    if (url === "/api/health") return { json: async () => ({ gemini_configured: true, minecraft_dev_test_mode: devMode, minecraft_vision_enabled: visionMode }) };
    if (url === "/api/minecraft/events-ticket") return { ok: true, json: async () => ({ ticket: "signed-test-ticket" }) };
    if (url === "/api/minecraft/dev-ticket") return { ok: true, json: async () => ({ ticket: "signed-dev-ticket", expires_in: 300 }) };
    if (url === "/api/minecraft/dev-update") { devUpdates.push(JSON.parse(context.lastFetchBody)); return { ok: true }; }
    if (url === "/api/minecraft/dev-clear") { devClears.push(JSON.parse(context.lastFetchBody)); return { ok: true }; }
    if (url === "/api/minecraft/vision-ticket") return { ok: true, json: async () => ({ ticket: "signed-vision-ticket", expires_in: 300 }) };
    if (url === "/api/minecraft/screenshot") {
      screenshotRequests.push(context.lastFetchBody);
      return { ok: true, json: async () => ({ analysis: "TEST VISION RESULT", status: "fresh", captured_at: new Date().toISOString(), test_mode: false }) };
    }
    return { ok: true, json: async () => ({ response: "OK" }) };
  };
  const context = vm.createContext({
    document,
    window: {
      speechSynthesis,
      SpeechSynthesisUtterance: function SpeechSynthesisUtterance(text) { this.text = text; },
      SpeechRecognition: SpeechRecognitionMock,
    },
    EventSource: EventSourceMock,
    FormData: FormDataMock,
    localStorage: {
      getItem: (key) => storage.has(key) ? storage.get(key) : null,
      setItem: (key, value) => storage.set(key, String(value)),
      removeItem: (key) => storage.delete(key),
    },
    navigator: { language: "en-US", mediaDevices },
    crypto: { randomUUID: () => "123e4567-e89b-12d3-a456-426614174000" },
    fetch: async (url, options) => {
      context.lastFetchBody = options?.body;
      return fetch(url);
    },
    Date,
    URL,
    setTimeout: (callback) => { timers.push(callback); return timers.length; },
    clearTimeout() {},
    setInterval: (callback) => { intervals.push(callback); return intervals.length; },
    clearInterval() {},
  });
  vm.runInContext(appSource, context);
  return {
    elements,
    get eventSource() { return eventSource; },
    storage,
    timers,
    intervals,
    devUpdates,
    devClears,
    screenshotRequests,
    get displayShareRequests() { return displayShareRequests; },
    utterances,
    speechSynthesis,
    flush: () => new Promise((resolve) => setImmediate(resolve)),
  };
}

function state(overrides = {}) {
  return {
    player_username: "Alex",
    x: 1.5,
    y: 64,
    z: -12.25,
    health: 18,
    hunger: 16,
    armor_points: 12,
    held_item: { item_id: "minecraft:iron_sword", count: 1, slot: null },
    inventory: [],
    biome: "minecraft:plains",
    dimension: "minecraft:overworld",
    game_mode: "survival",
    xp_level: 7,
    time_of_day: 1000,
    alive: true,
    ...overrides,
  };
}

test("Minecraft SSE maps connection states and renders latest state", async () => {
  const app = createHarness();
  await app.flush();
  assert.equal(app.elements["#minecraft-connection"].textContent, "Connecting");
  assert.match(app.eventSource.url, /api\/minecraft\/events\?ticket=signed-test-ticket/);

  app.eventSource.onmessage({ data: JSON.stringify({ status: "fresh", state: state(), updated_at: "2026-11-11T12:00:00Z" }) });
  assert.equal(app.elements["#minecraft-connection"].textContent, "Connected");
  assert.equal(app.elements["#minecraft-player"].textContent, "Alex");
  assert.equal(app.elements["#minecraft-health"].textContent, "18");
  assert.equal(app.elements["#minecraft-hunger"].textContent, "16");
  assert.equal(app.elements["#minecraft-coordinates"].textContent, "1.5, 64.0, -12.3");
  assert.equal(app.elements["#minecraft-biome"].textContent, "minecraft:plains");
  assert.equal(app.elements["#minecraft-dimension"].textContent, "minecraft:overworld");
  assert.equal(app.elements["#minecraft-game-mode"].textContent, "survival");
  assert.equal(app.elements["#minecraft-held-item"].textContent, "minecraft:iron_sword x1");
  assert.equal(app.elements["#minecraft-xp"].textContent, "7");

  app.eventSource.onmessage({ data: JSON.stringify({ status: "stale", state: state(), updated_at: "2026-11-11T11:00:00Z" }) });
  assert.equal(app.elements["#minecraft-connection"].textContent, "Stale data");
  app.eventSource.onmessage({ data: JSON.stringify({ status: "missing", state: null }) });
  assert.equal(app.elements["#minecraft-connection"].textContent, "Disconnected");
  assert.equal(app.elements["#minecraft-player"].textContent, "Waiting for game data");
});

test("SSE retry returns through connecting and fresh states", async () => {
  const app = createHarness();
  await app.flush();
  const previous = app.eventSource;
  app.eventSource.onerror();
  assert.equal(app.elements["#minecraft-connection"].textContent, "Disconnected");
  app.timers.shift()();
  await app.flush();
  assert.notEqual(app.eventSource, previous);
  app.eventSource.onopen();
  assert.equal(app.elements["#minecraft-connection"].textContent, "Connecting");
  app.eventSource.onmessage({ data: JSON.stringify({ status: "fresh", state: state(), updated_at: new Date().toISOString() }) });
  assert.equal(app.elements["#minecraft-connection"].textContent, "Connected");
});

test("opt-in announcements speak only meaningful changes and do not interrupt", async () => {
  const app = createHarness({ announcements: true });
  await app.flush();
  app.eventSource.onmessage({ data: JSON.stringify({ status: "fresh", state: state(), updated_at: new Date().toISOString() }) });
  assert.equal(app.utterances.length, 0);
  app.eventSource.onmessage({ data: JSON.stringify({ status: "fresh", state: state({ health: 12 }), updated_at: new Date().toISOString() }) });
  assert.equal(app.utterances.length, 1);
  assert.match(app.utterances[0].text, /health 12/);
  app.eventSource.onmessage({ data: JSON.stringify({ status: "fresh", state: state({ health: 12 }), updated_at: new Date().toISOString() }) });
  assert.equal(app.utterances.length, 1);
});

test("muted voice settings suppress Minecraft announcements", async () => {
  const app = createHarness({ announcements: true, muted: true });
  await app.flush();
  app.eventSource.onmessage({ data: JSON.stringify({ status: "fresh", state: state(), updated_at: new Date().toISOString() }) });
  app.eventSource.onmessage({ data: JSON.stringify({ status: "fresh", state: state({ health: 10 }), updated_at: new Date().toISOString() }) });
  assert.equal(app.utterances.length, 0);
});

test("announcements do not interrupt speech playback or push-to-talk", async () => {
  const speakingApp = createHarness({ announcements: true, speaking: true });
  await speakingApp.flush();
  speakingApp.eventSource.onmessage({ data: JSON.stringify({ status: "fresh", state: state(), updated_at: new Date().toISOString() }) });
  speakingApp.eventSource.onmessage({ data: JSON.stringify({ status: "fresh", state: state({ health: 11 }), updated_at: new Date().toISOString() }) });
  assert.equal(speakingApp.utterances.length, 0);

  const listeningApp = createHarness({ announcements: true });
  await listeningApp.flush();
  listeningApp.eventSource.onmessage({ data: JSON.stringify({ status: "fresh", state: state(), updated_at: new Date().toISOString() }) });
  listeningApp.elements["#talk-button"].dispatch("click");
  listeningApp.eventSource.onmessage({ data: JSON.stringify({ status: "fresh", state: state({ hunger: 8 }), updated_at: new Date().toISOString() }) });
  assert.equal(listeningApp.utterances.length, 0);
});

test("simulator stays hidden by default", async () => {
  const app = createHarness();
  await app.flush();
  assert.equal(app.elements["#minecraft-test-controls"].hidden, true);
  await app.elements["#minecraft-test-toggle"].dispatch("click");
  assert.equal(app.devUpdates.length, 0);
});

test("enabled simulator sends clearly marked fixture data and clears it", async () => {
  const app = createHarness({ devMode: true });
  await app.flush();
  assert.equal(app.elements["#minecraft-test-controls"].hidden, false);
  await app.elements["#minecraft-test-toggle"].dispatch("click");
  assert.equal(app.devUpdates.length, 1);
  assert.equal(app.devUpdates[0].step, 0);
  assert.equal(app.elements["#minecraft-test-toggle"].textContent, "Stop simulated updates");
  await app.intervals[0]();
  assert.equal(app.devUpdates.length, 2);
  assert.equal(app.devUpdates[1].step, 1);
  assert.ok(app.devUpdates[1].sequence > app.devUpdates[0].sequence);

  app.eventSource.onmessage({ data: JSON.stringify({ status: "fresh", test_mode: true, state: state({ player_username: "JarvisTest" }), updated_at: new Date().toISOString() }) });
  assert.equal(app.elements["#minecraft-test-banner"].hidden, false);
  assert.match(app.elements["#minecraft-test-banner"].textContent, /SIMULATED, NOT LIVE/);

  await app.elements["#minecraft-test-toggle"].dispatch("click");
  assert.equal(app.devClears.length, 1);
  assert.ok(app.devClears[0].sequence > app.devUpdates[1].sequence);
  assert.equal(app.elements["#minecraft-test-toggle"].textContent, "Start simulated updates");
});

test("vision is off by default and manual screenshot analysis is explicit", async () => {
  const app = createHarness({ visionMode: true });
  await app.flush();
  assert.equal(app.elements["#vision-enabled"].checked, false);
  assert.equal(app.elements["#vision-auto-enabled"].checked, false);
  assert.equal(app.intervals.length, 0);

  app.elements["#vision-enabled"].checked = true;
  await app.elements["#vision-enabled"].dispatch("change");
  await app.elements["#vision-analyze"].dispatch("click");
  assert.equal(app.elements["#vision-file"].clickCount, 1);
  app.elements["#vision-file"].files = [{
    name: "clearly-labelled-test-fixture.png",
    type: "image/png",
    size: 128,
    lastModified: Date.now(),
  }];
  await app.elements["#vision-file"].dispatch("change");
  assert.equal(app.screenshotRequests.length, 1);
  assert.match(app.elements["#vision-analysis"].textContent, /TEST VISION RESULT/);
});

test("automatic capture requires explicit screen sharing and stops when disabled", async () => {
  const app = createHarness({ visionMode: true });
  await app.flush();
  assert.equal(app.displayShareRequests, 0);
  app.elements["#vision-enabled"].checked = true;
  await app.elements["#vision-enabled"].dispatch("change");
  await app.elements["#vision-share-screen"].dispatch("click");
  assert.equal(app.displayShareRequests, 1);
  assert.equal(app.elements["#vision-auto-enabled"].checked, false);
  app.elements["#vision-auto-enabled"].checked = true;
  await app.elements["#vision-auto-enabled"].dispatch("change");
  assert.equal(app.intervals.length, 1);
  await app.intervals[0]();
  assert.equal(app.screenshotRequests.length, 1);

  app.elements["#vision-enabled"].checked = false;
  await app.elements["#vision-enabled"].dispatch("change");
  assert.equal(app.elements["#vision-auto-enabled"].checked, false);
  assert.equal(app.elements["#vision-share-screen"].textContent, "Share game window");
});
