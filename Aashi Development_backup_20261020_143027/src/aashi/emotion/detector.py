"""Rule-based context detector: which mood fits this message?

Pure Python, deterministic, no network and no model call. It reads only the
user's latest message (plus the temporary, in-memory :class:`Session`) and
returns an :class:`~aashi.emotion.emotions.EmotionContext`.

Design rules
------------
* **Conservative.** An unrecognised message is neutral/focused and gets no
  personality at all, so ordinary and technical questions behave exactly as
  they did before the emotion layer existed.
* **Context, not keywords alone.** Achievement beats technical vocabulary ("I
  fixed the bug!" is a celebration, not a debugging request); "my build failed"
  is technical while "I failed my exam" is personal.
* **English + Hinglish**, since Kartik writes both.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

from aashi.emotion.emotions import NEUTRAL, ContextKind, Emotion, EmotionContext

__all__ = ["STRESS_MEMORY_TURNS", "Session", "detect"]

STRESS_MEMORY_TURNS: Final[int] = 3
"""How many later turns a stressed mood is carried (this conversation only)."""


@dataclass
class Session:
    """Temporary, in-memory mood context for the current conversation only.

    Never written to disk or the database: it is created with the chat window
    and cleared whenever the chat changes. ("Stressed today" must not become
    "Kartik is always stressed".)
    """

    stressed_turns_left: int = 0

    def reset(self) -> None:
        """Forget everything about the current mood."""
        self.stressed_turns_left = 0


def _rx(*alternatives: str) -> re.Pattern[str]:
    return re.compile("|".join(alternatives), re.IGNORECASE)


_LAUGH = _rx(r"😂", r"🤣", r"😜", r"😝", r"😛", r"😆", r"😹", r"\blol\b", r"\blmao\b",
             r"\bha(?:ha)+\b", r"\bhehe+\b", r"\bjk\b")
_INSULT = _rx(r"\buseless\b", r"\bstupid\b", r"\bdumb\b", r"\bidiot\b", r"\bnoob\b",
              r"\bbekar\b", r"\bbakwas\b", r"\bpagal\b", r"\bnikamm?a\b", r"\byou suck\b",
              r"\bworst\b", r"\bkuch nahi (?:aata|jaan)", r"\bbilkul bekar\b")
_TEASE = _rx(r"\bbada aaya\b", r"\bchal na\b", r"\bnice try\b", r"\btu bhi na\b",
             r"\btum bhi na\b", r"\bkuch bhi\b", r"\bacha ji\b", r"\bachha ji\b")
_SARCASM = _rx(r"🙄", r"\bwah ji wah\b", r"\bwow,? (?:so|very) (?:smart|clever)\b",
               r"\boh really\b", r"\bsure,? sure\b", r"\bvery impressive\b")
_CUTE = _rx(r"🥺", r"🥹", r"\bhmph+\b", r"\baww+\b", r"\bpls pls\b", r"\bplease please\b")

_CRISIS = _rx(r"\bkill myself\b", r"\bend (?:my|it all)\b", r"\bwant to die\b", r"\bsuicid",
              r"\bself[- ]?harm\b", r"\bhurt myself\b", r"\bno reason to live\b",
              r"\bmarna chahta\b", r"\bjeena nahi\b", r"\bdon'?t want to (?:live|be here)\b")
_GRIEF = _rx(r"\b(?:my )?(?:dog|cat|pet|grandfather|grandmother|dadi|dada|nani|nana|friend|father|"
             r"mother|papa|mummy)\b.{0,25}\b(?:died|passed away|is no more|expired)\b",
             r"\bbroke up\b", r"\bbreakup\b", r"\bheartbroken\b", r"\bdil toot\b")
_CORRECTION = _rx(r"\byou(?:'re| are) (?:wrong|incorrect|mistaken)\b", r"\bthat(?:'s| is) (?:wrong|incorrect|not right)\b",
                  r"\bthis is (?:wrong|incorrect)\b", r"\bwrong answer\b", r"\byou made a mistake\b",
                  r"\bnot what i asked\b", r"\bgalat\b", r"\bsahi nahi\b", r"\btumne galat\b",
                  r"\bthat(?:'s| is) not (?:correct|true)\b", r"\byou got (?:it|that) wrong\b")
_DISTRESS = _rx(r"\bstress(?:ed|ful)?\b", r"\banxi(?:ous|ety)\b", r"\bpanic", r"\boverwhelm",
                r"\bcan'?t (?:take|handle|cope|do this)\b", r"\bdepress", r"\bhopeless\b",
                r"\blonely\b", r"\bscared\b", r"\bafraid\b", r"\bworried\b", r"\bupset\b",
                r"\bcrying\b", r"\bpareshaa?n\b", r"\bghabra", r"\budaas\b", r"\btension\b",
                r"\bfrustrat", r"\bnothing (?:is )?work", r"\bi give up\b", r"\bfed up\b",
                r"\btang aa\b", r"\birritat", r"\bso annoying\b", r"\bugh+\b", r"\bburn(?:t|ed)? out\b",
                r"\bfeeling (?:low|down|sad|bad)\b", r"\bbura lag\b", r"\bsad\b")
_CARING = _rx(r"\btired\b", r"\bexhausted\b", r"\bsleepy\b", r"\bsleepless\b", r"\bno sleep\b",
              r"\bdidn'?t sleep\b", r"\bsick\b", r"\bfever\b", r"\bheadache\b", r"\bunwell\b",
              r"\bnot feeling well\b", r"\bthak(?:a|e|i)\b", r"\bbimaa?r\b", r"\bbukhaa?r\b",
              r"\btabiyat\b", r"\bsar dard\b", r"\bhaven'?t eaten\b", r"\bskipped (?:lunch|dinner|breakfast)\b",
              r"\bmissing home\b", r"\bghar ki yaad\b")
_FAILURE = _rx(r"\bi failed\b", r"\bfailed (?:my|the|in) (?:exam|interview|class|course|subject|paper|semester|viva|test at school)\b",
               r"\bfail ho (?:gaya|gayi)\b", r"\b(?:didn'?t|did not) pass\b", r"\bgot rejected\b",
               r"\brejected me\b", r"\b(?:not|didn'?t get) selected\b", r"\bbad marks\b", r"\blow marks\b",
               r"\bdisappoint", r"\bdemotivat", r"\bi (?:messed|screwed) up\b", r"\bgalti ho gayi\b",
               r"\bi lost (?:the|my) (?:match|game|chance|job|competition)\b")
_ACH_MILESTONE = _rx(r"\blaunched\b", r"\bdeployed\b", r"\bshipped\b", r"\bmilestone\b",
                     r"\bgot (?:selected|placed|promoted)\b", r"\bgot the job\b", r"\bi passed\b",
                     r"\bcleared (?:the|my) (?:exam|interview|round)\b", r"\bcompleted the project\b")
_ACH_WORKED = _rx(r"\bit worked\b", r"\bit works now\b", r"\bworks now\b", r"\bfinally work",
                  r"\bgot it working\b", r"\bfixed (?:the|that|my|this|it)\b", r"\bi fixed\b",
                  r"\bi (?:finally )?(?:did|solved|cracked|built|made) it\b", r"\bsolved it\b",
                  r"\bho gaya\b", r"\bho gayi\b", r"\bban gaya\b", r"\bchal gaya\b", r"\bcracked (?:it|the)\b")
_ACH_PROUD = _rx(r"\bmy score improved\b", r"\bimproved (?:a lot|my)\b", r"\bgot better\b",
                 r"\btopped\b", r"\bfirst (?:rank|place)\b", r"\bi won\b", r"\bfinished (?:my|the)\b")
_EXCITED = _rx(r"\bomg\b", r"\byo{3,}\b", r"\blet'?s go{2,}\b", r"\bcan'?t wait\b", r"\bso excited\b",
               r"\bi'?m excited\b", r"\bamazing news\b", r"\bguess what\b")
_STUDY = _rx(r"\bstudy(?:ing)?\b", r"\bexams?\b", r"\bhomework\b", r"\bassignment\b", r"\brevis(?:e|ion)\b",
             r"\bsyllabus\b", r"\bchapter\b", r"\bteach me\b", r"\bquiz me\b",
             r"\bpractice (?:questions?|problems?)\b", r"\bpadhai\b", r"\bsamjha(?:o|na| do)\b",
             r"\bdoubt hai\b", r"\bi(?:'m| am) learning\b", r"\blearn (?:about|how|to)\b", r"\bmy class\b",
             r"\bviva\b", r"\bsemester\b")
_CURIOUS = _rx(r"\bi wonder\b", r"\bcurious\b", r"\bjust wondering\b", r"\brandom question\b",
               r"\bkya hota agar\b", r"\bout of curiosity\b", r"\bfun fact\b",
               r"\btell me something (?:interesting|cool)\b")
_CONCERN = _rx(r"\b(?:deleted|overwrote|overwritten|lost) (?:all )?(?:my|the) (?:files?|data|work|code|database|project)\b",
               r"\bproduction (?:is )?down\b", r"\bserver (?:is )?down\b", r"\bdata loss\b",
               r"\bapi key (?:leaked|exposed|got leaked)\b", r"\bpassword (?:leaked|exposed)\b")
_CHILL = _rx(r"\bbored\b", r"\bnothing much\b", r"\btimepass\b", r"\bkya scene\b", r"\bfree hu\b",
             r"\bjust chilling\b", r"\bkya kar (?:rahi|raha|rahe)\b")
_TECH = _rx(r"```", r"`[^`]+`", r"\bpython\b", r"\bjava(?:script)?\b", r"\bc\+\+\b", r"\brust\b",
            r"\bsql\b", r"\bhtml\b", r"\bcss\b", r"\breact\b", r"\bapi\b", r"\bjson\b", r"\bgit\b",
            r"\bdocker\b", r"\blinux\b", r"\bbash\b", r"\bregex\b", r"\bfunction\b", r"\bclass\b",
            r"\bvariable\b", r"\bloop\b", r"\barray\b", r"\bdecorator", r"\balgorithm", r"\brecursion\b",
            r"\bcompile", r"\bexception\b", r"\berror\b", r"\btraceback\b", r"\bstack\b", r"\bdatabase\b",
            r"\bserver\b", r"\binstall", r"\bpip\b", r"\bnpm\b", r"\blibrary\b", r"\bframework\b",
            r"\bsyntax\b", r"\bdebug", r"\bbug\b", r"\bcode\b", r"\bscript\b", r"\bprogram", r"\.py\b",
            r"\bdef \w+\(", r"\bimport \w+")

# Casual conversation with Aashi herself: addressing her, or chatting in Hinglish / social English.
_ADDRESS = _rx(r"\byou\b", r"\byour\b", r"\bu\b", r"\bur\b", r"\baashi\b", r"\btum\b", r"\btu\b",
               r"\btumhe\b", r"\btumhara\b", r"\btumhari\b", r"\btumse\b", r"\btera\b", r"\bteri\b",
               r"\btujhe\b", r"\baap\b", r"\baapko\b", r"\baapki\b")
_CHAT_MARKERS = _rx(r"\byaar\b", r"\barre\b", r"\bkaise\b", r"\bkaisi\b", r"\bkaisa\b", r"\bkyun\b", r"\bkyu\b",
                    r"\bbatao\b", r"\bbata\b", r"\bsuno\b", r"\bsunao\b", r"\brhi\b", r"\brahi\b", r"\brhe\b",
                    r"\brahe\b", r"\bmujhe\b", r"\bmera\b", r"\bmeri\b", r"\bhaan\b", r"\bnahi\b", r"\bnhi\b",
                    r"\bgossip\b", r"\bkya kar\b", r"\bi (?:feel|miss|love|hate|think|wish|want|like)\b",
                    r"\bdo you\b", r"\bare you\b", r"\bhow'?s your\b", r"\btell me about yourself\b",
                    r"\blikh rhi\b", r"\bbaat kar\b", r"\bbol rhi\b", r"\bbol rahi\b")
# A request for an explanation / list / write-up: these keep their structure.
_STRUCTURED_REQUEST = _rx(r"\bexplain\b", r"\bsteps?\b", r"\bstep by step\b", r"\bcompare\b",
                          r"\bdifference between\b", r"\bsummari[sz]e\b", r"\bsummary\b", r"\btutorial\b",
                          r"\bhow (?:to|do|does|can|should)\b", r"\bdefine\b", r"\bexamples?\b",
                          r"\bwrite (?:a|an|me|the)\b", r"\bplan\b", r"\bguide\b", r"\btable\b", r"\bflowchart\b",
                          r"\bdiagram\b", r"\bworkflow\b", r"\bpipeline\b", r"\barchitecture\b", r"\bpoints?\b",
                          r"\bbullets?\b", r"\boutline\b", r"\bvs\b", r"\bpros and cons\b", r"\blist of\b",
                          r"\bcode\b", r"\bconvert\b", r"\btranslate\b")
_QUESTION_WORD = re.compile(r"^(?:what|why|how|which|when|where|who)\b", re.IGNORECASE)
_CHAT_MAX_CHARS = 240

_GREETING = re.compile(
    r"^(?:hi+|hey+|heyy+|hello+|hii+|yo+|hola|oye|hlo|helo|namaste|namaskar|sup|wass?up|gm|gn|"
    r"good (?:morning|afternoon|evening|night)|what'?s up|whats up)"
    r"(?: aashi| there| buddy| yaar| dost| everyone)?$",
    re.IGNORECASE,
)
_SMALLTALK = re.compile(
    r"^(?:how are you|how r u|how'?s it going|how are you doing|kaise ho|kaisi ho|kya haal(?: hai)?|"
    r"kaise ho aashi|kaisi ho aashi|how'?s your day)(?: aashi| today)?$",
    re.IGNORECASE,
)
_GRATITUDE = re.compile(
    r"^(?:ok(?:ay)? )?(?:thanks|thank you|thankyou|thx|ty|shukriya|dhanyavaad|thanks a lot|thank you so much)"
    r"(?: aashi| yaar)?$",
    re.IGNORECASE,
)
_NON_WORD_EDGES = re.compile(r"^[\W_]+|[\W_]+$")


def _bare(text: str) -> str:
    """Lower-cased message with punctuation / emoji trimmed off both ends."""
    return _NON_WORD_EDGES.sub("", text.strip().lower())


def _ctx(emotion: Emotion, kind: ContextKind, *secondary: Emotion, **flags: bool) -> EmotionContext:
    return EmotionContext(emotion, kind, tuple(secondary), expressive=True, **flags)


def detect(message: str, session: Session | None = None) -> EmotionContext:
    """Decide which mood fits ``message``.

    Args:
        message: The user's latest message, exactly as typed.
        session: Temporary in-memory context for this conversation. It is
            updated here (a stressed mood is remembered for a few turns).

    Returns:
        The detected context. For ordinary and technical messages it is
        non-expressive, meaning "do not touch the prompt or the reply".
    """
    session = session if session is not None else Session()
    text = (message or "").strip()
    if not text:
        return NEUTRAL

    has_laugh = bool(_LAUGH.search(text))
    technical = bool(_TECH.search(text))
    bare = _bare(text)

    def stressed(ctx: EmotionContext) -> EmotionContext:
        session.stressed_turns_left = STRESS_MEMORY_TURNS
        return ctx

    # 1. Safety first: a person in real distress is never joked with.
    if _CRISIS.search(text):
        return stressed(_ctx(Emotion.EMPATHETIC, ContextKind.CRISIS, Emotion.CARING, Emotion.CALM, serious=True, plain=True))
    if _GRIEF.search(text):
        return stressed(_ctx(Emotion.EMPATHETIC, ContextKind.COMFORTING, Emotion.COMFORTING, serious=True, plain=True))

    # 2. Playful banter (a laugh marker with teasing/insult), before the plain-correction check.
    if has_laugh and (_INSULT.search(text) or _TEASE.search(text)):
        return _ctx(Emotion.PLAYFUL, ContextKind.PLAYFUL, Emotion.MILD_GUSSA, Emotion.CUTE, plain=True)
    if _SARCASM.search(text):
        return _ctx(Emotion.SARCASTIC, ContextKind.PLAYFUL, Emotion.PLAYFUL, plain=True)

    # 3. The user says Aashi is wrong.
    if _CORRECTION.search(text):
        return _ctx(Emotion.APOLOGETIC, ContextKind.CORRECTION, Emotion.FOCUSED)

    # 4. Stress / frustration, tiredness, personal failure.
    if _DISTRESS.search(text):
        return stressed(_ctx(Emotion.COMFORTING, ContextKind.COMFORTING, Emotion.CALM, Emotion.CARING, plain=not technical))
    if _CARING.search(text):
        return _ctx(Emotion.CARING, ContextKind.CARING, Emotion.COMFORTING, plain=True)
    if _FAILURE.search(text):
        return _ctx(Emotion.MOTIVATIONAL, ContextKind.MOTIVATIONAL, Emotion.COMFORTING, Emotion.TEACHER, plain=True)

    # 5. Good news. Beats technical vocabulary: "I fixed the bug!" is a celebration.
    if _ACH_MILESTONE.search(text):
        session.stressed_turns_left = 0
        return _ctx(Emotion.CELEBRATORY, ContextKind.ACHIEVEMENT, Emotion.EXCITED, Emotion.PROUD, plain=True)
    if _ACH_WORKED.search(text):
        session.stressed_turns_left = 0
        return _ctx(Emotion.EXCITED, ContextKind.ACHIEVEMENT, Emotion.PROUD, plain=True)
    if _ACH_PROUD.search(text):
        session.stressed_turns_left = 0
        return _ctx(Emotion.PROUD, ContextKind.ACHIEVEMENT, Emotion.EXCITED, plain=True)

    # 6. Alarm about something genuinely wrong: practical, not dramatic.
    if _CONCERN.search(text):
        return _ctx(Emotion.CONCERNED, ContextKind.TECHNICAL, Emotion.CALM, Emotion.FOCUSED)

    # 7. Casual playfulness (only when it is not a technical message).
    if (has_laugh and not technical) or _TEASE.search(text) or _INSULT.search(text) and not technical:
        return _ctx(Emotion.PLAYFUL, ContextKind.PLAYFUL, Emotion.FRIENDLY, plain=True)
    if _CUTE.search(text):
        return _ctx(Emotion.CUTE, ContextKind.PLAYFUL, Emotion.FRIENDLY, plain=True)

    # 8. Studying / learning.
    if _STUDY.search(text):
        return _ctx(Emotion.TEACHER, ContextKind.STUDY, Emotion.CURIOUS)

    # 9. Excitement and curiosity.
    if _EXCITED.search(text):
        return _ctx(Emotion.EXCITED, ContextKind.CASUAL, Emotion.FRIENDLY, plain=True)
    if _CURIOUS.search(text) and not technical:
        return _ctx(Emotion.CURIOUS, ContextKind.CASUAL, Emotion.FRIENDLY, plain=True)

    # 10. Greetings, small talk, thanks and plain chilling: only when that is the WHOLE message.
    if _GREETING.match(bare) or _SMALLTALK.match(bare):
        return _ctx(Emotion.FRIENDLY, ContextKind.CASUAL, Emotion.CHILL, greeting=True, plain=True)
    if _GRATITUDE.match(bare):
        return _ctx(Emotion.FRIENDLY, ContextKind.CASUAL, Emotion.CHILL, greeting=True, plain=True)
    if _CHILL.search(text) and not technical:
        return _ctx(Emotion.CHILL, ContextKind.CASUAL, Emotion.FRIENDLY, plain=True)

    # 11. Everyday conversation with Aashi herself ("ye kaise baat kar rhi ho?"): a short
    #     message that addresses her or chats in Hinglish, and is not a request for an
    #     explanation, a list or code. It should read like a person texting.
    if (
        not technical
        and len(text) <= _CHAT_MAX_CHARS
        and not _STRUCTURED_REQUEST.search(text)
        and (not _QUESTION_WORD.match(text) or _ADDRESS.search(text))
        and (_ADDRESS.search(text) or _CHAT_MARKERS.search(text))
    ):
        return _ctx(Emotion.FRIENDLY, ContextKind.CASUAL, Emotion.CHILL, plain=True)

    # 12. Nothing recognised. Technical or neutral work stays neutral (no note, no opener) ...
    kind = ContextKind.TECHNICAL if technical else ContextKind.OTHER
    # ... except that a stressed mood from a moment ago is carried gently.
    if session.stressed_turns_left > 0:
        session.stressed_turns_left -= 1
        return EmotionContext(Emotion.CALM, kind, (Emotion.FOCUSED,), expressive=True, carried=True)
    return EmotionContext(Emotion.FOCUSED, kind)
