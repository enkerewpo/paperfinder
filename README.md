# paperfinder

wheatfox

Python toolkit that ingests paper metadata from DBLP collections and ranks
stored entries against natural language queries with DeepSeek.

## Quickstart

```bash
pip install paperfinder
paperfinder config --init
paperfinder fetch --all-targets
paperfinder query --prompt "embodied intelligence" --top-k 5
```