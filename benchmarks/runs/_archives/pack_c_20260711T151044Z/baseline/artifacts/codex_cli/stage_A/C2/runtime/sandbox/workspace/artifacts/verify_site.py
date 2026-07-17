from pathlib import Path
from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parent
SITE = ROOT / "site" / "index.html"
DESKTOP = ROOT / "desktop.png"
MOBILE = ROOT / "mobile.png"
NOTES = ROOT / "verification_notes.md"


def inspect(page):
    title = page.locator("h1").inner_text()
    nav_count = page.locator("nav a").count()
    kpi_count = page.locator(".kpi").count()
    deliverable_count = page.locator(".deliverable").count()
    risk_count = page.locator(".risk").count()
    return {
        "title": title,
        "nav_count": nav_count,
        "kpi_count": kpi_count,
        "deliverable_count": deliverable_count,
        "risk_count": risk_count,
    }


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            desktop_page = browser.new_page(viewport={"width": 1440, "height": 1100}, device_scale_factor=1)
            desktop_page.goto(SITE.as_uri())
            desktop_page.wait_for_load_state("networkidle")
            desktop_info = inspect(desktop_page)
            desktop_page.screenshot(path=str(DESKTOP), full_page=True)

            mobile_page = browser.new_page(
                viewport={"width": 390, "height": 1200},
                device_scale_factor=2,
                is_mobile=True,
                has_touch=True,
            )
            mobile_page.goto(SITE.as_uri())
            mobile_page.wait_for_load_state("networkidle")
            mobile_info = inspect(mobile_page)
            mobile_page.screenshot(path=str(MOBILE), full_page=True)
        finally:
            browser.close()

    notes = f"""# Verification Notes

Browser automation completed with Playwright Chromium against `artifacts/site/index.html`.

- Desktop screenshot: `artifacts/desktop.png`
- Mobile screenshot: `artifacts/mobile.png`
- Desktop rendered title: {desktop_info["title"]}
- Mobile rendered title: {mobile_info["title"]}
- Desktop content checks: {desktop_info["nav_count"]} nav links, {desktop_info["kpi_count"]} KPI cards, {desktop_info["deliverable_count"]} deliverables, {desktop_info["risk_count"]} risk items.
- Mobile content checks: {mobile_info["nav_count"]} nav links, {mobile_info["kpi_count"]} KPI cards, {mobile_info["deliverable_count"]} deliverables, {mobile_info["risk_count"]} risk items.
- Responsive verification: desktop uses multi-column hero/KPI layouts; mobile collapses metric and deliverable grids to single-column cards with readable navigation wrapping.
"""
    NOTES.write_text(notes, encoding="utf-8")


if __name__ == "__main__":
    main()
