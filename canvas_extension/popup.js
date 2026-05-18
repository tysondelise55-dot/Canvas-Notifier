const chatView     = document.getElementById('chat-view');
const settingsView = document.getElementById('settings-view');
const messagesEl   = document.getElementById('messages');
const input        = document.getElementById('question-input');
const sendBtn      = document.getElementById('send-btn');

let history = [];

// Boot: check settings, restore conversation
chrome.storage.local.get(['canvasUrl', 'canvasToken', 'openrouterKey', 'userName', 'modelName'], (s) => {
  if (!s.canvasUrl || !s.canvasToken || !s.openrouterKey) {
    showSettings();
  } else {
    loadSettingsInputs(s);
    chrome.storage.session.get(['chatHistory'], (r) => {
      if (r.chatHistory?.length) {
        history = r.chatHistory;
        messagesEl.innerHTML = '';
        for (const m of history) renderMessage(m.role, m.content);
        messagesEl.scrollTop = messagesEl.scrollHeight;
      }
    });
  }
});

document.getElementById('settings-btn').addEventListener('click', showSettings);
document.getElementById('back-btn').addEventListener('click', showChat);
document.getElementById('save-btn').addEventListener('click', saveSettings);
document.getElementById('clear-btn').addEventListener('click', clearChat);
sendBtn.addEventListener('click', sendQuestion);

input.addEventListener('input', () => {
  input.style.height = 'auto';
  input.style.height = Math.min(input.scrollHeight, 80) + 'px';
  sendBtn.disabled = !input.value.trim();
});

input.addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    if (!input.value.trim()) return;
    sendQuestion();
  }
});

function showSettings() {
  chatView.classList.add('hidden');
  settingsView.classList.remove('hidden');
  chrome.storage.local.get(['canvasUrl', 'canvasToken', 'openrouterKey', 'userName', 'modelName'], loadSettingsInputs);
}

function showChat() {
  settingsView.classList.add('hidden');
  chatView.classList.remove('hidden');
}

function loadSettingsInputs(s) {
  if (s.userName)      document.getElementById('user-name').value      = s.userName;
  if (s.canvasUrl)     document.getElementById('canvas-url').value     = s.canvasUrl;
  if (s.canvasToken)   document.getElementById('canvas-token').value   = s.canvasToken;
  if (s.openrouterKey) document.getElementById('openrouter-key').value = s.openrouterKey;
  if (s.modelName)     document.getElementById('model-name').value     = s.modelName;
}

function saveSettings() {
  const canvasUrl     = document.getElementById('canvas-url').value.trim();
  const canvasToken   = document.getElementById('canvas-token').value.trim();
  const openrouterKey = document.getElementById('openrouter-key').value.trim();
  const userName      = document.getElementById('user-name').value.trim();
  const modelName     = document.getElementById('model-name').value.trim();

  if (!canvasUrl || !canvasToken || !openrouterKey) {
    alert('Please fill in Canvas URL, Canvas Token, and OpenRouter API Key.');
    return;
  }
  chrome.storage.local.set({ canvasUrl, canvasToken, openrouterKey, userName, modelName }, () => {
    const msg = document.getElementById('save-msg');
    msg.classList.remove('hidden');
    setTimeout(() => { msg.classList.add('hidden'); showChat(); }, 1000);
  });
}

function clearChat() {
  history = [];
  chrome.storage.session.remove(['chatHistory']);
  messagesEl.innerHTML = '';
  const welcome = document.createElement('div');
  welcome.className = 'message assistant';
  welcome.innerHTML = '<div class="bubble">Hi! Ask me anything about your Canvas assignments, or get help with essays, math, science — any homework question.</div>';
  messagesEl.appendChild(welcome);
}

function isCanvasQuestion(text) {
  const lower    = text.toLowerCase();
  const keywords = ['due', 'assign', 'class', 'course', 'quiz', 'exam', 'canvas',
                    'submit', 'grade', 'missing', 'tonight', 'tomorrow', 'overdue',
                    'test', 'week', 'schedule', 'homework'];
  return keywords.some(k => lower.includes(k));
}

// Simple markdown renderer
function renderMarkdown(text) {
  let html = text
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/\*(.+?)\*/g, '<em>$1</em>')
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/^#{1,3} (.+)$/gm, '<strong>$1</strong>');

  const lines = html.split('\n');
  const out   = [];
  let inList  = false;
  for (const line of lines) {
    if (/^[-*] (.+)/.test(line)) {
      if (!inList) { out.push('<ul>'); inList = true; }
      out.push('<li>' + line.replace(/^[-*] /, '') + '</li>');
    } else {
      if (inList) { out.push('</ul>'); inList = false; }
      out.push(line);
    }
  }
  if (inList) out.push('</ul>');
  return out.join('\n').replace(/\n\n+/g, '<br><br>').replace(/\n/g, '<br>');
}

function renderMessage(role, content) {
  const div    = document.createElement('div');
  div.className = `message ${role}`;
  const bubble = document.createElement('div');
  bubble.className = 'bubble';
  if (role === 'assistant') {
    bubble.innerHTML = renderMarkdown(content);
  } else {
    bubble.textContent = content;
  }
  div.appendChild(bubble);
  messagesEl.appendChild(div);
  messagesEl.scrollTop = messagesEl.scrollHeight;
  return bubble;
}

function sendQuestion() {
  const question = input.value.trim();
  if (!question) return;

  renderMessage('user', question);
  history.push({ role: 'user', content: question });

  input.value = '';
  input.style.height = 'auto';
  sendBtn.disabled = true;
  input.disabled   = true;

  // Loading bubble
  const loadingDiv    = document.createElement('div');
  loadingDiv.className = 'message assistant';
  const loadingBubble = document.createElement('div');
  loadingBubble.className = 'bubble loading';
  loadingBubble.textContent = isCanvasQuestion(question) ? 'Checking your Canvas…' : 'Claude is thinking…';
  loadingDiv.appendChild(loadingBubble);
  messagesEl.appendChild(loadingDiv);
  messagesEl.scrollTop = messagesEl.scrollHeight;

  chrome.runtime.sendMessage(
    { type: 'ASK', history: history.slice(-20) },
    (response) => {
      input.disabled   = false;
      sendBtn.disabled = false;
      loadingBubble.classList.remove('loading');

      if (response?.success) {
        loadingBubble.innerHTML = renderMarkdown(response.answer);
        history.push({ role: 'assistant', content: response.answer });
        chrome.storage.session.set({ chatHistory: history });
      } else {
        loadingBubble.textContent = response?.error || 'Something went wrong. Check your settings.';
        loadingBubble.style.color = '#ef4444';
        history.pop();
      }
      messagesEl.scrollTop = messagesEl.scrollHeight;
    }
  );
}
