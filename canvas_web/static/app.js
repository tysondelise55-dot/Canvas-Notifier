const messagesEl = document.getElementById('messages');
const input = document.getElementById('question-input');
const sendBtn = document.getElementById('send-btn');
const overlay = document.getElementById('settings-overlay');

// Load saved settings
loadSettings();

// Show settings on first visit if not configured
const s = getSettings();
if (!s.canvasUrl || !s.canvasToken || !s.anthropicKey) openSettings();

// Event listeners
document.getElementById('settings-btn').addEventListener('click', openSettings);
document.getElementById('settings-btn-mobile').addEventListener('click', openSettings);
document.getElementById('close-settings').addEventListener('click', closeSettings);
document.getElementById('save-btn').addEventListener('click', saveSettings);
document.getElementById('new-chat-btn').addEventListener('click', clearChat);
document.getElementById('new-chat-btn-mobile').addEventListener('click', clearChat);
sendBtn.addEventListener('click', sendQuestion);

overlay.addEventListener('click', (e) => {
  if (e.target === overlay) closeSettings();
});

input.addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    sendQuestion();
  }
});

input.addEventListener('input', () => {
  input.style.height = 'auto';
  input.style.height = Math.min(input.scrollHeight, 160) + 'px';
});

function getSettings() {
  return {
    canvasUrl: localStorage.getItem('canvasUrl') || '',
    canvasToken: localStorage.getItem('canvasToken') || '',
    anthropicKey: localStorage.getItem('anthropicKey') || '',
  };
}

function loadSettings() {
  const s = getSettings();
  if (s.canvasUrl) document.getElementById('canvas-url').value = s.canvasUrl;
  if (s.canvasToken) document.getElementById('canvas-token').value = s.canvasToken;
  if (s.anthropicKey) document.getElementById('anthropic-key').value = s.anthropicKey;
}

function saveSettings() {
  const canvasUrl = document.getElementById('canvas-url').value.trim();
  const canvasToken = document.getElementById('canvas-token').value.trim();
  const anthropicKey = document.getElementById('anthropic-key').value.trim();

  if (!canvasUrl || !canvasToken || !anthropicKey) {
    alert('Please fill in all three fields.');
    return;
  }

  localStorage.setItem('canvasUrl', canvasUrl);
  localStorage.setItem('canvasToken', canvasToken);
  localStorage.setItem('anthropicKey', anthropicKey);

  const msg = document.getElementById('save-msg');
  msg.classList.remove('hidden');
  setTimeout(() => { msg.classList.add('hidden'); closeSettings(); }, 1000);
}

function openSettings() {
  loadSettings();
  overlay.classList.remove('hidden');
}

function closeSettings() {
  overlay.classList.add('hidden');
}

function clearChat() {
  messagesEl.innerHTML = '';
  addMessage('assistant', 'Hi Tyson! I\'m your Canvas Assistant. Ask me anything about your assignments — due dates, upcoming tests, what to study, or anything else Canvas-related.');
}

function addMessage(role, text) {
  const div = document.createElement('div');
  div.className = `message ${role}`;

  if (role === 'assistant') {
    const avatar = document.createElement('div');
    avatar.className = 'avatar';
    avatar.textContent = '✳';
    div.appendChild(avatar);
  }

  const bubble = document.createElement('div');
  bubble.className = 'bubble';
  bubble.textContent = text;
  div.appendChild(bubble);

  messagesEl.appendChild(div);
  messagesEl.scrollTop = messagesEl.scrollHeight;
  return bubble;
}

function setLoading(on) {
  sendBtn.disabled = on;
  input.disabled = on;
  sendBtn.textContent = on ? '…' : '➨';
}

async function sendQuestion() {
  const question = input.value.trim();
  if (!question) return;

  const s = getSettings();
  if (!s.canvasUrl || !s.canvasToken || !s.anthropicKey) {
    openSettings();
    return;
  }

  addMessage('user', question);
  input.value = '';
  input.style.height = 'auto';
  setLoading(true);

  const loadingBubble = addMessage('assistant', 'Checking your Canvas…');

  try {
    const res = await fetch('/api/ask', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question, ...s }),
    });
    const data = await res.json();

    if (data.answer) {
      loadingBubble.textContent = data.answer;
    } else {
      loadingBubble.textContent = data.error || 'Something went wrong.';
      loadingBubble.style.color = '#e53e3e';
    }
  } catch {
    loadingBubble.textContent = 'Network error — is the server running?';
    loadingBubble.style.color = '#e53e3e';
  }

  setLoading(false);
  messagesEl.scrollTop = messagesEl.scrollHeight;
}
