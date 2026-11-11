const $ = (selector) => document.querySelector(selector);
const sessionKey = "jarvis-session-id";
const historyKey = "jarvis-chat-history";
const voiceKey = "jarvis-voice-enabled";
const volumeKey = "jarvis-voice-volume";
const speechVoiceKey = "jarvis-speech-voice";
const speechRateKey = "jarvis-speech-rate";
const minecraftAnnouncementsKey = "jarvis-minecraft-announcements";

function getSessionId() {
  let id = localStorage.getItem(sessionKey);
  if (!id) {
    id = crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random()}-${Math.random()}`;
    localStorage.setItem(sessionKey, id);
  }
  return id;
}

const sessionId = getSessionId();
const messages = $("#message-list");
const form = $("#chat-form");
const input = $("#message-input");
const talkButton = $("#talk-button");
const statusTitle = $("#status-title");
const statusSubtitle = $("#status-subtitle");
const micIndicator = $("#mic-indicator");
const micLabel = $("#mic-label");
let recognition = null;
let listening = false;
let waiting = false;
let savedMessages = [];

try {
  const parsed = JSON.parse(localStorage.getItem(historyKey) || "[]");
  if (Array.isArray(parsed)) savedMessages = parsed.filter((item) => item && ["user", "assistant"].includes(item.role) && typeof item.text === "string");
} catch { savedMessages = []; }

const voiceToggle = $("#voice-toggle");
const volumeControl = $("#volume-control");
const voiceSelect = $("#voice-select");
const speedControl = $("#speed-control");
voiceToggle.checked = localStorage.getItem(voiceKey) !== "false";
volumeControl.value = localStorage.getItem(volumeKey) || "75";
$("#volume-value").textContent = `${volumeControl.value}%`;
const storedRate = Number(localStorage.getItem(speechRateKey));
speedControl.value = String(Number.isFinite(storedRate) && storedRate >= 0.8 && storedRate <= 1.3 ? storedRate : 1.1);
$("#speed-value").textContent = `${Number(speedControl.value).toFixed(1)}x`;

let availableVoices = [];
const speechSupported = Boolean(window.speechSynthesis && typeof window.SpeechSynthesisUtterance === "function");

function getVoiceId(voice) {
  return voice.voiceURI || `${voice.name}::${voice.lang}`;
}

function refreshSpeechVoices() {
  if (!speechSupported) return;

  const preferredVoiceId = voiceSelect.value || localStorage.getItem(speechVoiceKey) || "";
  availableVoices = window.speechSynthesis.getVoices();
  voiceSelect.replaceChildren();

  if (!availableVoices.length) {
    const option = document.createElement("option");
    option.value = "";
    option.textContent = "No voices available";
    voiceSelect.append(option);
    voiceSelect.disabled = true;
    return;
  }

  const defaultOption = document.createElement("option");
  defaultOption.value = "";
  defaultOption.textContent = "System default";
  voiceSelect.append(defaultOption);

  for (const voice of availableVoices) {
    const option = document.createElement("option");
    option.value = getVoiceId(voice);
    option.textContent = `${voice.name} (${voice.lang})`;
    voiceSelect.append(option);
  }

  const hasPreferredVoice = availableVoices.some((voice) => getVoiceId(voice) === preferredVoiceId);
  voiceSelect.value = hasPreferredVoice ? preferredVoiceId : "";
  voiceSelect.disabled = false;
  if (!hasPreferredVoice && preferredVoiceId) localStorage.removeItem(speechVoiceKey);
}

if (speechSupported) {
  refreshSpeechVoices();
  if (typeof window.speechSynthesis.addEventListener === "function") {
    window.speechSynthesis.addEventListener("voiceschanged", refreshSpeechVoices);
  } else {
    window.speechSynthesis.onvoiceschanged = refreshSpeechVoices;
  }
} else {
  const option = document.createElement("option");
  option.value = "";
  option.textContent = "Speech unavailable";
  voiceSelect.append(option);
  voiceSelect.disabled = true;
}

function setStatus(title, subtitle, state = "ready") {
  statusTitle.textContent = title;
  statusSubtitle.textContent = subtitle;
  micIndicator.classList.toggle("active", state === "listening");
  micIndicator.classList.toggle("busy", state === "thinking");
  $("#orb-wrap").classList.toggle("is-listening", state === "listening");
  $("#orb-wrap").classList.toggle("is-thinking", state === "thinking");
  document.body.classList.toggle("is-listening", state === "listening");
  document.body.classList.toggle("is-speaking", state === "speaking");
  micLabel.textContent = state === "listening" ? "LISTENING — SPEAK NOW" : state === "thinking" ? "PROCESSING REQUEST" : state === "speaking" ? "JARVIS IS SPEAKING" : "MICROPHONE STANDBY";
}

function renderMessage(role, text, { save = true } = {}) {
  $("#welcome-card")?.remove();
  const row = document.createElement("article");
  row.className = `message ${role === "user" ? "user-message" : "assistant-message"}`;
  const avatar = document.createElement("div");
  avatar.className = "message-avatar";
  avatar.textContent = role === "user" ? "Y" : "J";
  const content = document.createElement("div");
  content.className = "message-content";
  const label = document.createElement("div");
  label.className = "message-label";
  label.textContent = role === "user" ? "YOU" : "JARVIS";
  const body = document.createElement("p");
  body.textContent = text;
  content.append(label, body);
  row.append(avatar, content);
  messages.append(row);
  messages.scrollTop = messages.scrollHeight;
  if (save) {
    savedMessages.push({ role, text });
    try { localStorage.setItem(historyKey, JSON.stringify(savedMessages.slice(-100))); } catch { /* Storage may be disabled or full. */ }
  }
}

for (const item of savedMessages) renderMessage(item.role, item.text, { save: false });

const announcementToggle = $("#minecraft-announcements");
announcementToggle.checked = localStorage.getItem(minecraftAnnouncementsKey) === "true";
let lastMinecraftAnnouncementSignature = "";
let lastMinecraftAnnouncementAt = 0;
let eventSource = null;
let eventConnectPending = false;
let eventReconnectTimer = null;
let eventReconnectDelayMs = 1000;
let developmentTestModeEnabled = false;
let developmentTestRun = null;
let developmentTestTimer = null;
let developmentTestRequestInFlight = false;
let visionServerEnabled = false;
let visionEnabled = false;
let screenStream = null;
let screenVideo = null;
let automaticCaptureTimer = null;
let visionTicket = null;
let visionAnalysisInFlight = false;
let latestVisionAnalysis = null;

function setMinecraftConnection(status) {
  const indicator = $("#minecraft-connection");
  indicator.textContent = status;
  indicator.className = `minecraft-connection ${status.toLowerCase().replace(/ /g, "-")}`;
}

function formatMinecraftTime(value) {
  if (!value) return "Never";
  const updated = new Date(value);
  return Number.isNaN(updated.getTime()) ? "Unknown" : updated.toLocaleTimeString();
}

function minecraftAnnouncementSignature(state) {
  const held = state.held_item ? `${state.held_item.item_id}:${state.held_item.count}` : "empty";
  return [state.player_username, state.health, state.hunger, state.biome, state.dimension,
    state.game_mode, state.alive, held].join("|");
}

function maybeAnnounceMinecraftChange(state) {
  const signature = minecraftAnnouncementSignature(state);
  const changed = lastMinecraftAnnouncementSignature && signature !== lastMinecraftAnnouncementSignature;
  lastMinecraftAnnouncementSignature = signature;
  const now = Date.now();
  if (!changed || !announcementToggle.checked || !voiceToggle.checked || listening || waiting
      || !speechSupported || window.speechSynthesis.speaking || window.speechSynthesis.pending
      || now - lastMinecraftAnnouncementAt < 15000) return;

  lastMinecraftAnnouncementAt = now;
  const held = state.held_item ? `${state.held_item.count} ${state.held_item.item_id}` : "empty-handed";
  const message = `${state.player_username}: health ${state.health}, hunger ${state.hunger}, ${state.biome}, ${held}.`;
  speak(message, { interrupt: false });
}

function renderMinecraftState(payload) {
  if (!payload || payload.status === "missing" || !payload.state) {
    setMinecraftConnection("Disconnected");
    $("#minecraft-test-banner").hidden = true;
    $("#minecraft-player").textContent = "Waiting for game data";
    for (const selector of ["#minecraft-health", "#minecraft-hunger", "#minecraft-coordinates", "#minecraft-biome",
      "#minecraft-dimension", "#minecraft-game-mode", "#minecraft-held-item", "#minecraft-xp"]) {
      $(selector).textContent = "--";
    }
    $("#minecraft-updated-at").textContent = "Never";
    return;
  }

  const state = payload.state;
  setMinecraftConnection(payload.status === "stale" ? "Stale data" : "Connected");
  $("#minecraft-test-banner").hidden = payload.test_mode !== true;
  if (payload.test_mode === true) {
    $("#minecraft-test-banner").textContent = "DEVELOPMENT TEST DATA · SIMULATED, NOT LIVE GAME STATE";
  }
  $("#minecraft-player").textContent = `${state.player_username}${state.alive ? "" : " (dead)"}`;
  $("#minecraft-health").textContent = `${state.health}`;
  $("#minecraft-hunger").textContent = `${state.hunger}`;
  $("#minecraft-coordinates").textContent = `${state.x.toFixed(1)}, ${state.y.toFixed(1)}, ${state.z.toFixed(1)}`;
  $("#minecraft-biome").textContent = state.biome;
  $("#minecraft-dimension").textContent = state.dimension;
  $("#minecraft-game-mode").textContent = state.game_mode;
  $("#minecraft-held-item").textContent = state.held_item ? `${state.held_item.item_id} x${state.held_item.count}` : "Empty";
  $("#minecraft-xp").textContent = `${state.xp_level}`;
  $("#minecraft-updated-at").textContent = formatMinecraftTime(payload.updated_at);
  if (payload.status === "fresh" && payload.test_mode !== true) maybeAnnounceMinecraftChange(state);
}

function setVisionStatus(message) {
  $("#vision-status").textContent = message;
}

function stopScreenCapture() {
  if (automaticCaptureTimer) clearInterval(automaticCaptureTimer);
  automaticCaptureTimer = null;
  if (screenStream) for (const track of screenStream.getTracks()) track.stop();
  screenStream = null;
  screenVideo = null;
  $("#vision-share-screen").textContent = "Share game window";
  $("#vision-auto-enabled").checked = false;
  $("#vision-auto-enabled").disabled = true;
}

function setVisionEnabled(enabled) {
  visionEnabled = enabled && visionServerEnabled;
  $("#vision-analyze").disabled = !visionEnabled;
  $("#vision-share-screen").disabled = !visionEnabled;
  $("#vision-interval").disabled = !visionEnabled;
  $("#vision-enabled").checked = visionEnabled;
  if (!visionEnabled) {
    stopScreenCapture();
    setVisionStatus(visionServerEnabled ? "Disabled" : "Disabled by server");
  } else {
    setVisionStatus("Enabled · manual analysis only");
  }
}

async function getVisionTicket() {
  if (visionTicket && visionTicket.expiresAt - Date.now() > 30000) return visionTicket.value;
  const response = await fetch("/api/minecraft/vision-ticket", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId }),
  });
  if (!response.ok) throw new Error("Screenshot vision ticket unavailable.");
  const body = await response.json();
  visionTicket = { value: body.ticket, expiresAt: Date.now() + body.expires_in * 1000 };
  return visionTicket.value;
}

async function uploadScreenshot(blob, filename, capturedAt, timestampBasis) {
  if (!visionEnabled || visionAnalysisInFlight) return;
  visionAnalysisInFlight = true;
  $("#vision-analysis-status").textContent = "Analyzing screenshot…";
  try {
    const formData = new FormData();
    formData.append("file", blob, filename);
    formData.append("timestamp_basis", timestampBasis);
    if (capturedAt) formData.append("captured_at", capturedAt.toISOString());
    const ticket = await getVisionTicket();
    const response = await fetch("/api/minecraft/screenshot", {
      method: "POST",
      headers: { "X-Jarvis-Vision-Ticket": ticket },
      body: formData,
    });
    const body = await response.json();
    if (!response.ok) throw new Error(body.detail || `Screenshot analysis failed (${response.status}).`);
    latestVisionAnalysis = body;
    $("#vision-analysis").textContent = `${body.test_mode ? "DEVELOPMENT TEST DATA · " : ""}${body.analysis}`;
    $("#vision-analysis-status").textContent = body.status === "fresh" ? "Current capture analyzed" : "Historical or unverified capture analyzed";
    $("#vision-last-captured").textContent = body.captured_at ? formatMinecraftTime(body.captured_at) : "Capture time unknown";
  } catch (error) {
    $("#vision-analysis-status").textContent = error.message || "Screenshot analysis failed.";
  } finally {
    visionAnalysisInFlight = false;
  }
}

async function captureSharedScreen() {
  if (!screenStream || !screenVideo || !visionEnabled) return;
  const width = screenVideo.videoWidth;
  const height = screenVideo.videoHeight;
  if (!width || !height || visionAnalysisInFlight) return;
  const scale = Math.min(1, 1536 / Math.max(width, height));
  const canvas = document.createElement("canvas");
  canvas.width = Math.round(width * scale);
  canvas.height = Math.round(height * scale);
  const context = canvas.getContext("2d", { alpha: false });
  context.drawImage(screenVideo, 0, 0, canvas.width, canvas.height);
  const blob = await new Promise((resolve) => canvas.toBlob(resolve, "image/jpeg", 0.72));
  if (blob) await uploadScreenshot(blob, "minecraft-screen.jpg", new Date(), "live-capture");
}

async function shareGameWindow() {
  if (!visionEnabled) return;
  if (screenStream) {
    stopScreenCapture();
    setVisionStatus("Enabled · screen sharing stopped");
    return;
  }
  if (!navigator.mediaDevices?.getDisplayMedia) {
    setVisionStatus("Screen sharing is unavailable; use manual screenshot analysis.");
    return;
  }
  try {
    screenStream = await navigator.mediaDevices.getDisplayMedia({ video: true, audio: false });
    screenVideo = document.createElement("video");
    screenVideo.muted = true;
    screenVideo.playsInline = true;
    screenVideo.srcObject = screenStream;
    await screenVideo.play();
    screenStream.getVideoTracks()[0].addEventListener("ended", stopScreenCapture, { once: true });
    $("#vision-share-screen").textContent = "Stop screen sharing";
    $("#vision-auto-enabled").disabled = false;
    setVisionStatus("Screen shared · auto capture is off");
  } catch {
    setVisionStatus("Screen sharing was cancelled or unavailable.");
  }
}

function updateAutomaticCapture() {
  if (automaticCaptureTimer) clearInterval(automaticCaptureTimer);
  automaticCaptureTimer = null;
  if (!visionEnabled || !screenStream || !$("#vision-auto-enabled").checked) return;
  const seconds = Number($("#vision-interval").value);
  localStorage.setItem("jarvis-vision-interval", String(seconds));
  setVisionStatus(`Automatic capture · every ${seconds} seconds`);
  automaticCaptureTimer = setInterval(captureSharedScreen, seconds * 1000);
}

async function getDevelopmentTicket() {
  const response = await fetch("/api/minecraft/dev-ticket", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId }),
  });
  if (!response.ok) throw new Error("Development test ticket unavailable.");
  const ticket = await response.json();
  return { ticket: ticket.ticket, expiresAt: Date.now() + ticket.expires_in * 1000 };
}

async function sendDevelopmentUpdate() {
  if (!developmentTestRun || developmentTestRequestInFlight) return;
  developmentTestRequestInFlight = true;
  try {
    if (developmentTestRun.expiresAt - Date.now() < 30000) {
      Object.assign(developmentTestRun, await getDevelopmentTicket());
    }
    const response = await fetch("/api/minecraft/dev-update", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Jarvis-Dev-Ticket": developmentTestRun.ticket,
      },
      body: JSON.stringify({
        session_id: sessionId,
        source_id: developmentTestRun.sourceId,
        sequence: developmentTestRun.sequence,
        step: developmentTestRun.step,
      }),
    });
    if (!response.ok) throw new Error("Development update rejected.");
    developmentTestRun.sequence += 1;
    developmentTestRun.step += 1;
  } catch {
    setMinecraftConnection("Disconnected");
  } finally {
    developmentTestRequestInFlight = false;
  }
}

async function toggleDevelopmentTestMode() {
  const button = $("#minecraft-test-toggle");
  if (!developmentTestModeEnabled) return;
  button.disabled = true;
  try {
    if (developmentTestRun) {
      if (developmentTestTimer) clearInterval(developmentTestTimer);
      developmentTestTimer = null;
      const currentRun = developmentTestRun;
      developmentTestRun = null;
      if (currentRun.expiresAt - Date.now() < 30000) Object.assign(currentRun, await getDevelopmentTicket());
      await fetch("/api/minecraft/dev-clear", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Jarvis-Dev-Ticket": currentRun.ticket,
        },
        body: JSON.stringify({ session_id: sessionId, source_id: currentRun.sourceId, sequence: currentRun.sequence }),
      });
      button.textContent = "Start simulated updates";
    } else {
      const ticket = await getDevelopmentTicket();
      developmentTestRun = {
        ...ticket,
        sourceId: crypto.randomUUID(),
        sequence: Date.now(),
        step: 0,
      };
      button.textContent = "Stop simulated updates";
      await sendDevelopmentUpdate();
      developmentTestTimer = setInterval(sendDevelopmentUpdate, 3000);
    }
  } catch {
    developmentTestRun = null;
    if (developmentTestTimer) clearInterval(developmentTestTimer);
    developmentTestTimer = null;
    button.textContent = "Start simulated updates";
    setMinecraftConnection("Disconnected");
  } finally {
    button.disabled = false;
  }
}

function scheduleMinecraftReconnect() {
  if (eventReconnectTimer) return;
  const delay = eventReconnectDelayMs;
  eventReconnectDelayMs = Math.min(eventReconnectDelayMs * 2, 30000);
  eventReconnectTimer = setTimeout(() => {
    eventReconnectTimer = null;
    connectMinecraftEvents();
  }, delay);
}

async function connectMinecraftEvents() {
  if (eventConnectPending) return;
  eventConnectPending = true;
  setMinecraftConnection("Connecting");
  try {
    const response = await fetch("/api/minecraft/events-ticket", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: sessionId }),
    });
    if (!response.ok) throw new Error("Minecraft event ticket unavailable.");
    const { ticket } = await response.json();
    eventSource?.close();
    eventSource = new EventSource(`/api/minecraft/events?ticket=${encodeURIComponent(ticket)}`);
    eventSource.onopen = () => {
      eventReconnectDelayMs = 1000;
      if ($("#minecraft-connection").textContent !== "Connected"
          && $("#minecraft-connection").textContent !== "Stale data") setMinecraftConnection("Connecting");
    };
    eventSource.onmessage = (event) => {
      try { renderMinecraftState(JSON.parse(event.data)); } catch { setMinecraftConnection("Disconnected"); }
    };
    eventSource.onerror = () => {
      setMinecraftConnection("Disconnected");
      eventSource.close();
      scheduleMinecraftReconnect();
    };
  } catch {
    setMinecraftConnection("Disconnected");
    scheduleMinecraftReconnect();
  } finally {
    eventConnectPending = false;
  }
}

connectMinecraftEvents();
$("#minecraft-test-toggle").addEventListener("click", toggleDevelopmentTestMode);
$("#vision-enabled").addEventListener("change", () => setVisionEnabled($("#vision-enabled").checked));
$("#vision-share-screen").addEventListener("click", shareGameWindow);
$("#vision-auto-enabled").addEventListener("change", updateAutomaticCapture);
$("#vision-interval").value = localStorage.getItem("jarvis-vision-interval") || "60";
$("#vision-interval").addEventListener("change", updateAutomaticCapture);
$("#vision-analyze").addEventListener("click", () => {
  if (!visionEnabled) return;
  if (screenStream) captureSharedScreen();
  else $("#vision-file").click();
});
$("#vision-file").addEventListener("change", async (event) => {
  const file = event.target.files?.[0];
  event.target.value = "";
  if (!file || !visionEnabled) return;
  if (!(file.type === "image/png" || file.type === "image/jpeg")) {
    $("#vision-analysis-status").textContent = "Choose a PNG or JPEG screenshot.";
    return;
  }
  if (file.size > 8 * 1024 * 1024) {
    $("#vision-analysis-status").textContent = "Screenshot exceeds the 8 MiB limit.";
    return;
  }
  const modified = file.lastModified > 0 ? new Date(file.lastModified) : null;
  await uploadScreenshot(file, file.name, modified, modified ? "file-modified" : "unknown");
});
announcementToggle.addEventListener("change", () => {
  localStorage.setItem(minecraftAnnouncementsKey, String(announcementToggle.checked));
});

$("#copy-session-id").addEventListener("click", async () => {
  try {
    await navigator.clipboard.writeText(sessionId);
    setStatus("Session ID copied.", "Paste it into the Minecraft mod configuration.");
  } catch {
    setStatus("Clipboard unavailable.", "Copy the current JARVIS session ID from browser localStorage.");
  }
});

async function checkHealth() {
  try {
    const response = await fetch("/api/health");
    const health = await response.json();
    developmentTestModeEnabled = health.minecraft_dev_test_mode === true;
    $("#minecraft-test-controls").hidden = !developmentTestModeEnabled;
    visionServerEnabled = health.minecraft_vision_enabled === true;
    $("#vision-enabled").disabled = !visionServerEnabled;
    $("#vision-analyze").disabled = !visionServerEnabled || !visionEnabled;
    $("#vision-share-screen").disabled = !visionServerEnabled || !visionEnabled;
    $("#vision-interval").disabled = !visionServerEnabled || !visionEnabled;
    $("#vision-auto-enabled").disabled = true;
    setVisionStatus(visionServerEnabled ? "Disabled · enable before sharing or analyzing" : "Disabled by server");
    $("#connection-label").textContent = health.gemini_configured ? "SYSTEM ONLINE" : "API KEY NEEDED";
    $(".connection").classList.toggle("offline", !health.gemini_configured);
    if (!health.gemini_configured) {
      statusSubtitle.textContent = "Add your Gemini API key to the server's .env file to begin.";
    }
  } catch {
    $("#minecraft-test-controls").hidden = true;
    visionServerEnabled = false;
    setVisionEnabled(false);
    $("#connection-label").textContent = "OFFLINE";
    $(".connection").classList.add("offline");
    statusSubtitle.textContent = "Cannot reach the assistant server.";
  }
}
checkHealth();

function setBusy(isBusy) {
  waiting = isBusy;
  $(".send-button").disabled = isBusy;
  input.disabled = isBusy;
  if (isBusy) setStatus("Thinking...", "Waiting for Gemini...", "thinking");
  else setStatus("At your service.", "Ready when you are.");
}

async function sendMessage(rawText) {
  const text = rawText.trim();
  if (!text || waiting) return;
  setBusy(true);
  renderMessage("user", text);
  input.value = "";
  input.style.height = "auto";
  try {
    const response = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: sessionId, message: text }),
    });
    let data = null;
    try { data = await response.json(); } catch { /* The server may return a non-JSON error page. */ }
    if (!response.ok) {
      throw new Error(typeof data?.detail === "string" ? data.detail : `The assistant server returned an error (${response.status}).`);
    }
    if (typeof data?.response !== "string" || !data.response.trim()) {
      throw new Error("The assistant server returned an empty response. Please try again.");
    }
    if (voiceToggle.checked) speak(data.response);
    renderMessage("assistant", data.response);
  } catch (error) {
    const message = error instanceof TypeError
      ? "I couldn't reach the JARVIS server. Check that it is running and Codespaces forwarded port 8000."
      : error.message;
    renderMessage("assistant", `I couldn't complete that request. ${message}`, { save: false });
  } finally {
    setBusy(false);
    if (!voiceToggle.checked || !window.speechSynthesis) input.focus();
  }
}

form.addEventListener("submit", (event) => {
  event.preventDefault();
  sendMessage(input.value);
});
input.addEventListener("input", () => {
  input.style.height = "auto";
  input.style.height = `${Math.min(input.scrollHeight, 150)}px`;
});
input.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    form.requestSubmit();
  }
});

const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
if (SpeechRecognition) {
  recognition = new SpeechRecognition();
  recognition.lang = navigator.language || "en-US";
  recognition.continuous = false;
  recognition.interimResults = true;
  recognition.onstart = () => {
    listening = true;
    talkButton.classList.add("recording");
    talkButton.setAttribute("aria-pressed", "true");
    $("#talk-label").textContent = "Listening... tap to stop";
    setStatus("I'm listening.", "Go ahead — I'm all ears.", "listening");
  };
  recognition.onresult = (event) => {
    let finalText = "";
    let interimText = "";
    for (let i = event.resultIndex; i < event.results.length; i += 1) {
      if (event.results[i].isFinal) finalText += event.results[i][0].transcript;
      else interimText += event.results[i][0].transcript;
    }
    input.value = finalText || interimText;
    if (finalText) sendMessage(finalText);
  };
  recognition.onerror = (event) => {
    const message = event.error === "not-allowed" ? "Allow microphone access in your browser settings, or type below." : event.error === "no-speech" ? "I didn't hear anything. Try again or type below." : "Speech recognition stopped. You can still type below.";
    statusSubtitle.textContent = message;
  };
  recognition.onend = () => {
    listening = false;
    talkButton.classList.remove("recording");
    talkButton.setAttribute("aria-pressed", "false");
    $("#talk-label").textContent = "Push to talk";
    if (!waiting) setStatus("At your service.", statusSubtitle.textContent || "Ready when you are.");
  };
} else {
  talkButton.title = "Speech recognition is not supported in this browser. Type your message instead.";
}

talkButton.addEventListener("click", () => {
  if (!recognition) {
    statusSubtitle.textContent = "Speech recognition is not available in this browser. Please type your message instead.";
    input.focus();
    return;
  }
  if (listening) recognition.stop();
  else {
    try { recognition.start(); }
    catch { statusSubtitle.textContent = "Microphone is already starting. Please try again in a moment."; }
  }
});

function speak(text, { interrupt = true } = {}) {
  if (!speechSupported || !voiceToggle.checked) return;
  try {
    if (interrupt) window.speechSynthesis.cancel();
    else if (window.speechSynthesis.speaking || window.speechSynthesis.pending || listening || waiting) return;
    const utterance = new window.SpeechSynthesisUtterance(text);
    utterance.volume = Number(volumeControl.value) / 100;
    utterance.rate = Number(speedControl.value);
    utterance.pitch = 1;
    utterance.voice = availableVoices.find((voice) => getVoiceId(voice) === voiceSelect.value) || null;
    utterance.onstart = () => setStatus("Speaking.", "Here's what I found.", "speaking");
    utterance.onend = () => setStatus("At your service.", "Ready when you are.");
    utterance.onerror = () => setStatus("At your service.", "Voice playback isn't available right now.");
    window.speechSynthesis.speak(utterance);
  } catch {
    setStatus("At your service.", "Voice playback isn't available right now.");
  }
}

voiceToggle.addEventListener("change", () => {
  localStorage.setItem(voiceKey, String(voiceToggle.checked));
  if (!voiceToggle.checked && window.speechSynthesis) {
    window.speechSynthesis.cancel();
    setStatus("At your service.", "Voice replies are muted.");
  }
});
volumeControl.addEventListener("input", () => {
  $("#volume-value").textContent = `${volumeControl.value}%`;
  localStorage.setItem(volumeKey, volumeControl.value);
});
voiceSelect.addEventListener("change", () => {
  localStorage.setItem(speechVoiceKey, voiceSelect.value);
});
speedControl.addEventListener("input", () => {
  const speed = Number(speedControl.value);
  $("#speed-value").textContent = `${speed.toFixed(1)}x`;
  localStorage.setItem(speechRateKey, String(speed));
});

$("#clear-button").addEventListener("click", async () => {
  if (waiting) return;
  if (recognition && listening) recognition.stop();
  if (window.speechSynthesis) window.speechSynthesis.cancel();
  try {
    await fetch("/api/clear", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: sessionId }),
    });
  } catch { /* Local transcript can still be cleared while offline. */ }
  savedMessages = [];
  localStorage.removeItem(historyKey);
  messages.replaceChildren();
  messages.innerHTML = '<div class="welcome-card" id="welcome-card"><div class="welcome-icon"><span>✦</span></div><div><h3>Fresh start.</h3><p>Your conversation has been cleared. What would you like to explore?</p></div></div>';
  setStatus("At your service.", "Ready when you are.");
});
