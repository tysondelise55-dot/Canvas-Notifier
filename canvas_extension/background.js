async function fetchCanvasData(canvasUrl, canvasToken) {
  const base    = canvasUrl.replace(/\/$/, '');
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
        for (const a of assignments) a._course_name = course.name;
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

async function askAI(apiKey, model, messages, canvasData, userName) {
  const today = new Date().toLocaleDateString('en-US', {
    weekday: 'long', year: 'numeric', month: 'long', day: 'numeric'
  });

  const assignmentLines = canvasData.assignments.map(a => {
    const due = a.due_at
      ? new Date(a.due_at).toLocaleString('en-US', {
          weekday: 'short', month: 'short', day: 'numeric',
          hour: 'numeric', minute: '2-digit'
        })
      : 'No due date';
    const submitted = a.submission?.submitted_at ? ' ✓ submitted' : '';
    const type      = a.submission_types?.includes('online_quiz') ? ' [QUIZ/TEST]' : '';
    return `- ${a.name}${type} | ${a._course_name} | due: ${due}${submitted}`;
  }).join('\n');

  const name   = userName ? ` for a high school student named ${userName}` : ' for a high school student';
  const system = `You are Canvas Assistant, an AI-powered study helper and homework tutor${name}.

## Your role
You have two core capabilities:
1. **Canvas assistant** — You have live data from the student's Canvas LMS including all upcoming assignments, due dates, course names, and submission statuses. Use this for accurate, specific answers about coursework.
2. **Homework tutor** — You can help with any subject: writing essays, solving math problems, explaining science concepts, reviewing history, studying for tests, brainstorming, proofreading, and more.

## Today's date
${today}

## Canvas data
Courses: ${canvasData.courses.map(c => c.name).join(', ') || 'None found'}

Upcoming assignments:
${assignmentLines || 'No upcoming assignments found.'}

## How to respond
- For Canvas questions: only reference assignments in the data above. Flag ⚠️ for items due within 24 hours. Never flag already-submitted work.
- For essay/writing help: help structure, improve, and give feedback — guide the student rather than writing it for them.
- For math: show step-by-step work with explanations.
- For concepts: use simple language and examples.
- Tone: warm, encouraging, and concise — like a knowledgeable tutor.
- Format: use markdown (bold, bullets, etc.) for clarity.`;

  const res = await fetch('https://openrouter.ai/api/v1/chat/completions', {
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${apiKey}`,
      'Content-Type': 'application/json',
      'X-Title': 'Canvas Assistant',
    },
    body: JSON.stringify({
      model:      model || 'nvidia/nemotron-3-super-120b-a12b:free',
      max_tokens: 1024,
      messages:   [{ role: 'system', content: system }, ...messages],
    }),
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.error?.message || `OpenRouter error (${res.status}). Check your API key.`);
  }

  const data = await res.json();
  return data.choices[0].message.content;
}

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message.type === 'ASK') {
    chrome.storage.local.get(
      ['canvasUrl', 'canvasToken', 'openrouterKey', 'userName', 'modelName'],
      async (settings) => {
        const { canvasUrl, canvasToken, openrouterKey, userName, modelName } = settings;
        if (!canvasUrl || !canvasToken || !openrouterKey) {
          sendResponse({ success: false, error: 'Please configure your settings first.' });
          return;
        }
        try {
          const canvasData = await fetchCanvasData(canvasUrl, canvasToken);
          const answer     = await askAI(openrouterKey, modelName, message.history, canvasData, userName);
          sendResponse({ success: true, answer });
        } catch (e) {
          sendResponse({ success: false, error: e.message });
        }
      }
    );
    return true;
  }
});
