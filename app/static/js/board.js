// Filtering and sorting are client-side: cards are server-rendered once, then
// hidden with x-show and reordered with CSS `order` (works because the card
// list is a grid), so nothing reloads.
const SORTS = {
  review: "Needs review first",
  newest: "Newest added",
  match: "Best match",
  theme: "Theme",
  status: "Status",
  cv: "CV verdict",
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
    activeTheme: "all",
    showExcluded: false,
    sort: "review",
    statusFilter: "active",
    sorts: SORTS,
    statusFilters: STATUS_FILTERS,
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
          (this.showExcluded || !j.excluded) &&
          (this.activeTheme === "all" || j.theme_code === this.activeTheme) &&
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
        case "match": return by((j) => this.rankIn(this.config.matchOrder, j.match_level));
        case "theme": return by((j) => this.rankIn(this.config.themeOrder, j.theme_code));
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
  };
}
