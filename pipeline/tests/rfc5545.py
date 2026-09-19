"""A small, strict RFC 5545 reader for tests, written without icalendar.

The feeds are generated with `icalendar`, and `validate_ics` reads them back
with the same library, so a bug in that library's serializer could be
invisible to both. This module reads the raw bytes the way the RFC's grammar
does (sections 3.1 to 3.3, 3.6.1), independently, and raises RFC5545Error on
the first thing a strict client could reject:

- lines end in CRLF, and no bare CR or LF appears anywhere else;
- no physical line is longer than 75 octets, and every physical line is valid
  UTF-8 on its own, so a fold never splits a multi-byte character;
- unfolding (CRLF then one space or tab) yields `NAME[;PARAM=VALUE]:VALUE`
  content lines with no control characters;
- BEGIN/END nest and match, with one VCALENDAR outermost;
- TEXT values escape backslash, comma, semicolon and newline;
- a VEVENT has UID, DTSTAMP (UTC) and DTSTART, no once-only property twice,
  not both DTEND and DURATION, and a STATUS from the event value set.

It is not a full validator (no RRULE, no value-type checks for every
property); it checks what this feed emits.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime

CONTENT_LINE = re.compile(
    r"^(?P<name>[A-Za-z0-9-]+)"
    r'(?P<params>(?:;[A-Za-z0-9-]+=(?:"[^"]*"|[^";:,]*)(?:,(?:"[^"]*"|[^";:,]*))*)*)'
    r":(?P<value>.*)$"
)
CONTROL = re.compile(r"[\x00-\x08\x0a-\x1f\x7f]")
UTC_DATE_TIME = re.compile(r"^\d{8}T\d{6}Z$")
LOCAL_DATE_TIME = re.compile(r"^\d{8}T\d{6}$")
DATE_ONLY = re.compile(r"^\d{8}$")

# Properties whose value type is TEXT (RFC 5545 section 3.3.11, RFC 7986 for
# NAME). The X-WR-CALNAME and X-WR-CALDESC extensions are deliberately not
# here: no RFC defines them, and the feeds write them without escaping
# commas (their RFC 7986 twins NAME and DESCRIPTION are escaped).
TEXT_PROPERTIES = frozenset({"SUMMARY", "DESCRIPTION", "LOCATION", "COMMENT", "UID", "TZID", "TZNAME", "NAME"})
# RFC 5545 section 3.6.1: each of these MAY occur once in a VEVENT, no more.
VEVENT_ONCE_ONLY = frozenset(
    {
        "DTSTAMP",
        "UID",
        "DTSTART",
        "CLASS",
        "CREATED",
        "DESCRIPTION",
        "GEO",
        "LAST-MODIFIED",
        "LOCATION",
        "ORGANIZER",
        "PRIORITY",
        "SEQUENCE",
        "STATUS",
        "SUMMARY",
        "TRANSP",
        "URL",
        "RECURRENCE-ID",
        "DTEND",
        "DURATION",
    }
)
VEVENT_STATUS_VALUES = frozenset({"TENTATIVE", "CONFIRMED", "CANCELLED"})


class RFC5545Error(ValueError):
    pass


@dataclass
class Prop:
    name: str
    params: str
    value: str

    def param(self, name: str) -> str | None:
        for part in self.params.split(";"):
            if part.upper().startswith(name.upper() + "="):
                return part.split("=", 1)[1].strip('"')
        return None


@dataclass
class Component:
    name: str
    props: list[Prop] = field(default_factory=list)
    children: list[Component] = field(default_factory=list)

    def first(self, name: str) -> Prop | None:
        return next((p for p in self.props if p.name == name), None)

    def all(self, name: str) -> list[Prop]:
        return [p for p in self.props if p.name == name]

    def walk(self, name: str) -> list[Component]:
        found = [self] if self.name == name else []
        for child in self.children:
            found.extend(child.walk(name))
        return found


def unescape_text(value: str) -> str:
    """A TEXT value with its escapes resolved; RFC5545Error on an unescaped
    comma or semicolon, or a backslash that is not a valid escape."""
    out: list[str] = []
    i = 0
    while i < len(value):
        ch = value[i]
        if ch == "\\":
            if i + 1 >= len(value) or value[i + 1] not in "\\;,nN":
                raise RFC5545Error(f"invalid TEXT escape in {value!r}")
            nxt = value[i + 1]
            out.append("\n" if nxt in "nN" else nxt)
            i += 2
            continue
        if ch in ",;":
            raise RFC5545Error(f"unescaped {ch!r} in TEXT value {value!r}")
        out.append(ch)
        i += 1
    return "".join(out)


def _unfold(raw: bytes) -> list[str]:
    if not raw.endswith(b"\r\n"):
        raise RFC5545Error("the stream does not end in CRLF")
    physical = raw[:-2].split(b"\r\n")
    lines: list[str] = []
    for number, chunk in enumerate(physical, start=1):
        if b"\r" in chunk or b"\n" in chunk:
            raise RFC5545Error(f"line {number}: bare CR or LF")
        if len(chunk) > 75:
            raise RFC5545Error(f"line {number}: {len(chunk)} octets, more than 75")
        try:
            text = chunk.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise RFC5545Error(f"line {number}: not valid UTF-8 on its own (a fold split a character?)") from exc
        if text[:1] in (" ", "\t"):
            if not lines:
                raise RFC5545Error("the first line is a continuation")
            lines[-1] += text[1:]
        else:
            lines.append(text)
    return lines


def _open(stack: list[Component], root: Component | None, name: str) -> Component:
    comp = Component(name)
    if stack:
        stack[-1].children.append(comp)
    elif root is not None:
        raise RFC5545Error("more than one top-level component")
    elif name != "VCALENDAR":
        raise RFC5545Error(f"top-level component is {name}, not VCALENDAR")
    return comp


def _close(stack: list[Component], name: str) -> None:
    if not stack or stack[-1].name != name:
        raise RFC5545Error(f"END:{name} does not close {stack[-1].name if stack else 'anything'}")
    stack.pop()


def parse(raw: bytes) -> Component:
    """The VCALENDAR in raw, as a tree; RFC5545Error on any violation."""
    stack: list[Component] = []
    root: Component | None = None
    for line in _unfold(raw):
        if CONTROL.search(line):
            raise RFC5545Error(f"control character in {line[:40]!r}")
        match = CONTENT_LINE.match(line)
        if not match:
            raise RFC5545Error(f"not a content line: {line[:60]!r}")
        name, params, value = match["name"].upper(), match["params"], match["value"]
        if name == "BEGIN":
            comp = _open(stack, root, value.upper())
            root = root or comp
            stack.append(comp)
        elif name == "END":
            _close(stack, value.upper())
        elif not stack:
            raise RFC5545Error(f"property {name} outside any component")
        else:
            if name in TEXT_PROPERTIES:
                unescape_text(value)
            stack[-1].props.append(Prop(name, params, value))
    if stack or root is None:
        raise RFC5545Error("unterminated component" if stack else "no VCALENDAR")
    _check_calendar(root)
    return root


def _check_calendar(cal: Component) -> None:
    for required in ("VERSION", "PRODID"):
        if cal.first(required) is None:
            raise RFC5545Error(f"VCALENDAR is missing {required}")
    defined_zones = {unescape_text(tz.first("TZID").value) for tz in cal.walk("VTIMEZONE") if tz.first("TZID")}
    for vevent in cal.walk("VEVENT"):
        _check_vevent(vevent, defined_zones)


def _check_vevent(vevent: Component, defined_zones: set[str]) -> None:
    uid = vevent.first("UID")
    label = f"VEVENT {uid.value if uid else '?'}"
    for name in VEVENT_ONCE_ONLY:
        if len(vevent.all(name)) > 1:
            raise RFC5545Error(f"{label}: {name} occurs more than once")
    stamp, start = vevent.first("DTSTAMP"), vevent.first("DTSTART")
    if uid is None or stamp is None or start is None:
        raise RFC5545Error(f"{label}: missing UID, DTSTAMP or DTSTART")
    if vevent.first("DTEND") and vevent.first("DURATION"):
        raise RFC5545Error(f"{label}: both DTEND and DURATION")
    if not UTC_DATE_TIME.match(stamp.value):
        raise RFC5545Error(f"{label}: DTSTAMP {stamp.value!r} is not a UTC date-time")
    datetime.strptime(stamp.value, "%Y%m%dT%H%M%SZ")
    _check_dtstart(label, start, defined_zones)
    end = vevent.first("DTEND")
    if end is not None and (end.param("VALUE"), end.param("TZID")) != (start.param("VALUE"), start.param("TZID")):
        raise RFC5545Error(f"{label}: DTEND is not the same value type and zone as DTSTART")
    status = vevent.first("STATUS")
    if status is not None and status.value not in VEVENT_STATUS_VALUES:
        raise RFC5545Error(f"{label}: STATUS {status.value!r} is not TENTATIVE, CONFIRMED or CANCELLED")


def _check_dtstart(label: str, start: Prop, defined_zones: set[str]) -> None:
    if start.param("VALUE") == "DATE":
        if not DATE_ONLY.match(start.value):
            raise RFC5545Error(f"{label}: DTSTART;VALUE=DATE {start.value!r} is not a date")
        datetime.strptime(start.value, "%Y%m%d")
        return
    if UTC_DATE_TIME.match(start.value):
        return
    if not LOCAL_DATE_TIME.match(start.value):
        raise RFC5545Error(f"{label}: DTSTART {start.value!r} is not a date-time")
    zone = start.param("TZID")
    if zone is not None and zone not in defined_zones:
        raise RFC5545Error(f"{label}: DTSTART names TZID {zone!r}, which no VTIMEZONE defines")
