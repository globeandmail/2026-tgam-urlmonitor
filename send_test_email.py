"""Send a test email to verify Gmail credentials work."""
import monitor

monitor.send_email_gmail(
    "URL Monitor Test - Please Ignore",
    "This is a test email from your URL Monitor.\n\nIf you received this, email notifications are working!"
)
