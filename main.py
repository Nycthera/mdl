#!/usr/bin/env python3

import os
import sys
import json
import shutil
import zipfile
import signal
import time
from urllib.parse import urlparse
from concurrent.futures import ThreadPoolExecutor
import requests
from requests.exceptions import ChunkedEncodingError, ConnectionError
from rich.console import Console
from rich.progress import Progress, BarColumn, TextColumn

# ------------------ CONFIG PATH ------------------
def get_config_path():
    config_dir = os.path.join(os.path.expanduser("~"), ".config", "manga_downloader")
    os.makedirs(config_dir, exist_ok=True)
    return os.path.join(config_dir, "config.json")

CONFIG_FILE = get_config_path()
stop_signal = False
console = Console()

# ------------------ SIGNAL HANDLER ------------------
def signal_handler(sig, frame):
    global stop_signal
    stop_signal = True
    console.print("\n[red]Received interrupt. Stopping gracefully...[/]")

signal.signal(signal.SIGINT, signal_handler)

# ------------------ COLORS (legacy) ------------------
class Colors:
    RESET = "\033[0m"
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    CYAN = "\033[36m"
    MAGENTA = "\033[35m"
    BOLD = "\033[1m"

def cprint(msg, color=Colors.RESET):
    print(color + msg + Colors.RESET)

# ------------------ BASE URLS ------------------
BASE_URLS = [
    "https://scans.lastation.us/manga/",
    "https://official.lowee.us/manga/",
    "https://hot.planeptune.us/manga/"
]

session = requests.Session()
session.headers.update({"User-Agent": "Mozilla/5.0"})

# ------------------ CONFIG ------------------
def create_default_config():
    default_config = {
        "manga_name": "",
        "start_chapter": 1,
        "start_page": 1,
        "max_pages": 50,
        "workers": 10,
        "cbz": True
    }
    with open(CONFIG_FILE, "w") as f:
        json.dump(default_config, f, indent=4)
    cprint(f"Default config created: {CONFIG_FILE}", Colors.GREEN)

def load_config():
    if not os.path.exists(CONFIG_FILE):
        create_default_config()
    with open(CONFIG_FILE, "r") as f:
        return json.load(f)

# ------------------ HELPERS ------------------
def validate_manga_input(manga_name):
    if not manga_name:
        cprint("Error: No manga name or URL specified. Use -M/--manga or set a default in config.", Colors.RED)
        sys.exit(1)

def extract_manga_name(manga_input):
    if manga_input.startswith("http"):
        path = urlparse(manga_input).path
        parts = [p for p in path.split("/") if p]
        if len(parts) >= 2:
            return parts[1]
        else:
            return parts[-1]
    return manga_input

def url_exists(url):
    try:
        r = session.head(url, allow_redirects=True, timeout=5)
        return r.status_code == 200
    except:
        return False

# ------------------ DOWNLOAD ------------------
def download_image(url, folder, max_retries=5, backoff_factor=1.0):
    if stop_signal:
        return f"{Colors.RED}Download interrupted{Colors.RESET}"
    os.makedirs(folder, exist_ok=True)
    filename = os.path.basename(url)
    filepath = os.path.join(folder, filename)
    if os.path.exists(filepath):
        return f"{Colors.YELLOW}Already downloaded: {filename}{Colors.RESET}"

    for attempt in range(1, max_retries + 1):
        try:
            r = session.get(url, timeout=15)
            r.raise_for_status()
            with open(filepath, "wb") as f:
                f.write(r.content)
            return f"{Colors.GREEN}Saved as {filepath}{Colors.RESET}"
        except (ChunkedEncodingError, ConnectionError) as e:
            if attempt == max_retries:
                return f"{Colors.RED}Failed to download {filename} after {max_retries} attempts: {e}{Colors.RESET}"
            time.sleep(backoff_factor * attempt)
        except requests.HTTPError as e:
            return f"{Colors.RED}HTTP error for {filename}: {e}{Colors.RESET}"
        except Exception as e:
            return f"{Colors.RED}Unexpected error for {filename}: {e}{Colors.RESET}"

# ------------------ CBZ ------------------
def create_cbz_for_all(manga_name):
    manga_folder_name = manga_name.replace("-", " ").replace("_", " ")
    os.makedirs(manga_folder_name, exist_ok=True)
    cbz_path = os.path.join(manga_folder_name, f"{manga_folder_name}.cbz")
    console.print(f"[magenta]Creating CBZ archive: {cbz_path}[/]")
    with zipfile.ZipFile(cbz_path, 'w') as cbz:
        for root, _, files in os.walk(manga_folder_name):
            files = sorted(files)
            for file in files:
                file_path = os.path.join(root, file)
                if file_path == cbz_path:
                    continue
                arcname = os.path.relpath(file_path, manga_folder_name)
                cbz.write(file_path, arcname=arcname)
    console.print(f"[magenta]Created {cbz_path}[/]")

    for root, dirs, _ in os.walk(manga_folder_name):
        for d in dirs:
            shutil.rmtree(os.path.join(root, d))
    console.print(f"[green]Cleaned chapter folders in {manga_folder_name}[/]")

# ------------------ URL GATHERING WITH PROGRESS ------------------
def gather_all_urls(manga_name, start_chapter=1, start_page=1, max_pages=50, max_decimals=5, workers=10):
    urls_to_download = []
    folder_base = manga_name.replace("-", " ").replace("_", " ")
    console.print(f"[yellow]Gathering pages for {manga_name}...[/]")

    chapter = start_chapter
    while True:
        if stop_signal:
            break
        chapter_str = f"{chapter:04d}"
        found_any = any(url_exists(f"{base}{manga_name}/{chapter_str}-001.png") for base in BASE_URLS)

        if found_any:
            chapter_folder = os.path.join(folder_base, f"chapter_{chapter_str}")
            os.makedirs(chapter_folder, exist_ok=True)
            urls = [f"{base}{manga_name}/{chapter_str}-{page:03d}.png" for base in BASE_URLS for page in range(1, max_pages + 1)]
            pages_found = 0

            with Progress(
                TextColumn(f"[bold yellow]Checking Chapter {chapter_str}[/]"),
                BarColumn(),
                "[progress.percentage]{task.percentage:>3.1f}%",
                console=console
            ) as progress:
                task = progress.add_task("Checking", total=len(urls))
                with ThreadPoolExecutor(max_workers=workers) as executor:
                    results = list(executor.map(url_exists, urls))
                for url, exists in zip(urls, results):
                    progress.update(task, advance=1)
                    if exists:
                        urls_to_download.append((url, chapter_folder))
                        pages_found += 1
            console.print(f"[green]Chapter {chapter_str}: {pages_found} pages found[/]")

        else:
            decimal_found_any = False
            for dec in range(1, max_decimals + 1):
                chapter_decimal_str = f"{chapter_str}.{dec}"
                first_page_url = f"{BASE_URLS[0]}{manga_name}/{chapter_decimal_str}-001.png"
                if url_exists(first_page_url):
                    decimal_found_any = True
                    chapter_folder = os.path.join(folder_base, f"chapter_{chapter_decimal_str}")
                    os.makedirs(chapter_folder, exist_ok=True)
                    urls = [f"{base}{manga_name}/{chapter_decimal_str}-{page:03d}.png" for base in BASE_URLS for page in range(1, max_pages + 1)]
                    pages_found = 0

                    with Progress(
                        TextColumn(f"[bold yellow]Checking Chapter {chapter_decimal_str}[/]"),
                        BarColumn(),
                        "[progress.percentage]{task.percentage:>3.1f}%",
                        console=console
                    ) as progress:
                        task = progress.add_task("Checking", total=len(urls))
                        with ThreadPoolExecutor(max_workers=workers) as executor:
                            results = list(executor.map(url_exists, urls))
                        for url, exists in zip(urls, results):
                            progress.update(task, advance=1)
                            if exists:
                                urls_to_download.append((url, chapter_folder))
                                pages_found += 1
                    console.print(f"[green]Chapter {chapter_decimal_str}: {pages_found} pages found[/]")

            if not decimal_found_any:
                console.print(f"[red]Chapter {chapter_str} not found. Stopping.[/]")
                break

        chapter += 1

    return urls_to_download

# ------------------ DOWNLOAD WITH PAGES/SEC ------------------
def download_all_pages(urls_to_download, max_workers=10, manga_name="manga"):
    manga_folder_name = manga_name.replace("-", " ").replace("_", " ")
    total_pages = len(urls_to_download)
    if total_pages == 0:
        return

    start_time = time.time()

    # Pre-create all folders
    for _, folder in urls_to_download:
        os.makedirs(folder, exist_ok=True)

    with Progress(
        TextColumn("[bold green]Downloading[/]"),
        BarColumn(),
        "[progress.percentage]{task.percentage:>3.1f}%",
        "•",
        TextColumn("{task.fields[pages_per_sec]} pages/sec"),
        console=console
    ) as progress:
        task = progress.add_task("Downloading", total=total_pages, pages_per_sec="0.0")

        def download_worker(args):
            url, folder = args
            return download_image(url, folder)

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            for idx, result in enumerate(executor.map(download_worker, urls_to_download), 1):
                if stop_signal:
                    break
                elapsed = max(time.time() - start_time, 0.001)
                pps = idx / elapsed
                progress.update(task, advance=1, pages_per_sec=f"{pps:.2f}")
                # Print only errors to avoid slowing terminal
                if "Failed" in result or "HTTP" in result:
                    console.print(result)

# ------------------ CLI ------------------
def parse_args():
    import argparse
    parser = argparse.ArgumentParser(description="Manga Downloader CLI")
    parser.add_argument("-M", "--manga", help="Manga name or direct URL")
    parser.add_argument("--start-chapter", type=int, help="Starting chapter")
    parser.add_argument("--start-page", type=int, help="Starting page")
    parser.add_argument("--max-pages", type=int, help="Maximum pages per chapter")
    parser.add_argument("--workers", type=int, help="Number of concurrent downloads")
    parser.add_argument("--cbz", action="store_true", help="Create CBZ archive after download")
    return parser.parse_args()

# ------------------ MAIN ------------------
def main():
    config = load_config()
    args = parse_args()

    manga_name = args.manga or config.get("manga_name")
    start_chapter = args.start_chapter or config.get("start_chapter", 1)
    start_page = args.start_page or config.get("start_page", 1)
    max_pages = args.max_pages or config.get("max_pages", 50)
    workers = args.workers or config.get("workers", 10)
    cbz_flag = args.cbz or config.get("cbz", True)

    validate_manga_input(manga_name)
    manga_name = extract_manga_name(manga_name)

    console.print(f"[magenta]Starting download for manga: {manga_name} from chapter {start_chapter} page {start_page}[/]")

    urls_to_download = gather_all_urls(
        manga_name,
        start_chapter=start_chapter,
        start_page=start_page,
        max_pages=max_pages,
        max_decimals=50,
        workers=workers
    )

    console.print(f"[cyan]Total pages to download: {len(urls_to_download)}[/]")

    download_all_pages(urls_to_download, max_workers=workers, manga_name=manga_name)

    if cbz_flag and not stop_signal:
        create_cbz_for_all(manga_name)
    else:
        console.print("[cyan]Skipping CBZ archive creation.[/]")

if __name__ == "__main__":
    main()
