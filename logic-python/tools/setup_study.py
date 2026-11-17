"""
Create the study's agent, its after-conversation questionnaire and its three experiments
(docs/REVIEW.md: D23 persona, D20 timing, I5 UK window, P2 questionnaires, P1 one experiment per condition).

    python tools/setup_study.py            # shows what would be created, changes nothing
    python tools/setup_study.py --apply    # creates what is missing

It only ADDS documents and never changes or deletes an existing one: something that already exists
under the same name is left exactly as it is and reported. The three experiments are built from one
template, so they are identical except for the condition (title, description, behaviour weights).

Participants see an experiment's title when they join, so the titles are neutral; the condition is
written in the description, which only the dashboard shows.
"""
from __future__ import annotations

import copy
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from bson import ObjectId

from services.schedule_utils import STUDY_WINDOW

AGENT_TITLE = "Lexi (study persona)"
FORM_NAME = "Study: after every conversation"

# The agreed persona (docs/REVIEW.md D23; protocol appendix A.1). Change it there and here together.
PERSONA = """You are Lexi, an empathetic, attentive and friendly AI companion.

# Your Core Objective
Your primary goal is to be a great listener. You provide a safe, judgment-free space for the user to share their daily experiences, thoughts and emotions. You care about how they feel and what is happening in their life.

# Tone and Personality
- Conversational, warm and natural, like a supportive friend.
- Show empathy and validate the user's feelings.
- Do not sound robotic, clinical or like a therapist. Do NOT give medical or professional advice.

# Behavioral Rules
1. Encourage sharing: if the user gives a very short or generic answer (e.g., "my day was okay"), gently ask one open-ended follow-up question.
2. Validate emotions: when the user shares a feeling (positive or negative) or an upcoming event, acknowledge it directly.
3. Be concise: this is a mobile chat app. Keep replies to 2-3 sentences and ask only ONE question at a time.
4. Natural flow: match the user's energy. If they are brief, do not overwhelm them.
5. Use only what you actually know: refer to earlier conversations only if they appear in the context you were given. Never invent or guess past events.
6. If asked, say honestly that you are an AI.
7. Safety: if the user mentions wanting to harm themselves or others, or being in immediate danger, respond with care and without judgment, do not try to treat or analyse, and gently encourage them to contact local emergency services or a crisis line, or someone they trust."""

AGREE = {"left": "Strongly disagree", "right": "Strongly agree", "range": 7, "required": True, "numbered": True}

# The four questions after every conversation (protocol, Questionnaires; proposed, to be confirmed).
AFTER_CONVERSATION_QUESTIONS = [
    {"type": "scale-radio", "props": {"fieldKey": "open", "label": "I felt like I could be open during this conversation.", **AGREE}},
    {"type": "scale-radio", "props": {"fieldKey": "enjoyed", "label": "I enjoyed this conversation with Lexi.", **AGREE}},
    {"type": "scale-radio", "props": {"fieldKey": "in_control", "label": "I felt in control of this conversation.", **AGREE}},
    {"type": "radio-selection", "props": {
        "fieldKey": "start_liked",
        "label": "Did you like the way this conversation started?",
        "selectionOptions": [{"label": "Like", "value": "like"}, {"label": "Dislike", "value": "dislike"}],
        "required": True,
    }},
]

# title -> (what the dashboard shows as description, behaviour weights)
CONDITIONS = [
    ("Lexi Study 1", "CONDITION: Reactive (baseline). No notifications are sent; the drawn times are only logged.",
     {"affective": 0, "temporal": 0, "behaviouralGap": 0, "generic": 0, "reactive": 100}),
    ("Lexi Study 2", "CONDITION: Standard Proactive (neutral). Two notifications a day from the fixed neutral pool.",
     {"affective": 0, "temporal": 0, "behaviouralGap": 0, "generic": 100, "reactive": 0}),
    ("Lexi Study 3", "CONDITION: Affective Proactive (warm). Two notifications a day written from the participant's memory.",
     {"affective": 100, "temporal": 0, "behaviouralGap": 0, "generic": 0, "reactive": 0}),
]


def agent_document(now: datetime) -> dict:
    return {
        "title": AGENT_TITLE,
        "summary": "The agreed study persona (D23). One agent for all three conditions.",
        "systemStarterPrompt": PERSONA,
        "beforeUserSentencePrompt": "",
        "afterUserSentencePrompt": "",
        "firstChatSentence": "Hi, I'm Lexi! I'm here to listen. How are you feeling today?",
        "model": "gpt-4o",
        "temperature": 0.7,
        "maxTokens": None,
        "topP": None,
        "frequencyPenalty": None,
        "presencePenalty": None,
        "stopSequences": [],
        "createdAt": now,
        "timestamp": int(now.timestamp() * 1000),
    }


def form_document() -> dict:
    return {
        "name": FORM_NAME,
        "title": "A few quick questions",
        "instructions": "Please answer about the conversation you just finished.",
        "questions": copy.deepcopy(AFTER_CONVERSATION_QUESTIONS),
    }


def experiment_document(title: str, description: str, weights: dict, agent_id: str, form_id: str, now: datetime) -> dict:
    """One experiment. Everything except title, description and weights is the same for all three."""
    return {
        "agentsMode": "Single",
        "activeAgent": agent_id,
        "abAgents": None,
        "displaySettings": {
            "welcomeHeader": "Welcome",
            "welcomeContent": "This study is conducted by Ben-Gurion University of the Negev (BGU).\n"
                              "You are invited to talk with Lexi, an AI companion, about your day and whatever is on your mind.",
        },
        "isActive": True,
        "title": title,
        "description": description,
        "experimentForms": {"registration": None, "preConversation": None, "postConversation": form_id},
        "studySettings": {"durationDays": 14, "endSurveyForm": None, "onboardingCompletionCode": "", "finalCompletionCode": ""},
        "maxMessages": None,
        "maxConversations": None,
        "maxParticipants": None,
        "experimentFeatures": {
            "userAnnotation": False,
            "streamMessage": False,
            "proactiveSettings": {
                "enabled": True,
                "frequency": 30,
                "heuristics": {"temporal": True, "affective": True, "behaviouralGap": True},
                "heuristicWeights": dict(weights),
                "heuristicPrompts": {k: {"memoryPrompt": "", "messagePrompt": ""}
                                     for k in ("affective", "temporal", "behaviouralGap", "generic")},
                "schedule": {
                    "allowedDays": [0, 1, 2, 3, 4, 5, 6],
                    "mode": "random",
                    "fireTimes": [],
                    "randomWindows": [dict(STUDY_WINDOW)],
                },
                "llmModel": "gpt-4o",
                "defaultLanguage": "en",
            },
        },
        "createdAt": now,
        "timestamp": int(now.timestamp() * 1000),
        "numberOfParticipants": 0,
        "totalSessions": 0,
        "openSessions": 0,
    }


def differences(a: dict, b: dict, path: str = "") -> list:
    """Paths at which two experiment documents differ (used to prove the three are identical otherwise)."""
    out = []
    for key in sorted(set(a) | set(b)):
        here = f"{path}.{key}" if path else key
        if isinstance(a.get(key), dict) and isinstance(b.get(key), dict):
            out += differences(a[key], b[key], here)
        elif a.get(key) != b.get(key):
            out.append(here)
    return out


def setup(db, apply: bool, now: datetime | None = None) -> dict:
    """Create what is missing. Returns {"agent": id, "form": id, "experiments": {title: id}, "created": [...]}."""
    now = now or datetime.now(timezone.utc)
    created = []

    agent = db["agents"].find_one({"title": AGENT_TITLE})
    if agent is None:
        agent = {"_id": ObjectId(), **agent_document(now)}
        created.append(f"agent '{AGENT_TITLE}'")
        if apply:
            db["agents"].insert_one(agent)

    form = db["forms"].find_one({"name": FORM_NAME})
    if form is None:
        form = {"_id": ObjectId(), **form_document()}
        created.append(f"form '{FORM_NAME}'")
        if apply:
            db["forms"].insert_one(form)

    experiments = {}
    for title, description, weights in CONDITIONS:
        existing = db["experiments"].find_one({"title": title})
        if existing is None:
            existing = {"_id": ObjectId(),
                        **experiment_document(title, description, weights, str(agent["_id"]), str(form["_id"]), now)}
            created.append(f"experiment '{title}'")
            if apply:
                db["experiments"].insert_one(existing)
        experiments[title] = str(existing["_id"])
    return {"agent": str(agent["_id"]), "form": str(form["_id"]), "experiments": experiments, "created": created}


def main() -> None:
    from dotenv import load_dotenv
    from pymongo import MongoClient

    load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))
    apply = "--apply" in sys.argv
    db = MongoClient(os.environ["MONGODB_URL"])[os.environ["MONGODB_DB_NAME"]]
    result = setup(db, apply)
    print("APPLIED" if apply else "DRY RUN (nothing changed; add --apply to create)")
    print("would create / created:" if result["created"] else "nothing to create: everything already exists")
    for item in result["created"]:
        print("  +", item)
    print("agent:", result["agent"], "| form:", result["form"])
    for title, exp_id in result["experiments"].items():
        print(f"  {title}: {exp_id}")
    if apply:
        ids = ",".join(result["experiments"].values())
        print("\nstudy link (random assignment):  <server>/join/study?e=" + ids)


if __name__ == "__main__":
    main()
