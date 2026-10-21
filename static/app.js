const $ = s => document.querySelector(s);
const log = $('#log'), input = $('#msg'), core = $('#core'), statusEl = $('#status');
let busy = false;

async function api(url, opts = {}) {
  const r = await fetch(url, {headers: {'Content-Type': 'application/json'}, ...opts});
  let d = {}; try { d = await r.json(); } catch (e) {}
  if (!r.ok) throw new Error(d.error || 'Request failed (' + r.status + ')');
  return d;
}
function setState(cls, text) { core.className = 'core ' + cls; statusEl.textContent = text; }
function toast(text, bad) {
  const t = $('#toast'); t.textContent = text; t.className = 'toast' + (bad ? ' bad' : ''); t.hidden = false;
  clearTimeout(toast.id); toast.id = setTimeout(() => t.hidden = true, 4000);
}
function addMsg(role, text, source, err) {
  const d = document.createElement('div'); d.className = 'm ' + role + (err ? ' err' : '');
  d.textContent = text;
  if (role === 'assistant' && source) {
    const s = document.createElement('small'); s.textContent = source === 'ai' ? 'AI model' : 'Built-in rules'; d.appendChild(s);
  }
  log.appendChild(d); log.scrollTop = log.scrollHeight;
}
function list(id, items, render) {
  const ul = $('#' + id); ul.replaceChildren();
  if (!items.length) { const li = document.createElement('li'); li.className = 'empty'; li.textContent = 'Nothing here yet.'; ul.appendChild(li); return; }
  items.forEach(x => ul.appendChild(render(x)));
}
function row(kind, x, sub, canToggle) {
  const li = document.createElement('li'); if (x.done) li.className = 'done';
  const sp = document.createElement('span'); sp.textContent = '#' + x.id + ' ' + x.text; li.appendChild(sp);
  if (sub) { const s = document.createElement('small'); s.textContent = sub; li.appendChild(s); }
  if (canToggle) { const b = document.createElement('button'); b.textContent = x.done ? 'Undo' : 'Done'; b.setAttribute('aria-label', (x.done ? 'Undo ' : 'Complete ') + x.text);
    b.onclick = () => act('/api/' + kind + '/' + x.id + '/toggle', {method: 'POST'}); li.appendChild(b); }
  const d = document.createElement('button'); d.textContent = '✕'; d.setAttribute('aria-label', 'Delete ' + x.text);
  d.onclick = () => act('/api/' + kind + '/' + x.id, {method: 'DELETE'}); li.appendChild(d);
  return li;
}
async function act(url, opts) { try { await api(url, opts); await load(false); } catch (e) { toast(e.message, true); } }

async function load(withHistory = true) {
  try {
    const s = await api('/api/state');
    const m = $('#mode'); m.textContent = s.ai_connected ? 'AI mode: connected' : 'AI mode: not connected (rule-based)'; m.className = 'badge' + (s.ai_connected ? ' ai' : '');
    list('tasks', s.tasks, x => row('tasks', x, '', true));
    list('reminders', s.reminders, x => row('reminders', x, x.due ? x.due.replace('T', ' ').slice(0, 16) : '', true));
    list('notes', s.notes, x => row('notes', x));
    const a = $('#activity'); a.replaceChildren();
    if (!s.activity.length) a.innerHTML = '<li class="empty">No activity yet.</li>';
    s.activity.forEach(x => { const li = document.createElement('li'); li.textContent = x.created.slice(11, 16) + '  ' + x.text; a.appendChild(li); });
    if (withHistory) {
      log.replaceChildren();
      if (!s.history.length) addMsg('assistant', "Hello, I'm JARVIS. Type 'help' to see what I can do.", 'rules');
      s.history.forEach(h => addMsg(h.role, h.content, h.source));
    }
  } catch (e) { toast('Could not load data: ' + e.message, true); }
}

// ---- speech output ----
const speakBox = $('#speak');
speakBox.checked = localStorage.getItem('speak') === 'on';
speakBox.onchange = () => { localStorage.setItem('speak', speakBox.checked ? 'on' : 'off'); if (!speakBox.checked) speechSynthesis.cancel(); };
if (!('speechSynthesis' in window)) { speakBox.disabled = true; speakBox.parentElement.title = 'Not supported in this browser'; }
function speak(text) {
  if (!speakBox.checked || !('speechSynthesis' in window)) return;
  speechSynthesis.cancel();
  const u = new SpeechSynthesisUtterance(text);
  u.onstart = () => setState('speaking', 'Speaking…'); u.onend = u.onerror = () => setState('', 'Standing by');
  speechSynthesis.speak(u);
}

// ---- chat ----
async function send(text) {
  text = (text || '').trim();
  if (!text) { toast('Please type a message first.', true); return; }
  if (busy) return; busy = true; $('#send').disabled = true;
  addMsg('user', text); input.value = ''; setState('thinking', 'Thinking…');
  try {
    const r = await api('/api/chat', {method: 'POST', body: JSON.stringify({message: text})});
    addMsg('assistant', r.reply, r.source); setState('', 'Standing by'); speak(r.reply); load(false);
  } catch (e) { addMsg('assistant', e.message, '', true); setState('', 'Standing by'); }
  busy = false; $('#send').disabled = false; input.focus();
}
$('#send').onclick = () => send(input.value);
input.addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); send(input.value); } });
$('#clear').onclick = async () => {
  if (!confirm('Clear all chat history? This cannot be undone.')) return;
  try { await api('/api/chat/clear', {method: 'POST'}); await load(); toast('Chat history cleared.'); } catch (e) { toast(e.message, true); }
};
document.querySelectorAll('form[data-kind]').forEach(f => f.onsubmit = async e => {
  e.preventDefault(); const i = f.querySelector('input'); if (!i.value.trim()) { toast('Please enter some text.', true); return; }
  try { await api('/api/' + f.dataset.kind, {method: 'POST', body: JSON.stringify({text: i.value})}); i.value = ''; load(false); } catch (err) { toast(err.message, true); }
});

// ---- voice input ----
const SR = window.SpeechRecognition || window.webkitSpeechRecognition, mic = $('#mic');
if (!SR) { mic.disabled = true; mic.title = 'Voice input is not supported in this browser (try Chrome or Edge)'; }
else {
  const rec = new SR(); rec.lang = 'en-US'; rec.interimResults = false; let on = false, heard = '';
  const stop = () => { on = false; mic.classList.remove('on'); mic.setAttribute('aria-label', 'Start voice input'); setState('', 'Standing by'); };
  rec.onresult = e => { heard = e.results[0][0].transcript; input.value = heard; };
  rec.onerror = e => { stop(); toast(e.error === 'not-allowed' ? 'Microphone permission was denied. Allow it in your browser settings.' : e.error === 'no-speech' ? "I didn't hear anything. Try again." : 'Voice input error: ' + e.error, true); };
  rec.onend = () => { const h = heard; heard = ''; if (on) stop(); if (h) send(h); };
  mic.onclick = () => {
    if (on) { rec.stop(); return; }
    speechSynthesis && speechSynthesis.cancel();
    try { rec.start(); on = true; mic.classList.add('on'); mic.setAttribute('aria-label', 'Stop listening'); setState('listening', 'Listening…'); } catch (e) { toast('Voice input could not start.', true); }
  };
}

// ---- reminder alerts ----
setInterval(async () => {
  try { const r = await api('/api/reminders/due');
    r.due.forEach(x => { const t = 'Reminder: ' + x.text; toast(t); addMsg('assistant', t, 'rules'); speak(t);
      if ('Notification' in window && Notification.permission === 'granted') new Notification('JARVIS', {body: t}); });
    if (r.due.length) load(false);
  } catch (e) {}
}, 15000);
load();
