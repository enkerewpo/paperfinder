"""Paper enrichment services for pfdr."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

import aiohttp
from dataclasses import dataclass
from loguru import logger

from ..config import Settings
from ..llm import create_llm_client
from ..models import Paper


@dataclass
class EnrichmentResult:
    """Result of paper enrichment."""

    paper: Paper
    abstract: Optional[str] = None
    keywords: List[str] = None
    category: Optional[str] = None
    success: bool = True
    error: Optional[str] = None
    enriched_fields: List[str] = None  # Track which fields were actually enriched

    def __post_init__(self):
        if self.keywords is None:
            self.keywords = []
        if self.enriched_fields is None:
            self.enriched_fields = []


class AbstractEnrichmentService:
    """Service for enriching papers with abstracts from various sources."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.session: Optional[aiohttp.ClientSession] = None

    async def __aenter__(self):
        self.session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=30),
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            },
        )
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()

    async def enrich_abstract(self, paper: Paper) -> Optional[str]:
        """Try to get abstract from various sources."""
        if paper.abstract:
            return paper.abstract

        # Try different sources based on available identifiers
        if paper.doi:
            abstract = await self._get_abstract_from_doi(paper.doi)
            if abstract:
                return abstract

        # Try Semantic Scholar API
        if paper.doi or paper.title:
            abstract = await self._get_abstract_from_semantic_scholar(paper)
            if abstract:
                return abstract

        if paper.url:
            abstract = await self._get_abstract_from_url(paper.url)
            if abstract:
                return abstract

        # Try arXiv if it's an arXiv paper
        if "arxiv" in paper.identifier.lower():
            abstract = await self._get_arxiv_abstract(paper.identifier)
            if abstract:
                return abstract

        return None

    async def _get_abstract_from_doi(self, doi: str) -> Optional[str]:
        """Get abstract from DOI using CrossRef API."""
        try:
            url = f"https://api.crossref.org/works/{doi}"
            async with self.session.get(url) as response:
                if response.status == 200:
                    data = await response.json()
                    abstract = data.get("message", {}).get("abstract")
                    if abstract:
                        # Remove HTML tags and clean up
                        abstract = re.sub(r"<[^>]+>", "", abstract)
                        abstract = re.sub(r"\s+", " ", abstract).strip()
                        return abstract
        except Exception as e:
            logger.debug(f"Failed to get abstract from DOI {doi}: {e}")
        return None

    async def _get_abstract_from_semantic_scholar(self, paper: Paper) -> Optional[str]:
        """Get abstract from Semantic Scholar API with rate limiting."""
        try:
            # Rate limit: wait 1 second between requests
            await asyncio.sleep(1.0)

            # Try DOI first (most reliable)
            if paper.doi:
                url = f"https://api.semanticscholar.org/graph/v1/paper/DOI:{paper.doi}"
                params = {"fields": "abstract"}

                async with self.session.get(url, params=params) as response:
                    if response.status == 200:
                        data = await response.json()
                        abstract = data.get("abstract")
                        if abstract and len(abstract.strip()) > 50:
                            return abstract.strip()

            # If DOI didn't work or no DOI, try title search
            if paper.title:
                search_url = "https://api.semanticscholar.org/graph/v1/paper/search"
                params = {
                    "query": paper.title,
                    "limit": 3,  # Get top 3 results to find best match
                    "fields": "abstract,title,authors",
                }

                async with self.session.get(search_url, params=params) as response:
                    if response.status == 200:
                        data = await response.json()
                        papers = data.get("data", [])

                        if papers:
                            # Find best match by title similarity
                            best_match = self._find_best_title_match(
                                paper.title, papers
                            )
                            if best_match:
                                abstract = best_match.get("abstract")
                                if abstract and len(abstract.strip()) > 50:
                                    return abstract.strip()

        except Exception as e:
            logger.debug(f"Failed to get abstract from Semantic Scholar: {e}")
        return None

    def _find_best_title_match(self, target_title: str, papers: list) -> Optional[dict]:
        """Find the best matching paper by title similarity."""
        target_lower = target_title.lower()
        best_match = None
        best_score = 0

        for paper in papers:
            paper_title = paper.get("title", "").lower()

            # Simple similarity scoring
            # 1. Exact match gets highest score
            if paper_title == target_lower:
                return paper

            # 2. Check if target title is contained in paper title
            if target_lower in paper_title:
                score = len(target_lower) / len(paper_title)
                if score > best_score:
                    best_score = score
                    best_match = paper

            # 3. Check if paper title is contained in target title
            elif paper_title in target_lower:
                score = len(paper_title) / len(target_lower)
                if score > best_score:
                    best_score = score
                    best_match = paper

            # 4. Word overlap scoring
            target_words = set(target_lower.split())
            paper_words = set(paper_title.split())
            overlap = len(target_words.intersection(paper_words))
            if overlap > 0:
                score = overlap / max(len(target_words), len(paper_words))
                if score > best_score:
                    best_score = score
                    best_match = paper

        # Only return if we have a reasonable match (score > 0.3)
        return best_match if best_score > 0.3 else None

    async def _get_abstract_from_url(self, url: str) -> Optional[str]:
        """Try to extract abstract from paper URL."""
        try:
            async with self.session.get(url) as response:
                if response.status == 200:
                    html = await response.text()
                    # Look for common abstract patterns
                    patterns = [
                        r'<div[^>]*class="[^"]*abstract[^"]*"[^>]*>(.*?)</div>',
                        r'<p[^>]*class="[^"]*abstract[^"]*"[^>]*>(.*?)</p>',
                        r'<section[^>]*class="[^"]*abstract[^"]*"[^>]*>(.*?)</section>',
                        r'<div[^>]*id="[^"]*abstract[^"]*"[^>]*>(.*?)</div>',
                    ]

                    for pattern in patterns:
                        match = re.search(pattern, html, re.DOTALL | re.IGNORECASE)
                        if match:
                            abstract = match.group(1)
                            # Clean up HTML tags
                            abstract = re.sub(r"<[^>]+>", "", abstract)
                            abstract = re.sub(r"\s+", " ", abstract).strip()
                            if len(abstract) > 50:  # Reasonable abstract length
                                return abstract
        except Exception as e:
            logger.debug(f"Failed to get abstract from URL {url}: {e}")
        return None

    async def _get_arxiv_abstract(self, arxiv_id: str) -> Optional[str]:
        """Get abstract from arXiv API."""
        try:
            # Extract arXiv ID from identifier
            arxiv_match = re.search(r"arxiv/(\d+\.\d+)", arxiv_id.lower())
            if not arxiv_match:
                return None

            arxiv_num = arxiv_match.group(1)
            url = f"http://export.arxiv.org/api/query?id_list={arxiv_num}"

            async with self.session.get(url) as response:
                if response.status == 200:
                    xml_content = await response.text()
                    # Simple XML parsing for abstract
                    abstract_match = re.search(
                        r"<summary[^>]*>(.*?)</summary>", xml_content, re.DOTALL
                    )
                    if abstract_match:
                        abstract = abstract_match.group(1)
                        abstract = re.sub(r"\s+", " ", abstract).strip()
                        return abstract
        except Exception as e:
            logger.debug(f"Failed to get arXiv abstract for {arxiv_id}: {e}")
        return None


class KeywordExtractionService:
    """Service for extracting keywords from papers using LLM."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.llm_client = create_llm_client(settings)

    async def extract_keywords(self, paper: Paper) -> List[str]:
        """Extract keywords from paper title and abstract."""
        if not paper.title:
            logger.warning(f"Cannot extract keywords: paper {paper.identifier} has no title")
            return []

        # Prepare content for keyword extraction
        content = f"Title: {paper.title}"
        if paper.abstract:
            content += f"\nAbstract: {paper.abstract}"
        if paper.authors:
            content += f"\nAuthors: {', '.join(paper.authors[:3])}"  # First 3 authors

        prompt = f"""Extract 3-5 key technical terms from this computer science paper. 
Focus on specific technical concepts, methodologies, systems, algorithms, or research areas.
DO NOT include: author names, publication venues, years, dates, common words like "paper", "study", "research", "work", "method", "system", "approach".

Paper content:
{content}

Return only technical keywords separated by commas, no explanations."""

        try:
            logger.debug(f"Calling LLM to extract keywords for paper {paper.identifier}")
            response = await self.llm_client.chat_completion(
                messages=[{"role": "user", "content": prompt}], temperature=0.3
            )
            
            if not response or not response.strip():
                logger.warning(f"LLM returned empty response for keywords extraction (paper {paper.identifier})")
                return []

            keywords_text = response.strip()
            keywords = [kw.strip() for kw in keywords_text.split(",") if kw.strip()]

            # Simple cleaning - trust the LLM to do the filtering
            cleaned_keywords = [kw.strip().lower() for kw in keywords if kw.strip()]
            result = cleaned_keywords[:5]  # Limit to 5 keywords
            logger.debug(f"Extracted {len(result)} keywords for paper {paper.identifier}: {result}")
            return result

        except RuntimeError as e:
            # LLM not configured or other runtime errors
            logger.error(
                f"LLM configuration error for keywords extraction (paper {paper.identifier}): {e}"
            )
            raise  # Re-raise to let caller know LLM is not available
        except Exception as e:
            logger.exception(f"Failed to extract keywords for paper {paper.identifier}: {e}")
            return []


class PaperClusteringService:
    """Service for clustering papers into categories using LLM."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.llm_client = create_llm_client(settings)
        self.category_cache: Dict[str, str] = {}

    async def cluster_papers(
        self, papers: List[Paper], existing_categories: List[str] = None
    ) -> Dict[str, str]:
        """Cluster papers into categories and return paper_id -> category mapping."""
        if not papers:
            return {}

        # First, analyze all papers to determine good categories
        categories = await self._determine_categories(papers, existing_categories)

        # Then assign each paper to a category
        assignments = {}
        for paper in papers:
            category = await self._assign_paper_to_category(paper, categories)
            assignments[paper.identifier] = category

        return assignments

    async def _determine_categories(
        self, papers: List[Paper], existing_categories: List[str] = None
    ) -> List[str]:
        """Determine broad, distinct categories for papers based on OSDI/SOSP-style classification."""
        # Sample papers for category determination (max 20 to avoid token limits)
        sample_papers = papers[:20]

        paper_info = []
        for paper in sample_papers:
            info = f"Title: {paper.title}"
            if paper.abstract:
                info += (
                    f"\nAbstract: {paper.abstract[:200]}..."  # Truncate long abstracts
                )
            paper_info.append(info)

        # Build prompt with existing categories as reference
        existing_categories_text = ""
        if existing_categories:
            existing_categories_text = f"\n\nExisting categories in the system (use as reference):\n{', '.join(existing_categories)}"

        prompt = f"""Based on these computer science papers, suggest 6-8 broad, distinct categories that would effectively group them for a systems conference like OSDI or SOSP.

Guidelines:
- Use broad, high-level categories that can accommodate many papers over time
- Avoid overly specific subcategories (e.g., use "Distributed Systems" not "Consensus Algorithms")
- Ensure categories are mutually exclusive and cover different research domains
- Focus on systems and infrastructure topics

Suggested category style (use as inspiration):
- Operating Systems
- Distributed Systems  
- Storage Systems
- Networking
- Security and Privacy
- Machine Learning Systems
- Databases
- Performance and Optimization

{existing_categories_text}

Papers:
{chr(10).join(paper_info)}

Return only the category names, one per line, no explanations. Use clear, concise names."""

        try:
            response = await self.llm_client.chat_completion(
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,  # Slightly higher for more diverse suggestions
            )

            categories = [
                cat.strip() for cat in response.strip().split("\n") if cat.strip()
            ]

            # Clean up and validate categories
            cleaned_categories = []
            for cat in categories[:8]:  # Limit to 8 categories
                # Remove any numbering or bullets
                cat = cat.strip("0123456789.-• ")
                if cat and len(cat) > 2:  # Avoid very short categories
                    cleaned_categories.append(cat)

            # Ensure we have at least 4 categories
            if len(cleaned_categories) < 4:
                cleaned_categories.extend(self._get_fallback_categories())

            return cleaned_categories[:8]

        except Exception as e:
            logger.error(f"Failed to determine categories: {e}")
            return self._get_fallback_categories()

    def _get_fallback_categories(self) -> List[str]:
        """Fallback categories based on OSDI/SOSP conference topics."""
        return [
            "Operating Systems",
            "Distributed Systems",
            "Storage Systems",
            "Networking",
            "Security and Privacy",
            "Machine Learning Systems",
            "Databases",
            "Performance and Optimization",
        ]

    async def _assign_paper_to_category(
        self, paper: Paper, categories: List[str]
    ) -> str:
        """Assign a single paper to the most appropriate category."""
        if not paper.title:
            return categories[0] if categories else "other"

        content = f"Title: {paper.title}"
        if paper.abstract:
            content += f"\nAbstract: {paper.abstract}"

        categories_text = "\n".join(
            [f"{i + 1}. {cat}" for i, cat in enumerate(categories)]
        )

        prompt = f"""Given this computer science paper, assign it to the most appropriate category from the list below.

Paper:
{content}

Categories:
{categories_text}

Return only the category name (not the number), no explanations."""

        try:
            response = await self.llm_client.chat_completion(
                messages=[{"role": "user", "content": prompt}], temperature=0.1
            )

            assigned_category = response.strip().lower()
            logger.debug(f"LLM assigned category for paper {paper.identifier}: '{assigned_category}' (raw response: '{response.strip()}')")

            # Validate the response is one of our categories
            for cat in categories:
                if assigned_category == cat.lower() or assigned_category in cat.lower():
                    logger.debug(f"Matched category '{assigned_category}' to '{cat}' for paper {paper.identifier}")
                    return cat

            # If no match, return the first category as fallback
            fallback = categories[0] if categories else "other"
            logger.warning(f"No category match found for paper {paper.identifier}, using fallback: '{fallback}' (LLM response: '{assigned_category}')")
            return fallback

        except Exception as e:
            logger.error(f"Failed to assign category for paper {paper.identifier}: {e}")
            return categories[0] if categories else "other"


class PaperEnrichmentService:
    """Main service that orchestrates all enrichment tasks."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.abstract_service = AbstractEnrichmentService(settings)
        self.keyword_service = KeywordExtractionService(settings)
        self.clustering_service = PaperClusteringService(settings)

    async def enrich_paper(self, paper: Paper) -> EnrichmentResult:
        """Enrich a single paper with abstract, keywords, and category."""
        result = EnrichmentResult(paper=paper)

        try:
            # Enrich abstract
            async with self.abstract_service as service:
                result.abstract = await service.enrich_abstract(paper)

            # Extract keywords
            result.keywords = await self.keyword_service.extract_keywords(paper)

            # Note: Category assignment is done in batch for efficiency
            result.success = True

        except Exception as e:
            logger.error(f"Failed to enrich paper {paper.identifier}: {e}")
            result.success = False
            result.error = str(e)

        return result

    async def enrich_papers_batch(
        self, papers: List[Paper], fields: List[str] = None, force: bool = False
    ) -> List[EnrichmentResult]:
        """Enrich multiple papers efficiently with granular field control.

        Args:
            papers: List of papers to enrich
            fields: List of fields to enrich ['abstract', 'keywords', 'category']
            force: Force re-enrichment even if already enriched
        """
        if fields is None:
            fields = ["abstract", "keywords", "category"]

        results = []

        # Filter papers: skip only if paper has both keywords AND category (complete enrichment)
        # Otherwise, always execute full enrichment flow: abstract -> keywords -> category
        papers_to_enrich = []
        for paper in papers:
            # Check if paper has completed full enrichment (has keywords AND category)
            has_keywords = paper.keywords and len(paper.keywords) > 0
            has_category = paper.category is not None and paper.category.strip() != ""
            
            if has_keywords and has_category and not force:
                # Paper has completed enrichment, skip it
                logger.debug(f"Paper {paper.identifier} skipped (has keywords and category, force={force})")
                results.append(
                    EnrichmentResult(
                        paper=paper,
                        abstract=paper.abstract,
                        keywords=paper.keywords,
                        category=paper.category,
                        success=True,
                        error="Skipped - already fully enriched",
                        enriched_fields=[],
                    )
                )
                continue
            
            # Paper needs enrichment - always execute full flow for requested fields
            paper_needs_fields = []
            
            # Step 1: Always try to enrich abstract (if requested)
            if "abstract" in fields:
                if not paper.abstract or force:
                    paper_needs_fields.append("abstract")
            
            # Step 2: Always enrich keywords (if requested) unless paper has keywords AND category
            # Will use abstract if available, otherwise use title only
            if "keywords" in fields:
                if not has_keywords or force:
                    paper_needs_fields.append("keywords")
            
            # Step 3: Always enrich category (if requested) unless paper has keywords AND category
            # Will use abstract if available, otherwise use title only
            if "category" in fields:
                if not has_category or force:
                    paper_needs_fields.append("category")
            
            if paper_needs_fields:
                papers_to_enrich.append((paper, paper_needs_fields))
            else:
                # Create a result indicating the paper was skipped
                results.append(
                    EnrichmentResult(
                        paper=paper,
                        abstract=paper.abstract,
                        keywords=paper.keywords,
                        category=paper.category,
                        success=True,
                        error="Skipped - already enriched",
                        enriched_fields=[],
                    )
                )

        if not papers_to_enrich:
            return results

        # Process abstracts and keywords in parallel
        async with self.abstract_service as service:
            tasks = []
            for paper, paper_fields in papers_to_enrich:
                logger.debug(f"Task for {paper.identifier}: {paper_fields}")
                task = self._enrich_single_paper(paper, service, paper_fields, force)
                tasks.append(task)

            enrichment_results = await asyncio.gather(*tasks, return_exceptions=True)

            # Handle any exceptions
            for i, result in enumerate(enrichment_results):
                if isinstance(result, Exception):
                    paper, _ = papers_to_enrich[i]
                    logger.exception(f"Enrichment task failed for paper {paper.identifier}: {result}")
                    results.append(
                        EnrichmentResult(
                            paper=paper,
                            success=False,
                            error=str(result),
                            enriched_fields=[],
                        )
                    )
                else:
                    results.append(result)

        # Now assign categories in batch for papers that need it
        # Build mapping of paper identifiers to results that need categories
        papers_needing_categories = [
            paper for paper, fields in papers_to_enrich if "category" in fields
        ]
        papers_needing_category_ids = {paper.identifier for paper in papers_needing_categories}

        if papers_needing_categories:
            logger.debug(f"{len(papers_needing_categories)} papers need categories")
            # Get existing categories from all papers for reference
            existing_categories = await self._get_existing_categories()
            # Create papers with enriched abstracts for category assignment
            papers_for_category = []
            for result in results:
                if result.success and result.paper.identifier in papers_needing_category_ids:
                    # Use enriched abstract if available
                    paper_for_category = Paper(
                        identifier=result.paper.identifier,
                        title=result.paper.title,
                        authors=result.paper.authors,
                        venue=result.paper.venue,
                        year=result.paper.year,
                        url=result.paper.url,
                        doi=result.paper.doi,
                        source=result.paper.source,
                        abstract=result.abstract or result.paper.abstract,  # Use enriched abstract
                    )
                    papers_for_category.append(paper_for_category)
            
            if papers_for_category:
                category_assignments = await self.clustering_service.cluster_papers(
                    papers_for_category, existing_categories
                )
                for result in results:
                    if result.success and result.paper.identifier in papers_needing_category_ids:
                        assigned_category = category_assignments.get(
                            result.paper.identifier, "other"
                        )
                        result.category = assigned_category
                        if result.category:
                            result.enriched_fields.append("category")
                            logger.success(f"{result.paper.identifier}  category({result.category})")

        return results

    async def _get_existing_categories(self) -> List[str]:
        """Get existing categories from all papers in the system."""
        try:
            # Import here to avoid circular imports
            from ..storage import PaperStore

            store = PaperStore(self.settings)
            all_papers = store.list()

            # Extract unique categories
            categories = set()
            for paper in all_papers:
                if paper.category:
                    categories.add(paper.category)

            return list(categories)
        except Exception as e:
            logger.debug(f"Failed to get existing categories: {e}")
            return []

    async def _enrich_single_paper(
        self,
        paper: Paper,
        abstract_service: AbstractEnrichmentService,
        fields: List[str],
        force: bool = False,
    ) -> EnrichmentResult:
        """Enrich a single paper (used in batch processing)."""
        result = EnrichmentResult(paper=paper)
        enriched_items = []

        try:
            # Step 1: Enrich abstract
            if "abstract" in fields and (not paper.abstract or force):
                enriched_abstract = await abstract_service.enrich_abstract(paper)
                if enriched_abstract:
                    result.abstract = enriched_abstract
                    result.enriched_fields.append("abstract")
                    enriched_items.append("abstract")
                else:
                    result.abstract = paper.abstract
            else:
                result.abstract = paper.abstract

            # Step 2: Enrich keywords (use enriched abstract if available)
            if "keywords" in fields:
                original_abstract = paper.abstract
                paper.abstract = result.abstract or paper.abstract
                try:
                    enriched_keywords = await self.keyword_service.extract_keywords(paper)
                    paper.abstract = original_abstract
                    if enriched_keywords and len(enriched_keywords) > 0:
                        result.keywords = enriched_keywords
                        result.enriched_fields.append("keywords")
                        enriched_items.append(f"keywords({len(enriched_keywords)})")
                        logger.debug(f"Keywords for {paper.identifier}: {enriched_keywords}")
                    else:
                        result.keywords = paper.keywords
                except RuntimeError as e:
                    logger.error(f"LLM configuration error for keywords extraction (paper {paper.identifier}): {e}")
                    paper.abstract = original_abstract
                    raise
                except Exception as e:
                    logger.exception(f"Failed to extract keywords for paper {paper.identifier}: {e}")
                    paper.abstract = original_abstract
                    result.keywords = paper.keywords
            else:
                result.keywords = paper.keywords

            # Note: category is handled separately in batch
            result.category = paper.category

            result.success = True
            
            # Log summary for this paper (only if something was enriched)
            if enriched_items:
                logger.success(f"{paper.identifier}  {' '.join(enriched_items)}")

        except Exception as e:
            result.success = False
            result.error = str(e)

        return result


def get_category_color(category: str) -> str:
    """Generate a consistent color for a category based on its text hash.

    Uses HSL color space to ensure better color distribution and sufficient
    contrast with white text by maintaining a dark background.
    """
    if not category:
        return "#6c757d"  # Default gray

    # Create hash from category name
    hash_obj = hashlib.md5(category.lower().encode())
    hash_hex = hash_obj.hexdigest()

    # Use different parts of hash for HSL components to ensure better distribution
    # Hue: 0-360 degrees (use first 3 hex chars for better distribution)
    hue = int(hash_hex[0:3], 16) % 360

    # Saturation: 60-90% (avoid too gray or too saturated)
    saturation = 60 + (int(hash_hex[3:5], 16) % 30)

    # Lightness: 15-25% (dark enough for white text contrast)
    lightness = 15 + (int(hash_hex[5:7], 16) % 10)

    # Convert HSL to RGB
    def hsl_to_rgb(h, s, l):
        h = h / 360.0
        s = s / 100.0
        l = l / 100.0

        def hue_to_rgb(p, q, t):
            if t < 0:
                t += 1
            if t > 1:
                t -= 1
            if t < 1 / 6:
                return p + (q - p) * 6 * t
            if t < 1 / 2:
                return q
            if t < 2 / 3:
                return p + (q - p) * (2 / 3 - t) * 6
            return p

        if s == 0:
            r = g = b = l  # achromatic
        else:
            q = l * (1 + s) if l < 0.5 else l + s - l * s
            p = 2 * l - q
            r = hue_to_rgb(p, q, h + 1 / 3)
            g = hue_to_rgb(p, q, h)
            b = hue_to_rgb(p, q, h - 1 / 3)

        return (int(r * 255), int(g * 255), int(b * 255))

    r, g, b = hsl_to_rgb(hue, saturation, lightness)

    # Convert to hex color
    return f"#{r:02x}{g:02x}{b:02x}"
