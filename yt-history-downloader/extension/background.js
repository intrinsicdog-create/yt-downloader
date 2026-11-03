// Relays requests from the YouTube page to the native helper (host/yt_host.py).
// The browser launches the helper itself via Native Messaging; no server, no port.
const HOST = "com.ythd.helper";

let port = null;
let nextId = 1;
const pending = new Map(); // request id -> sendResponse

function friendly(msg = "") {
  if (/not found/i.test(msg)) {
    return "Helper not installed. Run install.py from the project folder (see README), then reload this page.";
  }
  if (/forbidden/i.test(msg)) {
    return "Browser refused to start the helper. Re-run install.py so the extension ID is registered.";
  }
  return msg || "Helper disconnected";
}

function failAll(error) {
  for (const cb of pending.values()) cb({ ok: false, error });
  pending.clear();
}

function connect() {
  if (port) return port;
  port = chrome.runtime.connectNative(HOST);
  port.onMessage.addListener((m) => {
    const cb = pending.get(m.id);
    if (!cb) return;
    pending.delete(m.id);
    cb(m.ok ? { ok: true, data: m.data } : { ok: false, error: m.error || "Helper error" });
  });
  port.onDisconnect.addListener(() => {
    const err = chrome.runtime.lastError && chrome.runtime.lastError.message;
    port = null;
    failAll(friendly(err));
  });
  return port;
}

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (msg.type !== "download" && msg.type !== "status") return false;

  const id = nextId++;
  pending.set(id, sendResponse);
  try {
    connect().postMessage({ id, type: msg.type, payload: msg.payload });
  } catch (e) {
    pending.delete(id);
    sendResponse({ ok: false, error: friendly(e.message) });
  }
  return true; // keep the message channel open for the async response
});
