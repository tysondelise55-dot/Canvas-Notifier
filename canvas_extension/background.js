async function fetchCanvasData(canvasUrl, canvasToken) {
  const base = canvasUrl.replace(/\/$/, '');
  const headers = { 'Authorization': `Bearer ${canvasToken}` };

  const coursesRes = await fetch(
    `${base}/api/v1/courses?enrollment_state=active&per_page=50`,
    { headers }
  );
  if (!coursesRes.ok) throw new Error('Failed to fetch courses. Check your Canvas URL and token.');
  const courses = await coursesRes.json();

  const allAssignments = [];
  for (const course of courses) {
    try {
      let url = `${base}/api/v1/courses/${course.id}/assignments?per_page=50&bucket=upcoming&order_by=due_at&include[]=submission`;
      while (url) {
        const res = await fetch(url, { headers });
        if (!res.ok) break;
        const assignments = await res.json();
        for (const a of assignments) {
          a._course_name = course.name;
        }
        allAssignments.push(...assignments);
        const link = res.headers.get('Link') || '';
        const next = link.split(',').find(p => p.includes('rel="next"'));
        url = next ? next.trim().split(';')[0].trim().slice(1, -1) : null;
      }
    } catch {
      // skip courses that error
    }
  }

  return { courses, assignments: allAssignments };
}

async function askClaude(apiKey, question, canvasData) {
  const today = new Date();
  const assignmentLines = canvasData.assignments.map(a => {
    const due = a.due_at
      ? new Date(a.due_at).toLocaleString('en-US', { weekday: 'short', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' })
      : 'No due date';
    const submitted = a.submission?.submitted_at ? ' ✓ submitted' : '';
    const type = a.submission_types?.includes('online_quiz') ? ' [QUIZ/TEST]' : '';
    return `- ${a.name}${type} | ${a._course_name} | due: ${due}${submitted}`;
  }).join('\n');

  const system = `You are a friendly Canvas LMS assistant for a 9th-grade high school student named Tyson.
You have real-time access to his Canvas assignments and courses.
Today is ${today.toLocaleDateString('en-US', { weekday: 'long', year: 'numeric', month: 'long', day: 'numeric' })}.
Be concise, warm, and encouraging. When helpful, offer a quick study tip or reminder.
If an assignment is close (within 2 days), flag it clearly.

CANVAS DATA
Courses: ${canvasData.courses.map(c => c.name).join(', ')}

Upcoming assignments:
${assignmentLines || 'No upcoming assignments found.'}`;

  const res = await fetch('https://api.anthropic.com/v1/messages', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'x-api-key': apiKey,
      'anthropic-version': '2023-06-01',
      'anthropic-dangerous-direct-browser-access': 'true'
    },
    body: JSON.stringify({
      model: 'claude-haiku-4-5-20251001',
      max_tokens: 1024,
      system,
      messages: [{ role: 'user', content: question }]
    })
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.error?.message || 'Claude API error. Check your Anthropic API key.');
  }

  const data = await res.json();
  return data.content[0].text;
}

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message.type === 'ASK') {
    chrome.storage.local.get(['canvasUrl', 'canvasToken', 'anthropicKey'], async (settings) => {
      const { canvasUrl, canvasToken, anthropicKey } = settings;
      if (!canvasUrl || !canvasToken || !anthropicKey) {
        sendResponse({ success: false, error: 'Please configure your settings first.' });
        return;
      }
      try {
        const canvasData = await fetchCanvasData(canvasUrl, canvasToken);
        const answer = await askClaude(anthropicKey, message.question, canvasData);
        sendResponse({ success: true, answer });
      } catch (e) {
        sendResponse({ success: false, error: e.message });
      }
    });
    return true;
  }
});
