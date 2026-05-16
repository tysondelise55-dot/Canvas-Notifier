"""Send a sample text and email to verify credentials are working."""
import os
import smtplib
from email.mime.text import MIMEText

from dotenv import load_dotenv
from twilio.rest import Client as TwilioClient

load_dotenv()

TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN  = os.getenv("TWILIO_AUTH_TOKEN", "")
TWILIO_FROM_NUMBER = os.getenv("TWILIO_FROM_NUMBER", "")
MY_PHONE_NUMBER    = os.getenv("MY_PHONE_NUMBER", "")
EMAIL_FROM         = os.getenv("EMAIL_FROM", "")
EMAIL_APP_PASSWORD = os.getenv("EMAIL_APP_PASSWORD", "")
EMAIL_TO           = os.getenv("EMAIL_TO", "")

SAMPLE = "Test from Canvas Notifier — SMS and email are working!"


def test_sms():
    if not all([TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_FROM_NUMBER, MY_PHONE_NUMBER]):
        print("SMS SKIPPED: missing Twilio env vars")
        return
    try:
        TwilioClient(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN).messages.create(
            body=SAMPLE, from_=TWILIO_FROM_NUMBER, to=MY_PHONE_NUMBER
        )
        print(f"SMS sent to {MY_PHONE_NUMBER}")
    except Exception as e:
        print(f"SMS FAILED: {e}")


def test_email():
    if not all([EMAIL_FROM, EMAIL_APP_PASSWORD, EMAIL_TO]):
        print("Email SKIPPED: missing email env vars")
        return
    try:
        msg = MIMEText(SAMPLE)
        msg["Subject"] = "Canvas Notifier — Test Message"
        msg["From"] = EMAIL_FROM
        msg["To"] = EMAIL_TO
        with smtplib.SMTP("smtp.gmail.com", 587) as smtp:
            smtp.starttls()
            smtp.login(EMAIL_FROM, EMAIL_APP_PASSWORD)
            smtp.sendmail(EMAIL_FROM, EMAIL_TO, msg.as_string())
        print(f"Email sent to {EMAIL_TO}")
    except Exception as e:
        print(f"Email FAILED: {e}")


test_sms()
test_email()
