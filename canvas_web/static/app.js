/* Canvas Assistant — chat UI */

marked.use({ breaks: true, gfm: true });

const messagesEl   = document.getElementById('messages');
const chatArea     = document.getElementById('chat-area');
const welcome      = document.getElementById('welcome');
const inputEl      = document.getElementById('question-input');
const sendBtn      = document.getElementById('send-btn');
const convList     = document.getElementById('conv-list');
const sidebar      = document.getElementById('sidebar');
const overlay      = document.getElementById('sidebar-overlay');
const settingsOver = document.getElementById('settings-overlay');

let activeConvId = null;

// ── Boot ──────────────────────────────────────────────────────────────────

loadConversations();

// ── Sidebar toggle (mobile) ───────────────────────────────────────────────

document.getElementById('menu-btn').addEventListener('click', openSidebar);
overlay.addEventListener('click', closeSidebar);

function openSidebar()  { sidebar.classList.add('open');    overlay.classList.remove('hidden'); }
function closeSidebar() { sidebar.classList.remove('open'); overlay.classList.add('hidden'); }

// ── New chat ──────────────────────────────────────────────────────────────

document.getElementById('new-chat-btn').addEventListener('click', startNewChat);
document.getElementById('new-chat-btn-mobile').addEventListener('click', startNewChat);

async function startNewChat() {
  closeSidebar();
  const res  = await fetch('/api/conversations', { method: 'POST', credentials: 'same-origin' });
  const conv = await res.json();
  activeConvId = conv.id;
  messagesEl.innerHTML = '';
  showWelcome(true);
  await loadConversations();
  setActiveItem(conv.id);
}

// ── Load conversation list ────────────────────────────────────────────────

async function loadConversations() {
  const res   = await fetch('/api/conversations', { credentials: 'same-origin' });
  const convs = await res.json();
  renderConvList(convs);
}

function renderConvList(convs) {
  convList.innerHTML = '';
  if (!convs.length) return;

  const groups = groupByDate(convs);
  for (const [label, items] of Object.entries(groups)) {
    if (!items.length) continue;
    const gl = document.createElement('div');
    gl.className = 'conv-group-label';
    gl.textContent = label;
    convList.appendChild(gl);

    for (const c of items) {
      convList.appendChild(makeConvItem(c));
    }
  }

  if (activeConvId) setActiveItem(activeConvId);
}

function makeConvItem(c) {
  const el = document.createElement('div');
  el.className = 'conv-item';
  el.dataset.id = c.id;

  const title = document.createElement('div');
  title.className = 'conv-title';
  title.textContent = c.title;

  const del = document.createElement('button');
  del.className = 'conv-delete';
  del.title = 'Delete';
  del.textContent = '✕';
  del.addEventListener('click', async (e) => {
    e.stopPropagation();
    if (!confirm('Delete this chat?')) return;
    await fetch(`/api/conversations/${c.id}`, { method: 'DELETE', credentials: 'same-origin' });
    if (activeConvId === c.id) {
      activeConvId = null;
      messagesEl.innerHTML = '';
      showWelcome(false);
    }
    await loadConversations();
  });

  el.appendChild(title);
  el.appendChild(del);
  el.addEventListener('click', () => openConversation(c.id));
  return el;
}

function setActiveItem(id) {
  document.querySelectorAll('.conv-item').forEach(el => {
    el.classList.toggle('active', parseInt(el.dataset.id) === id);
  });
}

// ── Open conversation ─────────────────────────────────────────────────────

async function openConversation(id) {
  closeSidebar();
  activeConvId = id;
  setActiveItem(id);

  const res  = await fetch(`/api/conversations/${id}`, { credentials: 'same-origin' });
  const conv = await res.json();

  messagesEl.innerHTML = '';
  if (conv.messages.length === 0) {
    showWelcome(true);
  } else {
    showWelcome(false);
    for (const m of conv.messages) {
      addMessage(m.role, m.content);
    }
    scrollToBottom();
  }
}

// ── Welcome / chat toggle ─────────────────────────────────────────────────

function showWelcome(show) {
  welcome.classList.toggle('hidden', !show);
  chatArea.classList.toggle('hidden', show);
}

// ── Suggestions ───────────────────────────────────────────────────────────

document.querySelectorAll('.suggestion-btn').forEach(btn => {
  btn.addEventListener('click', async () => {
    const text = btn.textContent;
    if (!activeConvId) {
      const res  = await fetch('/api/conversations', { method: 'POST', credentials: 'same-origin' });
      const conv = await res.json();
      activeConvId = conv.id;
      await loadConversations();
      setActiveItem(conv.id);
    }
    showWelcome(false);
    await sendMessage(text);
  });
});

// ── Input ─────────────────────────────────────────────────────────────────

inputEl.addEventListener('input', () => {
  inputEl.style.height = 'auto';
  inputEl.style.height = Math.min(inputEl.scrollHeight, 160) + 'px';
  sendBtn.disabled = !inputEl.value.trim();
});

inputEl.addEventListener('keydown', async (e) => {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    if (!inputEl.value.trim()) return;
    await handleSend();
  }
});

sendBtn.addEventListener('click', handleSend);

async function handleSend() {
  const text = inputEl.value.trim();
  if (!text) return;

  if (!activeConvId) {
    const res  = await fetch('/api/conversations', { method: 'POST', credentials: 'same-origin' });
    const conv = await res.json();
    activeConvId = conv.id;
    await loadConversations();
    setActiveItem(conv.id);
  }

  showWelcome(false);
  await sendMessage(text);
}

async function sendMessage(text) {
  inputEl.value = '';
  inputEl.style.height = 'auto';
  sendBtn.disabled = true;

  addMessage('user', text);
  const loadingBubble = addLoadingMessage();
  scrollToBottom();

  try {
    const res  = await fetch(`/api/conversations/${activeConvId}/message`, {
      method:      'POST',
      credentials: 'same-origin',
      headers:     { 'Content-Type': 'application/json' },
      body:        JSON.stringify({ question: text }),
    });
    const data = await res.json();

    loadingBubble.classList.remove('msg-loading');

    if (data.answer) {
      loadingBubble.innerHTML = marked.parse(data.answer);
      if (data.title) updateConvTitle(activeConvId, data.title);
    } else {
      loadingBubble.textContent = data.error || 'Something went wrong.';
      loadingBubble.style.color = '#ef4444';
    }
  } catch {
    loadingBubble.textContent = 'Network error — is the server running?';
    loadingBubble.style.color = '#ef4444';
  }

  scrollToBottom();
}

// ── Message rendering ─────────────────────────────────────────────────────

function addMessage(role, text) {
  const wrapper = document.createElement('div');
  wrapper.className = `message ${role}`;

  if (role === 'assistant') {
    const avatar = document.createElement('div');
    avatar.className = 'msg-avatar';
    avatar.textContent = '✳';
    wrapper.appendChild(avatar);
  }

  const bubble = document.createElement('div');
  bubble.className = 'msg-bubble';

  if (role === 'assistant') {
    bubble.innerHTML = marked.parse(text);
  } else {
    bubble.textContent = text;
  }

  wrapper.appendChild(bubble);
  messagesEl.appendChild(wrapper);
  return bubble;
}

function addLoadingMessage() {
  const wrapper = document.createElement('div');
  wrapper.className = 'message assistant';

  const avatar = document.createElement('div');
  avatar.className = 'msg-avatar';
  avatar.textContent = '✳';

  const bubble = document.createElement('div');
  bubble.className = 'msg-bubble msg-loading';
  bubble.textContent = 'Checking your Canvas…';

  wrapper.appendChild(avatar);
  wrapper.appendChild(bubble);
  messagesEl.appendChild(wrapper);
  return bubble;
}

function scrollToBottom() {
  chatArea.scrollTop = chatArea.scrollHeight;
}

// ── Update title in sidebar ───────────────────────────────────────────────

function updateConvTitle(id, title) {
  const item = convList.querySelector(`[data-id="${id}"] .conv-title`);
  if (item) item.textContent = title;
}

// ── Settings modal ────────────────────────────────────────────────────────

document.getElementById('settings-btn').addEventListener('click', openSettings);
document.getElementById('close-settings').addEventListener('click', closeSettings);
settingsOver.addEventListener('click', (e) => { if (e.target === settingsOver) closeSettings(); });

document.getElementById('save-settings-btn').addEventListener('click', async () => {
  const body = {
    canvas_url:     document.getElementById('s-canvas-url').value.trim(),
    canvas_token:   document.getElementById('s-canvas-token').value.trim(),
    openrouter_key: document.getElementById('s-openrouter-key').value.trim(),
    model_name:     document.getElementById('s-model-name').value.trim(),
  };
  await fetch('/api/settings', {
    method:      'POST',
    credentials: 'same-origin',
    headers:     { 'Content-Type': 'application/json' },
    body:        JSON.stringify(body),
  });
  const msg = document.getElementById('save-msg');
  msg.classList.remove('hidden');
  setTimeout(() => { msg.classList.add('hidden'); closeSettings(); }, 1200);
});

async function openSettings() {
  const res  = await fetch('/api/settings', { credentials: 'same-origin' });
  const data = await res.json();
  document.getElementById('s-canvas-url').value     = data.canvas_url     || '';
  document.getElementById('s-canvas-token').value   = data.canvas_token   || '';
  document.getElementById('s-openrouter-key').value = data.openrouter_key || '';
  document.getElementById('s-model-name').value     = data.model_name     || '';
  settingsOver.classList.remove('hidden');
}

function closeSettings() {
  settingsOver.classList.add('hidden');
}

// ── Date grouping ─────────────────────────────────────────────────────────

function groupByDate(convs) {
  const now       = new Date();
  const today     = startOf(now);
  const yesterday = startOf(new Date(now - 86400000));
  const week      = startOf(new Date(now - 7 * 86400000));

  const groups = { 'Today': [], 'Yesterday': [], 'Previous 7 days': [], 'Older': [] };
  for (const c of convs) {
    const d = new Date(c.updated_at);
    if (d >= today)         groups['Today'].push(c);
    else if (d >= yesterday) groups['Yesterday'].push(c);
    else if (d >= week)     groups['Previous 7 days'].push(c);
    else                    groups['Older'].push(c);
  }
  return groups;
}

function startOf(date) {
  return new Date(date.getFullYear(), date.getMonth(), date.getDate());
}
