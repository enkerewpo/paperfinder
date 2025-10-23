# pfdr

wheatfox

Python toolkit that ingests paper metadata from DBLP collections and ranks
stored entries against natural language queries with DeepSeek.

## Quickstart

```bash
pip install pfdr
pfdr config --init
pfdr fetch --all-targets
pfdr query --top-k 5 "embodied intelligence"
```