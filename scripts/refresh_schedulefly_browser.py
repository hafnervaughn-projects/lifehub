from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lifehub.schedulefly_page import parse_personal_schedulefly_rows, parse_personal_schedulefly_text

HOME_URL = "https://app.schedulefly.com/welcome.aspx"
SCHEDULE_URL = "https://app.schedulefly.com/schedule.aspx?view=0"
LOGIN_URL = "https://app.schedulefly.com/login.aspx"


async def main() -> int:
    parser = argparse.ArgumentParser(description="Refresh LifeHub work schedule from a saved Schedulefly browser session.")
    parser.add_argument("--headed", action="store_true", help="Show the browser. Use this the first time to log in.")
    parser.add_argument("--employee", default="Vaughn")
    parser.add_argument("--profile-dir", default=str(ROOT / ".schedulefly-browser-profile"))
    args = parser.parse_args()

    try:
        from playwright.async_api import async_playwright
    except ImportError:
        print("Playwright is not installed. Run: python3 -m pip install playwright && python3 -m playwright install chromium")
        return 2

    async with async_playwright() as playwright:
        context = await playwright.chromium.launch_persistent_context(
            args.profile_dir,
            headless=not args.headed,
            viewport={"width": 1280, "height": 900},
        )
        page = context.pages[0] if context.pages else await context.new_page()
        await page.goto(HOME_URL, wait_until="domcontentloaded")
        if "login.aspx" in page.url.lower():
            if not args.headed:
                await context.close()
                print("Schedulefly session expired. Run this once on the Pi with --headed and log in manually.")
                return 3
            print("Log into Schedulefly in the browser window. Waiting for the home page...")
            await page.wait_for_url(lambda url: "welcome.aspx" in url or "schedule.aspx" in url, timeout=180_000)
        await page.goto(HOME_URL, wait_until="domcontentloaded")
        await page.wait_for_load_state("domcontentloaded")
        text = await page.evaluate("() => document.body.innerText")
        rows = await page.evaluate(
            """() => Array.from(document.querySelectorAll('tr'))
              .map(tr => Array.from(tr.children).map(td => td.innerText.trim()))
              .filter(row => row.length)"""
        )
        shifts = parse_personal_schedulefly_rows(rows, datetime.now().date()) or parse_personal_schedulefly_text(text, datetime.now().date())
        if shifts:
            print(f"Found shifts from home page: {page.url}")
        if not shifts:
            debug_path = ROOT / "mock_data" / "schedulefly_debug.txt"
            debug_html_path = ROOT / "mock_data" / "schedulefly_debug.html"
            debug_rows_path = ROOT / "mock_data" / "schedulefly_debug_rows.json"
            debug_summary_path = ROOT / "mock_data" / "schedulefly_debug_summary.txt"
            debug_text = text
            debug_html = await page.evaluate("() => document.documentElement.outerHTML")
            current_url = page.url
            debug_path.write_text(debug_text, encoding="utf-8")
            debug_html_path.write_text(debug_html, encoding="utf-8")
            debug_rows_path.write_text(json.dumps(rows, indent=2), encoding="utf-8")
            lowered_lines = [line for line in debug_text.splitlines() if "vaughn" in line.lower()]
            time_lines = [line for line in debug_text.splitlines() if "AM" in line or "PM" in line][:20]
            debug_summary_path.write_text(
                "\n".join(
                    [
                        f"Home URL: {current_url}",
                        f"Rows found: {len(rows)}",
                        "",
                        "Lines containing Vaughn:",
                        *[line.strip() for line in lowered_lines[:12]],
                        "",
                        "First AM/PM lines:",
                        *[line.strip() for line in time_lines],
                    ]
                ),
                encoding="utf-8",
            )
            await context.close()
            print(f"No shifts found for {args.employee}.")
            print(f"Current Schedulefly URL: {current_url}")
            print(f"Saved page text to {debug_path}. Check whether your name appears differently there.")
            print(f"Saved page HTML to {debug_html_path}.")
            print(f"Saved short summary to {debug_summary_path}.")
            if lowered_lines:
                print("Lines containing Vaughn:")
                for line in lowered_lines[:8]:
                    print(f"  {line.strip()}")
            else:
                print("The visible page text did not contain Vaughn.")
            return 4
        output = ROOT / "mock_data" / "work_schedule.json"
        output.write_text(json.dumps(shifts, indent=2), encoding="utf-8")
        await context.close()
        print(f"Updated {output} with {len(shifts)} Schedulefly shifts.")
        return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
