# Example profile (fictional)

Everything in this folder describes **Alex Muster**, a made-up candidate, so a fresh clone runs end to end without anyone's real data.

`python scripts/sync_profile.py` copies it into the gitignored working folders (`profile/`, `cv_profile/`, `data/`) whenever `PROFILE_SOURCE_DIR` isn't set. To use your own profile, keep a folder with the same layout somewhere private (e.g. a notes vault) and point `PROFILE_SOURCE_DIR` at it in `.env`:

```
<your folder>/
  profile/            filters.md, constraints.md, projects.md, coursework.md, themes/theme-*.md
  seed-jobs.md        hand-labeled jobs (eval ground truth)
  seed_descriptions.json   optional: {job_id: description} for the seed jobs
  cv_profile/cv_template.md   optional: copied only if you don't have one locally yet
```
