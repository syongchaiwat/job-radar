// Hover tooltip + click-through for every [data-cluster-map] on the page.
(() => {
  const esc = (t) => String(t).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  document.querySelectorAll("[data-cluster-map]").forEach((map) => {
    const tip = map.querySelector("[data-map-tip]");
    map.querySelectorAll("circle[data-title]").forEach((dot) => {
      dot.addEventListener("mouseenter", () => {
        const d = dot.dataset;
        tip.innerHTML = `<b>${esc(d.title)}</b><br><span class="text-gray-400">${esc(d.company)} · ${esc(d.lane)}</span><br>${esc(d.arch)}` +
          (d.note ? `<br><span class="text-amber-300">${esc(d.note)}</span>` : "");
        tip.classList.remove("hidden");
      });
      dot.addEventListener("mousemove", (e) => {
        const box = map.getBoundingClientRect();
        tip.style.left = Math.min(e.clientX - box.left + 12, box.width - tip.offsetWidth - 8) + "px";
        tip.style.top = e.clientY - box.top + 12 + "px";
      });
      dot.addEventListener("mouseleave", () => tip.classList.add("hidden"));
      dot.addEventListener("click", () => { window.location.href = "/jobs/" + dot.dataset.jobId; });
    });
  });
})();
