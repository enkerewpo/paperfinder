# paperfinder

Python toolkit that ingests paper metadata from DBLP collections and ranks
stored entries against natural language queries with DeepSeek.

## Features
- Incremental DBLP ingestion with on-disk checkpoints for long-running jobs
- JSON storage of paper metadata (title, authors, doi, venue, abstract when available)
- DeepSeek API integration with offline keyword-overlap scoring fallback
- Simple task queue to pause/resume ingestion or query work

## Quickstart
```bash
# Fetch papers from a DBLP API endpoint (adds format/json automatically)
python -m paperfinder.cli fetch --source-url "https://dblp.org/search/publ/api?q=stream:conf/hotos:2023" --page-size 200

# Or supply many sources via text file
python -m paperfinder.cli fetch --sources-file sources.txt

# Inspect task history
python -m paperfinder.cli tasks

# Resume a paused task
python -m paperfinder.cli fetch --source-url "..." --resume-task <task-id>

# Query stored papers
export DEEPSEEK_API_KEY=sk-...
python -m paperfinder.cli query --prompt "具身智能 多模态 存储 文件系统" --top-k 5
```

## Configuration
All metadata, task state, and per-source sync markers live under `data/` by default;
override with the
`PAPERFINDER_DATA_DIR`, `PAPERFINDER_PAPERS_FILE`, `PAPERFINDER_TASKS_FILE`, and
`PAPERFINDER_INGEST_STATE_FILE`
environment variables as needed.
