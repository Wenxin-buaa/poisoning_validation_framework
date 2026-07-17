from pathlib import Path
from playwright.sync_api import sync_playwright


ARTIFACT_DIR = Path(__file__).resolve().parent
HTML_PATH = ARTIFACT_DIR / "dashboard.html"
DESKTOP_PATH = ARTIFACT_DIR / "dashboard_desktop.png"
MOBILE_PATH = ARTIFACT_DIR / "dashboard_mobile.png"
NOTES_PATH = ARTIFACT_DIR / "verification_notes.md"


def verify_page(page, viewport_name):
    page.goto(HTML_PATH.as_uri())
    page.wait_for_load_state("networkidle")
    title = page.locator("h1").inner_text()
    metrics = page.locator(".metric-card").count()
    risks = page.locator(".risk").count()
    assert "Document automation" in title, f"{viewport_name}: missing dashboard title"
    assert metrics == 4, f"{viewport_name}: expected 4 metric cards, saw {metrics}"
    assert risks == 2, f"{viewport_name}: expected 2 risk cards, saw {risks}"


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--disable-gpu", "--single-process"])
        desktop = browser.new_page(viewport={"width": 1440, "height": 1050}, device_scale_factor=1)
        verify_page(desktop, "desktop")
        desktop.screenshot(path=str(DESKTOP_PATH), full_page=True)
        desktop.close()
        browser.close()

        browser = p.chromium.launch(headless=True, args=["--disable-gpu", "--single-process"])
        mobile = browser.new_page(
            viewport={"width": 390, "height": 1200},
            device_scale_factor=2,
            is_mobile=True,
        )
        verify_page(mobile, "mobile")
        mobile.screenshot(path=str(MOBILE_PATH), full_page=True)
        mobile.close()
        browser.close()

    NOTES_PATH.write_text(
        "\n".join(
            [
                "# Verification Notes",
                "",
                "Rendered `dashboard.html` with Python Playwright using Chromium in headless mode.",
                "",
                "- Desktop screenshot: `dashboard_desktop.png` at a 1440px viewport.",
                "- Mobile screenshot: `dashboard_mobile.png` at a 390px mobile viewport.",
                "- DOM checks passed for the dashboard title, four metric cards, and two risk cards in both viewports.",
                "- Visual review targets: professional Tech Innovation theme, readable metric cards, responsive single-column mobile layout, and visible recommendation/risk sections.",
                "",
            ]
        ),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
