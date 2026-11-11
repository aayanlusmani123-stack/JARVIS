const $ = (selector) => document.querySelector(selector);
const sessionKey = "jarvis-session-id";
const historyKey = "jarvis-chat-history";
const voiceKey = "jarvis-voice-enabled";
const volumeKey = "jarvis-voice-volume";

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
voiceToggle.checked = localStorage.getItem(voiceKey) !== "false";
volumeControl.value = localStorage.getItem(volumeKey) || "75";
$("#volume-value").textContent = `${volumeControl.value}%`;

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

async function checkHealth() {
  try {
    const response = await fetch("/api/health");
    const health = await response.json();
    $("#connection-label").textContent = health.gemini_configured ? "SYSTEM ONLINE" : "API KEY NEEDED";
    $(".connection").classList.toggle("offline", !health.gemini_configured);
    if (!health.gemini_configured) {
      statusSubtitle.textContent = "Add your Gemini API key to the server's .env file to begin.";
    }
  } catch {
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
  if (isBusy) setStatus("One moment.", "Thinking that through...", "thinking");
  else setStatus("At your service.", "Ready when you are.");
}

async function sendMessage(rawText) {
  const text = rawText.trim();
  if (!text || waiting) return;
  renderMessage("user", text);
  input.value = "";
  input.style.height = "auto";
  setBusy(true);
  try {
    const response = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: sessionId, message: text }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "Your message could not be sent.");
    renderMessage("assistant", data.response);
    if (voiceToggle.checked) speak(data.response);
  } catch (error) {
    renderMessage("assistant", `I couldn't complete that request. ${error.message}`, { save: false });
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

function speak(text) {
  if (!window.speechSynthesis || !voiceToggle.checked) return;
  window.speechSynthesis.cancel();
  const utterance = new SpeechSynthesisUtterance(text);
  utterance.volume = Number(volumeControl.value) / 100;
  utterance.rate = 1;
  utterance.pitch = 1;
  utterance.onstart = () => setStatus("Speaking.", "Here's what I found.", "speaking");
  utterance.onend = () => setStatus("At your service.", "Ready when you are.");
  utterance.onerror = () => setStatus("At your service.", "Voice playback isn't available right now.");
  window.speechSynthesis.speak(utterance);
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
