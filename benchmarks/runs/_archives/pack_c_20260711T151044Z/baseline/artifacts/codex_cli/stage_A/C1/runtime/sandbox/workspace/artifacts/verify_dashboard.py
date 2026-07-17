from pathlib import Path
from playwright.sync_api import sync_playwright


ARTIFACT_DIR = Path(__file__).resolve().parent
HTML_PATH = ARTIFACT_DIR / "dashboard.html"
DESKTOP_PNG = ARTIFACT_DIR / "dashboard_desktop.png"
MOBILE_PNG = ARTIFACT_DIR / "dashboard_mobile.png"
NOTES_PATH = ARTIFACT_DIR / "verification_notes.md"


def check_page(page, viewport_name):
    page.goto(HTML_PATH.as_uri())
    page.wait_for_load_state("networkidle")
    page.wait_for_selector("text=Document Automation Pilot")

    expected_text = [
        "Turnaround dropped",
        "60%",
        "Recommendation: extend one quarter",
        "2 days",
        "4 items",
        "4.5 / 5",
        "42 docs",
        "Risks to Resolve Next Quarter",
    ]
    missing = [text for text in expected_text if not page.get_by_text(text, exact=False).count()]
    if missing:
        raise AssertionError(f"{viewport_name} missing expected text: {missing}")

    overflow = page.evaluate(
        """
        () => {
          const doc = document.documentElement;
          const body = document.body;
          return Math.max(body.scrollWidth, doc.scrollWidth) - doc.clientWidth;
        }
        """
    )
    if overflow > 1:
        raise AssertionError(f"{viewport_name} has horizontal overflow of {overflow}px")


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        desktop = browser.new_page(viewport={"width": 1440, "height": 1100}, device_scale_factor=1)
        check_page(desktop, "desktop")
        desktop.screenshot(path=str(DESKTOP_PNG), full_page=True)

        mobile = browser.new_page(viewport={"width": 390, "height": 1200}, is_mobile=True, device_scale_factor=2)
        check_page(mobile, "mobile")
        mobile.screenshot(path=str(MOBILE_PNG), full_page=True)
        browser.close()

    notes = f"""# Verification Notes

Rendered `dashboard.html` with Playwright Chromium from a local `file://` URL.

- Desktop screenshot: `dashboard_desktop.png`
- Mobile screenshot: `dashboard_mobile.png`

Checks performed:

- Confirmed the dashboard title, recommendation, key improvement message, four metric values, and risk section render in both viewports.
- Captured full-page PNG screenshots at 1440px desktop width and 390px mobile width.
- Checked both viewports for horizontal overflow.

Result: verification completed successfully.
"""
    NOTES_PATH.write_text(notes, encoding="utf-8")


if __name__ == "__main__":
    main()
