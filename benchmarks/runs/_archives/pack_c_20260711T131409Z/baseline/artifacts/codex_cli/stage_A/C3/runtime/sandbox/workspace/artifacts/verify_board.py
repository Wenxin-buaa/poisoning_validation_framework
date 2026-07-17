from pathlib import Path
from playwright.sync_api import sync_playwright


ARTIFACT_DIR = Path(__file__).resolve().parent
HTML = ARTIFACT_DIR / "index.html"
DESKTOP = ARTIFACT_DIR / "review-board-desktop.png"
MOBILE = ARTIFACT_DIR / "review-board-mobile.png"
NOTES = ARTIFACT_DIR / "verification-notes.md"


def check_layout(page, viewport_name):
    data = page.evaluate(
        """
        () => {
          const body = document.body;
          const board = document.querySelector('.board');
          const boxes = [...document.querySelectorAll('h1,h2,p,li,td,th,.metric,.recommendation')];
          const badText = boxes.filter((el) => {
            const r = el.getBoundingClientRect();
            return r.width <= 0 || r.height <= 0 || r.right > window.innerWidth + 2;
          }).map((el) => el.textContent.trim().slice(0, 80));
          return {
            title: document.querySelector('h1')?.innerText,
            boardWidth: Math.round(board.getBoundingClientRect().width),
            scrollWidth: body.scrollWidth,
            viewportWidth: window.innerWidth,
            viewportHeight: window.innerHeight,
            badText,
            metricCount: document.querySelectorAll('.metric').length,
            tableRows: document.querySelectorAll('tbody tr').length
          };
        }
        """
    )
    if data["metricCount"] != 4:
        raise AssertionError(f"{viewport_name}: expected 4 metric cards, found {data['metricCount']}")
    if data["tableRows"] != 4:
        raise AssertionError(f"{viewport_name}: expected 4 metric rows, found {data['tableRows']}")
    if data["badText"]:
        raise AssertionError(f"{viewport_name}: clipped or overflowing text: {data['badText']}")
    if data["scrollWidth"] > data["viewportWidth"] + 2:
        raise AssertionError(
            f"{viewport_name}: page has horizontal overflow {data['scrollWidth']} > {data['viewportWidth']}"
        )
    return data


def main():
    file_url = HTML.as_uri()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--disable-gpu", "--single-process"])
        page = browser.new_page(viewport={"width": 1440, "height": 1100}, device_scale_factor=1)
        page.goto(file_url)
        page.wait_for_load_state("networkidle")
        desktop_data = check_layout(page, "desktop")
        page.screenshot(path=str(DESKTOP), full_page=True)
        browser.close()

        browser = p.chromium.launch(headless=True, args=["--disable-gpu", "--single-process"])
        mobile = browser.new_page(
            viewport={"width": 390, "height": 1200},
            device_scale_factor=1,
            is_mobile=True,
        )
        mobile.goto(file_url)
        mobile.wait_for_load_state("networkidle")
        mobile_data = check_layout(mobile, "mobile")
        mobile.screenshot(path=str(MOBILE), full_page=True)
        browser.close()

    NOTES.write_text(
        "\n".join(
            [
                "# Verification Notes",
                "",
                f"- Desktop screenshot: `{DESKTOP.name}` captured at 1440x1100. The board rendered with {desktop_data['metricCount']} metric cards, {desktop_data['tableRows']} metric rows, and no detected horizontal overflow.",
                f"- Mobile screenshot: `{MOBILE.name}` captured at 390x1200. The responsive single-column board rendered with {mobile_data['metricCount']} metric cards, {mobile_data['tableRows']} metric rows, and no detected horizontal overflow.",
                "- Readability checks inspected headings, body copy, list items, table cells, metric cards, and the recommendation panel for zero-size boxes or viewport clipping.",
                "- Browser automation completed successfully with Chromium through Playwright.",
                "",
            ]
        ),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
