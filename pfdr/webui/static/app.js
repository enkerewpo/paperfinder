class PFDRDashboard {
    constructor() {
        this.papers = [];
        this.filtered = [];
        this.authors = new Set();
        this.categories = [];
        this.keywords = [];
        this.state = {
            query: "",
            scope: "all",
            strict: false,
            sort: "relevance",
            category: "",
            keyword: ""
        };
        this.refs = {};
        this.charts = {};
    }

    async init() {
        this.cacheRefs();
        this.bindEvents();
        await this.refreshAll();
    }

    cacheRefs() {
        this.refs.searchInput = document.getElementById("searchInput");
        this.refs.searchScope = document.getElementById("searchScope");
        this.refs.categoryFilter = document.getElementById("categoryFilter");
        this.refs.sortMode = document.getElementById("sortMode");
        this.refs.strictToggle = document.getElementById("strictToggle");
        this.refs.resultMeta = document.getElementById("resultMeta");
        this.refs.paperCount = document.getElementById("paperCount");
        this.refs.authorCount = document.getElementById("authorCount");
        this.refs.papersContainer = document.getElementById("papersContainer");
        this.refs.categoriesContainer = document.getElementById("categoriesContainer");
        this.refs.refreshButton = document.getElementById("refreshButton");
        this.refs.showChartBtn = document.getElementById("showChartBtn");
        this.refs.chartContainer = document.getElementById("chartContainer");

        this.refs.paperTemplate = document.getElementById("paperRowTemplate");
        this.refs.categoryTemplate = document.getElementById("categoryTemplate");

        this.refs.fetchForm = document.getElementById("fetchForm");
        this.refs.queryForm = document.getElementById("queryForm");
        this.refs.enrichForm = document.getElementById("enrichForm");
    }

    bindEvents() {
        this.refs.searchInput.addEventListener("input", () => this.onSearch());
        this.refs.searchScope.addEventListener("change", () => this.onSearch());
        this.refs.categoryFilter.addEventListener("change", () => this.onSearch());
        this.refs.sortMode.addEventListener("change", () => this.onSearch());
        this.refs.strictToggle.addEventListener("change", () => this.onSearch());
        
        if (this.refs.refreshButton) {
            this.refs.refreshButton.addEventListener("click", () => this.refreshAll());
        }

        if (this.refs.showChartBtn) {
            this.refs.showChartBtn.addEventListener("click", () => this.toggleCharts());
        }

        this.refs.fetchForm.addEventListener("submit", async (event) => {
            event.preventDefault();
            await this.submitCommandForm(event.currentTarget, "/api/fetch", "POST");
        });

        this.refs.queryForm.addEventListener("submit", async (event) => {
            event.preventDefault();
            await this.submitQueryForm(event.currentTarget);
        });

        this.refs.enrichForm.addEventListener("submit", async (event) => {
            event.preventDefault();
            await this.submitEnrichForm(event.currentTarget);
        });
    }

    async submitEnrichForm(form) {
        const submitButton = form.querySelector("button[type='submit']");
        
        if (submitButton) {
            submitButton.disabled = true;
            submitButton.textContent = "Enriching...";
        }

        try {
            const formData = new FormData(form);
            formData.append("enrich_abstracts", document.getElementById("enrichAbstracts").checked);
            formData.append("extract_keywords", document.getElementById("extractKeywords").checked);
            formData.append("cluster_papers", document.getElementById("clusterPapers").checked);

            const response = await fetch("/api/enrich", {
                method: "POST",
                body: formData
            });

            if (!response.ok) {
                const errorText = await response.text();
                throw new Error(errorText || `Request failed (${response.status})`);
            }

            const result = await response.json();
            alert(`Enrichment completed: ${result.message}`);
            
            // Refresh data
            await this.refreshAll();

        } catch (error) {
            alert(`Enrichment failed: ${error.message}`);
        } finally {
            if (submitButton) {
                submitButton.disabled = false;
                submitButton.textContent = "Enrich Papers";
            }
        }
    }

    toggleCharts() {
        const container = this.refs.chartContainer;
        const btn = this.refs.showChartBtn;
        
        if (container.style.display === "none") {
            container.style.display = "block";
            btn.textContent = "Hide Chart";
            this.renderCharts();
        } else {
            container.style.display = "none";
            btn.textContent = "Chart";
        }
    }

    async renderCharts() {
        // Category chart
        const categoryCtx = document.getElementById("categoryChart");
        if (categoryCtx && this.categories.length > 0) {
            if (this.charts.category) {
                this.charts.category.destroy();
            }
            
            this.charts.category = new Chart(categoryCtx, {
                type: 'pie',
                data: {
                    labels: this.categories.map(c => c.category),
                    datasets: [{
                        data: this.categories.map(c => c.count),
                        backgroundColor: [
                            '#FF6384', '#36A2EB', '#FFCE56', '#4BC0C0',
                            '#9966FF', '#FF9F40', '#FF6384', '#C9CBCF'
                        ]
                    }]
                },
                options: {
                    responsive: true,
                    plugins: {
                        title: {
                            display: true,
                            text: 'Paper Categories'
                        },
                        legend: {
                            position: 'bottom'
                        }
                    }
                }
            });
        }

        // Keyword chart
        const keywordCtx = document.getElementById("keywordChart");
        if (keywordCtx && this.keywords.length > 0) {
            if (this.charts.keyword) {
                this.charts.keyword.destroy();
            }
            
            const topKeywords = this.keywords.slice(0, 10);
            this.charts.keyword = new Chart(keywordCtx, {
                type: 'bar',
                data: {
                    labels: topKeywords.map(k => k.keyword),
                    datasets: [{
                        label: 'Frequency',
                        data: topKeywords.map(k => k.count),
                        backgroundColor: '#36A2EB'
                    }]
                },
                options: {
                    responsive: true,
                    plugins: {
                        title: {
                            display: true,
                            text: 'Top Keywords'
                        }
                    },
                    scales: {
                        y: {
                            beginAtZero: true
                        }
                    }
                }
            });
        }
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
            const category = node.querySelector(".paper-category");
            const keywords = node.querySelector(".paper-keywords");
            const abstract = node.querySelector(".paper-abstract");
            const scoreEl = node.querySelector(".paper-score");
            const copy = node.querySelector("button[title='Copy citation']");
            const abstractBtn = node.querySelector("button[title='Toggle abstract']");

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

            if (paper.category) {
                category.textContent = paper.category;
                // Apply color from API
                if (paper.category_color) {
                    category.style.setProperty('background-color', paper.category_color, 'important');
                    category.style.setProperty('color', '#ffffff', 'important');
                }
            } else {
                category.style.display = "none";
            }

            // Keywords
            if (paper.keywords && paper.keywords.length > 0) {
                keywords.innerHTML = "";
                paper.keywords.forEach(keyword => {
                    const keywordEl = document.createElement("span");
                    keywordEl.className = "badge bg-light text-dark me-1";
                    keywordEl.textContent = keyword;
                    keywords.appendChild(keywordEl);
                });
            } else {
                keywords.style.display = "none";
            }

            // Abstract
            if (paper.abstract) {
                abstract.textContent = paper.abstract;
                abstractBtn.style.display = "block";
                abstractBtn.addEventListener("click", () => {
                    if (abstract.style.display === "none") {
                        abstract.style.display = "block";
                    } else {
                        abstract.style.display = "none";
                    }
                });
            } else {
                abstractBtn.style.display = "none";
            }

            scoreEl.textContent = item.score.toFixed(2);

            copy.addEventListener("click", () => {
                const citation = `${paper.title} (${paper.year || 'n.d.'})`;
                navigator.clipboard.writeText(citation).then(() => {
                    // Visual feedback
                    const originalText = copy.innerHTML;
                    copy.innerHTML = "✓";
                    setTimeout(() => {
                        copy.innerHTML = originalText;
                    }, 1000);
                });
            });

            fragment.appendChild(node);
        });

        container.appendChild(fragment);
    }

    async submitCommandForm(form, endpoint, method = "POST") {
        const submitButton = form.querySelector("button[type='submit']");
        
        if (submitButton) {
            submitButton.disabled = true;
            submitButton.textContent = "Processing...";
        }

        try {
            const validation = this.validateForm(form);
            if (!validation.ok) {
                alert(validation.message);
                return;
            }

            const payload = this.buildPayload(form);
            if (!payload) {
                alert("Please fill in all required fields.");
                return;
            }

            const response = await fetch(endpoint, {
                method: method,
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
            alert(result.message || "Operation completed successfully");
            
            // Refresh data
            await this.refreshAll();

        } catch (error) {
            alert(`Operation failed: ${error.message}`);
        } finally {
            if (submitButton) {
                submitButton.disabled = false;
                submitButton.textContent = "Submit";
            }
        }
    }

    validateForm(form) {
        const requiredFields = form.querySelectorAll("[required]");
        for (const field of requiredFields) {
            if (!field.value.trim()) {
                return {
                    ok: false,
                    message: `Please fill in the ${field.name || field.id} field.`
                };
            }
        }
        return { ok: true };
    }

    buildPayload(form) {
        const formData = new FormData(form);
        const params = new URLSearchParams();
        
        for (const [key, value] of formData.entries()) {
            if (value.trim()) {
                params.append(key, value.trim());
            }
        }
        
        return params.toString();
    }

    async refreshAll() {
        try {
            await Promise.all([
                this.loadPapers(),
                this.loadCategories(),
                this.loadKeywords()
            ]);
            this.updateUI();
        } catch (error) {
            console.error("Failed to refresh data:", error);
        }
    }

    async loadPapers() {
        const params = new URLSearchParams();
        if (this.state.category) {
            params.append("category", this.state.category);
        }
        if (this.state.keyword) {
            params.append("keyword", this.state.keyword);
        }
        
        const response = await fetch(`/api/papers?${params.toString()}`);
        if (!response.ok) {
            throw new Error(`Failed to load papers: ${response.status}`);
        }
        
        const data = await response.json();
        this.papers = data.papers || [];
        this.filtered = [...this.papers];
        
        // Extract authors
        this.authors.clear();
        this.papers.forEach(paper => {
            if (paper.authors) {
                paper.authors.forEach(author => this.authors.add(author));
            }
        });
    }

    async loadTasks() {
        const response = await fetch("/api/tasks");
        if (!response.ok) {
            throw new Error(`Failed to load tasks: ${response.status}`);
        }
        
        const data = await response.json();
        this.renderTasks(data.tasks || []);
    }

    async loadCategories() {
        const response = await fetch("/api/categories");
        if (!response.ok) {
            throw new Error(`Failed to load categories: ${response.status}`);
        }
        
        const data = await response.json();
        this.categories = data.categories || [];
        this.renderCategories();
        this.updateCategoryFilter();
    }

    async loadKeywords() {
        const response = await fetch("/api/keywords");
        if (!response.ok) {
            throw new Error(`Failed to load keywords: ${response.status}`);
        }
        
        const data = await response.json();
        this.keywords = data.keywords || [];
    }

    renderCategories() {
        const container = this.refs.categoriesContainer;
        if (!container) return;
        
        container.innerHTML = "";
        
        this.categories.forEach(category => {
            const node = this.refs.categoryTemplate.content.cloneNode(true);
            const item = node.querySelector(".category-item");
            const name = node.querySelector(".category-name");
            const count = node.querySelector(".category-count");
            
            name.textContent = category.category;
            count.textContent = category.count;
            
            // Apply color if available
            if (category.color) {
                item.style.setProperty('background-color', category.color, 'important');
                item.style.setProperty('color', '#ffffff', 'important');
            }
            
            item.addEventListener("click", () => {
                this.state.category = category.category;
                this.refs.categoryFilter.value = category.category;
                this.onSearch();
            });
            
            container.appendChild(node);
        });
    }

    updateCategoryFilter() {
        const filter = this.refs.categoryFilter;
        if (!filter) return;
        
        // Clear existing options except "All categories"
        filter.innerHTML = '<option value="">All categories</option>';
        
        this.categories.forEach(category => {
            const option = document.createElement("option");
            option.value = category.category;
            option.textContent = `${category.category} (${category.count})`;
            filter.appendChild(option);
        });
    }

    renderTasks(tasks) {
        const container = this.refs.tasksContainer;
        if (!container) return;
        
        container.innerHTML = "";
        
        if (tasks.length === 0) {
            container.innerHTML = '<div class="list-group-item text-muted text-center">No tasks</div>';
            return;
        }
        
        tasks.forEach(task => {
            const node = this.refs.taskTemplate.content.cloneNode(true);
            const title = node.querySelector(".task-title");
            const description = node.querySelector(".task-description");
            const meta = node.querySelector(".task-meta");
            const status = node.querySelector(".task-status");
            
            title.textContent = task.task_type || "Unknown task";
            description.textContent = task.payload?.description || "No description";
            meta.textContent = `Created: ${new Date(task.created_at).toLocaleString()}`;
            status.textContent = task.status;
            status.className = `badge ${this.getStatusClass(task.status)}`;
            
            container.appendChild(node);
        });
    }

    getStatusClass(status) {
        switch (status) {
            case "completed": return "bg-success";
            case "failed": return "bg-danger";
            case "in_progress": return "bg-primary";
            case "pending": return "bg-warning";
            default: return "bg-secondary";
        }
    }

    onSearch() {
        this.state.query = this.refs.searchInput.value;
        this.state.scope = this.refs.searchScope.value;
        this.state.strict = this.refs.strictToggle.checked;
        this.state.sort = this.refs.sortMode.value;
        this.state.category = this.refs.categoryFilter.value;
        
        this.filtered = this.papers.filter(paper => {
            if (this.state.category && paper.category !== this.state.category) {
                return false;
            }
            
            if (!this.state.query) {
                return true;
            }
            
            const query = this.state.query.toLowerCase();
            const strict = this.state.strict;
            
            switch (this.state.scope) {
                case "title":
                    return strict ? paper.title?.toLowerCase() === query : 
                           paper.title?.toLowerCase().includes(query);
                case "authors":
                    return paper.authors?.some(author => 
                        strict ? author.toLowerCase() === query : 
                        author.toLowerCase().includes(query));
                case "venue":
                    return strict ? paper.venue?.toLowerCase() === query : 
                           paper.venue?.toLowerCase().includes(query);
                case "keywords":
                    return paper.keywords?.some(keyword => 
                        strict ? keyword.toLowerCase() === query : 
                        keyword.toLowerCase().includes(query));
                case "category":
                    return strict ? paper.category?.toLowerCase() === query : 
                           paper.category?.toLowerCase().includes(query);
                default: // "all"
                    const searchFields = [
                        paper.title,
                        paper.venue,
                        paper.category,
                        ...(paper.authors || []),
                        ...(paper.keywords || [])
                    ];
                    return searchFields.some(field => 
                        field && (strict ? field.toLowerCase() === query : 
                                 field.toLowerCase().includes(query)));
            }
        });
        
        this.sortResults();
        this.updateUI();
    }

    sortResults() {
        switch (this.state.sort) {
            case "year_desc":
                this.filtered.sort((a, b) => (b.year || 0) - (a.year || 0));
                break;
            case "year_asc":
                this.filtered.sort((a, b) => (a.year || 0) - (b.year || 0));
                break;
            case "title":
                this.filtered.sort((a, b) => (a.title || "").localeCompare(b.title || ""));
                break;
            default: // "relevance" - keep original order
                break;
        }
    }

    updateUI() {
        this.renderPapers();
        this.updateCounts();
    }

    renderPapers() {
        const container = this.refs.papersContainer;
        if (!container) return;
        
        container.innerHTML = "";
        
        if (this.filtered.length === 0) {
            container.innerHTML = '<div class="text-muted text-center py-4">No papers found</div>';
            return;
        }
        
        const fragment = document.createDocumentFragment();
        this.filtered.forEach(paper => {
            const node = this.refs.paperTemplate.content.cloneNode(true);
            const article = node.querySelector(".paper-row");
            const title = node.querySelector(".paper-title");
            const authors = node.querySelector(".paper-authors");
            const year = node.querySelector(".paper-year");
            const venue = node.querySelector(".paper-venue");
            const category = node.querySelector(".paper-category");
            const keywords = node.querySelector(".paper-keywords");
            const abstract = node.querySelector(".paper-abstract");
            const copy = node.querySelector("button[title='Copy citation']");
            const abstractBtn = node.querySelector("button[title='Toggle abstract']");

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

            if (paper.category) {
                category.textContent = paper.category;
                // Apply color from API
                if (paper.category_color) {
                    category.style.setProperty('background-color', paper.category_color, 'important');
                    category.style.setProperty('color', '#ffffff', 'important');
                }
            } else {
                category.style.display = "none";
            }

            // Keywords
            if (paper.keywords && paper.keywords.length > 0) {
                keywords.innerHTML = "";
                paper.keywords.forEach(keyword => {
                    const keywordEl = document.createElement("span");
                    keywordEl.className = "badge bg-light text-dark me-1";
                    keywordEl.textContent = keyword;
                    keywords.appendChild(keywordEl);
                });
            } else {
                keywords.style.display = "none";
            }

            // Abstract
            if (paper.abstract) {
                abstract.textContent = paper.abstract;
                abstractBtn.style.display = "block";
                abstractBtn.addEventListener("click", () => {
                    if (abstract.style.display === "none") {
                        abstract.style.display = "block";
                    } else {
                        abstract.style.display = "none";
                    }
                });
            } else {
                abstractBtn.style.display = "none";
            }

            // Hide score for regular paper list
            const scoreEl = node.querySelector(".paper-score");
            scoreEl.style.display = "none";

            copy.addEventListener("click", () => {
                const citation = `${paper.title} (${paper.year || 'n.d.'})`;
                navigator.clipboard.writeText(citation).then(() => {
                    // Visual feedback
                    const originalText = copy.innerHTML;
                    copy.innerHTML = "✓";
                    setTimeout(() => {
                        copy.innerHTML = originalText;
                    }, 1000);
                });
            });

            fragment.appendChild(node);
        });

        container.appendChild(fragment);
    }

    updateCounts() {
        if (this.refs.paperCount) {
            this.refs.paperCount.textContent = `${this.filtered.length} papers`;
        }
        if (this.refs.authorCount) {
            this.refs.authorCount.textContent = `${this.authors.size} authors`;
        }
        if (this.refs.resultMeta) {
            this.refs.resultMeta.textContent = `${this.filtered.length} results`;
        }
    }
}

// Initialize the dashboard when DOM is loaded
document.addEventListener('DOMContentLoaded', () => {
    new PFDRDashboard().init();
});