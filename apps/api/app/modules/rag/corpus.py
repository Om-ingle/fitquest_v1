"""FitQuest curated fitness knowledge corpus (Phase 4C.2).

A SMALL set of general physical-activity guidance documents used to seed
the RAG knowledge base (via ``ingestion.py`` — never manual SQL inserts).

What this corpus IS:
- paraphrased, conservative summaries of well-established public-health
  guidance, each attributed to a trustworthy public source (source_url),
- general coaching material: activity principles, walking, gradual
  progression, recovery, consistency.

What this corpus is NOT:
- medical advice, diagnosis, treatment, or medication guidance,
- fabricated research claims or invented statistics (the only numbers
  present are the widely published public-health activity recommendations
  of the cited organizations),
- synthetic test data — the automated tests use their own clearly-marked
  fixtures (tests/test_rag.py) and never ingest this corpus.
"""

from __future__ import annotations


class CorpusDocument(dict):
    """A curated corpus document: title, source, source_url, content, metadata."""


CORPUS: list[CorpusDocument] = [
    CorpusDocument(
        title="Physical activity guidelines for adults",
        source="WHO",
        source_url="https://www.who.int/news-room/fact-sheets/detail/physical-activity",
        content=(
            "The World Health Organization recommends that adults aged 18-64 "
            "do at least 150-300 minutes of moderate-intensity aerobic "
            "physical activity per week, or at least 75-150 minutes of "
            "vigorous-intensity activity, or an equivalent combination. "
            "Moderate-intensity activity noticeably raises the heart rate "
            "and breathing while still allowing conversation. In addition, "
            "adults should do muscle-strengthening activity at moderate or "
            "greater intensity on two or more days per week. Some activity "
            "is better than none: adults who do not currently meet these "
            "recommendations benefit from starting with small amounts and "
            "gradually increasing frequency, intensity, and duration. "
            "WHO also recommends limiting the amount of time spent being "
            "sedentary, replacing it with activity of any intensity."
        ),
        metadata={"topic": "activity-principles", "kind": "curated_knowledge"},
    ),
    CorpusDocument(
        title="Walking as everyday physical activity",
        source="CDC",
        source_url="https://www.cdc.gov/physical-activity-basics/about.html",
        content=(
            "Walking is one of the easiest and safest ways to be active. "
            "Brisk walking counts as moderate-intensity physical activity: "
            "a pace where talking is possible but singing is not. Walking "
            "requires no special equipment beyond supportive shoes, can be "
            "done almost anywhere, and can be split into shorter bouts "
            "across the day that still add up toward weekly activity goals. "
            "Everyday choices such as taking the stairs, parking farther "
            "away, or short walking breaks during sedentary work all "
            "contribute. The U.S. Centers for Disease Control and Prevention "
            "encourages adults to move more and sit less, emphasizing that "
            "some physical activity is better than none."
        ),
        metadata={"topic": "walking", "kind": "curated_knowledge"},
    ),
    CorpusDocument(
        title="Gradual progression and the principle of overload",
        source="WHO",
        source_url="https://www.who.int/news-room/fact-sheets/detail/physical-activity",
        content=(
            "Fitness improves when the body is challenged slightly beyond "
            "what it is used to, then given time to adapt. This means "
            "increasing activity gradually rather than suddenly: a practical "
            "approach for beginners is to first build a consistent routine "
            "at a comfortable level, and only then increase duration or "
            "intensity in small increments week by week. WHO guidance "
            "specifically advises people who are inactive to start with "
            "small amounts of activity and increase gradually, since "
            "abrupt large jumps in volume or intensity raise the risk of "
            "soreness, burnout, and injury. If an increase leaves lasting "
            "fatigue or pain, scaling back to the previous comfortable "
            "level is the sensible response. Progress that feels almost "
            "too easy at first is usually the kind that lasts."
        ),
        metadata={"topic": "progression", "kind": "curated_knowledge"},
    ),
    CorpusDocument(
        title="Recovery and rest days",
        source="CDC",
        source_url="https://www.cdc.gov/physical-activity-basics/about.html",
        content=(
            "Rest is part of training, not a break from it. Recovery days "
            "give muscles, joints, and the nervous system time to adapt to "
            "recent activity, which is when fitness gains actually settle "
            "in. For gentle, moderate-intensity activity like walking, "
            "recovery can mean a lighter or shorter day rather than full "
            "rest. Warning signs that suggest taking it easier include "
            "sharp pain, unusual persistent fatigue, or soreness that does "
            "not fade after a couple of easy days. Adequate sleep supports "
            "recovery and makes regular activity easier to sustain. Anyone "
            "experiencing chest pain, dizziness, or injury should stop and "
            "seek guidance from a qualified healthcare professional rather "
            "than pushing through."
        ),
        metadata={"topic": "recovery", "kind": "curated_knowledge"},
    ),
    CorpusDocument(
        title="Building activity consistency and habits",
        source="CDC",
        source_url="https://www.cdc.gov/physical-activity-basics/about.html",
        content=(
            "Consistency matters more than intensity for long-term health. "
            "Regular moderate activity several days a week delivers more "
            "lasting benefit than occasional all-out sessions followed by "
            "long gaps. Habits stick better when activity is tied to an "
            "existing daily routine — the same time each day, or anchored "
            "to something already habitual like a lunch break or commute. "
            "Starting with a small, almost trivially achievable daily "
            "target and only expanding it once it feels automatic is a "
            "reliable pattern. Missing a day is normal and does not erase "
            "progress; the useful skill is returning to the routine the "
            "next day rather than restarting from zero. Tracking progress "
            "and celebrating small milestones helps maintain motivation."
        ),
        metadata={"topic": "consistency", "kind": "curated_knowledge"},
    ),
    CorpusDocument(
        title="Returning to activity after a break",
        source="WHO",
        source_url="https://www.who.int/news-room/fact-sheets/detail/physical-activity",
        content=(
            "After time away from activity, fitness is regained faster "
            "than it was first built, but patience still pays. The "
            "recommended approach is to resume at a comfortable fraction "
            "of the previous level — for many people roughly half the "
            "usual duration or intensity for the first week or two — and "
            "rebuild gradually from there. Expect some initial soreness "
            "after the first sessions; persistent or sharp pain is a "
            "signal to ease off. Setting a small, concrete first goal, "
            "such as a short daily walk for a week, rebuilds both capacity "
            "and the habit itself. People with underlying health "
            "conditions, or who experience symptoms such as chest pain or "
            "dizziness during activity, should consult a qualified "
            "healthcare professional before resuming."
        ),
        metadata={"topic": "recovery", "kind": "curated_knowledge"},
    ),
]
