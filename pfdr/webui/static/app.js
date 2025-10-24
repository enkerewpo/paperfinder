class PFDRDashboard {
    constructor() {
        this.papers = [];
        this.filtered = [];
        this.authors = new Set();
        this.state = {
            query: "",
            scope: "all",
            strict: false,
            sort: "relevance"
        };
        this.refs = {};
    }

    async init() {
        this.cacheRefs();
        this.bindEvents();
        await this.refreshAll();
    }

    cacheRefs() {
        this.refs.searchInput = document.getElementById("searchInput");
        this.refs.searchScope = document.getElementById("searchScope");
        this.refs.sortMode = document.getElementById("sortMode");
        this.refs.strictToggle = document.getElementById("strictToggle");
        this.refs.resultMeta = document.getElementById("resultMeta");
        this.refs.paperCount = document.getElementById("paperCount");
        this.refs.authorCount = document.getElementById("authorCount");
        this.refs.papersContainer = document.getElementById("papersContainer");
        this.refs.tasksContainer = document.getElementById("tasksContainer");
        this.refs.refreshButton = document.getElementById("refreshButton");

        this.refs.paperTemplate = document.getElementById("paperRowTemplate");
        this.refs.taskTemplate = document.getElementById("taskTemplate");

        this.refs.fetchForm = document.getElementById("fetchForm");
        this.refs.queryForm = document.getElementById("queryForm");
    }

    bindEvents() {
        this.refs.searchInput.addEventListener("input", () => this.onSearch());
        this.refs.searchScope.addEventListener("change", () => this.onSearch());
        this.refs.sortMode.addEventListener("change", () => this.onSearch());
        this.refs.strictToggle.addEventListener("change", () => this.onSearch());
        
        if (this.refs.refreshButton) {
            this.refs.refreshButton.addEventListener("click", () => this.refreshAll());
        }

        this.refs.fetchForm.addEventListener("submit", async (event) => {
            event.preventDefault();
            await this.submitCommandForm(event.currentTarget, "/api/fetch", "POST");
        });

        this.refs.queryForm.addEventListener("submit", async (event) => {
            event.preventDefault();
            await this.submitQueryForm(event.currentTarget);
        });
    }

    async submitQueryForm(form) {
        const submitButton = form.querySelector("button[type='submit']");
        const output = form.querySelector("output");
        const promptTextarea = form.querySelector("textarea[name='prompt']");
        
        if (output) {
            output.value = "Preparing query...";
        }

        if (submitButton) {
            submitButton.disabled = true;
            submitButton.textContent = "Querying...";
        }

        // Start timer
        const startTime = Date.now();
        const timerInterval = setInterval(() => {
            const elapsed = Math.floor((Date.now() - startTime) / 1000);
            if (output) {
                output.value = `Querying AI... ${elapsed}s elapsed`;
            }
        }, 1000);

        try {
            const validation = this.validateForm(form);
            if (!validation.ok) {
                if (output) {
                    output.value = validation.message;
                }
                return;
            }

            const payload = this.buildPayload(form);
            if (!payload) {
                if (output) {
                    output.value = "Fill in the prompt before submitting.";
                }
                return;
            }

            const response = await fetch("/api/query", {
                method: "POST",
                headers: {
                    "Content-Type": "application/x-www-form-urlencoded"
                },
                body: payload
            });

            if (!response.ok) {
                const errorText = await response.text();
                throw new Error(errorText || `Request failed (${response.status})`);
            }

            const result = await response.json();
            this.displayQueryResults(result, output, promptTextarea);

        } catch (error) {
            if (output) {
                output.value = error.message || "Query failed.";
            }
        } finally {
            clearInterval(timerInterval);
            if (submitButton) {
                submitButton.disabled = false;
                submitButton.textContent = "Run query";
            }
        }
    }

    displayQueryResults(result, output, promptTextarea) {
        if (!result || !result.results?.length) {
            output.value = "No matches returned.";
            return;
        }

        // Clear the main paper list and show query results
        this.showQueryResults(result.results, promptTextarea.value);
        
        // Update output with summary
        const top3 = result.results.slice(0, 3).map((item) => {
            const paper = item.paper || {};
            const title = paper.title || "Untitled";
            return `${title} (${item.score.toFixed(2)})`;
        });
        output.value = `Found ${result.results.length} results. Top 3: ${top3.join(" • ")}`;
    }

    showQueryResults(results, query) {
        console.log("Showing query results:", results.length, "results for query:", query);
        const container = this.refs.papersContainer;
        if (!container) {
            console.error("papersContainer not found in showQueryResults!");
            return;
        }
        container.innerHTML = "";

        // Add query header
        const header = document.createElement("div");
        header.className = "query-results-header";
        header.innerHTML = `
            <h3>AI Query Results</h3>
            <p class="query-text">"${query}"</p>
            <p class="result-count">${results.length} papers found</p>
        `;
        container.appendChild(header);

        // Render results
        const fragment = document.createDocumentFragment();
        results.forEach((item, index) => {
            const paper = item.paper;
            const node = this.refs.paperTemplate.content.cloneNode(true);
            const article = node.querySelector(".paper-row");
            const title = node.querySelector(".paper-title");
            const authors = node.querySelector(".paper-authors");
            const year = node.querySelector(".paper-year");
            const venue = node.querySelector(".paper-venue");
            const scoreEl = node.querySelector(".paper-score");
            const copy = node.querySelector("button[title='Copy citation']");

            // Add ranking number
            article.classList.add("query-result");
            article.setAttribute("data-rank", index + 1);

            title.textContent = paper.title || "Untitled paper";
            if (paper.url) {
                title.href = paper.url;
            } else if (paper.doi) {
                title.href = `https://doi.org/${paper.doi}`;
            } else {
                title.href = "#";
            }

            const authorList = Array.isArray(paper.authors) ? paper.authors.join(", ") : "";
            authors.textContent = authorList || "Unknown authors";

            if (paper.year) {
                year.textContent = paper.year.toString();
            } else {
                year.style.display = "none";
            }

            if (paper.venue) {
                venue.textContent = paper.venue;
            } else {
                venue.style.display = "none";
            }

            // Add AI score
            scoreEl.textContent = item.score.toFixed(3);
            scoreEl.title = item.reason || "No reason provided";
            
            // Add reason as a visible tag
            if (item.reason) {
                const reasonTag = document.createElement("span");
                reasonTag.className = "reason-tag";
                reasonTag.textContent = "AI Reason";
                reasonTag.addEventListener("click", (e) => {
                    e.stopPropagation();
                    this.showReasonPopup(item.reason, paper.title);
                });
                article.querySelector(".paper-meta").appendChild(reasonTag);
            }

            if (copy) {
                copy.addEventListener("click", () => {
                    const citation = this.buildCitation(paper);
                    if (navigator.clipboard && navigator.clipboard.writeText) {
                        navigator.clipboard.writeText(citation)
                            .then(() => this.markCopyButton(copy, "✓"))
                            .catch(() => {
                                this.fallbackCopy(citation);
                                this.markCopyButton(copy, "✓");
                            });
                    } else {
                        this.fallbackCopy(citation);
                        this.markCopyButton(copy, "✓");
                    }
                });
            }

            fragment.appendChild(node);
        });

        container.appendChild(fragment);
    }

    showReasonPopup(reason, paperTitle) {
        // Remove existing popup if any
        const existingPopup = document.querySelector('.reason-popup-overlay');
        if (existingPopup) {
            existingPopup.remove();
        }

        // Create overlay
        const overlay = document.createElement('div');
        overlay.className = 'reason-popup-overlay';
        overlay.addEventListener('click', () => this.closeReasonPopup());

        // Create popup
        const popup = document.createElement('div');
        popup.className = 'reason-popup';
        popup.innerHTML = `
            <div class="reason-popup-header">
                <h3 class="reason-popup-title">AI Reasoning</h3>
                <button class="reason-popup-close" type="button">&times;</button>
            </div>
            <div class="reason-popup-content">
                <p><strong>Paper:</strong> ${paperTitle}</p>
                <p><strong>Reason:</strong></p>
                <p>${reason}</p>
            </div>
        `;

        // Add close button event
        popup.querySelector('.reason-popup-close').addEventListener('click', () => this.closeReasonPopup());

        // Add to DOM
        overlay.appendChild(popup);
        document.body.appendChild(overlay);

        // Prevent popup clicks from closing
        popup.addEventListener('click', (e) => e.stopPropagation());
    }

    closeReasonPopup() {
        const popup = document.querySelector('.reason-popup-overlay');
        if (popup) {
            popup.remove();
        }
    }

    async submitCommandForm(form, endpoint, method, onSuccess) {
        const submitButton = form.querySelector("button[type='submit']");
        const output = form.querySelector("output");
        if (output) {
            output.value = "Running…";
        }

        if (submitButton) {
            submitButton.disabled = true;
        }

        try {
            const validation = this.validateForm(form);
            if (!validation.ok) {
                if (output) {
                    output.value = validation.message;
                }
                return;
            }

            const payload = this.buildPayload(form);
            if (!payload) {
                if (output) {
                    output.value = "Fill one option before submitting.";
                }
                return;
            }

            const response = await fetch(endpoint, {
                method,
                headers: {
                    "Content-Type": "application/x-www-form-urlencoded"
                },
                body: payload
            });

            if (!response.ok) {
                const errorText = await response.text();
                throw new Error(errorText || `Request failed (${response.status})`);
            }

            const result = await response.json();
            if (onSuccess) {
                onSuccess(result, form);
            } else if (output) {
                output.value = this.stringifyResult(result);
            }

            await this.refreshAll();
        } catch (error) {
            if (output) {
                output.value = error.message || "Command failed.";
            }
        } finally {
            if (submitButton) {
                submitButton.disabled = false;
            }
        }
    }

    validateForm(form) {
        const id = form.id;
        const data = new FormData(form);

        if (id === "fetchForm") {
            const url = data.get("url")?.toString().trim();
            const name = data.get("name")?.toString().trim();
            
            if (!url || !name) {
                return { ok: false, message: "Please fill in both URL and Name fields." };
            }
        }

        if (id === "deleteForm") {
            const pattern = data.get("pattern")?.toString().trim();
            const sourceUrl = data.get("source_url")?.toString().trim();
            const targetName = data.get("target_name")?.toString().trim();
            const filled = [pattern, sourceUrl, targetName].filter(Boolean);
            if (filled.length > 1) {
                return { ok: false, message: "Select only one deletion selector." };
            }
            if (!filled.length) {
                return { ok: false, message: "Fill one selector (pattern, source, or target)." };
            }
        }

        if (id === "queryForm") {
            const prompt = data.get("prompt")?.toString().trim();
            if (!prompt) {
                return { ok: false, message: "Prompt cannot be empty." };
            }
        }

        return { ok: true };
    }

    buildPayload(form) {
        const formData = new FormData(form);
        const params = new URLSearchParams();
        let hasValue = false;

        for (const [key, value] of formData.entries()) {
            if (value instanceof File) {
                continue;
            }

            if (value === "" || value === null) {
                continue;
            }

            if (value === "on") {
                params.append(key, "true");
                hasValue = true;
            } else {
                params.append(key, value);
                hasValue = true;
            }
        }

        return hasValue ? params : null;
    }

    stringifyResult(result) {
        if (!result) {
            return "";
        }

        if (result.message) {
            return result.message;
        }

        const summary = Object.entries(result)
            .map(([k, v]) => `${k}: ${typeof v === "object" ? JSON.stringify(v) : v}`)
            .join(" • ");
        return summary.slice(0, 220);
    }


    async refreshAll() {
        await Promise.all([
            this.loadPapers(),
            this.loadTasks()
        ]);
        this.onSearch();
        this.updateSummary();
    }

    async loadPapers() {
        try {
            console.log("Loading papers...");
            const response = await fetch("/api/papers?limit=2000");
            if (!response.ok) {
                throw new Error(`Failed to load papers (${response.status})`);
            }
            const payload = await response.json();
            this.papers = payload.papers || [];
            this.authors = this.collectAuthors(this.papers);
            console.log(`Loaded ${this.papers.length} papers`);
        } catch (error) {
            console.error("Error loading papers:", error);
            this.papers = [];
        }
    }

    async loadTasks() {
        try {
            const response = await fetch("/api/tasks");
            if (!response.ok) {
                throw new Error(`Failed to load tasks (${response.status})`);
            }
            const payload = await response.json();
            this.renderTasks(payload.tasks || []);
        } catch (error) {
            console.error(error);
            this.renderTasks([]);
        }
    }

    onSearch() {
        this.state.query = this.refs.searchInput.value.trim();
        this.state.scope = this.refs.searchScope.value;
        this.state.sort = this.refs.sortMode.value;
        this.state.strict = this.refs.strictToggle.checked;

        console.log("Search state:", this.state);
        console.log("Total papers:", this.papers.length);
        
        this.filtered = this.filterAndScorePapers();
        console.log("Filtered papers:", this.filtered.length);
        
        this.renderPapers();
        this.updateMeta();
    }

    filterAndScorePapers() {
        const tokens = this.state.query
            ? this.state.query.toLowerCase().split(/\s+/).filter(Boolean)
            : [];

        const entries = this.papers.map((paper) => {
            const score = this.evaluatePaper(paper, tokens, this.state.scope, this.state.strict);
            return { paper, score };
        });

        const filtered = tokens.length
            ? entries.filter(({ score }) => score > (this.state.strict ? 0 : 0.15))
            : entries;

        const sorter = this.getSorter(this.state.sort, tokens.length > 0);
        return filtered.sort(sorter);
    }

    evaluatePaper(paper, tokens, scope, strict) {
        if (!tokens.length) {
            return 1;
        }

        const fields = this.pickFields(paper, scope);
        if (!fields.length) {
            return 0;
        }

        let best = 0;
        for (const text of fields) {
            if (!text) {
                continue;
            }
            const normalized = text.toLowerCase();
            const score = strict
                ? this.strictScore(normalized, tokens)
                : this.fuzzyTokensScore(normalized, tokens);
            if (score > best) {
                best = score;
            }
        }
        return best;
    }

    pickFields(paper, scope) {
        switch (scope) {
            case "title":
                return [paper.title];
            case "authors":
                return [paper.authors?.join(" ")];
            case "venue":
                return [paper.venue, paper.source];
            case "abstract":
                return [paper.abstract];
            case "all":
            default:
                return [
                    paper.title,
                    paper.authors?.join(" "),
                    paper.venue,
                    paper.abstract,
                    paper.doi,
                    paper.identifier,
                    paper.source
                ];
        }
    }

    strictScore(text, tokens) {
        for (const token of tokens) {
            if (!text.includes(token)) {
                return 0;
            }
        }
        return 1;
    }

    fuzzyTokensScore(text, tokens) {
        let total = 0;
        for (const token of tokens) {
            total += this.fuzzyScore(text, token);
        }
        return total / tokens.length;
    }

    fuzzyScore(text, token) {
        if (!token) {
            return 1;
        }
        if (text.includes(token)) {
            return 1;
        }

        const words = text.split(/\s+/);
        let best = 0;

        for (const word of words) {
            if (!word) {
                continue;
            }
            const dist = this.levenshtein(word, token);
            const denom = Math.max(word.length, token.length);
            const similarity = 1 - dist / denom;
            if (similarity > best) {
                best = similarity;
            }
            if (best > 0.9) {
                return best;
            }
        }

        const sequential = this.sequentialScore(text, token);
        return Math.max(best, sequential * 0.85);
    }

    sequentialScore(text, token) {
        let score = 0;
        let index = -1;
        for (const char of token) {
            const found = text.indexOf(char, index + 1);
            if (found === -1) {
                return score / token.length;
            }
            const gap = found - index;
            score += gap <= 1 ? 1.2 : 1 / gap;
            index = found;
        }
        return Math.min(score / token.length, 1);
    }

    levenshtein(a, b) {
        const matrix = Array.from({ length: a.length + 1 }, () => new Array(b.length + 1).fill(0));

        for (let i = 0; i <= a.length; i++) {
            matrix[i][0] = i;
        }

        for (let j = 0; j <= b.length; j++) {
            matrix[0][j] = j;
        }

        for (let i = 1; i <= a.length; i++) {
            for (let j = 1; j <= b.length; j++) {
                const cost = a[i - 1] === b[j - 1] ? 0 : 1;
                matrix[i][j] = Math.min(
                    matrix[i - 1][j] + 1,
                    matrix[i][j - 1] + 1,
                    matrix[i - 1][j - 1] + cost
                );
            }
        }

        return matrix[a.length][b.length];
    }

    getSorter(mode, useScore) {
        switch (mode) {
            case "year_desc":
                return (a, b) => (b.paper.year || 0) - (a.paper.year || 0);
            case "year_asc":
                return (a, b) => (a.paper.year || 0) - (b.paper.year || 0);
            case "title":
                return (a, b) => {
                    const ta = (a.paper.title || "").toLowerCase();
                    const tb = (b.paper.title || "").toLowerCase();
                    if (ta < tb) return -1;
                    if (ta > tb) return 1;
                    return 0;
                };
            case "relevance":
            default:
                if (useScore) {
                    return (a, b) => b.score - a.score;
                }
                return (a, b) => (b.paper.year || 0) - (a.paper.year || 0);
        }
    }

    renderPapers() {
        console.log("Rendering papers...", this.filtered.length);
        const container = this.refs.papersContainer;
        if (!container) {
            console.error("papersContainer not found!");
            return;
        }
        container.innerHTML = "";

        if (!this.filtered.length) {
            const empty = document.createElement("div");
            empty.className = "empty-state";
            empty.textContent = this.state.query
                ? "No papers match the current search."
                : "No papers ingested yet.";
            container.appendChild(empty);
            return;
        }

        const fragment = document.createDocumentFragment();
        for (const { paper, score } of this.filtered) {
            const node = this.refs.paperTemplate.content.cloneNode(true);
            const article = node.querySelector(".paper-row");
            const title = node.querySelector(".paper-title");
            const authors = node.querySelector(".paper-authors");
            const year = node.querySelector(".paper-year");
            const venue = node.querySelector(".paper-venue");
            const scoreEl = node.querySelector(".paper-score");
            const copy = node.querySelector("button[title='Copy citation']");

            title.textContent = paper.title || "Untitled paper";
            if (paper.url) {
                title.href = paper.url;
            } else if (paper.doi) {
                title.href = `https://doi.org/${paper.doi}`;
            } else {
                title.href = "#";
            }

            const authorList = Array.isArray(paper.authors) ? paper.authors.join(", ") : "";
            authors.textContent = authorList || "Unknown authors";

            if (paper.year) {
                year.textContent = paper.year.toString();
            } else {
                year.style.display = "none";
            }

            if (paper.venue) {
                venue.textContent = paper.venue;
            } else {
                venue.style.display = "none";
            }

            if (score && this.state.query) {
                scoreEl.textContent = score.toFixed(3);
            } else {
                scoreEl.style.display = "none";
            }

            if (copy) {
                copy.addEventListener("click", () => {
                    const citation = this.buildCitation(paper);
                    if (navigator.clipboard && navigator.clipboard.writeText) {
                        navigator.clipboard.writeText(citation)
                            .then(() => this.markCopyButton(copy, "✓"))
                            .catch(() => {
                                this.fallbackCopy(citation);
                                this.markCopyButton(copy, "✓");
                            });
                    } else {
                        this.fallbackCopy(citation);
                        this.markCopyButton(copy, "✓");
                    }
                });
            }

            fragment.appendChild(node);
        }

        container.appendChild(fragment);
    }

    tagNode(text) {
        const span = document.createElement("span");
        span.textContent = text;
        return span;
    }

    buildCitation(paper) {
        const authors = Array.isArray(paper.authors) && paper.authors.length
            ? paper.authors.join(", ")
            : "Unknown";
        const title = paper.title || "Untitled";
        const year = paper.year || "n.d.";
        const venue = paper.venue || paper.source || "";
        const doi = paper.doi ? `doi:${paper.doi}` : "";
        return `${authors} (${year}). ${title}. ${venue}. ${doi}`.trim();
    }

    fallbackCopy(text) {
        const textarea = document.createElement("textarea");
        textarea.value = text;
        textarea.style.position = "fixed";
        textarea.style.top = "-9999px";
        document.body.appendChild(textarea);
        textarea.focus();
        textarea.select();
        try {
            document.execCommand("copy");
        } catch (error) {
            console.warn("Fallback copy failed", error);
        }
        document.body.removeChild(textarea);
    }

    markCopyButton(button, temporaryText) {
        const original = button.textContent;
        button.textContent = temporaryText;
        setTimeout(() => {
            button.textContent = original;
        }, 1200);
    }

    renderTasks(tasks) {
        this.refs.tasksContainer.innerHTML = "";
        const fragment = document.createDocumentFragment();

        tasks.slice(0, 5).forEach((task) => {
            const node = this.refs.taskTemplate.content.cloneNode(true);
            const title = node.querySelector(".task-title");
            const description = node.querySelector(".task-description");
            const meta = node.querySelector(".task-meta");
            const status = node.querySelector(".task-status");
            
            if (title) title.textContent = task.task_type || "task";
            if (description) description.textContent = task.description || "";
            if (meta) meta.textContent = this.timeAgo(task.updated_at);
            if (status) {
                status.textContent = task.status || "";
                status.className = `badge task-status badge-${task.status || 'secondary'}`;
            }
            
            fragment.appendChild(node);
        });

        this.refs.tasksContainer.appendChild(fragment);
    }

    updateSummary() {
        this.refs.paperCount.textContent = `${this.papers.length} papers`;
        this.refs.authorCount.textContent = `${this.authors.size} authors`;
    }

    collectAuthors(papers) {
        const authors = new Set();
        papers.forEach((paper) => {
            (paper.authors || []).forEach((author) => authors.add(author));
        });
        return authors;
    }

    updateMeta() {
        const visible = this.filtered.length;
        const total = this.papers.length;
        this.refs.resultMeta.textContent = `${visible} results`;
    }

    timeAgo(timestamp) {
        if (!timestamp) {
            return "";
        }
        const now = new Date();
        const then = new Date(timestamp);
        const diff = now - then;
        const minutes = Math.floor(diff / 60000);
        if (minutes < 1) {
            return "just now";
        }
        if (minutes < 60) {
            return `${minutes}m ago`;
        }
        const hours = Math.floor(minutes / 60);
        if (hours < 24) {
            return `${hours}h ago`;
        }
        const days = Math.floor(hours / 24);
        return `${days}d ago`;
    }
}

document.addEventListener("DOMContentLoaded", () => {
    const dashboard = new PFDRDashboard();
    dashboard.init().catch((error) => console.error("Failed to initialise dashboard", error));
});
