# Verification Notes

- Loaded static dashboard from `dashboard.html` using Python Playwright Chromium.
- Captured desktop screenshot: `dashboard_desktop.png` at 1440px viewport width.
- Captured mobile screenshot: `dashboard_mobile.png` at 390px viewport width.
- Verified expected dashboard text for recommendation, metric deltas, and risk labels before screenshot capture.
- Browser automation completed with Chromium launched using `--disable-gpu` and `--single-process`.
