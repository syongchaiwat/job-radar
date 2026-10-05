// Filtering and sorting are client-side: cards are server-rendered once, then
// hidden with x-show and reordered with CSS `order` (works because the card
// list is a grid), so nothing reloads.
const SORTS = {
  priority: "Priority",
  review: "Needs review first",
  newest: "Newest added",
  match: "Best match",
  archetype: "Archetype",
  status: "Status",
  cv: "CV verdict",
};

const MARKET_FILTERS = {
  all: "All",
  on: "Market data",
  off: "Not market data",
};

const STATUS_FILTERS = {
  active: "Active",
  review: "Needs review",
  progress: "In progress",
  archived: "Archived",
  all: "All",
};

function board() {
  return {
    jobs: [],
    config: {},
    search: "",
    activeArchetype: "all",
    activeLane: "all",
    showExcluded: false,
    sort: "review",
    statusFilter: "active",
    sorts: SORTS,
    statusFilters: STATUS_FILTERS,
    marketFilter: "all",
    marketFilters: MARKET_FILTERS,
    selecting: false,
    selected: [],
    init() {
      const el = document.getElementById("jobs-data");
      this.jobs = el ? JSON.parse(el.textContent) : [];
      const cfg = document.getElementById("board-config");
      this.config = cfg ? JSON.parse(cfg.textContent) : {};
    },
    matchesStatus(j) {
      switch (this.statusFilter) {
        case "review": return j.status === "new";
        case "progress": return this.config.inProgress.includes(j.status);
        case "archived": return this.config.archived.includes(j.status);
        case "active": return !this.config.archived.includes(j.status);
        default: return true;
      }
    },
    get visible() {
      const q = this.search.trim().toLowerCase();
      return this.jobs.filter(
        (j) =>
          this.matchesStatus(j) &&
          (this.marketFilter === "all" || (this.marketFilter === "on") === j.market_data) &&
          (this.showExcluded || !j.excluded) &&
          (this.activeArchetype === "all" || j.archetype === this.activeArchetype) &&
          (this.activeLane === "all" || j.lane === this.activeLane) &&
          (!q || j.company.toLowerCase().includes(q) || j.title.toLowerCase().includes(q))
      );
    },
    isVisible(jobId) {
      return this.visible.some((j) => j.job_id === jobId);
    },
    // Unknown values (no theme, not screened, no CV) sort last.
    rankIn(list, value) {
      const i = list.indexOf(value);
      return i === -1 ? list.length : i;
    },
    compare(a, b) {
      const newest = b.first_seen.localeCompare(a.first_seen);
      const by = (fn) => fn(a) - fn(b) || newest;
      switch (this.sort) {
        case "review": return by((j) => (j.status === "new" ? 0 : 1));
        case "priority": return (b.priority || 0) - (a.priority || 0) || newest;
        case "match": return by((j) => this.rankIn(this.config.matchOrder, j.match_level));
        case "archetype": return by((j) => this.rankIn(this.config.archetypeOrder, j.archetype));
        case "status": return by((j) => this.rankIn(this.config.statusOrder, j.status));
        case "cv": return by((j) => this.rankIn(["approve", "revise"], j.cv_verdict));
        default: return newest;
      }
    },
    get order() {
      const sorted = [...this.jobs].sort((a, b) => this.compare(a, b));
      return Object.fromEntries(sorted.map((j, i) => [j.job_id, i]));
    },
    orderOf(jobId) {
      return this.order[jobId];
    },
    pillClass(active) {
      return active
        ? "bg-accent/20 border-accent text-accent"
        : "border-gray-700 text-gray-400 hover:border-gray-500";
    },
    subtitle() {
      const total = this.jobs.length;
      const shown = this.visible.length;
      const toReview = this.jobs.filter((j) => j.status === "new").length;
      return `${shown} shown of ${total}` + (toReview ? ` · ${toReview} need review` : "");
    },
    // --- market data (pipeline revamp Phase 1) ---
    job(jobId) {
      return this.jobs.find((j) => j.job_id === jobId) || {};
    },
    marketOn(jobId) {
      return !!this.job(jobId).market_data;
    },
    async setMarket(ids, value) {
      const body = new URLSearchParams();
      ids.forEach((id) => body.append("job_ids", id));
      body.append("value", value ? "1" : "0");
      const res = await fetch("/jobs/market-data", { method: "POST", body });
      if (!res.ok) return;
      this.jobs.forEach((j) => { if (ids.includes(j.job_id)) j.market_data = value; });
    },
    toggleMarket(jobId) {
      this.setMarket([jobId], !this.marketOn(jobId));
    },
    // Select mode: clicking a card toggles it instead of opening the job.
    cardClick(event, jobId) {
      if (!this.selecting) return;
      event.preventDefault();
      const i = this.selected.indexOf(jobId);
      if (i === -1) this.selected.push(jobId); else this.selected.splice(i, 1);
    },
    isSelected(jobId) {
      return this.selected.includes(jobId);
    },
    selectVisible() {
      this.selected = this.visible.map((j) => j.job_id);
    },
    async bulkMarket(value) {
      if (!this.selected.length) return;
      await this.setMarket([...this.selected], value);
      this.selected = [];
    },
    stopSelecting() {
      this.selecting = false;
      this.selected = [];
    },
    marketCount() {
      return this.jobs.filter((j) => j.market_data).length;
    },
  };
}
