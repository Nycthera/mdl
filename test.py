from playwright.sync_api import sync_playwright
import time
import re

url = "https://weebcentral.com/chapters/01K74ZFJDKWWAV1S2RFE9PM9QK"
pattern = re.compile(r"\d{3,4}-\d{3,4}\.png$", re.IGNORECASE)
title_pattern = re.compile(r"/manga/([^/]+)/")  # extract title part

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False, slow_mo=50)
    page = browser.new_page()

    print("🌐 Loading page...")

    try:
        page.goto(url, wait_until="load", timeout=45000)
    except Exception as e:
        print(f"⚠️ Page load warning: {e}")

    time.sleep(5)

    print("🖱 Scrolling slowly to trigger lazy loading...")
    for _ in range(20):
        page.mouse.wheel(0, 1200)
        time.sleep(0.7)

    print("⏳ Waiting for images to finish loading...")
    time.sleep(5)

    img_elements = page.query_selector_all("img")
    img_urls = [img.get_attribute("src") for img in img_elements if img.get_attribute("src")]

    # ✅ Filter only manga page images
    matched_urls = [url for url in img_urls if pattern.search(url)]

    print(f"\n🖼 Found {len(matched_urls)} matching images\n")

    for i, u in enumerate(matched_urls, 1):
        print(f"{i:03d}: {u}")

        # Extract the manga title
        title_match = title_pattern.search(u)
        if title_match:
            title = title_match.group(1)
        else:
            print("⚠️ No title found in this URL")

        print(title)
    browser.close()
