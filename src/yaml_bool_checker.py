"""yaml-bool-checker-cli: check YAML files for unquoted boolean-looking values, fail CI when they appear.

Reads one or more YAML files (or folders of them), checks every
value for the YAML 1.1 boolean words — yes, no, on, off, y, n, in
any case — and reports each one with the file and line number.
Report-only: it never rewrites a file. Exit 0 when every file is
clean, 1 when any problem is found, 2 for a usage error.

Why this matters: a YAML 1.1 parser (PyYAML, and the parsers
behind GitHub Actions and many CI tools) reads an unquoted `yes`
as boolean true, `no` as false, `on` as true, `off` as false, and
`y`/`n` the same way. The value silently changes type with no
error at all. The classic case is the "Norway problem": a country
code `country: NO` becomes false, and a language code
`language: no` becomes false too. Quoting the value — `country:
"NO"` — keeps it text. This tool finds the unquoted ones before
the file ships.

What counts as a failure: a mapping value, a list item, or a
flow-collection value that is exactly one of those words,
unquoted. `enabled: on`, `debug: yes`, `country: NO`, a list item
`- off`, and a flow value in `flags: [yes, no]` are all reported.
The word's case does not matter: YES, No, ON, Y, and n are all
flagged, and the report shows the word as written.

What does NOT count as a failure, and why:
- A quoted value: `enabled: "yes"` and `answer: 'n'` are text
  on purpose, and pass.
- A key with that name: `on: push` (the GitHub Actions trigger)
  and `yes: 1` are keys, not values, and pass. A key named `on`
  is normal; the silent type change this tool guards against is
  a value changing type.
- A longer word that contains one: `note: yesterday`,
  `status: none`, and `mode: on-demand` are ordinary text, and
  pass. Only the whole value, exactly the word, is flagged.
- A value with an explicit type tag: `enabled: !!str yes` and
  `enabled: !!bool yes` say what they mean in the file itself,
  so there is no silent surprise, and they pass. An anchor
  (`&a yes`) is not a type tag, so it is still flagged.
- Text inside a comment, a block scalar (`|` and `>`), a
  multi-line quoted scalar, or a multi-line flow collection is
  literal content or quoted, and is skipped — but a boolean word
  inside a flow collection is still checked, because a flow
  value is a real value.
- `true` and `false` are real booleans already, not a surprise,
  and pass.

What it does not do: it does not parse YAML values, so it cannot
tell you whether a file is valid YAML in any other way — a file
can pass this check and still fail a real YAML parser for another
reason. It does not check indentation (that is what
yaml-indent-checker-cli does) or duplicate keys (that is what
yaml-duplicate-key-checker-cli does). It does not check whether a
value is the right type for the program reading it; that is a
schema's job. It uses no YAML library at all — the Python
standard library has no YAML parser, so this tool is a hand-rolled
line scanner (see "How it works" in the README), not a full parser.

Which parsers this is about: the check is for the YAML 1.1 world.
PyYAML and the parsers behind GitHub Actions and many CI tools
treat these words as booleans. YAML 1.2-only parsers do not — in
YAML 1.2 only `true` and `false` are booleans, so `country: NO`
stays text there. If every tool reading your files is YAML 1.2,
this check has nothing to find; if any of them is YAML 1.1, the
unquoted words are a real silent type change.
"""

import argparse
import fnmatch
import json
import os
import re
import sys
from pathlib import Path

__version__ = "1.0.0"

# YAML 1.1 boolean words, as PyYAML reads them, and the boolean
# each one becomes. The key is lowercase; the report shows the
# word as written in the file.
BOOL_WORDS = {
    "yes": True,
    "no": False,
    "on": True,
    "off": False,
    "y": True,
    "n": False,
}

DOUBLE_KEY_RE = re.compile(r'"((?:[^"\\]|\\.)*)"\s*:(\s|$)')
SINGLE_KEY_RE = re.compile(r"'((?:[^']|'')*)'\s*:(\s|$)")
PLAIN_KEY_RE = re.compile(r"(.+?)\s*:(\s|$)")
ANCHOR_OR_TAG_RE = re.compile(r"([&!][^\s]*)\s*")
FLOW_SPLIT_RE = re.compile(r"[,{}\[\]]")


class Problem:
    """One problem in one file: path, line number, plain reason."""

    def __init__(self, path, line, reason):
        self.path = path
        self.line = line
        self.reason = reason

    def text(self):
        return f"{self.path}:{self.line}: {self.reason}"

    def as_dict(self):
        return {"file": self.path, "line": self.line, "reason": self.reason}


def reason_for(word):
    """The plain reason for flagging one boolean word, as written."""
    value = BOOL_WORDS[word.lower()]
    return (f'unquoted value "{word}" reads as boolean '
            f'{"true" if value else "false"} under YAML 1.1 (PyYAML); '
            f'quote it if you mean the word "{word}"')


def bool_word(value):
    """Return the word when `value` is exactly a YAML 1.1 boolean word, else None.

    The value must be the whole word, nothing more: "yesterday"
    and "on-demand" are not boolean words, and neither is a value
    with anything after it. Case does not matter.
    """
    word = value.strip()
    if word.lower() in BOOL_WORDS:
        return word
    return None


def strip_comment(line):
    """Remove a trailing YAML comment: '#' outside quotes, at the start or after whitespace."""
    in_single = False
    in_double = False
    i = 0
    while i < len(line):
        ch = line[i]
        if in_single:
            if ch == "'":
                if i + 1 < len(line) and line[i + 1] == "'":
                    i += 2
                    continue
                in_single = False
        elif in_double:
            if ch == "\\":
                i += 2
                continue
            if ch == '"':
                in_double = False
        else:
            if ch == "'":
                in_single = True
            elif ch == '"':
                in_double = True
            elif ch == "#" and (i == 0 or line[i - 1] in " \t"):
                return line[:i]
        i += 1
    return line


def blank_quoted_strings(text):
    """Replace quoted spans with spaces, so words inside quotes are never flagged.

    Used on flow-collection lines, where a quoted "yes" must not be
    reported. Escaped quotes and doubled single quotes are honoured.
    """
    out = list(text)
    i = 0
    while i < len(text):
        ch = text[i]
        if ch == "'":
            out[i] = " "
            i += 1
            while i < len(text):
                if text[i] == "'":
                    out[i] = " "
                    if i + 1 < len(text) and text[i + 1] == "'":
                        out[i + 1] = " "
                        i += 2
                        continue
                    i += 1
                    break
                out[i] = " "
                i += 1
        elif ch == '"':
            out[i] = " "
            i += 1
            while i < len(text):
                if text[i] == "\\":
                    out[i] = " "
                    if i + 1 < len(text):
                        out[i + 1] = " "
                    i += 2
                    continue
                if text[i] == '"':
                    out[i] = " "
                    i += 1
                    break
                out[i] = " "
                i += 1
        else:
            i += 1
    return "".join(out)


def flow_delta(text):
    """Net change in flow-collection depth from one line, quotes ignored."""
    depth = 0
    in_single = False
    in_double = False
    i = 0
    while i < len(text):
        ch = text[i]
        if in_single:
            if ch == "'":
                if i + 1 < len(text) and text[i + 1] == "'":
                    i += 2
                    continue
                in_single = False
        elif in_double:
            if ch == "\\":
                i += 2
                continue
            if ch == '"':
                in_double = False
        else:
            if ch == "'":
                in_single = True
            elif ch == '"':
                in_double = True
            elif ch in "{[":
                depth += 1
            elif ch in "}]":
                depth -= 1
        i += 1
    return depth


def quote_closes(text, quote):
    """True when a quoted scalar starting with `quote` closes within `text`.

    `text` starts just after the opening quote.
    """
    i = 0
    while i < len(text):
        ch = text[i]
        if quote == '"':
            if ch == "\\":
                i += 2
                continue
            if ch == '"':
                return True
        else:
            if ch == "'":
                if i + 1 < len(text) and text[i + 1] == "'":
                    i += 2
                    continue
                return True
        i += 1
    return False


def unescape_double(raw):
    """Undo the escapes in the inside of a double-quoted YAML key."""
    out = []
    i = 0
    while i < len(raw):
        ch = raw[i]
        if ch == "\\" and i + 1 < len(raw):
            nxt = raw[i + 1]
            mapping = {"n": "\n", "t": "\t", "r": "\r",
                       "\\": "\\", '"': '"', "0": "\0"}
            out.append(mapping.get(nxt, nxt))
            i += 2
        else:
            out.append(ch)
            i += 1
    return "".join(out)


def parse_key_line(content):
    """Parse one mapping-entry line (comment already stripped).

    Returns (key, value) or None when the line is not a mapping entry.
    Quoted keys count the same as plain keys.
    """
    match = DOUBLE_KEY_RE.match(content)
    if match:
        return (unescape_double(match.group(1)),
                content[match.end():].strip())
    match = SINGLE_KEY_RE.match(content)
    if match:
        return (match.group(1).replace("''", "'"),
                content[match.end():].strip())
    match = PLAIN_KEY_RE.match(content)
    if not match:
        return None
    key = match.group(1).strip()
    if not key or key[0] in "{}[],&*!|>%@`":
        return None
    if key.startswith("? "):
        key = key[2:].strip()
        if not key:
            return None
    return (key, content[match.end():].strip())


def value_kind(value):
    """Classify what follows a key's colon, after anchor/tag markers.

    Returns ("empty" | "block" | "flow" | "quoted" | "scalar", rest),
    where rest is the value with any anchor/tag markers removed.
    """
    rest = value
    while True:
        match = ANCHOR_OR_TAG_RE.match(rest)
        if not match:
            break
        rest = rest[match.end():]
    if not rest:
        return ("empty", "")
    if rest[0] in "|>":
        return ("block", rest)
    if rest[0] in "{[":
        return ("flow", rest)
    if rest[0] in "\"'":
        return ("quoted", rest)
    return ("scalar", rest)


def has_explicit_tag(value):
    """True when the value starts with an explicit type tag (!...).

    A tag says what the value means in the file itself, so there is
    no silent surprise and it is not flagged. An anchor (&...) is
    not a type tag, so it does not count.
    """
    rest = value
    while True:
        match = ANCHOR_OR_TAG_RE.match(rest)
        if not match:
            return False
        if match.group(1).startswith("!"):
            return True
        rest = rest[match.end():]


def flow_bool_words(text):
    """Find boolean-word values inside one flow-collection line.

    `text` is the line with comments stripped and quoted strings
    blanked. Each comma-separated segment contributes only its value
    part (after the first colon, when the segment is a mapping
    entry); a bare segment is a value itself. A segment carrying an
    explicit type tag is skipped. Returns the words found, as
    written.
    """
    found = []
    for segment in FLOW_SPLIT_RE.split(text):
        if "!" in segment:
            continue
        if ":" in segment:
            segment = segment.split(":", 1)[1]
        word = bool_word(segment)
        if word is not None:
            found.append(word)
    return found


def scan_text(text, label):
    """Check one YAML document (as text) and return its problems.

    Every unquoted YAML 1.1 boolean word used as a value is
    reported at its own line: mapping values, list items, bare
    document scalars, and values inside flow collections. Keys are
    never flagged, quoted values are never flagged, and lines inside
    block scalars and multi-line quoted scalars are skipped. Every
    problem is reported, not just the first.
    """
    problems = []
    block_indent = None  # indent of a key owning a block scalar
    flow_depth = 0       # > 0 while inside a multi-line flow collection
    quote_char = None    # open quote while inside a multi-line quoted scalar

    for lineno, raw in enumerate(text.splitlines(), 1):
        line = raw.rstrip("\r").rstrip()
        stripped = strip_comment(line).strip()
        if not stripped:
            continue
        leading = line[:len(line) - len(line.lstrip(" \t"))]
        if flow_depth > 0:
            clean = blank_quoted_strings(strip_comment(line))
            for word in flow_bool_words(clean):
                problems.append(Problem(label, lineno, reason_for(word)))
            flow_depth += flow_delta(line)
            if flow_depth <= 0:
                flow_depth = 0
            continue
        if quote_char is not None:
            if quote_closes(line, quote_char):
                quote_char = None
            continue
        if block_indent is not None:
            if len(leading) > block_indent:
                continue
            block_indent = None
        if stripped == "---" or stripped.startswith("--- "):
            block_indent = None
            flow_depth = 0
            quote_char = None
            continue
        if stripped == "..." or stripped.startswith("... "):
            block_indent = None
            flow_depth = 0
            quote_char = None
            continue
        indent = len(leading)
        # Strip list-item markers: the dash carries the indent, the
        # value inside the item sits two spaces further in.
        is_list_item = False
        content_start = indent
        while True:
            rest = line[content_start:]
            if rest == "-":
                content_start = None
                break
            if rest.startswith("- "):
                is_list_item = True
                content_start += 2
                while (content_start < len(line)
                       and line[content_start] == " "):
                    content_start += 1
                continue
            break
        if content_start is None:
            continue
        content = strip_comment(line[content_start:]).strip()
        if not content:
            continue
        if content[0] in "{[":
            clean = blank_quoted_strings(content)
            for word in flow_bool_words(clean):
                problems.append(Problem(label, lineno, reason_for(word)))
            flow_depth = flow_delta(content)
            if flow_depth <= 0:
                flow_depth = 0
            continue
        parsed = parse_key_line(content)
        if parsed is None:
            # A bare scalar line: a list item is a value, and a
            # scalar at the top level is the whole document's value,
            # so both are checked. An indented continuation line is
            # part of the value above it, not a value of its own.
            if is_list_item or indent == 0:
                word = bool_word(content)
                if word is not None:
                    problems.append(Problem(label, lineno, reason_for(word)))
            continue
        key, value = parsed
        # What follows the key decides what the next lines mean.
        kind, rest = value_kind(value)
        block_indent = None
        flow_depth = 0
        quote_char = None
        if kind == "block":
            block_indent = content_start
        elif kind == "flow":
            clean = blank_quoted_strings(rest)
            for word in flow_bool_words(clean):
                problems.append(Problem(label, lineno, reason_for(word)))
            flow_depth = flow_delta(rest)
            if flow_depth <= 0:
                flow_depth = 0
        elif kind == "quoted":
            if not quote_closes(rest[1:], rest[0]):
                quote_char = rest[0]
        elif kind == "scalar":
            if not has_explicit_tag(value):
                word = bool_word(rest)
                if word is not None:
                    problems.append(Problem(label, lineno, reason_for(word)))

    problems.sort(key=lambda p: p.line)
    return problems


def check_file(path):
    """Check one file and return its problems."""
    label = str(path)
    try:
        data = Path(path).read_bytes()
    except OSError as exc:
        return [Problem(label, 1, f"cannot read file: {exc.strerror or exc}")]
    if b"\x00" in data:
        return [Problem(label, 1, "file contains a null byte, not a YAML file")]
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return [Problem(label, 1, "file is not valid UTF-8")]
    return scan_text(text, label)


def is_yaml_name(path):
    """True when a file name looks like a YAML file."""
    return path.name.lower().endswith((".yaml", ".yml"))


def collect(paths, recursive=True, exclude=()):
    """Gather the files to check and their problems.

    A file given directly is always checked, whatever its name. A
    folder is walked for .yaml and .yml files, recursively by
    default. `.git` folders are never walked, and directory links
    are never followed.
    """
    checked = []
    problems = []
    for given in paths:
        path = Path(given)
        if path.is_file():
            checked.append(path)
            problems.extend(check_file(path))
        elif path.is_dir():
            for root, dirs, files in os.walk(path, followlinks=False):
                dirs[:] = sorted(d for d in dirs
                                 if d != ".git"
                                 and not any(fnmatch.fnmatch(d, pat)
                                             for pat in exclude))
                for name in sorted(files):
                    candidate = Path(root) / name
                    if not is_yaml_name(candidate):
                        continue
                    if any(fnmatch.fnmatch(name, pat) for pat in exclude):
                        continue
                    checked.append(candidate)
                    problems.extend(check_file(candidate))
                if not recursive:
                    break
        else:
            problems.append(Problem(str(given), 1, "no such file or folder"))
    return checked, problems


def main(argv=None):
    """Entry point. Returns the exit code: 0 clean, 1 problems, 2 usage."""
    parser = argparse.ArgumentParser(
        prog="yaml_bool_checker",
        description="Check YAML files for unquoted YAML 1.1 boolean words.")
    parser.add_argument("paths", nargs="*", metavar="PATH",
                        help="YAML file or folder to check")
    parser.add_argument("--stdin", action="store_true",
                        help="check one YAML file read from standard input")
    parser.add_argument("--json", action="store_true",
                        help="print the result as JSON (human lines go to standard error)")
    parser.add_argument("--no-recursive", action="store_true",
                        help="do not walk into subfolders")
    parser.add_argument("--exclude", action="append", default=[],
                        metavar="PATTERN",
                        help="skip files and folders matching this name pattern")
    parser.add_argument("--version", action="version",
                        version=f"%(prog)s {__version__}")
    args = parser.parse_args(argv)

    if args.stdin:
        if args.paths:
            parser.error("--stdin takes no paths")
        text = sys.stdin.read()
        checked = ["<stdin>"]
        problems = scan_text(text, "<stdin>")
    else:
        if not args.paths:
            parser.error("give at least one file or folder, or use --stdin")
        checked, problems = collect(args.paths,
                                    recursive=not args.no_recursive,
                                    exclude=args.exclude)

    files_with_problems = len({p.path for p in problems})
    if args.json:
        result = {
            "files_checked": len(checked),
            "problems": [p.as_dict() for p in problems],
            "files_with_problems": files_with_problems,
        }
        print(json.dumps(result, indent=2))
        for problem in problems:
            print(problem.text(), file=sys.stderr)
    else:
        for problem in problems:
            print(problem.text())
        if problems:
            print(f"Checked {len(checked)} file(s), "
                  f"{len(problems)} problem(s) in {files_with_problems} file(s).")
        else:
            print(f"OK — {len(checked)} file(s) checked, "
                  f"no unquoted boolean words found.")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
