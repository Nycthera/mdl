"""WeebCentral scraper using Playwright for browser automation."""

import asyncio
import re
from typing import List, Tuple
from urllib.parse import urljoin

from playwright.async_api import async_playwright
from playwright_stealth import Stealth
from rich.console import Console
from rich.panel import Panel
from rich.align import Align
from rich.table import Table

console = Console()

# Title pattern from image URLs
TITLE_PATTERN = re.compile(r"/manga/([^/]+)/", re.IGNORECASE)

# Global configuration
CLEAN_OUTPUT = False


def set_clean_output(value: bool) -> None:
    """Set the clean output mode globally."""
    global CLEAN_OUTPUT
    CLEAN_OUTPUT = value


def extract_title_from_image_urls(img_urls: List[str]) -> str:
    """Extract manga title from image URLs."""
    for url in img_urls:
        match = TITLE_PATTERN.search(url)
        if match:
            return match.group(1)
    return "Unknown_Title"


async def fetch_weebcentral_images(url: str) -> Tuple[List[str], str]:
    """Fetch images from WeebCentral using Playwright."""
    if not CLEAN_OUTPUT:
        console.print(
            Panel.fit(
                f"[bold magenta]WeebCentral ✨[/bold magenta]\n[yellow]{url}[/]",
                title="[white on magenta] Weeb Mode [/]",
                border_style="magenta",
            )
        )

    async with Stealth().use_async(async_playwright()) as p:
        browser = None
        browser_name = None

        launch_order = [
            ("webkit", p.webkit),
            ("firefox", p.firefox),
            ("chromium", p.chromium),
        ]

        for name, engine in launch_order:
            try:
                if not CLEAN_OUTPUT:
                    console.print(f"[cyan]Trying {name} browser...[/]")

                browser = await engine.launch(headless=True, args=[])
                browser_name = name
                break
            except Exception as e:
                if not CLEAN_OUTPUT:
                    console.print(f"[yellow]{name} failed: {e}[/]")

        if not browser:
            raise RuntimeError("Failed to launch any Playwright browser")

        if not CLEAN_OUTPUT:
            console.print(f"[green]Using {browser_name} browser[/]")

        page = await browser.new_page()

        if not CLEAN_OUTPUT:
            console.print("[cyan] Loading page... please wait...[/]")
        try:
            response = await page.goto(url, wait_until="load", timeout=45000)
            if not response or response.status != 200:
                if not CLEAN_OUTPUT:
                    console.print(
                        f"[red] Failed to load page (status {response.status if response else 0})[/]"
                    )
                return [], "Unknown_Title"
        except Exception as e:
            if not CLEAN_OUTPUT:
                console.print(f"[red] Page load warning: {e}[/]")
            return [], "Unknown_Title"

        if not CLEAN_OUTPUT:
            console.print("[yellow] Scrolling for lazy-loaded images...[/]")
        for _ in range(20):
            await page.mouse.wheel(0, 1200)
            await asyncio.sleep(0.7)

        await asyncio.sleep(4)

        img_elements = await page.query_selector_all("img")
        img_urls = []
        for img in img_elements:
            src = await img.get_attribute("src")
            if src and "/manga/" in src and src.endswith(".png"):
                img_urls.append(urljoin(url, src))

        title = extract_title_from_image_urls(img_urls)

        await browser.close()

        if not CLEAN_OUTPUT:
            # --- Fancy summary table ---
            table = Table(
                title="[bold magenta]WeebCentral Extraction Summary[/bold magenta]"
            )
            table.add_column("Field", style="cyan", no_wrap=True)
            table.add_column("Value", style="white")

            table.add_row("Title", f"[bold white]{title}[/]")
            table.add_row("Images Found", f"[green]{len(img_urls)}[/]")
            table.add_row(
                "Status",
                (
                    "[bold green]Success[/]"
                    if img_urls
                    else "[bold red]No images found[/]"
                ),
            )

            console.print()
            console.print(
                Panel(
                    Align.center(table),
                    border_style="magenta",
                    title="✨ Scan Complete ✨",
                )
            )

        return img_urls, title
