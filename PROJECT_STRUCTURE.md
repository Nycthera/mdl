# Project Structure

```text
mdl/
├── main.py                 # Core Python CLI application
├── test.py                 # API integration testing
├── requirements.txt        # Python dependencies
├── README.md              # Project documentation
├── ARCHITECTURE.md        # Technical architecture docs
├── .github/
│   └── workflows/
│       └── python-tests.yml # CI/CD pipeline
├── test/
│   ├── test_main.py       # Comprehensive unit tests
│   └── __pycache__/       # Python bytecode cache
├── Manga-API/             # Node.js API server
│   ├── package.json       # Node.js dependencies
│   ├── app/
│   │   ├── index.js       # Express.js server
│   │   ├── routes.js      # API route definitions
│   │   ├── controller.js  # Request handlers
│   │   └── mangakakalot.js # Web scraping logic
│   └── index.html         # API documentation page
└── __pycache__/           # Python bytecode cache
```

## Key Files Explained

### Core Application

- **`main.py`** - 918-line Python CLI with multi-threading, progress tracking, and dual-source support
- **`test_main.py`** - Comprehensive pytest suite with mocking and edge case testing

### API Server

- **`mangakakalot.js`** - Web scraping service using Cheerio for HTML parsing
- **`controller.js`** - Express.js controllers with proper error handling
- **`routes.js`** - RESTful API endpoint definitions

### DevOps

- **`python-tests.yml`** - GitHub Actions CI/CD with automated testing and optional releases
- **`.gitignore`** - Professional exclusions for Python, Node.js, and IDE files
