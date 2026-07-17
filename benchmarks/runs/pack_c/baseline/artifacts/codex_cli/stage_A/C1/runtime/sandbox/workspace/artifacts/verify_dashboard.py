from pathlib import Path
from playwright.sync_api import sync_playwright


ARTIFACT_DIR = Path(__file__).resolve().parent
HTML_PATH = ARTIFACT_DIR / "dashboard.html"
DESKTOP_SHOT = ARTIFACT_DIR / "dashboard_desktop.png"
MOBILE_SHOT = ARTIFACT_DIR / "dashboard_mobile.png"
NOTES_PATH = ARTIFACT_DIR / "verification_notes.md"


def verify_text(page):
    required_text = [
        "Document automation is ready for one more quarter.",
        "60% faster than 5d baseline",
        "10 fewer issues",
        "+1.1 score improvement",
        "2.3x pilot volume",
        "Source Data Quality",
        "Review Ownership",
    ]
    body = page.locator("body").inner_text()
    missing = [text for text in required_text if text not in body]
    if missing:
        raise AssertionError(f"Missing expected dashboard text: {missing}")


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--disable-gpu", "--single-process"],
        )
        page = browser.new_page(viewport={"width": 1440, "height": 1100}, device_scale_factor=1)
        page.goto(HTML_PATH.as_uri())
        page.wait_for_load_state("networkidle")
        verify_text(page)
        page.screenshot(path=str(DESKTOP_SHOT), full_page=True)
        browser.close()

        browser = p.chromium.launch(
            headless=True,
            args=["--disable-gpu", "--single-process"],
        )
        mobile = browser.new_page(
            viewport={"width": 390, "height": 1200},
            device_scale_factor=2,
            is_mobile=True,
        )
        mobile.goto(HTML_PATH.as_uri())
        mobile.wait_for_load_state("networkidle")
        verify_text(mobile)
        mobile.screenshot(path=str(MOBILE_SHOT), full_page=True)
        browser.close()

    NOTES_PATH.write_text(
        "\n".join(
            [
                "# Verification Notes",
                "",
                f"- Loaded static dashboard from `{HTML_PATH.name}` using Python Playwright Chromium.",
                f"- Captured desktop screenshot: `{DESKTOP_SHOT.name}` at 1440px viewport width.",
                f"- Captured mobile screenshot: `{MOBILE_SHOT.name}` at 390px viewport width.",
                "- Verified expected dashboard text for recommendation, metric deltas, and risk labels before screenshot capture.",
                "- Browser automation completed with Chromium launched using `--disable-gpu` and `--single-process`.",
                "",
            ]
        ),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
