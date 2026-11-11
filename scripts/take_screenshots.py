"""Capture a PNG of every page of a RUNNING app for the README (run on your machine, with your real data).

    streamlit run app.py                         # in one terminal
    python -m scripts.take_screenshots           # in another;  needs:  pip install playwright && playwright install chromium

Images are written to docs/screenshots/. Screenshots of other data (e.g. test fixtures) must not be published as real results.
"""
from __future__ import annotations

import re
import sys

from config import settings

OUT = settings.PROJECT_ROOT / "docs" / "screenshots"


def page_titles() -> list[str]:
    src = (settings.PROJECT_ROOT / "app.py").read_text(encoding="utf-8")
    return re.findall(r'st\.Page\("pages/[a-z_]+\.py", title="([^"]+)"', src)


def main(url: str = "http://localhost:8501") -> None:
    from playwright.sync_api import sync_playwright

    OUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1500, "height": 1000}, device_scale_factor=2)
        page.goto(url)
        page.wait_for_selector("text=MarketPulse", timeout=60000)
        for title in page_titles():
            page.get_by_role("link", name=title).click()
            page.wait_for_timeout(4000)
            name = re.sub(r"[^a-z0-9]+", "_", title.lower()).strip("_")
            page.screenshot(path=str(OUT / f"{name}.png"), full_page=True)
            print("saved", name)
        browser.close()


if __name__ == "__main__":
    main(*sys.argv[1:2])
