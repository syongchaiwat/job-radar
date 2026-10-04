"""Archetype sets from the command line (the Classify page does the same).

Usage:
    python scripts/archetypes.py status            # active set, pool size, latest run
    python scripts/archetypes.py seed-v0           # set v0 from the legacy themes (once)
    python scripts/archetypes.py rework            # run a rework now and print the draft proposal
    python scripts/archetypes.py assign --job-id <id>
"""
import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(REPO_ROOT / ".env")

from sqlmodel import Session, select  # noqa: E402

from src.archetypes import commit, rework  # noqa: E402
from src.db import ArchetypeSet, ClassifyRun, Job, get_engine, init_db  # noqa: E402


def print_proposal(p: dict) -> None:
    s = p["summary"]
    print(f"\n{s['n_jobs']} jobs · tracks ARI {s['tracks_ari']} · flagged {s['flagged']} · unassigned {s['unassigned']} · thresholds {p['thresholds']}")
    for a in sorted(p["archetypes"], key=lambda a: -a["stats"]["size"]):
        st = a["stats"]
        print(f"\n■ {a['name']} [{a['key']}]  size {st['size']}  stability {st.get('stability')}  cohesion {st.get('cohesion')}  agree {st.get('tracks_agree')}  flagged {st['flagged']}")
        print(f"  {a['definition']}")
        print(f"  skills: {', '.join(s for s, _ in st['top_skills'])}")
        print("  jobs: " + "; ".join(p["jobs"][j]["title"][:40] for j in a["members"][:8]) + (" …" if len(a["members"]) > 8 else ""))
    print(f"\nNotes: {p['notes']}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["status", "seed-v0", "rework", "assign"])
    parser.add_argument("--job-id")
    args = parser.parse_args()
    engine = init_db(get_engine())
    with Session(engine) as session:
        if args.command == "seed-v0":
            aset = commit.seed_v0(session)
            print("seeded v0" if aset else "an archetype set already exists; nothing to do")
        elif args.command == "status":
            aset = rework.active_set(session)
            pool = session.exec(select(Job).where(Job.market_data == True)).all()  # noqa: E712
            run = session.exec(select(ClassifyRun).order_by(ClassifyRun.id.desc())).first()
            print(f"active set: {aset.version if aset else None} · market-data jobs: {len(pool)} · latest run: {run.id if run else None} {run.status if run else ''}")
        elif args.command == "rework":
            run = rework.start_run(session)
            rework.execute(run.id, engine)
            session.refresh(run)
            print(f"run {run.id}: {run.status} · {run.cost_tokens} tokens {run.error or ''}")
            if run.status == "draft":
                print_proposal(json.loads(run.proposal))
        elif args.command == "assign":
            r = commit.assign_job(session, args.job_id)
            session.commit()
            print(r)


if __name__ == "__main__":
    main()
