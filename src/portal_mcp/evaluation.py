"""MIS Teaching & Learning Evaluation: read a questionnaire and work out the "best" answers."""
import re

from .portal import _text

# Answer scales, lowest to highest. A question is auto-answered only when all its options belong to one known
# scale, so "highest" comes from the option wording, never from the order or ids in the page.
SCALES = [s.split("|") for s in (
    "strongly disagree|disagree|neutral|agree|strongly agree",
    "poor|acceptable|satisfactory|good|very good",
    "very poor|poor|fair|good|very good|excellent",
    "very dissatisfied|dissatisfied|neutral|satisfied|very satisfied")]

_TOKEN = re.compile(r'class="te_part_title">(?P<q>.*?)</div>|<input(?P<r>[^>]*type="radio"[^>]*)>(?P<l>[^<]*)'
                    r'|<textarea(?P<t>[^>]*)>', re.S | re.I)


def parse_form(page: str) -> dict:
    page = re.sub(r"<!--.*?-->", "", page, flags=re.S)
    info = lambda cls, prefix: re.sub("^" + prefix, "", _text((re.search(cls + r'">(.*?)</div>', page, re.S) or [0, ""])[1])).strip()
    attr = lambda tag, name: (re.search(name + r'="([^"]*)"', tag, re.I) or [0, ""])[1]
    questions, texts, title = {}, [], ""
    for m in _TOKEN.finditer(page):
        if m["q"] is not None:
            title = _text(m["q"])
        elif m["r"]:
            q = questions.setdefault(attr(m["r"], "name"), {"text": title, "options": []})
            q["options"].append({"value": attr(m["r"], "value"), "label": _text(m["l"])})
        else:
            texts.append({"name": attr(m["t"], "name"), "label": title, "required": "datatype=\"require" in m["t"].lower()})
    return {"course": info("te_info_title_a", r"Course/Section\s*:"), "semester": info("te_info_title_d", "Academic Year & Semester:"),
            "questions": [{"name": n, **q} for n, q in questions.items()], "texts": texts}


def best_option(options: list[dict]) -> dict | None:
    labels = [o["label"].lower() for o in options]
    scale = next((s for s in SCALES if set(labels) <= set(s)), None)
    return options[labels.index(max(labels, key=scale.index))] if scale and labels else None


def build_plan(form: dict, comment: str = "") -> dict:
    """What would be submitted. Anything unusual is listed in `problems` and blocks submission."""
    problems = [] if form["questions"] else ["The questionnaire is empty or closed."]
    answers, payload = {}, {}
    for q in form["questions"]:
        opt = best_option(q["options"])
        answers[q["text"]] = opt["label"] if opt else None
        if opt:
            payload[q["name"]] = opt["value"]
        else:
            problems.append("Cannot rank the options of: " + q["text"][:60])
    for t in form["texts"]:
        payload[t["name"]] = comment
        if t["required"] and not comment:
            problems.append(f"'{t['label'][:60]}' is required: pass comment=...")
    return {"answers": answers, "comment": comment, "problems": problems, "payload": {**payload, "Submit": "submit"}}
