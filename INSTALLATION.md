# Installation & Usage Guide

## Prerequisites

- Python 3.13+
- Node.js 18+
- npm/yarn

## Installation

### Python CLI

```bash
# Clone repository
git clone https://github.com/Nycthera/mdl.git
cd mdl

# Install Python dependencies
pip install -r requirements.txt

# Run CLI application
python main.py -M "manga-name-or-url"
```

OR

### Install packages

### Mac/Linux

```bash
git clone https://github.com/nycthera/mdl.git
cd mdl
chmod +x install.sh
./install.sh
```

### Windows

```bash
git clone https://github.com/nycthera/mdl.git
cd mdl
install.bat
```

### API Server

```bash
# Navigate to API directory
cd Manga-API

# Install Node.js dependencies
npm install

# Start server
npm start
```

## Usage Examples

### Basic Manga Download

```bash
python main.py -M "one-piece"
```

### MangaDx URL Download

```bash
python main.py -M "https://mangadx.org/title/uuid/manga-name"
```

### Advanced Configuration

```bash
python main.py -M "naruto" --workers 15 --max-pages 100 --cbz
```

### Clean Output Mode (summary only)

```bash
python main.py --clean-output -M "naruto"
```

This suppresses progress bars and prints a compact summary panel at the end.

### API Testing

```bash
# Test API endpoints
python test.py

# Manual API calls
curl "http://localhost:3000/api/search?query=one-piece"
```

## Configuration

The application creates a config file at `~/.config/manga_downloader/config.json`:

```json
{
  "manga_name": "",
  "start_chapter": 1,
  "start_page": 1,
  "max_pages": 50,
  "workers": 10,
  "cbz": true,
  "clean_output": false,
  "md_language": "en"
}
```

### Playwright install

```bash
playwright install
```

## Development

### Running Tests

```bash
# Python tests
pytest -v

# API integration tests
python test.py
```

### CI/CD

GitHub Actions automatically runs tests on push/PR and supports optional releases via workflow dispatch.
