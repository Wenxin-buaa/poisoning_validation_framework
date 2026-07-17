from pathlib import Path
from urllib.parse import quote

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parent
HTML = ROOT / "dashboard.html"
DESKTOP = ROOT / "dashboard_desktop.png"
MOBILE = ROOT / "dashboard_mobile.png"
NOTES = ROOT / "verification_notes.md"


def file_url(path: Path) -> str:
    return "file://" + quote(str(path))


def verify_page(page) -> None:
    page.goto(file_url(HTML))
    page.wait_for_load_state("networkidle")
    page.get_by_role("heading", name="Document automation is ready for another quarter.").wait_for()
    for text in [
        "3 days faster",
        "10 fewer issues",
        "+1.1 score lift",
        "+24 documents",
        "Continue the pilot with tighter review controls.",
    ]:
        assert page.get_by_text(text).count() >= 1, text


with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, args=["--single-process"])
    page = browser.new_page(viewport={"width": 1440, "height": 1050}, device_scale_factor=1)
    verify_page(page)
    page.screenshot(path=str(DESKTOP), full_page=True)
    browser.close()

    browser = p.chromium.launch(headless=True, args=["--single-process"])
    mobile = browser.new_page(
        viewport={"width": 390, "height": 1200},
        device_scale_factor=2,
        is_mobile=True,
    )
    verify_page(mobile)
    mobile.screenshot(path=str(MOBILE), full_page=True)
    browser.close()

NOTES.write_text(
    "\n".join(
        [
            "# Verification Notes",
            "",
            "- Loaded `artifacts/dashboard.html` with Playwright Chromium using a local `file://` URL.",
            "- Desktop screenshot captured at `artifacts/dashboard_desktop.png` with a 1440 x 1050 viewport.",
            "- Mobile screenshot captured at `artifacts/dashboard_mobile.png` with a 390 x 1200 viewport.",
            "- Verified the main heading, recommended decision, and all four metric deltas from `metrics.csv` were present in the rendered page.",
            "",
        ]
    ),
    encoding="utf-8",
)

print(f"wrote {DESKTOP}")
print(f"wrote {MOBILE}")
print(f"wrote {NOTES}")
