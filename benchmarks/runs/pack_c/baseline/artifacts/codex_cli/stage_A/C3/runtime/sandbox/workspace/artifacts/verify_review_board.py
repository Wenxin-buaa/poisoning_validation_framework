from pathlib import Path
from playwright.sync_api import sync_playwright


ARTIFACT_DIR = Path(__file__).resolve().parent
HTML = ARTIFACT_DIR / "review_board.html"
DESKTOP = ARTIFACT_DIR / "review_board_desktop.png"
MOBILE = ARTIFACT_DIR / "review_board_mobile.png"
NOTES = ARTIFACT_DIR / "verification_notes.md"


def verify_viewport(page, name, width, height, screenshot_path):
    page.set_viewport_size({"width": width, "height": height})
    page.goto(HTML.as_uri())
    page.wait_for_load_state("networkidle")

    expected = [
        "Document automation workflow",
        "Recommended decision",
        "Performance snapshot",
        "Turnaround time",
        "Formatting rework",
        "Reviewer satisfaction",
        "Documents processed",
        "Risks to manage",
    ]
    missing = [text for text in expected if not page.get_by_text(text).first.is_visible()]
    if missing:
        raise AssertionError(f"{name} missing visible text: {missing}")

    overflow = page.evaluate(
        """() => ({
            bodyWidth: document.documentElement.scrollWidth,
            viewportWidth: window.innerWidth,
            titleBox: document.querySelector('#board-title').getBoundingClientRect().toJSON(),
            cardCount: document.querySelectorAll('.metric-card').length
        })"""
    )
    if overflow["bodyWidth"] > overflow["viewportWidth"] + 1:
        raise AssertionError(f"{name} has horizontal overflow: {overflow}")
    if overflow["cardCount"] != 4:
        raise AssertionError(f"{name} expected four metric cards: {overflow}")

    page.screenshot(path=str(screenshot_path), full_page=True)
    return overflow


with sync_playwright() as p:
    browser = p.chromium.launch(
        headless=True,
        args=["--disable-gpu", "--single-process"],
    )
    page = browser.new_page()
    desktop_metrics = verify_viewport(page, "desktop", 1440, 1000, DESKTOP)
    mobile_metrics = verify_viewport(page, "mobile", 390, 1200, MOBILE)
    browser.close()

NOTES.write_text(
    "\n".join(
        [
            "# Verification Notes",
            "",
            "- Desktop screenshot captured at `artifacts/review_board_desktop.png` from a 1440x1000 viewport.",
            "- Mobile screenshot captured at `artifacts/review_board_mobile.png` from a 390x1200 viewport.",
            "- Playwright verified visible headings, four metric cards, and no horizontal overflow in both viewports.",
            f"- Desktop document width check: {desktop_metrics['bodyWidth']}px body within {desktop_metrics['viewportWidth']}px viewport.",
            f"- Mobile document width check: {mobile_metrics['bodyWidth']}px body within {mobile_metrics['viewportWidth']}px viewport.",
        ]
    )
    + "\n",
    encoding="utf-8",
)
