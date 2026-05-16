from flask import Flask, request, jsonify, render_template
import requests as req
import os
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

app = Flask(__name__)

ENV_CANVAS_URL   = os.getenv("CANVAS_API_URL", "")
ENV_CANVAS_TOKEN = os.getenv("CANVAS_API_TOKEN", "")
ENV_ANTHROPIC_KEY = os.getenv("ANTHROPIC_API_KEY", "")


def fetch_canvas_data(canvas_url, canvas_token):
    base = canvas_url.rstrip("/")
    headers = {"Authorization": f"Bearer {canvas_token}"}

    r = req.get(f"{base}/api/v1/courses", headers=headers,
                params={"enrollment_state": "active", "per_page": 50}, timeout=15)
    r.raise_for_status()
    courses = r.json()

    all_assignments = []
    for course in courses:
        cid = course["id"]
        cname = course.get("name", f"Course {cid}")
        try:
            url = f"{base}/api/v1/courses/{cid}/assignments"
            params = {"per_page": 50, "bucket": "upcoming",
                      "order_by": "due_at", "include[]": "submission"}
            while url:
                res = req.get(url, headers=headers, params=params, timeout=15)
                if not res.ok:
                    break
                assignments = res.json()
                for a in assignments:
                    a["_course_name"] = cname
                all_assignments.extend(assignments)
                link = res.headers.get("Link", "")
                next_url = None
                for part in link.split(","):
                    segs = part.strip().split(";")
                    if len(segs) >= 2 and 'rel="next"' in segs[1]:
                        next_url = segs[0].strip().strip("<>")
                url = next_url
                params = None
        except Exception:
            pass

    return {"courses": courses, "assignments": all_assignments}


def ask_claude(api_key, question, canvas_data):
    from datetime import datetime
    today = datetime.now().strftime("%A, %B %d, %Y")

    lines = []
    for a in canvas_data["assignments"]:
        due = a.get("due_at", "No due date")
        if due and due != "No due date":
            from datetime import timezone
            from dateutil import parser as dtparser
            try:
                dt = dtparser.parse(due).astimezone()
                due = dt.strftime("%a %b %d, %I:%M %p")
            except Exception:
                pass
        submitted = " (submitted)" if (a.get("submission") or {}).get("submitted_at") else ""
        quiz = " [QUIZ/TEST]" if "online_quiz" in (a.get("submission_types") or []) else ""
        lines.append(f"- {a['name']}{quiz} | {a['_course_name']} | due: {due}{submitted}")

    system = f"""You are a friendly Canvas LMS assistant for a high school student named Tyson.
You have real-time access to his upcoming Canvas assignments.
Today is {today}. Be concise, warm, and encouraging.
If an assignment is within 2 days, flag it clearly. Offer a quick study tip when helpful.

CANVAS DATA
Courses: {', '.join(c.get('name','') for c in canvas_data['courses'])}

Upcoming assignments:
{chr(10).join(lines) if lines else 'No upcoming assignments.'}"""

    res = req.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        },
        json={
            "model": "claude-haiku-4-5-20251001",
            "max_tokens": 1024,
            "system": system,
            "messages": [{"role": "user", "content": question}],
        },
        timeout=30,
    )
    res.raise_for_status()
    return res.json()["content"][0]["text"]


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/ask", methods=["POST"])
def ask():
    data = request.get_json()
    canvas_url    = ENV_CANVAS_URL   or data.get("canvasUrl", "").strip()
    canvas_token  = ENV_CANVAS_TOKEN or data.get("canvasToken", "").strip()
    anthropic_key = ENV_ANTHROPIC_KEY or data.get("anthropicKey", "").strip()
    question      = data.get("question", "").strip()

    if not all([canvas_url, canvas_token, anthropic_key, question]):
        return jsonify({"error": "Missing credentials — open Settings and fill in your Canvas URL, Canvas token, and Anthropic API key."}), 400

    try:
        canvas_data = fetch_canvas_data(canvas_url, canvas_token)
        answer = ask_claude(anthropic_key, question, canvas_data)
        return jsonify({"answer": answer})
    except req.HTTPError as e:
        return jsonify({"error": f"API error: {e.response.status_code} — check your credentials."}), 502
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    app.run(debug=True, port=5000)
