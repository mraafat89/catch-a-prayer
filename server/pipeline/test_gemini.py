"""Quick test: does Gemini Vision extract prayer times from a screenshot?"""
import asyncio
import base64
import json
import os
import re
import httpx
from playwright.async_api import async_playwright

GEMINI_KEY = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY", "")
URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent"

PROMPT = (
    "Look at this mosque website screenshot. Extract ALL prayer time information.\n"
    "Return ONLY valid JSON (no markdown) with this structure:\n"
    '{"fajr_adhan":"HH:MM AM/PM","fajr_iqama":"HH:MM AM/PM",'
    '"dhuhr_adhan":"HH:MM AM/PM","dhuhr_iqama":"HH:MM AM/PM",'
    '"asr_adhan":"HH:MM AM/PM","asr_iqama":"HH:MM AM/PM",'
    '"maghrib_adhan":"HH:MM AM/PM","maghrib_iqama":"HH:MM AM/PM",'
    '"isha_adhan":"HH:MM AM/PM","isha_iqama":"HH:MM AM/PM",'
    '"jumuah_time":"HH:MM AM/PM","has_data":true}\n'
    "Use null for missing fields. Prayer names may appear as Zuhr, Magrib, Fajir etc."
)

TEST_URLS = [
    "https://icbmasjid.com/",           # Known: has prayer table
    "https://www.masjidmanhattan.com/",  # Known: bullet list format
    "https://www.iccmw.org/",           # Known: H1 format
]


async def main():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True, args=["--no-sandbox"])

        for test_url in TEST_URLS:
            print(f"\n=== {test_url} ===")
            try:
                page = await browser.new_page(viewport={"width": 1280, "height": 2000})
                await page.goto(test_url, wait_until="networkidle", timeout=20000)
                await page.wait_for_timeout(5000)
                ss = await page.screenshot(full_page=True)
                await page.close()
                print(f"  Screenshot: {len(ss)} bytes")

                b64 = base64.b64encode(ss).decode("utf-8")
                async with httpx.AsyncClient(timeout=60) as c:
                    r = await c.post(
                        f"{URL}?key={GEMINI_KEY}",
                        json={
                            "contents": [{"parts": [
                                {"text": PROMPT},
                                {"inline_data": {"mime_type": "image/png", "data": b64}}
                            ]}],
                            "generationConfig": {"temperature": 0.1, "maxOutputTokens": 500}
                        }
                    )
                    result = r.json()
                    text = result.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "")
                    print(f"  Gemini: {text[:400]}")

                    # Try to parse JSON
                    json_match = re.search(r'\{[^{}]+\}', text, re.DOTALL)
                    if json_match:
                        data = json.loads(json_match.group())
                        adhan = sum(1 for k in ["fajr_adhan", "dhuhr_adhan", "asr_adhan", "maghrib_adhan", "isha_adhan"]
                                    if data.get(k) and data[k] != "null" and data[k] is not None)
                        iqama = sum(1 for k in ["fajr_iqama", "dhuhr_iqama", "asr_iqama", "maghrib_iqama", "isha_iqama"]
                                    if data.get(k) and data[k] != "null" and data[k] is not None)
                        print(f"  Parsed: {adhan} adhan, {iqama} iqama, has_data={data.get('has_data')}")

            except Exception as e:
                print(f"  Error: {e}")

            await asyncio.sleep(5)

        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
