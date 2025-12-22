# Architecture Documentation

## System Overview

MDL implements a dual-architecture approach combining a Python CLI application with a Node.js API server to create a robust manga downloading solution.

## Component Architecture

### Python CLI Application (`main.py`)

- **Concurrency Model**: asyncio with aiohttp for non-blocking, high-concurrency downloads (bounded by semaphores for smoother progress updates)
- **Data Sources**: Multi-source approach with automatic failover across manga hosting services
- **Progress Tracking**: Rich progress bars powered by `asyncio.as_completed` for incremental updates (spinner + elapsed/remaining)
- **Clean Output Mode**: Suppresses progress bars and prints a compact summary panel (title/chapters/pages/CBZ)
- **Error Handling**: RateLimiter class with exponential backoff and async timeout management
- **Configuration**: JSON-based user configuration management with graceful signal handling

### Node.js API Server (`Manga-API/`)

- **Web Scraping**: Cheerio-based HTML parsing for MangaKakalot
- **REST Endpoints**: 5 core endpoints with proper error handling
- **CORS Support**: Cross-origin request handling
- **Response Caching**: Efficient data retrieval patterns

## Technical Challenges Solved

1. **Rate Limiting Management**: Implemented exponential backoff to handle server rate limits
2. **Concurrent Download Optimization**: Balanced worker threads to maximize throughput without overwhelming servers
3. **Multi-Source Resilience**: Automatic failover between different manga hosting services
4. **Data Consistency**: UUID-based identification system for reliable manga tracking
5. **Cross-Platform Compatibility**: File system abstraction for Windows/macOS/Linux support

## Performance Optimizations

- **Async HTTP Pooling**: aiohttp ClientSession for connection reuse and reduced overhead
- **Concurrent Task Batching**: `asyncio.as_completed` + semaphores for smooth, incremental progress while keeping concurrency bounded
- **Memory Management**: Async streaming downloads with incremental file writes to prevent memory exhaustion
- **Progress Visualization**: Non-blocking Rich progress bars with async task updates and real-time metrics

## Testing Strategy

- **Unit Testing**: Comprehensive pytest suite with pytest-asyncio for async test support
- **Integration Testing**: Async API endpoint validation with aiohttp test clients
- **CI/CD Pipeline**: Automated testing on push/PR with Playwright browser automation
- **Error Simulation**: Async connection failure and timeout testing with proper async/await patterns
