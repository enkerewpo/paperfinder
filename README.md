# pfdr

[![PyPI version](https://badge.fury.io/py/pfdr.svg)](https://badge.fury.io/py/pfdr)
[![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

wheatfox

Python toolkit that ingests paper metadata from DBLP collections and ranks
stored entries against natural language queries with DeepSeek.

## Quickstart

### Command Line Interface

```bash
pip install pfdr
pfdr config --init
pfdr fetch --all-targets
pfdr query --top-k 5 "embodied intelligence"
```

### Web Interface

Start the web UI server:

```bash
pfdr webui
```

Then open your browser to `http://127.0.0.1:8000` to access the web interface.
