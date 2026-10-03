// Renders every [data-markdown] target from the hidden <textarea data-markdown-src>
// just before it. Runs on load and after each htmx swap (the CV panel is swapped in
// after Prepare CV / Regenerate).
function renderMarkdown(root) {
  root.querySelectorAll("[data-markdown]").forEach((target) => {
    const src = target.previousElementSibling;
    if (!src || !src.hasAttribute("data-markdown-src")) return;
    target.innerHTML = DOMPurify.sanitize(marked.parse(src.value, { breaks: true }));
  });
}

document.addEventListener("DOMContentLoaded", () => renderMarkdown(document));
// outerHTML swaps detach the old element, so just re-scan the whole page.
document.addEventListener("htmx:afterSettle", () => renderMarkdown(document));
