from dataclasses import dataclass, field
import yaml
from .redaction import censor

_FM = "---"


@dataclass
class ParsedWriteup:
    source_key: str
    challenge_ref: str
    title: str
    author: str | None
    sort_order: int
    tags: list[str] = field(default_factory=list)
    language: str | None = None
    visible: bool = True
    uncensored_body: str = ""
    censored_body: str = ""
    ok: bool = True


def _split_frontmatter(text: str):
    stripped = text.lstrip()
    if not stripped.startswith(_FM):
        return None, text
    rest = stripped[len(_FM):]
    end = rest.find("\n" + _FM)
    if end == -1:
        return None, text
    fm = rest[:end]
    body = rest[end + len("\n" + _FM):].lstrip("\n")
    try:
        data = yaml.safe_load(fm) or {}
    except yaml.YAMLError:
        return None, text
    if not isinstance(data, dict):
        return None, text
    return data, body


def parse_writeup_file(text: str, source_key: str) -> ParsedWriteup:
    data, body = _split_frontmatter(text)
    ok = True
    if data is None:
        data = {}
        ok = False  # missing/invalid frontmatter -> quarantine upstream

    tags = data.get("tags") or []
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",") if t.strip()]

    c = censor(body)
    if not c.ok:
        ok = False

    return ParsedWriteup(
        source_key=source_key,
        challenge_ref=str(data.get("challenge", "")).strip(),
        title=str(data.get("title", "")).strip(),
        author=(str(data["author"]).strip() if data.get("author") else None),
        sort_order=int(data.get("sort_order", 0) or 0),
        tags=[str(t) for t in tags],
        language=(str(data["language"]) if data.get("language") else None),
        visible=bool(data.get("visible", True)),
        uncensored_body=body,
        censored_body=c.censored,
        ok=ok,
    )
