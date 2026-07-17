from pathlib import Path
from playwright.sync_api import sync_playwright

ARTIFACT_DIR = Path(__file__).resolve().parent
HTML = ARTIFACT_DIR / "index.html"
DESKTOP = ARTIFACT_DIR / "desktop.png"
MOBILE = ARTIFACT_DIR / "mobile.png"
NOTES = ARTIFACT_DIR / "verification_notes.md"


def check_page(page, viewport_name):
    title = page.locator("h1").inner_text()
    cards = page.locator(".metric-card").count()
    recommendation = page.locator(".recommendation").inner_text()
    return {
        "viewport": viewport_name,
        "title": title,
        "metric_cards": cards,
        "has_recommendation": "Continue" in title and "reviewer checklist" in recommendation,
    }


with sync_playwright() as p:
    browser = p.chromium.launch(
        headless=True,
        args=["--disable-gpu", "--single-process"],
    )
    page = browser.new_page(viewport={"width": 1440, "height": 1100}, device_scale_factor=1)
    page.goto(HTML.as_uri())
    page.wait_for_load_state("networkidle")
    desktop_result = check_page(page, "desktop 1440x1100")
    page.screenshot(path=str(DESKTOP), full_page=True)

    page.set_viewport_size({"width": 390, "height": 1200})
    page.goto(HTML.as_uri())
    page.wait_for_load_state("networkidle")
    mobile_result = check_page(page, "mobile 390x1200")
    page.screenshot(path=str(MOBILE), full_page=True)
    browser.close()

expected = [
    desktop_result["metric_cards"] == 4,
    mobile_result["metric_cards"] == 4,
    desktop_result["has_recommendation"],
    mobile_result["has_recommendation"],
    DESKTOP.exists(),
    MOBILE.exists(),
]

status = "PASS" if all(expected) else "FAIL"
NOTES.write_text(
    "\n".join(
        [
            f"# Verification Notes",
            "",
            f"Status: {status}",
            "",
            f"- Desktop screenshot: `{DESKTOP.name}` captured at 1440x1100 and includes the executive recommendation plus {desktop_result['metric_cards']} metric cards.",
            f"- Mobile screenshot: `{MOBILE.name}` captured at 390x1200 and includes the executive recommendation plus {mobile_result['metric_cards']} metric cards.",
            "- Rendering check: Playwright loaded the static HTML via file URL, waited for network idle, and validated the primary headline/recommendation and metrics.",
            "- Browser launch flags: `--disable-gpu --single-process`.",
        ]
    )
    + "\n",
    encoding="utf-8",
)

if status != "PASS":
    raise SystemExit("verification failed")
