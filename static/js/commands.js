/**
 * static/js/commands.js
 * Shared slash-command system for Chat & Channels.
 *
 * To add a new command later:
 *   1. Add an entry to COMMANDS.
 *   2. Add a case to the switch in _dispatch().
 *   3. If it stores a message on the server, add a case to renderMsgContent().
 */

// ─── Registry ─────────────────────────────────────────────────────────────────
const COMMANDS = [
  { cmd: "/report",  args: "<username> [reason]", desc: "Report a user to admins"      },
  { cmd: "/me",      args: "<action>",             desc: "Send an action message"        },
  { cmd: "/display", args: "<url>",                desc: "Embed an image or video link"  },
  { cmd: "/youtube", args: "<url>",                desc: "Embed a YouTube video"          },
  { cmd: "/shrug",   args: "",                     desc: "Insert ¯\\_(ツ)_/¯ into input" },
  { cmd: "/flip",    args: "",                     desc: "Flip a coin"                   },
  { cmd: "/roll",    args: "[sides]",              desc: "Roll a die (default d6)"       },
  { cmd: "/clear",   args: "",                     desc: "Clear your local chat view"    },
  { cmd: "/ping",    args: "",                     desc: "Check connection latency"      },
  { cmd: "/time",    args: "",                     desc: "Show current local time"       },
  { cmd: "/online",  args: "",                     desc: "Show who is online"            },
];

// ─── Inject CSS once ──────────────────────────────────────────────────────────
(function () {
  if (document.getElementById("cmd-styles")) return;
  const s = document.createElement("style");
  s.id = "cmd-styles";
  s.textContent = `
    .cmd-popup {
      position: absolute; bottom: calc(100% + 6px); left: 0; right: 0;
      background: var(--bg-panel); border: 1px solid var(--border-hi);
      border-radius: var(--radius); box-shadow: 0 -4px 18px rgba(0,0,0,.4);
      z-index: 500; overflow: hidden; display: none;
    }
    .cmd-popup.open { display: block; }
    .cmd-item {
      display: flex; align-items: baseline; gap: 8px; padding: 8px 14px;
      cursor: pointer; border-bottom: 1px solid var(--border);
      transition: background .1s;
    }
    .cmd-item:last-child { border-bottom: none; }
    .cmd-item:hover, .cmd-item.sel { background: var(--bg-hover); }
    .cmd-name { font-family: var(--font-mono); font-size: .8rem; color: var(--cyan); font-weight: 600; flex-shrink: 0; }
    .cmd-args { font-family: var(--font-mono); font-size: .7rem; color: var(--text-dim); flex-shrink: 0; }
    .cmd-desc { font-family: var(--font-ui); font-size: .75rem; color: var(--text); margin-left: auto; text-align: right; }

    /* Rich message types */
    .msg-embed { max-width: 320px; margin-top: 6px; }
    .msg-embed img  { display:block; max-width:100%; max-height:280px; object-fit:contain; border-radius:8px; }
    .msg-embed video{ display:block; max-width:100%; max-height:240px; border-radius:8px; }
    .msg-embed iframe{ display:block; width:320px; height:180px; border:none; border-radius:8px; }
    .embed-err { font-family:var(--font-mono); font-size:.72rem; color:var(--text-dim); padding:4px 0; }
    .embed-err a { color:var(--cyan); }

    .bubble.me-bubble {
      background: transparent !important; border: none !important; box-shadow: none !important;
      font-style: italic; color: var(--text-dim) !important; padding-left: 2px !important;
    }
    .bubble.sys-bubble {
      background: var(--bg-card) !important; border: 1px dashed var(--border) !important;
      color: var(--text-dim) !important; font-family: var(--font-mono) !important; font-size: .8rem !important;
    }
  `;
  document.head.appendChild(s);
})();

// ─── initCommandBar ───────────────────────────────────────────────────────────
/**
 * Attach command autocomplete + dispatch to a textarea.
 *
 * @param {HTMLTextAreaElement} inputEl  - The message input
 * @param {HTMLElement}         wrapEl   - Container to anchor the popup (position:relative will be set)
 * @param {object}              h        - Handler callbacks (see below)
 *
 * Handlers:
 *   h.send(text, msgType)   — send a broadcast message
 *   h.showError(msg)        — show an error toast
 *   h.showInfo(msg)         — show a neutral info toast
 *   h.clearMessages()       — wipe the local message list
 *   h.getOnlineText()       — returns a string like "3 online"
 *   h.getSocket()           — returns the socket.io socket
 *   h.openReport(args)      — open the report UI, args = "username [reason]"
 *
 * @returns {{ tryDispatch(rawText): boolean }}
 */
function initCommandBar(inputEl, wrapEl, h) {
  const popup = document.createElement("div");
  popup.className = "cmd-popup";
  wrapEl.style.position = "relative";
  wrapEl.appendChild(popup);

  let sel     = -1;
  let current = [];   // currently shown commands

  // ── popup helpers ─────────────────────────────────────────
  function show(cmds) {
    current = cmds; sel = -1;
    popup.innerHTML = cmds.map((c, i) => `
      <div class="cmd-item" data-i="${i}">
        <span class="cmd-name">${c.cmd}</span>
        ${c.args ? `<span class="cmd-args">${_esc(c.args)}</span>` : ""}
        <span class="cmd-desc">${_esc(c.desc)}</span>
      </div>`).join("");
    popup.classList.add("open");
    popup.querySelectorAll(".cmd-item").forEach(el =>
      el.addEventListener("mousedown", e => { e.preventDefault(); pick(+el.dataset.i); })
    );
  }

  function hide() { popup.classList.remove("open"); sel = -1; current = []; }

  function highlight() {
    popup.querySelectorAll(".cmd-item").forEach((el, i) =>
      el.classList.toggle("sel", i === sel));
  }

  function pick(i) {
    const c = current[i]; if (!c) return;
    hide();
    if (c.args) {
      inputEl.value = c.cmd + " ";
      inputEl.dispatchEvent(new Event("input"));
    } else {
      inputEl.value = "";
      _dispatch(c.cmd, "");
    }
    inputEl.focus();
  }

  // ── listeners ─────────────────────────────────────────────
  inputEl.addEventListener("input", () => {
    const v = inputEl.value;
    if (!v.startsWith("/") || v.includes(" ")) { hide(); return; }
    const found = COMMANDS.filter(c => c.cmd.startsWith(v.toLowerCase()));
    found.length ? show(found) : hide();
  });

  inputEl.addEventListener("keydown", e => {
    if (!popup.classList.contains("open")) return;
    if (e.key === "ArrowDown") { e.preventDefault(); sel = Math.min(sel+1, current.length-1); highlight(); }
    else if (e.key === "ArrowUp") { e.preventDefault(); sel = Math.max(sel-1, -1); highlight(); }
    else if (e.key === "Enter" || e.key === "Tab") {
      if (sel >= 0) { e.preventDefault(); pick(sel); }
      else if (e.key === "Tab" && current.length === 1) { e.preventDefault(); pick(0); }
    } else if (e.key === "Escape") { e.preventDefault(); hide(); }
  });

  document.addEventListener("click", e => { if (!wrapEl.contains(e.target)) hide(); });

  // ── dispatch ──────────────────────────────────────────────
  function _dispatch(name, args) {
    switch (name) {

      case "/shrug":
        inputEl.value += " ¯\\_(ツ)_/¯";
        inputEl.dispatchEvent(new Event("input"));
        inputEl.focus();
        break;

      case "/clear":
        if (h.clearMessages) h.clearMessages();
        break;

      case "/time":
        if (h.showInfo) h.showInfo("🕐 " + new Date().toLocaleTimeString());
        break;

      case "/online":
        if (h.showInfo && h.getOnlineText) h.showInfo("👥 " + h.getOnlineText());
        break;

      case "/ping": {
        const sock = h.getSocket?.();
        if (!sock) { h.showInfo?.("No socket."); break; }
        const t0 = Date.now();
        sock.emit("cmd_ping", {}, () => {
          if (h.showInfo) h.showInfo(`🏓 Pong: ${Date.now() - t0}ms`);
        });
        break;
      }

      case "/report":
        if (h.openReport) { h.openReport(args); }
        break;

      case "/me":
        if (!args) { h.showError?.("Usage: /me <action>"); break; }
        h.send?.(args, "me");
        break;

      case "/display":
        if (!args) { h.showError?.("Usage: /display <url>"); break; }
        h.send?.(args, "display");
        break;

      case "/youtube":
        if (!args) { h.showError?.("Usage: /youtube <url>"); break; }
        h.send?.(args, "youtube");
        break;

      case "/flip": {
        const r = Math.random() < .5 ? "heads" : "tails";
        h.send?.(r, "flip");
        break;
      }

      case "/roll": {
        const sides  = Math.max(2, parseInt(args) || 6);
        const result = Math.floor(Math.random() * sides) + 1;
        h.send?.(`${result}/${sides}`, "roll");
        break;
      }

      default:
        h.showError?.(`Unknown command: ${name}`);
    }
  }

  // Public: call from send handler before normal send logic
  function tryDispatch(raw) {
    if (!raw.startsWith("/")) return false;
    const sp   = raw.indexOf(" ");
    const name = (sp < 0 ? raw : raw.slice(0, sp)).toLowerCase();
    const args = sp < 0 ? "" : raw.slice(sp + 1).trim();
    if (!COMMANDS.find(c => c.cmd === name)) return false;
    _dispatch(name, args);
    return true;
  }

  return { tryDispatch };
}

// ─── renderMsgContent ─────────────────────────────────────────────────────────
/**
 * Fills `bubble` with content based on msg.msg_type.
 * Returns true if the message is text-editable, false otherwise.
 */
function renderMsgContent(bubble, msg) {
  const type = msg.msg_type || "text";

  if (type === "text") {
    const b = document.createElement("span");
    b.className = "bubble-body"; b.textContent = msg.message;
    bubble.appendChild(b);
    return true;   // editable
  }

  if (type === "me") {
    bubble.classList.add("me-bubble");
    const b = document.createElement("span");
    b.className = "bubble-body";
    b.textContent = `* ${msg.username} ${msg.message}`;
    bubble.appendChild(b);
    return false;
  }

  if (type === "flip") {
    bubble.classList.add("sys-bubble");
    const b = document.createElement("span");
    b.className = "bubble-body";
    b.textContent = `🪙 ${msg.username} flipped — ${msg.message.toUpperCase()}`;
    bubble.appendChild(b);
    return false;
  }

  if (type === "roll") {
    bubble.classList.add("sys-bubble");
    const [rolled, sides] = msg.message.split("/");
    const b = document.createElement("span");
    b.className = "bubble-body";
    b.textContent = `🎲 ${msg.username} rolled a d${sides}: ${rolled}`;
    bubble.appendChild(b);
    return false;
  }

  if (type === "display") {
    const url  = msg.message;
    const ext  = url.split("?")[0].split(".").pop().toLowerCase();
    const wrap = document.createElement("div"); wrap.className = "msg-embed";
    if (["jpg","jpeg","png","gif","webp","svg","bmp"].includes(ext)) {
      const img = document.createElement("img");
      img.src = url; img.alt = "image";
      img.onerror = () => img.replaceWith(_embedErr(url));
      wrap.appendChild(img);
    } else if (["mp4","webm","ogg","mov"].includes(ext)) {
      const vid = document.createElement("video");
      vid.src = url; vid.controls = true;
      vid.onerror = () => vid.replaceWith(_embedErr(url));
      wrap.appendChild(vid);
    } else {
      // Unknown — attempt image, fall back to error
      const img = document.createElement("img");
      img.src = url; img.alt = "media";
      img.onerror = () => img.replaceWith(_embedErr(url));
      wrap.appendChild(img);
    }
    bubble.appendChild(wrap);
    return false;
  }

  if (type === "youtube") {
    const vid  = _ytId(msg.message);
    const wrap = document.createElement("div"); wrap.className = "msg-embed";
    if (vid) {
      const iframe = document.createElement("iframe");
      iframe.src = `https://www.youtube.com/embed/${vid}`;
      iframe.allow = "accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture";
      iframe.allowFullscreen = true;
      wrap.appendChild(iframe);
    } else {
      wrap.appendChild(_embedErr(msg.message));
    }
    bubble.appendChild(wrap);
    return false;
  }

  // Fallback — unknown type, render as text
  const b = document.createElement("span");
  b.className = "bubble-body"; b.textContent = msg.message;
  bubble.appendChild(b);
  return true;
}

function _embedErr(url) {
  const d = document.createElement("div"); d.className = "embed-err";
  d.innerHTML = `⚠ Could not embed: <a href="${_esc(url)}" target="_blank" rel="noopener">${_esc(url)}</a>`;
  return d;
}

function _ytId(url) {
  try {
    const u = new URL(url);
    if (u.hostname.includes("youtube.com")) return u.searchParams.get("v");
    if (u.hostname === "youtu.be") return u.pathname.slice(1).split("?")[0];
  } catch (_) {}
  return null;
}

function _esc(s) {
  return String(s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;");
}