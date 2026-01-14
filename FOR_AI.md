# FOR_AI.md - MDL Project Context for AI Assistants

## Project Overview

**MDL (Multi-Source Manga Downloader)** is a sophisticated, high-performance manga downloading solution featuring concurrent processing, multi-source integration, and comprehensive error handling. It demonstrates advanced system design patterns and full-stack development skills.

**Version:** 3.3 stable  
**License:** GNU General Public License v3.0  
**Primary Language:** Python 3.13  
**Architecture:** Single Python CLI application with async/await concurrency

## Core Technology Stack

### Python Application
- **Python 3.13** - Core application with advanced async features
- **asyncio** - Non-blocking concurrent operations
- **aiohttp** - Async HTTP client with connection pooling
- **playwright + playwright-stealth** - Browser automation for web scraping
- **rich** - Terminal UI with progress bars and formatted output
- **requests** - Synchronous HTTP for simple operations

### Development & Testing
- **pytest** - Unit testing framework
- **pytest-asyncio** - Async test support
- **GitHub Actions** - CI/CD pipeline for automated testing

## Architecture Deep Dive

### Concurrency Model
- **asyncio with semaphores** - Bounded concurrency for smoother progress updates
- **aiohttp ClientSession** - Persistent connection pooling for optimized network performance
- **asyncio.as_completed** - Incremental progress updates as tasks complete
- **Maximum 10 concurrent downloads** - Configurable worker limit to prevent server overload

### Data Sources & Resilience
- **Multi-Source Architecture** - Automatic failover between manga hosting services
- **MangaDx API Integration** - Primary source with UUID-based identification
- **Web Scraping Fallback** - Playwright-based scraping for additional sources
- **Pattern Matching** - Regex-based URL validation and image detection
  - Pattern: `/manga/[^/]+/\d{4}-\d{3,4}\.png$`
  - Title extraction: `/manga/([^/]+)/`

### Error Handling & Rate Limiting
- **RateLimiter class** - Exponential backoff to handle server constraints
- **5 retry attempts** - Automatic retry with increasing delays
- **Async timeout handling** - Graceful timeout management
- **Signal handling** - Clean shutdown on SIGINT (Ctrl+C)

### User Interface
- **Rich Progress Bars** - Real-time visualization with:
  - Spinner for active status
  - Time elapsed/remaining
  - Pages per second metrics
  - Bar column for visual progress
- **Clean Output Mode** - `--clean-output` flag suppresses progress bars and shows compact summary panel
- **Colored Console Output** - Rich console with styled text and panels

### Configuration Management
- **JSON-based config** - Stored in `~/.config/manga_downloader/config.json`
- **Default values** - Automatic creation if config doesn't exist
- **User preferences** - Persistent settings across runs

## Key Files & Structure

```
mdl/
├── main.py                 # Core CLI application (~415 lines)
│   ├── Async download logic with bounded concurrency
│   ├── RateLimiter class with exponential backoff
│   ├── Config management (JSON)
│   ├── Signal handlers for graceful shutdown
│   ├── Progress tracking with Rich
│   └── CBZ archive generation
│
├── test/
│   └── test_main.py        # Comprehensive unit tests
│       ├── Config creation/loading tests
│       ├── URL sanitization tests
│       ├── Download logic mocking
│       └── Edge case handling
│
├── requirements.txt        # Python dependencies
├── pytest.ini             # pytest configuration
├── install.sh/install.bat # Installation scripts
│
├── .github/workflows/
│   └── python-tests.yml   # CI/CD pipeline
│
└── Documentation
    ├── README.md           # User-facing documentation
    ├── ARCHITECTURE.md     # Technical architecture
    ├── PROJECT_STRUCTURE.md # File organization
    └── INSTALLATION.md     # Setup instructions
```

## Important Code Patterns

### 1. Async Download with Semaphore
```python
# Bounded concurrency to prevent overwhelming servers
semaphore = asyncio.Semaphore(workers)
async with semaphore:
    async with session.get(url) as response:
        content = await response.read()
```

### 2. Progress Tracking
```python
# Rich progress bars with multiple columns
progress = Progress(
    SpinnerColumn(),
    TextColumn("[progress.description]{task.description}"),
    BarColumn(),
    TimeElapsedColumn(),
    TimeRemainingColumn(),
)
```

### 3. Signal Handling
```python
# Graceful shutdown on interrupts
stop_signal = False
def signal_handler(sig, frame):
    global stop_signal
    stop_signal = True
signal.signal(signal.SIGINT, signal_handler)
```

### 4. Configuration Management
```python
# JSON config in user home directory
CONFIG_FILE = ~/.config/manga_downloader/config.json
def load_config():
    if not os.path.exists(CONFIG_FILE):
        create_default_config()
    return json.load(open(CONFIG_FILE))
```

## Command-Line Interface

### Main Arguments
- `-M, --manga-name` - Manga title or MangaDx URL
- `--workers` - Number of concurrent downloads (default: 10)
- `--max-pages` - Limit pages to download
- `--cbz` - Create CBZ archive format
- `--clean-output` - Suppress progress bars, show summary panel
- `--update` - Self-update from GitHub releases

### Usage Examples
```bash
# Basic download
python main.py -M "one-piece"

# MangaDx URL
python main.py -M "https://mangadx.org/title/uuid/manga-name"

# Advanced with options
python main.py -M "naruto" --workers 15 --max-pages 100 --cbz

# Clean output mode (minimal UI)
python main.py -M "naruto" --clean-output
```

## Testing Strategy

### Unit Tests (pytest)
- **Config management** - Creation, loading, defaults
- **URL sanitization** - Illegal character removal
- **Download mocking** - aiohttp response simulation
- **Edge cases** - Invalid inputs, network failures
- **Async testing** - pytest-asyncio for async functions

### CI/CD Pipeline
- **Automated testing** - Run on push/PR
- **Python 3.13 compatibility** - Version-specific tests
- **Optional releases** - Manual workflow dispatch

## Technical Challenges Solved

1. **Rate Limiting Management** - Exponential backoff prevents IP bans
2. **Concurrent Download Optimization** - Semaphore-based worker limiting
3. **Multi-Source Resilience** - Automatic failover between sources
4. **Data Consistency** - UUID-based manga identification
5. **Cross-Platform Compatibility** - pathlib for OS-agnostic paths
6. **Memory Efficiency** - Streaming downloads with async I/O
7. **Progress Visualization** - Non-blocking Rich updates

## Performance Metrics

- **Concurrency:** Up to 10 parallel async tasks
- **Retry Logic:** 5 attempts with exponential backoff
- **Progress Updates:** Real-time pages/second tracking
- **Memory:** Streaming downloads prevent memory exhaustion
- **Network:** Connection pooling with persistent sessions

## Configuration Options

Default config structure:
```json
{
  "manga_name": "",
  "workers": 10,
  "max_pages": null,
  "create_cbz": false,
  "clean_output": false
}
```

## Error Handling Patterns

1. **Network Errors** - Retry with exponential backoff
2. **Rate Limits** - Automatic delay and retry
3. **Invalid URLs** - UUID extraction and validation
4. **Missing Config** - Auto-create with defaults
5. **Interrupts** - Graceful shutdown with signal handlers
6. **Timeouts** - Async timeout context managers

## Development Workflow

1. **Local Testing** - `pytest -v` runs comprehensive test suite
2. **CI/CD** - GitHub Actions on push/PR
3. **Releases** - Manual workflow dispatch for version releases
4. **Updates** - Self-update mechanism via `--update` flag

## API Server Note

The README references a Node.js API server (`Manga-API/`) with 5 RESTful endpoints, but this directory is not present in the current repository structure. The main application functions independently without the API server.

## Dependencies

### Production
- `aiohttp` - Async HTTP client
- `playwright` - Browser automation
- `playwright-stealth` - Anti-detection for scraping
- `requests` - Synchronous HTTP
- `rich` - Terminal UI

### Development
- `pytest` - Testing framework
- `pytest-asyncio` - Async test support

## When Working on This Project

### Always Consider
1. **Async/await patterns** - All I/O should be non-blocking
2. **Semaphore limits** - Respect concurrent worker bounds
3. **Error handling** - Add retry logic with backoff
4. **Progress updates** - Keep Rich UI responsive
5. **Config validation** - Check for required fields
6. **Cross-platform** - Use pathlib, not string paths
7. **Clean shutdown** - Handle signals gracefully

### Common Tasks
- **Add new source** - Extend URL pattern matching
- **Modify concurrency** - Adjust semaphore limits
- **Update UI** - Modify Rich progress components
- **Add tests** - Use pytest with asyncio support
- **Change config** - Update default_config dict

### Code Style
- Type hints where beneficial
- Async functions for I/O operations
- Rich console for user output
- JSON for configuration
- pytest for testing
- Clear separation of concerns

## Summary for AI

This is a **production-ready Python CLI tool** that downloads manga using **async/await concurrency** with **intelligent rate limiting** and **multi-source failover**. The codebase demonstrates advanced Python patterns including asyncio, context managers, signal handling, and comprehensive error recovery. When modifying this project, maintain the async architecture, respect the semaphore-based concurrency model, and ensure all changes include appropriate error handling and user feedback via Rich console.
