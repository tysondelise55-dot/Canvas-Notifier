const chatView = document.getElementById('chat-view');
const settingsView = document.getElementById('settings-view');
const messagesEl = document.getElementById('messages');
const input = document.getElementById('question-input');
const sendBtn = document.getElementById('send-btn');

// Switch to settings if not configured yet
chrome.storage.local.get(['canvasUrl', 'canvasToken', 'anthropicKey'], (s) => {
  if (!s.canvasUrl || !s.canvasToken || !s.anthropicKey) showSettings();
  else loadSettingsInputs(s);
});

document.getElementById('settings-btn').addEventListener('click', showSettings);
document.getElementById('back-btn').addEventListener('click', showChat);
document.getElementById('save-btn').addEventListener('click', saveSettings);
sendBtn.addEventListener('click', sendQuestion);
input.addEventListener('keydown', (e) => { if (e.key === 'Enter') sendQuestion(); });

function showSettings() {
  chatView.classList.add('hidden');
  settingsView.classList.remove('hidden');
  chrome.storage.local.get(['canvasUrl', 'canvasToken', 'anthropicKey'], loadSettingsInputs);
}

function showChat() {
  settingsView.classList.add('hidden');
  chatView.classList.remove('hidden');
}

function loadSettingsInputs(s) {
  if (s.canvasUrl) document.getElementById('canvas-url').value = s.canvasUrl;
  if (s.canvasToken) document.getElementById('canvas-token').value = s.canvasToken;
  if (s.anthropicKey) document.getElementById('anthropic-key').value = s.anthropicKey;
}

function saveSettings() {
  const canvasUrl = document.getElementById('canvas-url').value.trim();
  const canvasToken = document.getElementById('canvas-token').value.trim();
  const anthropicKey = document.getElementById('anthropic-key').value.trim();
  if (!canvasUrl || !canvasToken || !anthropicKey) {
    alert('Please fill in all fields.');
    return;
  }
  chrome.storage.local.set({ canvasUrl, canvasToken, anthropicKey }, () => {
    const msg = document.getElementById('save-msg');
    msg.classList.remove('hidden');
    setTimeout(() => { msg.classList.add('hidden'); showChat(); }, 1000);
  });
}

function addMessage(role, text) {
  const div = document.createElement('div');
  div.className = `message ${role}`;
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
  sendBtn.textContent = on ? '...' : '➨';
}

function sendQuestion() {
  const question = input.value.trim();
  if (!question) return;

  addMessage('user', question);
  input.value = '';
  setLoading(true);

  const loadingBubble = addMessage('assistant', 'Checking your Canvas...');

  chrome.runtime.sendMessage({ type: 'ASK', question }, (response) => {
    setLoading(false);
    if (response?.success) {
      loadingBubble.textContent = response.answer;
    } else {
      loadingBubble.textContent = response?.error || 'Something went wrong. Check your settings.';
      loadingBubble.style.color = '#e53e3e';
    }
    messagesEl.scrollTop = messagesEl.scrollHeight;
  });
}
