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

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth

# URLs to monitor
URLS = {
    # Hudson's Bay main
    "HudsonsBay": "https://www.alvarezandmarsal.com/HudsonsBay",
    "HBC-MotionMaterials": "https://www.alvarezandmarsal.com/content/hudsons-bay-canada-motion-materials",
    "HBC-CourtOrders": "https://www.alvarezandmarsal.com/content/hudsons-bay-canada-court-orders",
    "HBC-MonitorsReports": "https://www.alvarezandmarsal.com/content/hudsons-bay-canada-monitors-reports",
    "HBC-Notices": "https://www.alvarezandmarsal.com/content/hudsons-bay-canada-notices-0",
    "HBC-WEPP": "https://www.alvarezandmarsal.com/content/hudsons-bay-canada-wepp",
    "HBC-NoticeToCreditors": "https://www.alvarezandmarsal.com/content/hudsons-bay-canada-notice-creditors",
    # RioCan HBC JV (FTI Consulting)
    "RioCanHBC-CourtOrders": "https://cfcanada.fticonsulting.com/RioCanHBCJV/courtOrders.htm",
    "RioCanHBC-Reports": "https://cfcanada.fticonsulting.com/RioCanHBCJV/reports.htm",
    "RioCanHBC-Motions": "https://cfcanada.fticonsulting.com/RioCanHBCJV/motions.htm",
    "RioCanHBC-Other": "https://cfcanada.fticonsulting.com/RioCanHBCJV/other.htm",
    # Popeyes (BDO)
    "Popeyes-BDO": "https://www.bdo.ca/services/financial-advisory-services/business-restructuring-turnaround-services/current-engagements/popeyes",
    # Toys R Us Canada
    "TRUCanada": "https://www.alvarezandmarsal.com/TRUCanada",
    "TRU-NoticeToCreditors": "https://www.alvarezandmarsal.com/content/toys-r-us-canada-notice-creditors",
    "TRU-MotionMaterials": "https://www.alvarezandmarsal.com/content/toys-r-us-canada-motion-materials",
    "TRU-CourtOrders": "https://www.alvarezandmarsal.com/content/toys-r-us-canada-court-orders",
    "TRU-MonitorsReports": "https://www.alvarezandmarsal.com/content/toys-r-us-canada-monitors-reports",
    "TRU-ServiceList": "https://www.alvarezandmarsal.com/content/toys-r-us-canada-service-list",
}

# File to store previous content
STATE_FILE = Path(__file__).parent / "data" / "previous_content.json"

# Directory for per-URL screenshots (one file per URL, overwritten each run)
SCREENSHOT_DIR = Path(__file__).parent / "data" / "screenshots"

# Email settings
RECIPIENT_EMAILS = [
    "dmcmillan@globeandmail.com",
    "SRobertson@globeandmail.com",
]


def extract_text_from_html(html: str) -> str:
    """Extract normalized body text from an HTML string."""
    soup = BeautifulSoup(html, "html.parser")

    # Remove structural chrome and third-party injected noise
    for element in soup(["script", "style", "nav", "footer", "header"]):
        element.decompose()

    # Remove cookie consent banners (injected dynamically, change unpredictably)
    # OneTrust (used by A&M)
    for element in soup(id="onetrust-consent-sdk"):
        element.decompose()
    # CookieYes (used by BDO) - strip any element whose first class starts with "cky-"
    for element in soup(lambda tag: any(c.startswith("cky-") for c in tag.get("class", []))):
        element.decompose()

    lines = [line.strip() for line in soup.get_text(separator="\n", strip=True).splitlines() if line.strip()]
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


def diff_to_html(diff_text: str) -> str:
    """Convert unified diff to color-coded HTML."""
    if not diff_text:
        return "<p><em>No differences found</em></p>"

    lines = []
    for line in diff_text.splitlines():
        escaped = line.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        if line.startswith("+") and not line.startswith("+++"):
            lines.append(f'<div style="background-color: #d4edda; color: #155724; padding: 2px 8px; font-family: monospace; white-space: pre-wrap;">{escaped}</div>')
        elif line.startswith("-") and not line.startswith("---"):
            lines.append(f'<div style="background-color: #f8d7da; color: #721c24; padding: 2px 8px; font-family: monospace; white-space: pre-wrap;">{escaped}</div>')
        elif line.startswith("@@"):
            lines.append(f'<div style="background-color: #e2e3e5; color: #383d41; padding: 2px 8px; font-family: monospace; margin-top: 10px;">{escaped}</div>')
        else:
            lines.append(f'<div style="padding: 2px 8px; font-family: monospace; white-space: pre-wrap;">{escaped}</div>')

    return "".join(lines)


def send_email_gmail(subject: str, body: str, html_body: str = None) -> None:
    """Send email via Gmail SMTP with optional HTML."""
    gmail_address = os.environ.get("GMAIL_ADDRESS")
    gmail_app_password = os.environ.get("GMAIL_APP_PASSWORD")

    if not gmail_address or not gmail_app_password:
        print("ERROR: GMAIL_ADDRESS and GMAIL_APP_PASSWORD environment variables required")
        print("Email would have been sent:")
        print(f"Subject: {subject}")
        print(f"Body:\n{body}")
        return

    msg = MIMEMultipart("alternative")
    msg["From"] = gmail_address
    msg["To"] = ", ".join(RECIPIENT_EMAILS)
    msg["Subject"] = subject

    # Attach plain text version
    msg.attach(MIMEText(body, "plain"))

    # Attach HTML version if provided
    if html_body:
        msg.attach(MIMEText(html_body, "html"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(gmail_address, gmail_app_password)
            server.sendmail(gmail_address, RECIPIENT_EMAILS, msg.as_string())
        print(f"Email sent successfully to {', '.join(RECIPIENT_EMAILS)}")
    except Exception as e:
        print(f"Failed to send email: {e}")


def check_for_changes() -> list[dict]:
    """
    Load each URL in a real browser, take a screenshot, extract text, and
    compare against the stored baseline.  Returns a list of changes detected.
    """
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    previous_state = load_previous_state()
    current_state = {}
    changes = []

    with Stealth().use_sync(sync_playwright()) as p:
        browser = p.chromium.launch()

        for name, url in URLS.items():
            print(f"Checking {name}: {url}")
            try:
                page = browser.new_page()
                page.goto(url, wait_until="domcontentloaded", timeout=30000)

                page.screenshot(path=str(SCREENSHOT_DIR / f"{name}.png"), full_page=True)
                current_text = extract_text_from_html(page.content())
                page.close()

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

            except Exception as e:
                print(f"  ERROR fetching {url}: {e}")
                if name in previous_state:
                    current_state[name] = previous_state[name]

            # Save after every URL so a hang or crash later doesn't lose earlier baselines.
            save_state(current_state)

        browser.close()

    return changes


def main():
    print(f"URL Monitor starting at {datetime.now().isoformat()}")
    print("-" * 50)

    changes = check_for_changes()

    if changes:
        print(f"\n{len(changes)} change(s) detected!")

        for change in changes:
            subject = f"URL Change Detected: {change['name']}"

            # Plain text version
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

            # HTML version
            html_body = f"""
<!DOCTYPE html>
<html>
<head>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 800px; margin: 0 auto; padding: 20px; }}
        .header {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 20px; border-radius: 8px; margin-bottom: 20px; }}
        .header h1 {{ margin: 0 0 10px 0; font-size: 24px; }}
        .info-box {{ background-color: #f8f9fa; border-left: 4px solid #667eea; padding: 15px; margin-bottom: 20px; }}
        .info-box p {{ margin: 5px 0; }}
        .label {{ font-weight: bold; color: #495057; }}
        .diff-container {{ background-color: #f8f9fa; border: 1px solid #dee2e6; border-radius: 8px; padding: 15px; overflow-x: auto; }}
        .diff-header {{ font-weight: bold; margin-bottom: 10px; color: #495057; }}
        .legend {{ display: flex; gap: 20px; margin-bottom: 15px; font-size: 14px; }}
        .legend-item {{ display: flex; align-items: center; gap: 5px; }}
        .legend-added {{ width: 16px; height: 16px; background-color: #d4edda; border: 1px solid #c3e6cb; }}
        .legend-removed {{ width: 16px; height: 16px; background-color: #f8d7da; border: 1px solid #f5c6cb; }}
        .footer {{ margin-top: 30px; padding-top: 20px; border-top: 1px solid #dee2e6; font-size: 12px; color: #6c757d; }}
        a {{ color: #667eea; }}
    </style>
</head>
<body>
    <div class="header">
        <h1>Change Detected</h1>
        <p>{change['name']}</p>
    </div>

    <div class="info-box">
        <p><span class="label">Page:</span> {change['name']}</p>
        <p><span class="label">URL:</span> <a href="{change['url']}">{change['url']}</a></p>
        <p><span class="label">Detected:</span> {change['timestamp']}</p>
    </div>

    <div class="diff-container">
        <div class="diff-header">Changes</div>
        <div class="legend">
            <div class="legend-item"><div class="legend-added"></div> Added</div>
            <div class="legend-item"><div class="legend-removed"></div> Removed</div>
        </div>
        {diff_to_html(change['diff'])}
    </div>

    <div class="footer">
        This is an automated message from URL Monitor.
    </div>
</body>
</html>
"""
            send_email_gmail(subject, body, html_body)
    else:
        print("\nNo changes detected.")

    print("-" * 50)
    print("Monitor complete.")


if __name__ == "__main__":
    main()
