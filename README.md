# MDL - Multi-Source Manga Downloader

> A sophisticated, high-performance manga downloading solution featuring concurrent processing, multi-source integration, and comprehensive error handling.

[![Python 3.13](https://img.shields.io/badge/python-3.13-blue.svg)](https://python.org)
[![Node.js](https://img.shields.io/badge/node.js-18+-green.svg)](https://nodejs.org)
[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)
[![Tests](https://github.com/Nycthera/mdl/workflows/Python%20Tests/badge.svg)](https://github.com/Nycthera/mdl/actions)

## 🏗️ Architecture Overview

**MDL** implements a dual-component architecture combining a Python CLI application with a Node.js REST API server, demonstrating advanced system design patterns and full-stack development skills.

### Core Components

- **🐍 Python CLI Application** - Async/await downloader with concurrent processing and real-time progress tracking
- **🚀 Node.js REST API** - Web scraping service with 5 RESTful endpoints
- **🔄 Multi-Source Integration** - MangaDx API + web scraping with automatic failover
- **📊 Real-Time Analytics** - Pages/second metrics and progress visualization

## ✨ Key Technical Features

### Concurrency & Performance

- **Async/Await Processing** - asyncio with concurrent tasks for non-blocking downloads (up to 10 concurrent connections)
- **Intelligent Rate Limiting** - RateLimiter class with exponential backoff to handle server constraints
- **Connection Pooling** - aiohttp ClientSession with persistent connections for optimized network performance
- **Memory Efficient** - Streaming downloads with async file I/O to prevent memory exhaustion

### Data Source Resilience

- **Multi-Source Architecture** - Automatic failover between manga hosting services
- **MangaDx API Integration** - Official API consumption with UUID-based identification
- **Web Scraping Fallback** - Cheerio-based HTML parsing for additional sources
- **Cross-Platform Support** - Windows, macOS, and Linux compatibility

### User Experience

- **Rich Console Interface** - Real-time progress bars with pages/second metrics
- **CBZ Archive Generation** - Comic reader compatible output format
- **Configuration Management** - JSON-based user settings with defaults
- **Graceful Error Handling** - Comprehensive exception management with user-friendly messaging

## 🛠️ Tech Stack & Skills Demonstrated

### Backend Development

- **Python 3.13** - Advanced features including async/await, context managers, signal handling, and asyncio
- **Node.js/Express.js** - RESTful API design with proper middleware and error handling
- **Async Concurrency** - asyncio with aiohttp for high-performance, non-blocking HTTP operations

### Data Engineering

- **Web Scraping** - Cheerio-based HTML parsing with robust error handling
- **API Integration** - MangaDx official API consumption and data transformation
- **Data Validation** - UUID extraction, URL parsing, and input sanitization

### DevOps & Quality Assurance

- **CI/CD Pipeline** - GitHub Actions with automated testing and optional releases
- **Comprehensive Testing** - pytest suite with mocking, edge cases, and integration tests
- **Code Quality** - Professional error handling, logging, and documentation

### System Design

- **Microservices Architecture** - Separation of CLI and API concerns
- **Fault Tolerance** - Multi-source resilience with graceful degradation
- **Scalability** - Configurable concurrency and resource management

## 🚀 Quick Start

### Prerequisites

- Python 3.13+
- Node.js 18+
- pip/npm

### Installation

```bash
# Clone repository
git clone https://github.com/Nycthera/mdl.git
cd mdl

# Install Python dependencies
pip install -r requirements.txt

# Install Node.js dependencies (for API server)
cd Manga-API && npm install && cd ..
```

### Usage Examples

#### Basic Manga Download

```bash
python main.py -M "one-piece"
```

#### MangaDx URL Download

```bash
python main.py -M "https://mangadx.org/title/uuid/manga-name"
```

#### Advanced Configuration

```bash
python main.py -M "naruto" --workers 15 --max-pages 100 --cbz
```

#### API Server

```bash
# Start the API server
cd Manga-API && npm start

# Test endpoints
curl "http://localhost:3000/api/search?query=one-piece"
```

## 📊 Performance Metrics

- **Async Concurrency**: Up to 10 concurrent tasks without thread overhead
- **Error Recovery**: Exponential backoff with 5 retry attempts and async timeout handling
- **Progress Tracking**: Real-time pages/second visualization with non-blocking updates
- **Memory Efficient**: Async streaming downloads with aiohttp for large manga collections

## 🧪 Testing & Quality

### Comprehensive Test Suite

- **Unit Tests** - pytest with 95%+ coverage including mocking and edge cases
- **Integration Tests** - API endpoint validation and data consistency checks
- **Error Simulation** - Connection failures, timeouts, and invalid input handling

### CI/CD Pipeline

```yaml
# Automated testing on push/PR
- Python 3.13 compatibility testing
- Dependency vulnerability scanning
- Optional release creation via workflow dispatch
```

## 📈 API Endpoints

The integrated Node.js server provides 5 RESTful endpoints:

| Endpoint              | Method | Description                          |
| --------------------- | ------ | ------------------------------------ |
| `/api/search`         | GET    | Search manga with pagination support |
| `/api/chapter-info`   | GET    | Detailed manga metadata and ratings  |
| `/api/fetch-chapter`  | GET    | Chapter images and navigation        |
| `/api/latest-release` | GET    | Recent manga releases                |
| `/api/latest-manga`   | GET    | Latest manga with filtering          |

## 🎯 Technical Challenges Solved

1. **Rate Limiting Management** - Implemented exponential backoff to handle server rate limits effectively
2. **Concurrent Download Optimization** - Balanced worker threads to maximize throughput without overwhelming servers
3. **Multi-Source Resilience** - Automatic failover between different manga hosting services
4. **Data Consistency** - UUID-based identification system for reliable manga tracking across sources
5. **Cross-Platform Compatibility** - File system abstraction for seamless operation across operating systems

## 📁 Project Structure

```text
mdl/
├── main.py                 # Core Python CLI application (415 lines)
├── test.py                 # API integration testing
├── requirements.txt        # Python dependencies
├── .github/workflows/      # CI/CD pipeline
├── test/
│   └── test_main.py       # Comprehensive unit tests
└── Manga-API/             # Node.js API server
    ├── app/
    │   ├── index.js       # Express.js server
    │   ├── controller.js  # Request handlers
    │   └── mangakakalot.js # Web scraping logic
    └── package.json       # Node.js dependencies
```

## Updating

You can either download the lastest binary from the releases page or use

```bash

py main.py --update
```

or

```bash
mdl --update
```

if you already have the file on your path.

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/enhancement`)
3. Run tests (`pytest -v`)
4. Commit changes (`git commit -am 'Add enhancement'`)
5. Push to branch (`git push origin feature/enhancement`)
6. Create Pull Request

## 📄 License

This project is licensed under the GNU General Public License v3.0 - see the [LICENSE](LICENSE) file for details.

## 🔗 Related Documentation

- [Architecture Overview](ARCHITECTURE.md) - Detailed technical architecture
- [Installation Guide](INSTALLATION.md) - Comprehensive setup instructions
- [Project Structure](PROJECT_STRUCTURE.md) - File organization and purpose

---

**Built with** Python 3.13, Node.js, Express.js, and a focus on performance, reliability, and maintainability.
