# Source Code Structure

This directory contains the refactored manga downloader code organized into logical modules and packages.

## Directory Layout

```text
src/
├── __init__.py              # Package initialization with version
├── cli.py                   # Command-line argument parsing
├── config.py                # Configuration file management
├── cbz.py                   # CBZ archive creation
├── downloader.py            # Image download functionality
├── rate_limiter.py          # Rate limiting for async requests
├── system_utils.py          # System utilities (update, credits)
├── utils.py                 # General utility functions
└── scrapers/                # Web scraper implementations
    ├── __init__.py          # Scraper utilities and base functions
    ├── generic.py           # Generic direct image source scraper
    ├── mangadex.py          # MangaDex API scraper
    └── weebcentral.py       # WeebCentral browser automation scraper
```

## Module Descriptions

### Core Modules

- **cli.py**: Handles command-line argument parsing. Defines all CLI flags and options.
- **config.py**: Manages user configuration. Loads, creates, and saves config files in `~/.config/manga_downloader/`.
- **utils.py**: Contains general utility functions like name sanitization, URL parsing, and async helpers.
- **system_utils.py**: System-level utilities including the update function and credits display.

### Download & Processing

- **downloader.py**: Handles image downloading with retry logic, progress tracking, and concurrency management.
- **cbz.py**: Creates CBZ (Comic Book Archive) files from downloaded manga chapters.
- **rate_limiter.py**: Implements rate limiting for APIs to avoid throttling.

### Scrapers Package

The `scrapers/` package contains different data sources:

- **scrapers/**init**.py**: Common scraper utilities (URL building, URL validation).
- **scrapers/generic.py**: Generic scraper for direct image hosting sites (LaStation, etc.).
- **scrapers/mangadex.py**: Official MangaDex API scraper for reliable manga downloads.
- **scrapers/weebcentral.py**: Playwright-based browser automation scraper for WeebCentral.

## Key Features

### Clean State Management

Each module has `set_clean_output()` and `set_stop_signal()` functions to manage global state consistently across modules.

### Modular Design

- Scrapers are independent and can be used standalone
- Download and CBZ creation are separated from scraping logic
- Configuration is isolated from application logic

### Type Hints

All functions include type hints for better IDE support and code clarity.

### Error Handling

Each module handles its own errors appropriately:

- Network errors are retried with exponential backoff
- Invalid input is validated early
- Playwright failures gracefully fall back to alternative browsers

## Usage Flow

1. `main.py` loads configuration and parses CLI arguments
2. Based on the manga source, it routes to the appropriate scraper:
   - MangaDex URL → `scrapers.mangadex.download_md_chapters()`
   - WeebCentral URL → `scrapers.weebcentral.fetch_weebcentral_images()`
   - Manga name → `scrapers.generic.gather_all_urls()`
3. Once URLs are collected, `downloader.download_all_pages()` downloads all images
4. If CBZ creation is enabled, `cbz.create_cbz_for_all()` creates the archive

## Adding New Scrapers

To add a new scraper:

1. Create a new file in `scrapers/` (e.g., `scrapers/newsource.py`)
2. Implement scraping functions that return image URLs
3. Add `set_clean_output()` and `set_stop_signal()` functions for state management
4. Import and use in `main.py`'s source detection logic

## Testing

Each module can be tested independently:

```python
# Test config
from src.config import load_config
config = load_config()

# Test utils
from src.utils import sanitize_folder_name
safe_name = sanitize_folder_name("Invalid/Name")

# Test scrapers
from src.scrapers.generic import gather_all_urls
urls = asyncio.run(gather_all_urls("manga-name"))
```
