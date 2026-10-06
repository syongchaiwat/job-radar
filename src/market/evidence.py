"""Which canonical skills your profile proves (projects.md Tools + CV template skills).

Terms are mapped to the skill dictionary deterministically first (alias, exact
name, name without a parenthetical, acronym in parentheses); the rest go to
Sonnet once and are cached in ProfileTerm, so only new terms ever cost a call.
"""
import json
import re
from pathlib import Path

from sqlalchemy import func
from sqlmodel import Session, select

from src.db import ProfileTerm, Skill, SkillAlias
from src.profile import context as pc
from src.llm.call import call, load_prompt
from src.llm.schemas import TermMappings

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
TEMPLATE = REPO_ROOT / "cv_profile" / "cv_template.md"


def _split_terms(line: str) -> list[str]:
    # split on commas that are not inside parentheses
    parts, depth, cur = [], 0, ""
    for ch in line:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth = max(0, depth - 1)
        if ch == "," and depth == 0:
            parts.append(cur)
            cur = ""
        else:
            cur += ch
    parts.append(cur)
    return [p.strip().strip(".") for p in parts if p.strip()]


def profile_terms() -> dict[str, set[str]]:
    """{term (lowercase): {source, ...}} from projects.md Tools lines and the CV template."""
    out: dict[str, set[str]] = {}
    current = None
    for line in pc.load_projects().splitlines():
        if line.startswith("## "):
            current = line[3:].strip()
        m = re.match(r"- \*\*Tools:\*\*\s*(.+)", line)
        if m and current:
            for t in _split_terms(m.group(1)):
                out.setdefault(t.lower(), set()).add(current)
    # completed courses (grades stripped); in-progress courses don't prove anything yet
    section, completed = "", False
    for line in pc.strip_grades(pc.load_coursework(), course_list=True).splitlines():
        if line.startswith("## "):
            section = re.sub(r"\s*\(source:.*\)", "", line[3:]).strip()
            completed = True  # a finished degree's list has no status heading
        elif line.startswith("**"):
            completed = line.lower().startswith("**completed")
        elif completed and line.startswith("- "):
            name = re.sub(r"\s*\([^)]*\)", "", line[2:]).strip()
            if name and "german" not in name.lower():
                out.setdefault(name.lower(), set()).add(f"Coursework: {section.split(',')[0]}")
    if TEMPLATE.exists():
        text = TEMPLATE.read_text()
        sec = re.search(r"## Technical Skills\s*\n(.*?)(?=\n## |\Z)", text, re.S)
        for line in (sec.group(1).splitlines() if sec else []):
            m = re.match(r"- \*\*[^*]+:\*\*\s*(.+)", line.strip())
            if m:
                for t in _split_terms(m.group(1)):
                    out.setdefault(t.lower(), set()).add("CV skills baseline")
    return out


def _deterministic(session: Session, term: str) -> tuple[list[int], str] | None:
    alias = session.get(SkillAlias, term)
    if alias:
        return [alias.skill_id], "alias"
    hit = session.exec(select(Skill).where(func.lower(Skill.name) == term)).first()
    if hit:
        return [hit.id], "exact"
    m = re.match(r"(.+?)\s*\((.+)\)$", term)
    if m:
        ids = []
        for cand in (m.group(1).strip(), m.group(2).strip()):
            a = session.get(SkillAlias, cand)
            s = a.skill_id if a else (session.exec(select(Skill).where(func.lower(Skill.name) == cand)).first() or Skill(id=None)).id
            if s:
                ids.append(s)
        if ids:
            return sorted(set(ids)), "stripped"
    return None


def refresh_term_map(session: Session, force: bool = False) -> dict[str, list[int]]:
    """Ensure every current profile term has a mapping; returns {term: [skill_id]}."""
    terms = profile_terms()
    cached = {r.term: r for r in session.exec(select(ProfileTerm)).all()}
    todo = []
    for term in terms:
        if term in cached and (not force or cached[term].method == "user"):  # your "not evidence" decisions survive a remap
            continue
        det = _deterministic(session, term)
        if det:
            row = cached.get(term) or ProfileTerm(term=term)
            row.skill_ids, row.method = json.dumps(det[0]), det[1]
            session.add(row)
            cached[term] = row
        else:
            todo.append(term)
    if todo:
        skills = session.exec(select(Skill)).all()
        by_name = {s.name.lower(): s.id for s in skills}
        for i in range(0, len(todo), 60):
            batch = todo[i:i + 60]
            prompt = load_prompt("market/profile_skill_map").format(
                skills=", ".join(sorted(s.name for s in skills)), terms="\n".join(batch)
            )
            parsed, _ = call("deep", prompt, TermMappings, method="json_schema")
            got = {m.term.lower(): m.skills for m in parsed.mappings}
            for term in batch:
                ids = sorted({by_name[n.lower()] for n in got.get(term, []) if n.lower() in by_name})
                row = cached.get(term) or ProfileTerm(term=term)
                row.skill_ids, row.method = json.dumps(ids), "llm"
                session.add(row)
                cached[term] = row
    session.commit()
    return {t: json.loads(cached[t].skill_ids) for t in terms if t in cached}


def evidence(session: Session, refresh: bool = True) -> dict[int, set[str]]:
    """{skill_id: {source project or 'CV skills baseline', ...}}"""
    term_map = refresh_term_map(session) if refresh else {
        r.term: json.loads(r.skill_ids) for r in session.exec(select(ProfileTerm)).all()
    }
    sources = profile_terms()
    out: dict[int, set[str]] = {}
    for term, ids in term_map.items():
        for sid in ids:
            out.setdefault(sid, set()).update(sources.get(term, set()))
    return out
