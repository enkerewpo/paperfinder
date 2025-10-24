"""Web UI subsystem for pfdr."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Request, Form, File, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import uvicorn

from .config import Settings
from .dblp import DblpIngestionTaskRunner
from .llm import create_llm_client
from .models import Paper, TaskMeta
from .state import IngestionStateStore
from .storage import PaperStore
from .tasks import TaskManager
from .services.enrichment import PaperEnrichmentService


class WebUI:
    """Web UI subsystem for pfdr."""
    
    def __init__(self, settings: Optional[Settings] = None):
        self.settings = settings or Settings()
        self.app = FastAPI(
            title="PFDR Console",
            description="Console for DBLP paper ingestion and AI-powered search",
            version="0.1.1"
        )
        self._setup_routes()
        self._setup_static_files()
    
    def _setup_static_files(self):
        """Setup static files and templates."""
        # Create static directory if it doesn't exist
        static_dir = Path(__file__).parent / "webui" / "static"
        static_dir.mkdir(parents=True, exist_ok=True)
        
        # Create templates directory if it doesn't exist
        templates_dir = Path(__file__).parent / "webui" / "templates"
        templates_dir.mkdir(parents=True, exist_ok=True)
        
        # Mount static files
        self.app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
        
        # Setup templates
        self.templates = Jinja2Templates(directory=str(templates_dir))
    
    def _setup_routes(self):
        """Setup all web routes."""
        
        @self.app.get("/", response_class=HTMLResponse)
        async def index(request: Request):
            """Main dashboard page."""
            return self.templates.TemplateResponse("index.html", {"request": request})
        
        @self.app.get("/api/papers")
        async def get_papers(
            limit: int = 1000, 
            pattern: Optional[str] = None,
            category: Optional[str] = None,
            keyword: Optional[str] = None
        ):
            """Get papers with optional filtering."""
            store = PaperStore(self.settings)
            papers = store.list()
            
            if pattern:
                papers = [p for p in papers if pattern.lower() in p.title.lower()]
            
            if category:
                papers = [p for p in papers if p.category and category.lower() in p.category.lower()]
            
            if keyword:
                papers = [p for p in papers if any(keyword.lower() in kw.lower() for kw in p.keywords)]
            
            papers = papers[:limit]
            
            # Add color information for each paper's category
            from pfdr.services.enrichment import get_category_color
            papers_with_colors = []
            for paper in papers:
                paper_dict = paper.to_dict()
                if paper.category:
                    paper_dict["category_color"] = get_category_color(paper.category)
                papers_with_colors.append(paper_dict)
            
            return {"papers": papers_with_colors}
        
        @self.app.get("/api/sources")
        async def get_sources():
            """Get ingestion sources."""
            state_store = IngestionStateStore(self.settings)
            states = state_store.list()
            return {"sources": [state.to_dict() for state in states]}
        
        @self.app.get("/api/tasks")
        async def get_tasks():
            """Get task status."""
            manager = TaskManager(settings=self.settings)
            tasks = manager.store.list()
            return {"tasks": [task.to_dict() for task in tasks]}
        
        @self.app.get("/api/config")
        async def get_config():
            """Get current configuration."""
            return {
                "llm_provider": self.settings.llm_provider,
                "llm_configured": bool(self.settings.llm_api_key),
                "llm_api_base": self.settings.llm_api_base,
                "llm_model": self.settings.llm_model,
                "data_dir": str(self.settings.data_dir),
                "targets": [
                    {
                        "name": target.name,
                        "url": target.url,
                        "enabled": target.enabled
                    }
                    for target in self.settings.ingestion_targets
                ]
            }
        
        @self.app.post("/api/fetch")
        async def start_fetch(
            source_url: Optional[str] = Form(None),
            sources_file: Optional[UploadFile] = File(None),
            target_name: Optional[str] = Form(None),
            all_targets: bool = Form(False),
            page_size: int = Form(200),
            max_entries: Optional[int] = Form(None)
        ):
            """Start a fetch task."""
            # Count source options
            source_options = sum([
                bool(source_url),
                bool(sources_file),
                bool(target_name),
                all_targets
            ])
            
            if source_options == 0:
                raise HTTPException(400, "Must specify one source option")
            if source_options > 1:
                raise HTTPException(400, "Can only specify one source option at a time")
            
            manager = TaskManager(settings=self.settings)
            runner = DblpIngestionTaskRunner(settings=self.settings, page_size=page_size)
            
            sources = []
            
            if source_url:
                sources = [source_url]
            elif sources_file:
                content = await sources_file.read()
                sources = [line.strip() for line in content.decode().splitlines() 
                          if line.strip() and not line.strip().startswith("#")]
            elif target_name:
                target = None
                for t in self.settings.ingestion_targets:
                    if t.name == target_name:
                        target = t
                        break
                
                if not target:
                    raise HTTPException(404, f"Target '{target_name}' not found")
                if not target.enabled:
                    raise HTTPException(400, f"Target '{target_name}' is disabled")
                
                sources = [target.url]
            elif all_targets:
                enabled_targets = self.settings.get_enabled_targets()
                if not enabled_targets:
                    raise HTTPException(400, "No enabled targets found")
                sources = [target.url for target in enabled_targets]
            
            if not sources:
                raise HTTPException(400, "No valid sources provided")
            
            task = manager.enqueue(
                "dblp_ingest",
                payload={
                    "sources": sources,
                    "max_entries": max_entries,
                }
            )
            
            # Run the task
            for pending in manager.drain():
                if pending.task_id != task.task_id:
                    continue
                runner.run(manager, pending)
                break
            
            return {"task_id": task.task_id, "status": "completed"}
        
        @self.app.post("/api/query")
        async def query_papers(
            prompt: str = Form(...),
            top_k: int = Form(10)
        ):
            """Query papers using AI."""
            store = PaperStore(self.settings)
            papers = store.list()
            
            if not papers:
                raise HTTPException(400, "No papers stored. Run fetch first.")
            
            client = create_llm_client(self.settings)
            ranked = client.rank_papers(prompt, papers, top_k=top_k)
            
            return {
                "results": [
                    {
                        "paper": item.paper.to_dict(),
                        "score": item.score,
                        "reason": item.reason
                    }
                    for item in ranked
                ]
            }
        
        @self.app.delete("/api/papers")
        async def remove_papers(
            pattern: Optional[str] = Form(None),
            source_url: Optional[str] = Form(None),
            target_name: Optional[str] = Form(None)
        ):
            """Remove papers and sources."""
            removal_options = sum([bool(pattern), bool(source_url), bool(target_name)])
            
            if removal_options == 0:
                raise HTTPException(400, "Must specify one removal option")
            if removal_options > 1:
                raise HTTPException(400, "Can only specify one removal option at a time")
            
            state_store = IngestionStateStore(self.settings)
            paper_store = PaperStore(self.settings)
            
            sources_to_delete = []
            
            if pattern:
                states = state_store.list()
                matching_sources = [
                    state.source_url for state in states
                    if pattern.lower() in state.source_url.lower()
                ]
                sources_to_delete = matching_sources
            elif source_url:
                states = state_store.list()
                if source_url in [state.source_url for state in states]:
                    sources_to_delete = [source_url]
                else:
                    raise HTTPException(404, f"Source URL '{source_url}' not found")
            elif target_name:
                target = None
                for t in self.settings.ingestion_targets:
                    if t.name == target_name:
                        target = t
                        break
                
                if not target:
                    raise HTTPException(404, f"Target '{target_name}' not found")
                
                sources_to_delete = [target.url]
                
                # Remove from configuration
                if self.settings.remove_ingestion_target(target_name):
                    self.settings.save_to_yaml()
            
            if not sources_to_delete:
                raise HTTPException(400, "No matching sources found")
            
            # Delete papers
            deleted_papers = paper_store.delete_by_sources(sources_to_delete)
            
            # Delete ingestion states
            deleted_states = 0
            if pattern:
                deleted_sources = state_store.delete_by_pattern(pattern)
                deleted_states = len(deleted_sources)
            else:
                if state_store.delete_by_source(source_url):
                    deleted_states = 1
            
            return {
                "deleted_papers": deleted_papers,
                "deleted_states": deleted_states
            }
        
        @self.app.post("/api/config/targets")
        async def add_target(
            name: str = Form(...),
            url: str = Form(...)
        ):
            """Add a new ingestion target."""
            try:
                self.settings.add_ingestion_target(name, url)
                self.settings.save_to_yaml()
                return {"message": f"Added target: {name}"}
            except Exception as e:
                raise HTTPException(400, f"Failed to add target: {e}")
        
        @self.app.get("/api/authors")
        async def get_authors(limit: int = 20, pattern: Optional[str] = None):
            """Get authors with paper counts."""
            store = PaperStore(self.settings)
            papers = store.list()
            author_counts = {}
            
            for paper in papers:
                for author in paper.authors:
                    if pattern and pattern.lower() not in author.lower():
                        continue
                    author_counts[author] = author_counts.get(author, 0) + 1
            
            sorted_authors = sorted(author_counts.items(), key=lambda x: x[1], reverse=True)
            sorted_authors = sorted_authors[:limit]
            
            return {
                "authors": [
                    {"author": author, "paper_count": count}
                    for author, count in sorted_authors
                ]
            }
        
        @self.app.post("/api/enrich")
        async def enrich_papers(
            enrich_abstracts: bool = Form(True),
            extract_keywords: bool = Form(True),
            cluster_papers: bool = Form(True),
            limit: Optional[int] = Form(None)
        ):
            """Enrich papers with abstracts, keywords, and categories."""
            store = PaperStore(self.settings)
            papers = store.list()
            
            if not papers:
                raise HTTPException(400, "No papers stored. Run fetch first.")
            
            # Filter papers that need enrichment
            papers_to_enrich = []
            for paper in papers:
                needs_enrichment = False
                if enrich_abstracts and not paper.abstract:
                    needs_enrichment = True
                if extract_keywords and not paper.keywords:
                    needs_enrichment = True
                if cluster_papers and not paper.category:
                    needs_enrichment = True
                
                if needs_enrichment:
                    papers_to_enrich.append(paper)
            
            if limit:
                papers_to_enrich = papers_to_enrich[:limit]
            
            if not papers_to_enrich:
                return {"message": "No papers need enrichment", "enriched_count": 0}
            
            # Enrich papers
            enrichment_service = PaperEnrichmentService(self.settings)
            results = await enrichment_service.enrich_papers_batch(papers_to_enrich)
            
            # Update papers in storage
            enriched_count = 0
            for result in results:
                if result.success:
                    paper = result.paper
                    if result.abstract:
                        paper.abstract = result.abstract
                    if result.keywords:
                        paper.keywords = result.keywords
                    if result.category:
                        paper.category = result.category
                    
                    store.update(paper)
                    enriched_count += 1
            
            return {
                "message": f"Enriched {enriched_count} papers",
                "enriched_count": enriched_count,
                "total_processed": len(results)
            }
        
        @self.app.get("/api/categories")
        async def get_categories():
            """Get paper categories with counts and colors."""
            from pfdr.services.enrichment import get_category_color
            
            store = PaperStore(self.settings)
            papers = store.list()
            
            category_counts = {}
            for paper in papers:
                if paper.category:
                    category_counts[paper.category] = category_counts.get(paper.category, 0) + 1
            
            sorted_categories = sorted(category_counts.items(), key=lambda x: x[1], reverse=True)
            
            return {
                "categories": [
                    {
                        "category": category, 
                        "count": count,
                        "color": get_category_color(category)
                    }
                    for category, count in sorted_categories
                ]
            }
        
        @self.app.get("/api/keywords")
        async def get_keywords(limit: int = 50):
            """Get most common keywords."""
            store = PaperStore(self.settings)
            papers = store.list()
            
            keyword_counts = {}
            for paper in papers:
                for keyword in paper.keywords:
                    keyword_counts[keyword] = keyword_counts.get(keyword, 0) + 1
            
            sorted_keywords = sorted(keyword_counts.items(), key=lambda x: x[1], reverse=True)
            sorted_keywords = sorted_keywords[:limit]
            
            return {
                "keywords": [
                    {"keyword": keyword, "count": count}
                    for keyword, count in sorted_keywords
                ]
            }
    
    def run(self, host: str = "127.0.0.1", port: int = 8000, reload: bool = False):
        """Run the web UI server."""
        if reload:
            # For reload mode, we need to use import string
            uvicorn.run(
                "pfdr.webui:create_webui_app",
                host=host,
                port=port,
                reload=reload,
                log_level="info"
            )
        else:
            # For normal mode, we can use the app object directly
            uvicorn.run(
                self.app,
                host=host,
                port=port,
                reload=reload,
                log_level="info"
            )


def create_webui_app() -> FastAPI:
    """Create and return a FastAPI app instance."""
    webui = WebUI()
    return webui.app
