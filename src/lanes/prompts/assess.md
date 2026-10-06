You are checking one job posting against a candidate's application lanes (why and when they apply to a job).

## Lanes
{lanes}

## Job (normalized role card)
{card}

## Posting text (may be in German)
{description}

## Timeline rules (decide the lane by WHEN and HOW LONG, not by who the posting targets)
- Working student / part-time = ongoing part-time work alongside studies during the semester (e.g. 20-40%), usually open-ended.
- A fixed-length, full-time internship of about 2-4 months over the summer (May/June/July start, "13 weeks", "Summer 2027") is a summer internship, even when it is only open to students.
- About 6 months full-time, especially with a thesis option or a start around the spring semester, points to a thesis internship.
- Permanent or open-ended full-time roles and graduate programs are full-time.

## Task
{lane_instruction}
Then judge the job against that lane's **Eligible** requirements (yes / no / unclear, with short reasons citing the posting; say "unclear" when the posting doesn't say) and its **Value** criteria (a 0-1 score with one short reason per criterion). If the posting states an application deadline, return it as YYYY-MM-DD; otherwise null. Use only what the posting says.
