# Architecture Documentation

## System Overview

MDL implements a dual-architecture approach combining a Python CLI application with a Node.js API server to create a robust manga downloading solution.

## Component Architecture

### Python CLI Application (`main.py`)

- **Concurrency Model**: ThreadPoolExecutor with configurable worker pools
- **Data Sources**: Multi-source approach with automatic fallback
- **Progress Tracking**: Real-time metrics with Rich library integration
- **Error Handling**: Exponential backoff retry mechanism
- **Configuration**: JSON-based user configuration management

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

- **Connection Pooling**: Reused HTTP sessions for reduced overhead
- **Batch Processing**: Efficient URL validation with parallel requests
- **Memory Management**: Streaming downloads to prevent memory exhaustion
- **Progress Visualization**: Non-blocking UI updates during long operations

## Testing Strategy

- **Unit Testing**: Comprehensive pytest suite with mocking
- **Integration Testing**: API endpoint validation
- **CI/CD Pipeline**: Automated testing on push/PR
- **Error Simulation**: Connection failure and timeout testing
