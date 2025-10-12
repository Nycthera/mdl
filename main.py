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
from collections import defaultdict
import pathlib

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
            name = parts[1]
            # Replace hyphens commonly used in URLs with spaces for nicer folder names
            return name.replace("-", " ")
        else:
            name = parts[-1]
            return name.replace("-", " ")
    return manga_input


def url_exists(url):
    try:
        r = session.head(url, allow_redirects=True, timeout=5)
        return r.status_code == 200
    except:
        return False

# ------------------ RATE LIMITER ------------------
class RateLimiter:
    def __init__(self, max_calls=5, per_seconds=1):
        self.max_calls = max_calls
        self.per_seconds = per_seconds
        self.lock = threading.Lock()
        self.calls = defaultdict(list)

    def acquire(self, key="global"):
        with self.lock:
            now = time.time()
            calls = self.calls[key]
            while calls and calls[0] <= now - self.per_seconds:
                calls.pop(0)
            if len(calls) >= self.max_calls:
                sleep_for = self.per_seconds - (now - calls[0])
                time.sleep(max(sleep_for, 0))
            self.calls[key].append(time.time())

rate_limiter = RateLimiter(max_calls=5, per_seconds=1)
rate_limiter_athome = RateLimiter(max_calls=1, per_seconds=1.5)

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
def create_cbz_for_all(folder_path):
    # Use sanitized base name for the CBZ (preserve spaces, remove illegal chars)
    base_folder = os.path.abspath(folder_path)
    base_name = os.path.basename(base_folder)
    safe_base_name = sanitize_folder_name(base_name)
    # Place the CBZ inside the manga root folder so the finished archive is located
    # within the manga folder itself (e.g., <Manga Folder>/<Manga Folder>.cbz)
    cbz_name = os.path.join(base_folder, f"{safe_base_name}.cbz")
    console.print(f"[magenta]Creating CBZ archive: {cbz_name}[/]")

    with zipfile.ZipFile(cbz_name, 'w') as cbz:
        for root, dirs, files in os.walk(base_folder):
            files = sorted(files)
            for file in files:
                file_path = os.path.join(root, file)
                # avoid adding the cbz itself if it's inside the folder
                if os.path.abspath(file_path) == os.path.abspath(cbz_name):
                    continue
                arcname = os.path.relpath(file_path, base_folder)
                cbz.write(file_path, arcname=arcname)

    console.print(f"[magenta]Created {cbz_name}[/]")

    # Delete only subfolders (per chapter folders) inside the manga root folder
    for item in os.listdir(base_folder):
        item_path = os.path.join(base_folder, item)
        # don't remove the generated cbz file
        if item.lower().endswith('.cbz'):
            continue
        if os.path.isdir(item_path):
            try:
                shutil.rmtree(item_path)
                console.print(f"[green]Deleted folder {item_path}[/]")
            except Exception as e:
                console.print(f"[red]Failed to delete {item_path}: {e}[/]")


# ----------- sanitize manga name -----------
def sanitize_folder_name(name: str) -> str:
    """Remove illegal characters from folder/file names."""
    # Replace illegal filesystem characters with underscore, but keep spaces
    cleaned = re.sub(r'[<>:"/\\|?*]', "", name)
    # Replace underscores/hyphens that were used as separators in some inputs with spaces
    cleaned = cleaned.replace("_", " ")
    cleaned = cleaned.replace("-", " ")
    # Collapse multiple spaces into one and trim
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    return cleaned


def get_slug_and_pretty(manga_input: str):
    """Return (slug_for_urls, pretty_folder_name).

    - slug_for_urls: hyphen-separated string suitable for building URLs
    - pretty_folder_name: sanitized name with spaces for folders/CBZ
    """
    if manga_input.startswith("http"):
        path = urlparse(manga_input).path
        parts = [p for p in path.split("/") if p]
        if len(parts) >= 2:
            slug = parts[1]
        else:
            slug = parts[-1]
    else:
        slug = manga_input

    # Normalize slug: replace whitespace with single hyphen and collapse multiples
    slug = re.sub(r"\s+", "-", slug).strip("-")
    # Create a pretty folder name (spaces instead of hyphens)
    pretty = sanitize_folder_name(slug.replace("-", " "))
    return slug, pretty

# ------------------ URL GATHERING WITH PROGRESS ------------------
def gather_all_urls(manga_name, start_chapter=1, start_page=1, max_pages=50, max_decimals=5, workers=10):
    urls_to_download = []
    folder_base = sanitize_folder_name(manga_name)
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

# ------------------ DOWNLOAD WITH PROGRESS ------------------
def download_all_pages(urls_to_download, max_workers=10, manga_name="manga"):
    manga_folder_name = sanitize_folder_name(manga_name)
    total_pages = len(urls_to_download)
    if total_pages == 0:
        return

    start_time = time.time()
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
        rate_limiter_athome.acquire("mangadex_api")
        params = {
            "manga": manga_uuid,
            "translatedLanguage[]": lang,
            "limit": limit,
            "offset": offset,
            "order[chapter]": "asc"
        }
        resp = requests.get(f"{API_ENDPOINT}/chapter", params=params)
        if resp.status_code == 429:
            console.print("[yellow]Rate limited by MangaDex, sleeping 5 seconds...[/]")
            time.sleep(5)
            continue
        elif resp.status_code != 200:
            console.print(f"[red]Error fetching chapters: {resp.status_code}[/]")
            break
        data = resp.json()
        batch = data.get("data", [])
        chapters.extend(batch)
        total = data.get("total", 0)
        if offset + limit >= total:
            break
        offset += limit
    return chapters

def get_images_md(chapter_id: str, use_saver=False, max_retries=5):
    for attempt in range(max_retries):
        rate_limiter_athome.acquire("mangadex_athome")
        resp = requests.get(f"https://api.mangadex.org/at-home/server/{chapter_id}")
        if resp.status_code == 429:
            wait = (attempt + 1) * 5
            console.print(f"[yellow]Rate limited. Waiting {wait}s...[/]")
            time.sleep(wait)
            continue
        elif resp.status_code != 200:
            console.print(f"[red]Error fetching chapter {chapter_id}: {resp.status_code}[/]")
            return []
        chapter_data = resp.json().get("chapter", {})
        base_url = resp.json().get("baseUrl")
        hash_code = chapter_data.get("hash")
        pages = chapter_data.get("dataSaver" if use_saver else "data", [])
        if not base_url or not hash_code or not pages:
            return []
        return [f"{base_url}/data/{hash_code}/{page}" for page in pages]
    return []

# ------------------ MANGADEX FUNCTIONS ------------------
def download_md_chapters(manga_url, lang="en", use_saver=False, create_cbz=True):
    # Extract UUID and clean manga title
    manga_uuid = extract_manga_uuid(manga_url)
    if not manga_uuid:
        console.print(f"[red]Could not extract manga UUID from URL[/]")
        return

    manga_name_clean = get_manga_name_from_md(manga_url, lang=lang)
    manga_name_clean = sanitize_folder_name(manga_name_clean)

    # Root folder named after manga
    manga_root_folder = manga_name_clean
    os.makedirs(manga_root_folder, exist_ok=True)

    console.print(f"[cyan]Downloading '{manga_name_clean}' in language '{lang}'[/]")
    chapters = fetch_all_chapters_md(manga_uuid, lang)
    console.print(f"[green]Found {len(chapters)} chapters[/]")

    for chapter in chapters:
        attr = chapter.get("attributes", {})
        chapter_num = attr.get("chapter", "Unknown")
        chapter_title = attr.get("title", "")
        chap_id = chapter.get("id")

        # Subfolder per chapter
        chapter_folder_name = f"Chapter_{chapter_num}_{chapter_title}".strip("_")
        chapter_folder_name = sanitize_folder_name(chapter_folder_name)
        chapter_folder = os.path.join(manga_root_folder, chapter_folder_name)

        images = get_images_md(chap_id, use_saver=use_saver)
        if not images:
            console.print(f"[yellow]Skipping Chapter {chapter_num} (no images)[/]")
            continue

        os.makedirs(chapter_folder, exist_ok=True)
        console.print(f"[yellow]Downloading Chapter {chapter_num}: {chapter_title}[/]")

        urls_to_download = [(url, chapter_folder) for url in images]
        download_all_pages(urls_to_download, max_workers=10, manga_name=manga_name_clean)

        if not os.listdir(chapter_folder):
            console.print(f"[red]Removing empty folder {chapter_folder_name}[/]")
            os.rmdir(chapter_folder)

    # ✅ Create CBZ from the manga root folder
    if create_cbz:
        create_cbz_for_all(manga_root_folder)


def get_manga_name_from_md(manga_url, lang="en"):
    manga_uuid = extract_manga_uuid(manga_url)
    if not manga_uuid:
        return extract_manga_name_from_url(manga_url)
    resp = requests.get(f"{API_ENDPOINT}/manga/{manga_uuid}")
    if resp.status_code != 200:
        return extract_manga_name_from_url(manga_url)
    data = resp.json().get("data", {})
    attributes = data.get("attributes", {})
    title_dict = attributes.get("title", {})
    return title_dict.get(lang) or title_dict.get("en") or list(title_dict.values())[0]

# ----- Folder you are gone ---------------
def safe_delete_folder(folder_path):
    try:
        folder = pathlib.Path(folder_path)
        for item in folder.rglob("*"):
            try:
                if item.is_file() or item.is_symlink():
                    item.unlink()
                elif item.is_dir():
                    shutil.rmtree(item)
            except Exception as e:
                console.print(f"[yellow]Warning: could not delete {item}: {e}[/]")
        # Try removing the root folder at the end
        if folder.exists():
            folder.rmdir()
        console.print(f"[green]Deleted folder {folder_path} after CBZ creation[/]")
    except Exception as e:
        console.print(f"[red]Failed to delete {folder_path}: {e}[/]")
        

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

    # Determine clean manga name
    if manga_name.startswith("http") and "mangadex" in manga_name.lower():
        download_md_chapters(manga_name, lang=md_lang, use_saver=False, create_cbz=cbz_flag)
        manga_name_clean = get_manga_name_from_md(manga_name, lang=md_lang)
        manga_name_clean = sanitize_folder_name(manga_name_clean)
    else:
        # Separate slug (for URLs) from pretty folder name (for filesystem)
        slug, pretty_name = get_slug_and_pretty(manga_name)
        urls_to_download = gather_all_urls(
            slug,
            start_chapter=start_chapter,
            start_page=start_page,
            max_pages=max_pages,
            max_decimals=50,
            workers=workers
        )
        download_all_pages(urls_to_download, max_workers=workers, manga_name=pretty_name)
        if cbz_flag and not stop_signal:
            create_cbz_for_all(pretty_name)
            
if __name__ == "__main__":
    print("""
\033[96m          
 _ __ ___   __ _ _ __   __ _  __ _                       
| '_ ` _ \\ / _` | '_ \\ / _` |/ _` |                      
| | | | | | (_| | | | | (_| | (_| |                      
|_| |_| |_|\\__,_|_| |_|\\__, |\\__,_|                      
     _                 |___/                 _           
  __| | _____      ___ __ | | ___   __ _  __| | ___ _ __ 
 / _` |/ _ \\ \\ /\\ / / '_ \\| |/ _ \\ / _` |/ _` |/ _ \\ '__|
| (_| | (_) \\ V  V /| | | | | (_) | (_| | (_| |  __/ |   
 \\__,_|\\___/ \\_/\\_/ |_| |_|_|\\___/ \\__,_|\\__,_|\\___|_|   
\033[95m

- nycthera, 2025
\033[0m
""")


    main()
