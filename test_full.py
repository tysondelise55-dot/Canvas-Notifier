"""Send a real test of both the daily summary and weekly briefing."""
from canvas_notifier import (
    CanvasClient, fetch_assignments, filter_upcoming, filter_weekly_big,
    build_message, build_weekly_briefing, send_sms, send_email,
    CANVAS_API_URL, CANVAS_API_TOKEN,
)

canvas = CanvasClient(CANVAS_API_URL, CANVAS_API_TOKEN)
assignments = fetch_assignments(canvas)

due     = filter_upcoming(assignments)
big     = filter_weekly_big(assignments)
message = build_message(due)
weekly  = build_weekly_briefing(big)

print("--- Daily Summary ---")
print(message)
print()
print("--- Weekly Briefing ---")
print(weekly)
print()

sms_body = message + f"\n\n{weekly}"
send_sms(sms_body)
send_email(message, weekly_briefing=weekly)
