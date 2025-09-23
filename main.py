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
import threading
import re



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
    "https://hot.planeptune.us/manga/",
    "https://scans-hot.planeptune.us/manga"
]

API_ENDPOINT = "https://api.mangadex.org"
md_output_folder = ""
md_manga_name = ""
md_manga_uuid = ""

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
        "cbz": True,
        "md_language": "en"
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

def extract_manga_name_from_url(manga_input):
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
                if "Failed" in result or "HTTP" in result:
                    console.print(result)
                    
# ----------- sanitize manga name -----------
def sanitize_folder_name(name: str) -> str:
    """Remove illegal characters from folder/file names."""
    return re.sub(r'[<>:"/\\|?*]', "_", name)



# ------------------ MANGADEX FUNCTIONS ------------------
def extract_manga_uuid(url: str) -> str:
    try:
        path = urlparse(url).path.strip("/")
        parts = path.split("/")
        if len(parts) >= 2 and parts[0] == "title":
            return parts[1]
    except Exception:
        pass
    return None

def fetch_all_chapters_md(manga_uuid: str, lang="en"):
    chapters = []
    limit = 100
    offset = 0

    while True:
        params = {
            "manga": manga_uuid,
            "translatedLanguage[]": lang,
            "limit": limit,
            "offset": offset,
            "order[chapter]": "asc"
        }
        resp = requests.get(f"{API_ENDPOINT}/chapter", params=params)
        if resp.status_code != 200:
            print(f"Error fetching chapters: {resp.status_code}")
            break
        data = resp.json()
        batch = data.get("data", [])
        chapters.extend(batch)
        total = data.get("total", 0)
        if offset + limit >= total:
            break
        offset += limit
    return chapters

def get_images_md(chapter_id: str, use_saver=False):
    resp = requests.get(f"https://api.mangadex.org/at-home/server/{chapter_id}")
    if resp.status_code != 200:
        print(f"Error fetching chapter {chapter_id}: {resp.status_code}")
        return []

    chapter_data = resp.json().get("chapter", {})
    base_url = resp.json().get("baseUrl")
    hash_code = chapter_data.get("hash")
    pages = chapter_data.get("dataSaver" if use_saver else "data", [])

    if not base_url or not hash_code or not pages:
        print(f"No pages found for chapter {chapter_id}")
        return []

    urls = [f"{base_url}/data/{hash_code}/{page}" for page in pages]
    return urls
def download_md_chapters(manga_url, lang="en"):
    manga_uuid = extract_manga_uuid(manga_url)
    manga_name = extract_manga_name_from_url(manga_url)
    if not manga_uuid:
        console.print(f"[red]Could not extract manga UUID from URL[/]")
        return

    # Root folder
    manga_root_folder = sanitize_folder_name(manga_name)
    os.makedirs(manga_root_folder, exist_ok=True)

    console.print(f"[cyan]Downloading '{manga_name}' in language '{lang}'[/]")
    chapters = fetch_all_chapters_md(manga_uuid, lang)
    console.print(f"[green]Found {len(chapters)} chapters[/]")

    for chapter in chapters:
        attr = chapter.get("attributes", {})
        chapter_num = attr.get("chapter", "Unknown")
        chapter_title = attr.get("title", "")
        chap_id = chapter.get("id")

        chapter_folder_name = f"Chapter_{chapter_num}_{chapter_title}".strip("_")
        chapter_folder_name = sanitize_folder_name(chapter_folder_name)
        chapter_folder = os.path.join(manga_root_folder, chapter_folder_name)
        os.makedirs(chapter_folder, exist_ok=True)

        console.print(f"[yellow]Downloading Chapter {chapter_num}: {chapter_title}[/]")
        images = get_images_md(chap_id)
        urls_to_download = [(url, chapter_folder) for url in images]
        download_all_pages(urls_to_download, max_workers=10, manga_name=manga_name)


# ------------------ CLI ------------------
def parse_args():
    import argparse
    parser = argparse.ArgumentParser(description="Manga Downloader CLI")
    parser.add_argument("-M", "--manga", help="Manga name or MangaDex URL")
    parser.add_argument("--start-chapter", type=int)
    parser.add_argument("--start-page", type=int)
    parser.add_argument("--max-pages", type=int)
    parser.add_argument("--workers", type=int)
    parser.add_argument("--cbz", action="store_true")
    parser.add_argument("--md-lang", default=None, help="Language code for MangaDex download")
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
    md_lang = args.md_lang or config.get("md_language", "en")

    validate_manga_input(manga_name)
    manga_name_clean = extract_manga_name_from_url(manga_name)

    console.print(f"[magenta]Starting download for: {manga_name_clean}[/]")

    # If MangaDex URL, use MD downloader
    if manga_name.startswith("http") and "mangadex" in manga_name.lower():
        download_md_chapters(manga_name, lang=md_lang)
    else:
        urls_to_download = gather_all_urls(
            manga_name_clean,
            start_chapter=start_chapter,
            start_page=start_page,
            max_pages=max_pages,
            max_decimals=50,
            workers=workers
        )
        console.print(f"[cyan]Total pages to download: {len(urls_to_download)}[/]")
        download_all_pages(urls_to_download, max_workers=workers, manga_name=manga_name_clean)

    if cbz_flag and not stop_signal:
        create_cbz_for_all(manga_name_clean)
    else:
        console.print("[cyan]Skipping CBZ archive creation.[/]")

if __name__ == "__main__":
    main()
