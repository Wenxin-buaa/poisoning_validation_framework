from pathlib import Path
from playwright.sync_api import Error, sync_playwright

ROOT = Path(__file__).resolve().parent
URL = (ROOT / "index.html").resolve().as_uri()

viewports = [
    ("desktop", 1440, 1100),
    ("mobile", 390, 1200),
]

notes = [
    "# Verification Notes",
    "",
    f"Rendered static microsite from `{URL}`.",
]

with sync_playwright() as p:
    browser = None
    failures = []
    for browser_name in ("chromium", "webkit", "firefox"):
        try:
            browser = getattr(p, browser_name).launch(headless=True)
            notes.append(f"Browser automation engine: `{browser_name}`.")
            break
        except Error as exc:
            failures.append(f"{browser_name}: {exc.__class__.__name__}: {str(exc).splitlines()[0]}")
    if browser is None:
        notes.append("")
        notes.append("Browser automation failed before screenshots could be captured.")
        notes.extend(f"- {failure}" for failure in failures)
        (ROOT / "verification_notes.md").write_text("\n".join(notes) + "\n", encoding="utf-8")
        raise SystemExit(1)
    for label, width, height in viewports:
        page = browser.new_page(viewport={"width": width, "height": height}, device_scale_factor=1)
        page.goto(URL)
        page.wait_for_load_state("networkidle")
        title = page.locator("h1").inner_text()
        metric_cards = page.locator(".metric-card").count()
        screenshot = ROOT / f"{label}.png"
        page.screenshot(path=str(screenshot), full_page=True)
        notes.append("")
        notes.append(f"- `{screenshot.name}`: {width}x{height} viewport captured; h1 `{title}` visible; {metric_cards} metric cards rendered.")
        page.close()
    browser.close()

(ROOT / "verification_notes.md").write_text("\n".join(notes) + "\n", encoding="utf-8")
