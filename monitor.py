"""
URL Change Monitor for Alvarez & Marsal HBC/TRU Canada pages
Checks for changes and sends email notifications via Gmail
"""

import json
import os
import smtplib
import difflib
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from pathlib import Path

import requests
from bs4 import BeautifulSoup

# URLs to monitor
URLS = {
    "HudsonsBay": "https://www.alvarezandmarsal.com/HudsonsBay",
    "TRUCanada": "https://www.alvarezandmarsal.com/TRUCanada",
}

# File to store previous content
STATE_FILE = Path(__file__).parent / "data" / "previous_content.json"

# Email settings
RECIPIENT_EMAIL = "dmcmillan@globeandmail.com"


def fetch_page_text(url: str) -> str:
    """Fetch a URL and extract body text content."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
    }
    response = requests.get(url, headers=headers, timeout=30)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")

    # Remove script and style elements
    for element in soup(["script", "style", "nav", "footer", "header"]):
        element.decompose()

    # Get text and normalize whitespace
    text = soup.get_text(separator="\n", strip=True)
    # Normalize multiple newlines
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return "\n".join(lines)


def load_previous_state() -> dict:
    """Load previously stored content."""
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {}


def save_state(state: dict) -> None:
    """Save current content state."""
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2))


def generate_diff(old_text: str, new_text: str) -> str:
    """Generate a human-readable diff between old and new text."""
    old_lines = old_text.splitlines()
    new_lines = new_text.splitlines()

    diff = difflib.unified_diff(
        old_lines, new_lines,
        fromfile="Previous",
        tofile="Current",
        lineterm=""
    )
    return "\n".join(diff)


def send_email_gmail(subject: str, body: str) -> None:
    """Send email via Gmail SMTP."""
    gmail_address = os.environ.get("GMAIL_ADDRESS")
    gmail_app_password = os.environ.get("GMAIL_APP_PASSWORD")

    if not gmail_address or not gmail_app_password:
        print("ERROR: GMAIL_ADDRESS and GMAIL_APP_PASSWORD environment variables required")
        print("Email would have been sent:")
        print(f"Subject: {subject}")
        print(f"Body:\n{body}")
        return

    msg = MIMEMultipart()
    msg["From"] = gmail_address
    msg["To"] = RECIPIENT_EMAIL
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(gmail_address, gmail_app_password)
            server.sendmail(gmail_address, RECIPIENT_EMAIL, msg.as_string())
        print(f"Email sent successfully to {RECIPIENT_EMAIL}")
    except Exception as e:
        print(f"Failed to send email: {e}")


def check_for_changes() -> list[dict]:
    """Check all URLs for changes. Returns list of changes detected."""
    previous_state = load_previous_state()
    current_state = {}
    changes = []

    for name, url in URLS.items():
        print(f"Checking {name}: {url}")
        try:
            current_text = fetch_page_text(url)
            current_state[name] = current_text

            if name in previous_state:
                if current_text != previous_state[name]:
                    diff = generate_diff(previous_state[name], current_text)
                    changes.append({
                        "name": name,
                        "url": url,
                        "diff": diff,
                        "timestamp": datetime.now().isoformat(),
                    })
                    print(f"  CHANGE DETECTED!")
                else:
                    print(f"  No changes")
            else:
                print(f"  First run - storing baseline")

        except requests.RequestException as e:
            print(f"  ERROR fetching {url}: {e}")
            # Keep previous state if fetch fails
            if name in previous_state:
                current_state[name] = previous_state[name]

    save_state(current_state)
    return changes


def main():
    print(f"URL Monitor starting at {datetime.now().isoformat()}")
    print("-" * 50)

    changes = check_for_changes()

    if changes:
        print(f"\n{len(changes)} change(s) detected!")

        for change in changes:
            subject = f"URL Change Detected: {change['name']}"
            body = f"""A change was detected on the monitored page.

Page: {change['name']}
URL: {change['url']}
Time: {change['timestamp']}

Changes:
{'-' * 40}
{change['diff']}
{'-' * 40}

This is an automated message from URL Monitor.
"""
            send_email_gmail(subject, body)
    else:
        print("\nNo changes detected.")

    print("-" * 50)
    print("Monitor complete.")


if __name__ == "__main__":
    main()
