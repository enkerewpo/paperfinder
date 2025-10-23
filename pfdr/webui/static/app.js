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
        this.refs.taskCount = document.getElementById("taskCount");
        this.refs.sourceCount = document.getElementById("sourceCount");
        this.refs.papersContainer = document.getElementById("papersContainer");
        this.refs.tasksContainer = document.getElementById("tasksContainer");
        this.refs.sourcesContainer = document.getElementById("sourcesContainer");
        this.refs.refreshButton = document.getElementById("refreshButton");

        this.refs.paperTemplate = document.getElementById("paperRowTemplate");
        this.refs.taskTemplate = document.getElementById("taskTemplate");
        this.refs.sourceTemplate = document.getElementById("sourceTemplate");

        this.refs.fetchForm = document.getElementById("fetchForm");
        this.refs.queryForm = document.getElementById("queryForm");
        this.refs.deleteForm = document.getElementById("deleteForm");
    }

    bindEvents() {
        this.refs.searchInput.addEventListener("input", () => this.onSearch());
        this.refs.searchScope.addEventListener("change", () => this.onSearch());
        this.refs.sortMode.addEventListener("change", () => this.onSearch());
        this.refs.strictToggle.addEventListener("change", () => this.onSearch());
        this.refs.refreshButton.addEventListener("click", () => this.refreshAll());

        this.refs.fetchForm.addEventListener("submit", async (event) => {
            event.preventDefault();
            await this.submitCommandForm(event.currentTarget, "/api/fetch", "POST");
        });

        this.refs.queryForm.addEventListener("submit", async (event) => {
            event.preventDefault();
            await this.submitCommandForm(event.currentTarget, "/api/query", "POST", (result, form) => {
                const output = form.querySelector("output");
                if (!result || !result.results?.length) {
                    output.value = "No matches returned.";
                    return;
                }

                const top = result.results.slice(0, 3).map((item) => {
                    const paper = item.paper || {};
                    const title = paper.title || "Untitled";
                    return `${title} (${item.score.toFixed(2)})`;
                });
                output.value = `Top ${result.results.length}: ${top.join(" • ")}`;
            });
        });

        this.refs.deleteForm.addEventListener("submit", async (event) => {
            event.preventDefault();
            await this.submitCommandForm(event.currentTarget, "/api/papers", "DELETE");
        });
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
            const sourceUrl = data.get("source_url")?.toString().trim();
            const targetName = data.get("target_name")?.toString().trim();
            const allTargets = data.get("all_targets");
            const choices = [sourceUrl, targetName, allTargets === "on"].filter((value) => {
                if (typeof value === "boolean") {
                    return value;
                }
                return Boolean(value);
            });
            if (!choices.length) {
                return { ok: false, message: "Choose one source option." };
            }
            if (choices.length > 1) {
                return { ok: false, message: "Choose only one source option." };
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
            this.loadTasks(),
            this.loadSources()
        ]);
        this.onSearch();
        this.updateSummary();
    }

    async loadPapers() {
        try {
            const response = await fetch("/api/papers?limit=2000");
            if (!response.ok) {
                throw new Error(`Failed to load papers (${response.status})`);
            }
            const payload = await response.json();
            this.papers = payload.papers || [];
            this.authors = this.collectAuthors(this.papers);
        } catch (error) {
            console.error(error);
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

    async loadSources() {
        try {
            const response = await fetch("/api/sources");
            if (!response.ok) {
                throw new Error(`Failed to load sources (${response.status})`);
            }
            const payload = await response.json();
            this.renderSources(payload.sources || []);
        } catch (error) {
            console.error(error);
            this.renderSources([]);
        }
    }

    onSearch() {
        this.state.query = this.refs.searchInput.value.trim();
        this.state.scope = this.refs.searchScope.value;
        this.state.sort = this.refs.sortMode.value;
        this.state.strict = this.refs.strictToggle.checked;

        this.filtered = this.filterAndScorePapers();
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
        const container = this.refs.papersContainer;
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
            const tags = node.querySelector(".paper-tags");
            const copy = node.querySelector(".icon-button");

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

            tags.innerHTML = "";
            if (paper.year) {
                tags.appendChild(this.tagNode(paper.year.toString()));
            }
            if (paper.venue) {
                tags.appendChild(this.tagNode(paper.venue));
            }
            if (paper.source && paper.source !== paper.venue) {
                tags.appendChild(this.tagNode(paper.source));
            }
            if (score && this.state.query) {
                tags.appendChild(this.tagNode(`score ${score.toFixed(2)}`));
            }

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

        tasks.slice(0, 6).forEach((task) => {
            const node = this.refs.taskTemplate.content.cloneNode(true);
            node.querySelector(".task-type").textContent = task.task_type || "task";
            node.querySelector(".task-status").textContent = task.status || "";
            node.querySelector(".task-updated").textContent = this.timeAgo(task.updated_at);
            fragment.appendChild(node);
        });

        this.refs.tasksContainer.appendChild(fragment);
        this.refs.taskCount.textContent = tasks.length.toString();
    }

    renderSources(sources) {
        this.refs.sourcesContainer.innerHTML = "";
        const fragment = document.createDocumentFragment();

        sources.forEach((source) => {
            const node = this.refs.sourceTemplate.content.cloneNode(true);
            node.querySelector(".source-name").textContent = source.name || source.source_url || "source";
            node.querySelector(".source-url").textContent = source.source_url || source.url || "—";
            fragment.appendChild(node);
        });

        this.refs.sourcesContainer.appendChild(fragment);
        this.refs.sourceCount.textContent = sources.length.toString();
    }

    updateSummary() {
        this.refs.paperCount.textContent = this.papers.length.toString();
        this.refs.authorCount.textContent = this.authors.size.toString();
    }

    updateMeta() {
        const visible = this.filtered.length;
        const total = this.papers.length;
        this.refs.resultMeta.textContent = `Showing ${visible} of ${total}`;
    }

    collectAuthors(papers) {
        const authors = new Set();
        papers.forEach((paper) => {
            (paper.authors || []).forEach((author) => authors.add(author));
        });
        return authors;
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
