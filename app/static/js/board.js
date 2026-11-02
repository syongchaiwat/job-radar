// Filtering and sorting are client-side: cards are server-rendered once, then
// hidden with x-show and reordered with CSS `order` (works because the card
// list is a grid), so nothing reloads.
const SORTS = {
  priority: "Priority",
  review: "Needs review first",
  next: "Next action",
  activity: "Last activity",
  newest: "Newest added",
  match: "Best match",
  archetype: "Archetype",
  status: "Status",
  cv: "Edited CV first",
};

const MARKET_FILTERS = {
  all: "All",
  on: "Market data",
  off: "Not market data",
};

const STATUS_FILTERS = {
  active: "Active",
  review: "Needs review",
  shortlist: "Shortlist",
  applied: "Applied",
  upcoming: "Upcoming",
  skipped: "Skipped",
  all: "All",
};

const APPLIED_SCOPES = { all: "All", open: "Open", closed: "Closed" };

// Next-action urgency for the "Next action" sort.
const NEXT_ORDER = ["debrief", "due", "upcoming", "follow_up"];

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
    appliedScope: "all",
    appliedScopes: APPLIED_SCOPES,
    expanded: null,
    marketFilter: "all",
    marketFilters: MARKET_FILTERS,
    selecting: false,
    selected: [],
    view: "cards",
    init() {
      try { this.view = localStorage.getItem("board.view") || "cards"; } catch (e) {}
      const el = document.getElementById("jobs-data");
      this.jobs = el ? JSON.parse(el.textContent) : [];
      const cfg = document.getElementById("board-config");
      this.config = cfg ? JSON.parse(cfg.textContent) : {};
      window.addEventListener("application-updated", (e) => {
        const j = this.job(e.detail.jobId);
        if (!j.job_id) return;
        Object.assign(j, e.detail.application, { app: e.detail.application, status: e.detail.application.status });
      });
    },
    matchesStatus(j) {
      const a = j.app;
      switch (this.statusFilter) {
        case "active": return j.status !== "skipped" && !a.closed;
        case "review": return j.status === "new";
        case "shortlist": return j.status === "shortlist";
        case "applied":
          return a.applied && (this.appliedScope === "all" || (this.appliedScope === "closed") === a.closed);
        case "upcoming": return !!(a.next && a.next.kind === "upcoming");
        case "skipped": return j.status === "skipped";
        default: return true;
      }
    },
    countWhere(fn) {
      return this.jobs.filter(fn).length;
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
    // Unknown values (no archetype, not screened, no CV) sort last.
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
        case "cv": return by((j) => (j.own_cv ? 0 : 1));
        case "activity": return (b.app.last_activity || "").localeCompare(a.app.last_activity || "") || newest;
        case "next": {
          const rank = (j) => (j.app.next ? NEXT_ORDER.indexOf(j.app.next.kind) : NEXT_ORDER.length + (j.app.applied && !j.app.closed ? 0 : 1));
          const day = (j) => (j.app.next && j.app.next.date) || "9999";
          return rank(a) - rank(b) || day(a).localeCompare(day(b)) || (b.app.last_activity || "").localeCompare(a.app.last_activity || "");
        }
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
        ? "bg-accent-dim/20 border-accent-dim/60 text-accent"
        : "border-gray-800 text-gray-400 hover:border-gray-600 hover:text-gray-200";
    },
    count(status) {
      return this.jobs.filter((j) => j.status === status).length;
    },
    // --- view toggle: cards (triage) or tracking table (applications) ---
    setView(v) {
      if (v === "table" && ["active", "review", "shortlist"].includes(this.statusFilter)) this.statusFilter = "applied";
      if (v === "table" && ["review", "priority"].includes(this.sort)) this.sort = "next";
      this.view = v;
      try { localStorage.setItem("board.view", v); } catch (e) {}
    },
    get sortedVisible() {
      return [...this.visible].sort((a, b) => this.compare(a, b));
    },
    initials(name) {
      const words = (name || "?").replace(/[^\p{L}\p{N} ]/gu, " ").split(/\s+/).filter(Boolean);
      return (words.length > 1 ? words[0][0] + words[1][0] : (words[0] || "?").slice(0, 2)).toUpperCase();
    },
    cap(s) {
      return s ? s[0].toUpperCase() + s.slice(1) : "";
    },
    logStage(j, extra = {}) {
      this.$dispatch("log-stage", { jobId: j.job_id, company: j.company, title: j.title, app: j.app, ...extra });
    },
    toggleRow(id) {
      this.expanded = this.expanded === id ? null : id;
    },
    nextText(n) {
      if (!n) return "";
      if (n.kind === "upcoming") return `${n.label} · ${weekday(n.date)} ${fmtDay(n.date)}${n.time ? " " + n.time : ""}`;
      if (n.kind === "due") return `Assessment due ${relDay(n.date)}`;
      if (n.kind === "follow_up") return `Follow up? ${n.days} days quiet`;
      return n.label;
    },
    nextClass(n) {
      return { upcoming: "text-accent", due: "text-amber-300", debrief: "text-amber-200", follow_up: "text-amber-300" }[n && n.kind] || "text-gray-500";
    },
    subtitle() {
      const total = this.jobs.length;
      const shown = this.visible.length;
      const toReview = this.countWhere((j) => j.status === "new");
      return `${shown} shown of ${total}` + (toReview ? ` · ${toReview} need review` : "");
    },
    // --- market data (pipeline revamp Phase 1) ---
    job(jobId) {
      return this.jobs.find((j) => j.job_id === jobId) || { app: {} };
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
    // --- bookmarks: a star to spot jobs on the board ---
    bookmarked(jobId) {
      return !!this.job(jobId).bookmarked;
    },
    async toggleBookmark(jobId) {
      const value = !this.bookmarked(jobId);
      const res = await fetch(`/jobs/${jobId}/bookmark`, { method: "POST", body: new URLSearchParams({ value: value ? "1" : "0" }) });
      if (res.ok) this.job(jobId).bookmarked = value;
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
