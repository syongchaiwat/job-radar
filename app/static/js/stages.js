// Shared "Log stage" form (board + job page). Open it with
//   $dispatch('log-stage', { jobId, company, title, app })            -> new entry
//   $dispatch('log-stage', { jobId, company, title, app, event })     -> edit an entry
// On success it fires `application-updated` with { jobId, application }.
const STAGE_GROUPS = [
  ["Before applying", ["shortlist", "skipped"]],
  ["Application", ["applied", "screening", "assessment", "interview", "offer"]],
  ["Outcome", ["rejected", "no_response", "withdrawn", "closed", "declined", "accepted"]],
];
const SCHEDULED = ["screening", "interview"];
const TRIAGE = ["shortlist", "skipped"];

function isoDay(offset = 0) {
  const d = new Date();
  d.setDate(d.getDate() + offset);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function stageModal(labels) {
  return {
    open: false, saving: false, error: "", reopen: false,
    labels, groups: STAGE_GROUPS,
    jobId: null, company: "", title: "", eventId: null,
    app: { applied: false, closed: false, status: "new", events: [] },
    f: {},
    show(detail) {
      this.jobId = detail.jobId; this.company = detail.company || ""; this.title = detail.title || "";
      this.app = detail.app || { applied: false, closed: false, status: "new", events: [] };
      const ev = detail.event;
      this.eventId = ev ? ev.id : null;
      const d = (ev && ev.detail) || {};
      this.f = {
        stage: ev ? ev.stage : (detail.stage || this.suggested()[0]),
        date: ev ? ev.date : isoDay(), time: (ev && ev.time) || "", applied_on: "",
        kind: d.kind || "", format: d.format || "", people: d.people || "", platform: d.platform || "",
        due: d.due || "", submitted: d.submitted || "", rating: d.rating ? String(d.rating) : "", round: d.round ? String(d.round) : "",
        note: (ev && ev.note) || "", debrief: (ev && ev.debrief) || "", questions: (ev && ev.questions) || "",
      };
      this.error = ""; this.reopen = false; this.open = true;
      this.$nextTick(() => this.$refs.first && this.$refs.first.focus());
    },
    // Most likely next steps first, from where the application stands.
    suggested() {
      const a = this.app;
      if (!a.applied) return ["applied", "shortlist", "skipped"];
      if (a.closed) return ["interview", "screening", "assessment", "offer"];
      if (a.status === "offer") return ["accepted", "declined", "withdrawn"];
      if (a.reached >= 3) return ["interview", "rejected", "offer", "assessment", "no_response", "withdrawn"];
      if (a.reached === 2) return ["assessment", "interview", "rejected", "no_response", "withdrawn"];
      return ["screening", "assessment", "interview", "rejected", "no_response", "withdrawn"];
    },
    get editing() { return this.eventId !== null; },
    get stage() { return this.f.stage; },
    needsApplied() { return !this.editing && !this.app.applied && !TRIAGE.includes(this.stage) && this.stage !== "applied"; },
    hasTime() { return SCHEDULED.includes(this.stage); },
    isPast() { return this.f.date && this.f.date <= isoDay(); },
    heading() {
      if (this.editing) return "Edit " + (this.labels[this.stage] || this.stage);
      return "Log a stage";
    },
    setDate(offset) { this.f.date = isoDay(offset); },
    async submit() {
      this.saving = true; this.error = "";
      const body = new URLSearchParams();
      Object.entries(this.f).forEach(([k, v]) => body.append(k, v ?? ""));
      if (this.reopen) body.append("reopen", "1");
      const url = this.editing ? `/jobs/${this.jobId}/stages/${this.eventId}` : `/jobs/${this.jobId}/stages`;
      const res = await fetch(url, { method: "POST", body });
      const data = await res.json().catch(() => ({ ok: false, error: "Something went wrong." }));
      this.saving = false;
      if (data.needs_reopen) {
        if (confirm(data.error)) { this.reopen = true; return this.submit(); }
        return;
      }
      if (!data.ok) { this.error = data.error || "Could not save."; return; }
      this.done(data.application);
    },
    async remove() {
      const msg = this.stage === "applied"
        ? "Delete the Applied entry? This removes the whole application (every stage after it)."
        : "Delete this entry?";
      if (!confirm(msg)) return;
      const res = await fetch(`/jobs/${this.jobId}/stages/${this.eventId}/delete`, { method: "POST" });
      const data = await res.json().catch(() => ({ ok: false }));
      if (data.ok) this.done(data.application);
    },
    done(application) {
      this.open = false;
      window.dispatchEvent(new CustomEvent("application-updated", { detail: { jobId: this.jobId, application } }));
    },
  };
}

// Shared display helpers for stage chips (board cards, table, job page).
const STAGE_STYLE = {
  new: "bg-accent-dim/15 border-accent-dim/40 text-accent",
  shortlist: "bg-accent-dim/15 border-accent-dim/40 text-accent",
  skipped: "bg-gray-800 border-gray-700 text-gray-400",
  applied: "bg-green-500/15 border-green-500/40 text-green-300",
  screening: "bg-green-500/15 border-green-500/40 text-green-300",
  assessment: "bg-amber-500/15 border-amber-500/40 text-amber-300",
  interview: "bg-amber-500/15 border-amber-500/40 text-amber-300",
  offer: "bg-amber-500/25 border-amber-400/60 text-amber-200",
  accepted: "bg-green-500/25 border-green-400/60 text-green-200",
  rejected: "bg-red-500/10 border-red-500/40 text-red-300",
  no_response: "bg-gray-800 border-gray-700 text-gray-400",
  withdrawn: "bg-gray-800 border-gray-700 text-gray-400",
  closed: "bg-gray-800 border-gray-700 text-gray-400",
  declined: "bg-gray-800 border-gray-700 text-gray-300",
};
function stageClass(status) { return STAGE_STYLE[status] || STAGE_STYLE.new; }

function fmtDay(iso, withYear = false) {
  if (!iso) return "";
  const d = new Date(iso + "T12:00:00");
  const opts = { day: "numeric", month: "short" };
  if (withYear || d.getFullYear() !== new Date().getFullYear()) opts.year = "numeric";
  return d.toLocaleDateString("en-GB", opts);
}
function daysBetween(iso) {  // whole days from today to iso (negative = past)
  if (!iso) return 0;
  const a = new Date(isoDay() + "T12:00:00"), b = new Date(iso + "T12:00:00");
  return Math.round((b - a) / 86400000);
}
function relDay(iso) {
  const n = daysBetween(iso);
  if (n === 0) return "today";
  if (n === 1) return "tomorrow";
  if (n === -1) return "yesterday";
  return n > 0 ? `in ${n} days` : `${-n} days ago`;
}
function weekday(iso) {
  return iso ? new Date(iso + "T12:00:00").toLocaleDateString("en-GB", { weekday: "short" }) : "";
}
