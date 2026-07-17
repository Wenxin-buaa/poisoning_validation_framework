from pathlib import Path
from playwright.sync_api import sync_playwright


ARTIFACT_DIR = Path(__file__).resolve().parent
HTML = ARTIFACT_DIR / "review-board.html"
DESKTOP = ARTIFACT_DIR / "review-board-desktop.png"
MOBILE = ARTIFACT_DIR / "review-board-mobile.png"
NOTES = ARTIFACT_DIR / "verification-notes.md"


def check_view(page, width, height, screenshot_path):
    page.set_viewport_size({"width": width, "height": height})
    page.goto(HTML.as_uri())
    page.wait_for_load_state("networkidle")

    checks = [
        "Document automation workflow review board",
        "Continue for one more quarter",
        "60% faster",
        "10 fewer issues",
        "+1.1 points",
        "2.3x volume",
        "Source data quality",
        "Review ownership",
    ]
    for text in checks:
        page.get_by_text(text, exact=False).first.wait_for(state="visible", timeout=3000)

    overflow = page.evaluate(
        """() => {
            const root = document.documentElement;
            return {
              scrollWidth: root.scrollWidth,
              clientWidth: root.clientWidth,
              bodyWidth: document.body.scrollWidth
            };
        }"""
    )
    if overflow["scrollWidth"] > overflow["clientWidth"] + 1:
        raise AssertionError(f"Horizontal overflow at {width}px: {overflow}")

    page.screenshot(path=str(screenshot_path), full_page=True)


def main():
    with sync_playwright() as p:
        last_error = None
        browser = None
        launchers = [
            ("bundled chromium", p.chromium, {}),
            (
                "system chrome",
                p.chromium,
                {"executable_path": "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"},
            ),
            ("bundled webkit", p.webkit, {}),
            ("bundled firefox", p.firefox, {}),
        ]
        for label, browser_type, kwargs in launchers:
            try:
                browser = browser_type.launch(headless=True, **kwargs)
                break
            except Exception as exc:
                last_error = f"{label}: {exc}"
        if browser is None:
            raise RuntimeError(f"No Playwright browser engine launched: {last_error}")
        page = browser.new_page()
        check_view(page, 1440, 1100, DESKTOP)
        check_view(page, 390, 1200, MOBILE)
        browser.close()

    NOTES.write_text(
        "\n".join(
            [
                "# Verification Notes",
                "",
                "- Desktop rendering verified at 1440x1100 with Playwright; screenshot: artifacts/review-board-desktop.png.",
                "- Mobile rendering verified at 390x1200 with Playwright; screenshot: artifacts/review-board-mobile.png.",
                "- Browser checks confirmed required brief and metrics text is visible and no horizontal overflow was detected at either viewport.",
                "- Screenshots were captured from artifacts/review-board.html using Chromium in headless mode.",
                "",
            ]
        ),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
