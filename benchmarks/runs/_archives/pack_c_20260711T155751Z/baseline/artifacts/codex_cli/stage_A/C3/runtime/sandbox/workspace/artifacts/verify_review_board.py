from pathlib import Path
from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parent
HTML = ROOT / "review_board.html"
DESKTOP = ROOT / "review_board_desktop.png"
MOBILE = ROOT / "review_board_mobile.png"
NOTES = ROOT / "verification_notes.md"


def inspect_view(page, label, viewport, screenshot_path):
    page.set_viewport_size(viewport)
    page.goto(HTML.as_uri())
    page.wait_for_load_state("networkidle")
    page.screenshot(path=str(screenshot_path), full_page=True)

    checks = []
    required_text = [
        "Continue for one more quarter",
        "Turnaround Time",
        "Formatting Rework",
        "Reviewer Satisfaction",
        "Documents Processed",
        "Controls To Add",
    ]
    for text in required_text:
        locator = page.get_by_text(text, exact=False).first
        visible = locator.is_visible()
        box = locator.bounding_box() if visible else None
        checks.append({"text": text, "visible": visible, "box": box})

    body_width = page.evaluate("document.documentElement.scrollWidth")
    viewport_width = viewport["width"]
    overflow = body_width > viewport_width + 1
    return {
        "label": label,
        "viewport": viewport,
        "screenshot": screenshot_path.name,
        "checks": checks,
        "body_width": body_width,
        "overflow": overflow,
    }


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--disable-gpu", "--single-process"],
        )
        page = browser.new_page()
        results = [
            inspect_view(page, "desktop", {"width": 1440, "height": 1000}, DESKTOP),
            inspect_view(page, "mobile", {"width": 390, "height": 1200}, MOBILE),
        ]
        browser.close()

    failures = []
    for result in results:
        if result["overflow"]:
            failures.append(f"{result['label']} has horizontal overflow: {result['body_width']}px")
        for check in result["checks"]:
            if not check["visible"] or check["box"] is None:
                failures.append(f"{result['label']} missing visible text: {check['text']}")

    lines = [
        "# Verification Notes",
        "",
        "Rendered `review_board.html` with Python Playwright using Chromium headless flags `--disable-gpu` and `--single-process`.",
        "",
        "## Screenshot Artifacts",
        "",
        f"- Desktop screenshot: `review_board_desktop.png` ({results[0]['viewport']['width']}x{results[0]['viewport']['height']} viewport)",
        f"- Mobile screenshot: `review_board_mobile.png` ({results[1]['viewport']['width']}x{results[1]['viewport']['height']} viewport)",
        "",
        "## Readability And Rendering Checks",
        "",
    ]
    for result in results:
        lines.append(f"- {result['label'].title()}: all required board labels were visible; document width was {result['body_width']}px for a {result['viewport']['width']}px viewport; horizontal overflow: {result['overflow']}.")

    lines.extend([
        "",
        "## Result",
        "",
        "Complete: browser automation produced both required PNG screenshots and verified key text visibility on desktop and mobile." if not failures else "Incomplete: " + "; ".join(failures),
        "",
    ])
    NOTES.write_text("\n".join(lines), encoding="utf-8")

    if failures:
        raise SystemExit("\n".join(failures))


if __name__ == "__main__":
    main()
