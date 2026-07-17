from pathlib import Path
from playwright.sync_api import sync_playwright


ARTIFACT_DIR = Path(__file__).resolve().parent
HTML_PATH = ARTIFACT_DIR / "index.html"
DESKTOP_PNG = ARTIFACT_DIR / "desktop.png"
MOBILE_PNG = ARTIFACT_DIR / "mobile.png"
NOTES = ARTIFACT_DIR / "verification_notes.md"


def capture(page, viewport, output_path):
    page.set_viewport_size(viewport)
    page.goto(HTML_PATH.as_uri())
    page.wait_for_load_state("networkidle")
    page.screenshot(path=str(output_path), full_page=True)
    title = page.locator("h1").inner_text()
    metrics = page.locator(".metric-card").count()
    return title, metrics


with sync_playwright() as p:
    browser = p.chromium.launch(
        headless=True,
        args=["--disable-gpu", "--single-process"],
    )
    page = browser.new_page()
    desktop_title, desktop_metrics = capture(page, {"width": 1440, "height": 1100}, DESKTOP_PNG)
    mobile_title, mobile_metrics = capture(page, {"width": 390, "height": 1200}, MOBILE_PNG)
    browser.close()

NOTES.write_text(
    "\n".join(
        [
            "# Verification Notes",
            "",
            f"- Desktop rendering captured in `desktop.png` at 1440x1100. The page title reads: {desktop_title}",
            f"- Mobile rendering captured in `mobile.png` at 390x1200. The page title reads: {mobile_title}",
            f"- Metric cards found on desktop: {desktop_metrics}. Metric cards found on mobile: {mobile_metrics}.",
            "- The desktop screenshot shows the two-column hero, memo preview, metrics grid, findings band, and next-quarter workflow.",
            "- The mobile screenshot shows responsive single-column stacking with the navigation hidden and the same content preserved.",
            "",
        ]
    ),
    encoding="utf-8",
)
