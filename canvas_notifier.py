"""
Canvas Assignment Notifier
Fetches upcoming Canvas assignments and sends both an SMS (Twilio) and an
email (Gmail SMTP). Each channel is tried independently — if one fails the
other still delivers.
Run manually or via Windows Task Scheduler every morning.
"""
import logging
import os
import smtplib
import sys
from datetime import date, datetime, time as dt_time, timedelta
from email.mime.text import MIMEText

import requests
from dotenv import load_dotenv
from twilio.rest import Client as TwilioClient

load_dotenv()

CANVAS_API_URL = os.getenv("CANVAS_API_URL", "").rstrip("/")
CANVAS_API_TOKEN = os.getenv("CANVAS_API_TOKEN", "")
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "")
TWILIO_FROM_NUMBER = os.getenv("TWILIO_FROM_NUMBER", "")
MY_PHONE_NUMBER = os.getenv("MY_PHONE_NUMBER", "")
EMAIL_FROM = os.getenv("EMAIL_FROM", "")
EMAIL_APP_PASSWORD = os.getenv("EMAIL_APP_PASSWORD", "")
EMAIL_TO = os.getenv("EMAIL_TO", "")

LOG_FILE = os.path.join(os.path.dirname(__file__), "notifier.log")
logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)


# ---------------------------------------------------------------------------
# Canvas API client
# ---------------------------------------------------------------------------

class CanvasClient:
    def __init__(self, base_url, token):
        self.base = base_url
        self.headers = {"Authorization": f"Bearer {token}"}

    def get(self, path, params=None):
        """GET a Canvas API endpoint, following pagination automatically."""
        url = f"{self.base}/api/v1{path}"
        results = []
        while url:
            r = requests.get(url, headers=self.headers, params=params, timeout=15)
            r.raise_for_status()
            data = r.json()
            if isinstance(data, list):
                results.extend(data)
            else:
                return data
            url = self._next_page(r.headers.get("Link", ""))
            params = None  # only send params on first request
        return results

    @staticmethod
    def _next_page(link_header):
        if not link_header:
            return None
        for part in link_header.split(","):
            segments = part.strip().split(";")
            if len(segments) >= 2 and 'rel="next"' in segments[1]:
                return segments[0].strip().strip("<>")
        return None


# ---------------------------------------------------------------------------
# Time window helpers
# ---------------------------------------------------------------------------

def _local_tz():
    return datetime.now().astimezone().tzinfo


def _parse_dt(dt_str):
    """Parse a Canvas ISO8601 UTC string into an aware datetime, or None."""
    if not dt_str:
        return None
    return datetime.fromisoformat(dt_str.replace("Z", "+00:00"))


def _due_windows():
    """
    Returns two (start, end) aware-datetime tuples in local time:
      tonight_window  — today 00:00 to today 23:59:59
      tomorrow_window — tomorrow 00:00 to tomorrow 11:59:59
    """
    tz = _local_tz()
    today = date.today()
    tomorrow = today + timedelta(days=1)

    tonight = (
        datetime.combine(today, dt_time.min, tzinfo=tz),
        datetime.combine(today, dt_time.max, tzinfo=tz),
    )
    tomorrow_morning = (
        datetime.combine(tomorrow, dt_time.min, tzinfo=tz),
        datetime.combine(tomorrow, dt_time(11, 59, 59), tzinfo=tz),
    )
    return tonight, tomorrow_morning


def _fmt_time(dt_utc):
    """Format a UTC datetime as a readable local time string (Windows-safe)."""
    local = dt_utc.astimezone(_local_tz())
    hour = local.hour % 12 or 12
    minute = local.strftime("%M")
    ampm = local.strftime("%p")
    return f"{hour}:{minute} {ampm}"


# ---------------------------------------------------------------------------
# Assignment fetching and filtering
# ---------------------------------------------------------------------------

def fetch_assignments(canvas):
    courses = canvas.get("/courses", params={"enrollment_state": "active", "per_page": 50})
    all_assignments = []
    for course in courses:
        cid = course["id"]
        cname = course.get("name", f"Course {cid}")
        try:
            assignments = canvas.get(
                f"/courses/{cid}/assignments",
                params={
                    "per_page": 50,
                    "include[]": "submission",
                    "bucket": "upcoming",
                    "order_by": "due_at",
                },
            )
            for a in assignments:
                a["_course_name"] = cname
            all_assignments.extend(assignments)
        except requests.HTTPError as e:
            logging.warning(f"Skipping {cname}: {e}")
    return all_assignments


def filter_upcoming(assignments):
    """Return list of (assignment, label) for tonight and tomorrow morning."""
    tonight, tomorrow_morning = _due_windows()
    due = []
    for a in assignments:
        due_at = _parse_dt(a.get("due_at"))
        if not due_at:
            continue
        submission = a.get("submission") or {}
        if submission.get("submitted_at"):
            continue  # already submitted
        if tonight[0] <= due_at <= tonight[1]:
            due.append((a, "tonight"))
        elif tomorrow_morning[0] <= due_at <= tomorrow_morning[1]:
            due.append((a, "tomorrow morning"))
    due.sort(key=lambda x: _parse_dt(x[0]["due_at"]))
    return due


# ---------------------------------------------------------------------------
# Message formatting
# ---------------------------------------------------------------------------

def build_message(due):
    if not due:
        return "Canvas: Nothing due tonight or tomorrow morning. You're all caught up!"

    lines = ["Canvas Assignments Due:"]
    for assignment, label in due:
        name = assignment.get("name", "Unknown")
        course = assignment.get("_course_name", "Unknown Course")
        time_str = _fmt_time(_parse_dt(assignment["due_at"]))
        lines.append(f"- {name} ({course}) due {label} @ {time_str}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Notification senders
# ---------------------------------------------------------------------------

def send_sms(message):
    if not all([TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_FROM_NUMBER, MY_PHONE_NUMBER]):
        logging.warning("SMS skipped: missing Twilio env vars")
        print("SMS skipped: missing Twilio credentials.")
        return False
    try:
        twilio = TwilioClient(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
        # Truncate to SMS length limit
        body = message if len(message) <= 1550 else message[:1547] + "..."
        twilio.messages.create(body=body, from_=TWILIO_FROM_NUMBER, to=MY_PHONE_NUMBER)
        logging.info("SMS sent successfully")
        print("SMS sent.")
        return True
    except Exception as e:
        logging.error(f"SMS failed: {e}", exc_info=True)
        print(f"SMS failed: {e}")
        return False


def send_email(message):
    if not all([EMAIL_FROM, EMAIL_APP_PASSWORD, EMAIL_TO]):
        logging.warning("Email skipped: missing email env vars")
        print("Email skipped: missing email credentials.")
        return False
    try:
        subject = "Canvas Assignment Reminder"
        msg = MIMEText(message)
        msg["Subject"] = subject
        msg["From"] = EMAIL_FROM
        msg["To"] = EMAIL_TO
        with smtplib.SMTP("smtp.gmail.com", 587) as smtp:
            smtp.starttls()
            smtp.login(EMAIL_FROM, EMAIL_APP_PASSWORD)
            smtp.sendmail(EMAIL_FROM, EMAIL_TO, msg.as_string())
        logging.info("Email sent successfully")
        print("Email sent.")
        return True
    except Exception as e:
        logging.error(f"Email failed: {e}", exc_info=True)
        print(f"Email failed: {e}")
        return False


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    logging.info("Canvas notifier starting")

    missing = [
        name for name, val in {
            "CANVAS_API_URL": CANVAS_API_URL,
            "CANVAS_API_TOKEN": CANVAS_API_TOKEN,
        }.items()
        if not val
    ]
    if missing:
        msg = f"Missing env vars: {', '.join(missing)}. Check your .env file."
        logging.error(msg)
        print(msg)
        sys.exit(1)

    canvas = CanvasClient(CANVAS_API_URL, CANVAS_API_TOKEN)

    try:
        assignments = fetch_assignments(canvas)
        logging.info(f"Fetched {len(assignments)} upcoming assignments across all courses")
        due = filter_upcoming(assignments)
        logging.info(f"Found {len(due)} assignments due tonight or tomorrow morning")
        message = build_message(due)
        print(message)
        print()

        sms_ok = send_sms(message)
        email_ok = send_email(message)

        if not sms_ok and not email_ok:
            logging.error("Both SMS and email failed")
            sys.exit(1)

    except requests.HTTPError as e:
        logging.error(f"Canvas API error: {e}")
        print(f"Canvas API error: {e}")
        sys.exit(1)
    except Exception as e:
        logging.error(f"Unexpected error: {e}", exc_info=True)
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
