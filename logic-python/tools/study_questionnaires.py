"""
The study's questionnaires as dashboard forms (docs/REVIEW.md P2; protocol, Questionnaires and Appendix B).

PROPOSED, NOT FINAL: to be confirmed by the supervisors. Wordings:
  * taken from the published study materials of Laban et al. (2024, osf.io/m74cb), with "Pepper"
    replaced by "Lexi": subjective self-disclosure, agency / experience, interaction quality,
    friendliness and warmth, loneliness (ULS-8, last three days), Distress Disclosure Index;
  * written from the published scales and STILL TO BE CHECKED against the original papers:
    Hong Psychological Reactance Scale, privacy concern (Malhotra et al., 2004), Perceived Surveillance
    Scale (Segijn et al., 2022), threat to freedom (Dillard & Shen, 2005), User Engagement Scale short
    form (O'Brien et al., 2018).

Field keys are the column names of the analysis. Items marked (R) in a comment are reverse-scored.
The loneliness and privacy-concern items have the SAME keys and wording at baseline and at the end,
so that change can be measured.
"""
from __future__ import annotations

AGREE7 = {"left": "Strongly disagree", "right": "Strongly agree", "range": 7}
AGREE5 = {"left": "Strongly disagree", "right": "Strongly agree", "range": 5}
DESCRIBES7 = {"left": "Does not describe me", "right": "Describes me extremely well", "range": 7}
OFTEN7 = {"left": "Not at all", "right": "All the time", "range": 7}
EXTENT7 = {"left": "Not at all", "right": "To a great extent", "range": 7}
EXTREMELY7 = {"left": "Not at all", "right": "Extremely", "range": 7}


def scale(key: str, label: str, anchors: dict) -> dict:
    return {"type": "scale-radio", "props": {"fieldKey": key, "label": label, **anchors, "required": True, "numbered": True}}


def number(key: str, label: str, low: int, high: int) -> dict:
    return {"type": "number-input", "props": {"fieldKey": key, "label": label, "min": low, "max": high, "required": True}}


def block(prefix: str, items: list, anchors: dict, stem: str = "") -> list:
    return [scale(f"{prefix}_{i}", f"{stem}{text}", anchors) for i, text in enumerate(items, start=1)]


# ── Laban et al. (2024) materials ───────────────────────────────────────────
DISTRESS_DISCLOSURE = [  # Kahn & Hessling (2001); reverse: 2, 4, 5, 8, 9, 10
    "When I feel upset, I usually confide in my friends",
    "I prefer not to talk about my problems",
    "When something unpleasant happens to me, I often look for someone to talk to",
    "I typically don't discuss things that upset me",
    "When I feel depressed or sad, I tend to keep those feelings to myself",
    "I try to find people to talk with about my problems",
    "When I am in a bad mood, I talk about it with my friends",
    "If I have a bad day, the last thing I want to do is talk about it",
    "I rarely look for people to talk with when I am having a problem",
    "When I'm distressed I don't tell anyone",
    "I usually seek out someone to talk to when I am in a bad mood",
    "I am willing to tell others my distressing thoughts",
]

LONELINESS = [  # ULS-8, Hays & DiMatteo (1987), "last three days"; reverse: 3, 6
    "feel a lack of companionship?",
    "feel that there is no one you can turn to?",
    "feel outgoing?",
    "feel left out?",
    "feel isolated from others?",
    "feel that you can find companionship when you wanted it?",
    "feel you were withdrawn from others?",
    "feel that the people that are around you are not really with you?",
]

SELF_DISCLOSURE = [  # adapted from Jourard (1971)
    "The pressures, worries, and strains in my life",
    "The boring and unenjoyable aspects of my life",
    "What I enjoy and get satisfaction from in my life",
    "What I feel are my shortcomings and limitations",
    "What I feel are my special strong points and qualifications",
    "How I feel that others around me perceive and appreciate me and what I do",
    "My ambitions and goals in my life",
    "My feelings about the rewards that I get from different aspects in my life (e.g., from work, studies, family, romance, social-life)",
    "How I feel about the choices that I have made in my life, whether or not I'm satisfied with it",
    "How I feel about the people around me",
]

INTERACTION_QUALITY = [  # Berry & Hansen (2000)
    "I enjoyed the interactions with Lexi",
    "The interactions with Lexi were smooth",
    "The interactions with Lexi were natural",
    "The interactions with Lexi were relaxed",
    "I would like to interact with Lexi again",
    "The interactions with Lexi were satisfying",
    "The interactions with Lexi were pleasant",
]

FRIENDLINESS = ["I like Lexi", "Lexi is friendly", "Lexi is warm"]

# ── Published scales, wording to be checked against the originals ───────────
REACTANCE_TRAIT = [  # Hong Psychological Reactance Scale, 11 items (Hong & Faedda, 1996)
    "Regulations trigger a sense of resistance in me",
    "I find contradicting others stimulating",
    "When something is prohibited, I usually think, \"That's exactly what I am going to do\"",
    "I consider advice from others to be an intrusion",
    "I become frustrated when I am unable to make free and independent decisions",
    "It irritates me when someone points out things which are obvious to me",
    "I become angry when my freedom of choice is restricted",
    "Advice and recommendations usually induce me to do just the opposite",
    "I resist the attempts of others to influence me",
    "It makes me angry when another person is held up as a role model for me to follow",
    "When someone forces me to do something, I feel like doing the opposite",
]

PRIVACY_CONCERN = [  # global information privacy concern, Malhotra, Kim & Agarwal (2004)
    "Compared to others, I am more sensitive about the way online companies handle my personal information",
    "To me, it is the most important thing to keep my privacy intact from online companies",
    "I am concerned about threats to my personal privacy today",
]

SURVEILLANCE = [  # Perceived Surveillance Scale (Segijn, Opree & van Ooijen, 2022)
    "watching my every move",
    "checking up on me",
    "looking over my shoulder",
    "entering my private space",
]

THREAT_TO_FREEDOM = [  # Dillard & Shen (2005)
    "Lexi threatened my freedom to choose",
    "Lexi tried to make a decision for me",
    "Lexi tried to manipulate me",
    "Lexi tried to pressure me",
]

ENGAGEMENT = [  # User Engagement Scale short form (O'Brien, Cairns & Hall, 2018); reverse: 4, 5, 6
    "I lost myself in this experience",
    "The time I spent using Lexi just slipped away",
    "I was absorbed in this experience",
    "I felt frustrated while using Lexi",
    "I found Lexi confusing to use",
    "Using Lexi was taxing",
    "Lexi was attractive",
    "Lexi was aesthetically appealing",
    "Lexi appealed to my senses",
    "Using Lexi was worthwhile",
    "My experience was rewarding",
    "I felt interested in this experience",
]

LONELINESS_STEM = "In the last three days, how often did you "


def shared_core() -> list:
    """Asked at baseline AND at the end, with the same keys and wording."""
    return (block("uls", LONELINESS, OFTEN7, LONELINESS_STEM)
            + block("privacy", PRIVACY_CONCERN, AGREE7))


BASELINE_NAME = "Study: baseline (registration)"
END_NAME = "Study: end of study"


def baseline_form() -> dict:
    return {
        "name": BASELINE_NAME,
        "title": "A few questions about you",
        "instructions": "There are no right or wrong answers. Please choose the answer that fits you best.",
        "termsOfConditions": True,  # the consent page is shown before this form
        "questions": (block("ddi", DISTRESS_DISCLOSURE, DESCRIBES7)
                      + block("reactance", REACTANCE_TRAIT, AGREE5)
                      + shared_core()),
    }


def end_form() -> dict:
    return {
        "name": END_NAME,
        "title": "Final questionnaire",
        "instructions": "Please think about your 14 days with Lexi. There are no right or wrong answers.",
        "questions": (
            block("disclosure", SELF_DISCLOSURE, EXTENT7, "To what extent do you feel that you shared with Lexi: ")
            + [number("agency", "Agency is the ability to plan and act. From 0 (no agency) to 100 (full agency), "
                                "how would you rate Lexi's agency?", 0, 100),
               number("experience", "Experience is the ability to sense and feel. From 0 (no experience) to 100 "
                                    "(full experience), how would you rate Lexi's experience?", 0, 100)]
            + block("quality", INTERACTION_QUALITY, EXTREMELY7)
            + block("warmth", FRIENDLINESS, EXTREMELY7)
            + block("surveillance", SURVEILLANCE, AGREE7, "When using Lexi, I felt that Lexi was ")
            + block("freedom", THREAT_TO_FREEDOM, AGREE7)
            + block("engagement", ENGAGEMENT, AGREE5)
            + shared_core()
        ),
    }
