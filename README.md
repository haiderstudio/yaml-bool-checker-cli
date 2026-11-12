# yaml-bool-checker-cli

Check YAML files for unquoted boolean-looking values, fail CI when a `yes`, `no`, `on`, or `off` would silently become a boolean.

[![CI](https://github.com/haiderstudio/yaml-bool-checker-cli/actions/workflows/ci.yml/badge.svg)](https://github.com/haiderstudio/yaml-bool-checker-cli/actions/workflows/ci.yml) [![Licence: MIT](https://img.shields.io/badge/Licence-MIT-yellow.svg)](LICENSE)

## What it does

`yaml_bool_checker` reads a YAML file and checks every value for
the YAML 1.1 boolean words — `yes`, `no`, `on`, `off`, `y`, `n`,
in any case — and reports each unquoted one with the file and
line number. The tool exits 1 when any problem is found, so it
can fail a CI run. A clean file exits 0.

- A YAML 1.1 parser (PyYAML, and the parsers behind GitHub
  Actions and many CI tools) reads an unquoted `yes` as boolean
  true, `no` as false, `on` as true, `off` as false, and `y`/`n`
  the same way. The value silently changes type with no error
  at all. This tool catches the unquoted words before the file
  ships, and points at the exact line.
- The classic case is the "Norway problem": `country: NO`
  becomes boolean false, and `language: no` (the language code
  for Norwegian) becomes false too. Quoting the value —
  `country: "NO"` — keeps it text.
- Every bad value is reported, not just the first: a file with
  five unquoted words fails with five reports, at lines 3, 4,
  5, 6, and 7.
- The word's case does not matter: `YES`, `No`, `ON`, `Y`, and
  `n` are all flagged, and the report shows the word as
  written, together with the boolean it would become.
- It checks mapping values (`enabled: on`), list items
  (`- off`), bare document scalars, and values inside flow
  collections (`flags: [yes, no]`, `{mode: on}`). A file given
  directly on the command line is always checked, whatever its
  name. A folder is walked for `.yaml` and `.yml` files,
  recursively by default (`--no-recursive` stops at the top
  level). `.git` folders are never walked, and directory links
  are never followed. `--exclude` skips files and folders by
  name pattern.
- `--json` prints the result as JSON (the human-readable lines
  go to standard error), and `--stdin` checks one YAML file read
  from standard input.

## Who it is for

Anyone who writes YAML for a YAML 1.1 parser — developers
writing GitHub Actions workflows, CI configs, Docker Compose
files, and app settings with PyYAML — and anyone who has lost a
country code, a language code, or a plain word like `on` to a
silent type change and only found out when something broke.

## What it does NOT do

- It does not flag quoted values. `enabled: "yes"` and
  `answer: 'n'` are text on purpose, and pass.
- It does not flag keys. `on: push` (the GitHub Actions
  trigger) and `yes: 1` are keys, not values, and pass. A key
  named `on` is normal; the silent type change this tool guards
  against is a value changing type.
- It does not flag a longer word that contains one. `note:
  yesterday`, `status: none`, and `mode: on-demand` are
  ordinary text, and pass. Only the whole value, exactly the
  word, is flagged.
- It does not flag a value with an explicit type tag.
  `enabled: !!str yes` and `enabled: !!bool yes` say what they
  mean in the file itself, so there is no silent surprise, and
  they pass. An anchor (`&a yes`) is not a type tag, so it is
  still flagged.
- It does not flag text inside a comment, a block scalar (`|`
  and `>`), or a multi-line quoted scalar. That text is literal
  content or quoted, not a value.
- It does not flag `true` and `false`. Those are real booleans
  already, not a surprise.
- It does not parse YAML values. It cannot tell you whether a
  file is valid YAML in any other way — a file can pass this
  check and still fail a real YAML parser for another reason.
- It does not check indentation (that is what
  yaml-indent-checker-cli does) or duplicate keys (that is what
  yaml-duplicate-key-checker-cli does). It does not check
  whether a value is the right type for the program reading it;
  that is a schema's job.
- It does not convert or rewrite anything. It is report-only,
  and it never touches the network.
- It uses no YAML library at all — the Python standard library
  has no YAML parser, so this tool is a hand-rolled line scanner
  (see "How it works" below), not a full parser.

## Which parsers this is about

The check is for the YAML 1.1 world. PyYAML and the parsers
behind GitHub Actions and many CI tools treat `yes`, `no`,
`on`, `off`, `y`, and `n` as booleans. YAML 1.2-only parsers do
not — in YAML 1.2 only `true` and `false` are booleans, so
`country: NO` stays text there. If every tool reading your
files is YAML 1.2, this check has nothing to find; if any of
them is YAML 1.1, the unquoted words are a real silent type
change. This tool does not claim otherwise.

## How this differs

- A GitHub search for `"yaml-bool-checker-cli"` returns
  0 results, and a search for `yaml boolean checker` returns
  0 results (checked Nov 11, 2026). The field is empty for
  this job; no dedicated tool owns it.
- Repo #57 (yaml-duplicate-key-checker-cli) checks duplicate
  keys; repo #71 (yaml-indent-checker-cli) checks indentation —
  boolean-looking values are a different check on the same
  files.

## How it works

The scanner reads lines and, for every line that carries
structure, looks at the value after the key: if the whole
value, unquoted, is exactly one of the six YAML 1.1 boolean
words, it is reported. List items and bare document scalars
are values too, and are checked the same way. Flow
collections are split into their values, quoted strings
blanked first, so `flags: [yes, no]` reports both words while
`flags: ["yes", "no"]` reports neither. Lines inside block
scalars and multi-line quoted scalars are skipped, because
that text is literal content, not a value. Comments are
stripped before any check, so a `# yes` in a comment never
causes a failure.

## Install

Python 3.10 or newer, nothing else to install.

```sh
git clone https://github.com/haiderstudio/yaml-bool-checker-cli.git
cd yaml-bool-checker-cli
```

## Usage

Check one clean file:

```sh
python3 src/yaml_bool_checker.py examples/good.yaml
```

```text
OK — 1 file(s) checked, no unquoted boolean words found.
```

Check a file with unquoted boolean words:

```sh
python3 src/yaml_bool_checker.py examples/bad-bool.yaml
```

```text
examples/bad-bool.yaml:3: unquoted value "on" reads as boolean true under YAML 1.1 (PyYAML); quote it if you mean the word "on"
examples/bad-bool.yaml:4: unquoted value "yes" reads as boolean true under YAML 1.1 (PyYAML); quote it if you mean the word "yes"
examples/bad-bool.yaml:5: unquoted value "off" reads as boolean false under YAML 1.1 (PyYAML); quote it if you mean the word "off"
examples/bad-bool.yaml:6: unquoted value "n" reads as boolean false under YAML 1.1 (PyYAML); quote it if you mean the word "n"
examples/bad-bool.yaml:7: unquoted value "YES" reads as boolean true under YAML 1.1 (PyYAML); quote it if you mean the word "YES"
Checked 1 file(s), 5 problem(s) in 1 file(s).
```

The exit code is 1, so a CI run fails.

Check the Norway problem — a country code and a language code that read as false:

```sh
python3 src/yaml_bool_checker.py examples/bad-norway.yaml
```

```text
examples/bad-norway.yaml:4: unquoted value "NO" reads as boolean false under YAML 1.1 (PyYAML); quote it if you mean the word "NO"
examples/bad-norway.yaml:5: unquoted value "no" reads as boolean false under YAML 1.1 (PyYAML); quote it if you mean the word "no"
examples/bad-norway.yaml:6: unquoted value "y" reads as boolean true under YAML 1.1 (PyYAML); quote it if you mean the word "y"
Checked 1 file(s), 3 problem(s) in 1 file(s).
```

Check a whole folder:

```sh
python3 src/yaml_bool_checker.py examples
```

```text
examples/bad-bool.yaml:3: unquoted value "on" reads as boolean true under YAML 1.1 (PyYAML); quote it if you mean the word "on"
examples/bad-bool.yaml:4: unquoted value "yes" reads as boolean true under YAML 1.1 (PyYAML); quote it if you mean the word "yes"
examples/bad-bool.yaml:5: unquoted value "off" reads as boolean false under YAML 1.1 (PyYAML); quote it if you mean the word "off"
examples/bad-bool.yaml:6: unquoted value "n" reads as boolean false under YAML 1.1 (PyYAML); quote it if you mean the word "n"
examples/bad-bool.yaml:7: unquoted value "YES" reads as boolean true under YAML 1.1 (PyYAML); quote it if you mean the word "YES"
examples/bad-norway.yaml:4: unquoted value "NO" reads as boolean false under YAML 1.1 (PyYAML); quote it if you mean the word "NO"
examples/bad-norway.yaml:5: unquoted value "no" reads as boolean false under YAML 1.1 (PyYAML); quote it if you mean the word "no"
examples/bad-norway.yaml:6: unquoted value "y" reads as boolean true under YAML 1.1 (PyYAML); quote it if you mean the word "y"
examples/configs/app.yaml:3: unquoted value "off" reads as boolean false under YAML 1.1 (PyYAML); quote it if you mean the word "off"
Checked 4 file(s), 9 problem(s) in 3 file(s).
```

Check one file from standard input:

```sh
printf 'app:\n  enabled: on\n' | python3 src/yaml_bool_checker.py --stdin
```

```text
<stdin>:2: unquoted value "on" reads as boolean true under YAML 1.1 (PyYAML); quote it if you mean the word "on"
Checked 1 file(s), 1 problem(s) in 1 file(s).
```

Machine-readable output:

```sh
python3 src/yaml_bool_checker.py examples/configs/app.yaml --json
```

```json
{
  "files_checked": 1,
  "problems": [
    {
      "file": "examples/configs/app.yaml",
      "line": 3,
      "reason": "unquoted value \"off\" reads as boolean false under YAML 1.1 (PyYAML); quote it if you mean the word \"off\""
    }
  ],
  "files_with_problems": 1
}
```

## Examples

- `examples/good.yaml` — a clean config: quoted `"yes"` and
  `"NO"`, real `true`/`false`, an `on:` key, `on-demand`,
  `yesterday`, and `none` as ordinary text, a block scalar
  holding `yes`/`no`/`on` lines, and quoted words in a flow
  list. Passes.
- `examples/bad-bool.yaml` — five problems in one file:
  `on`, `yes`, `off`, `n`, and `YES` as values. Fails with
  exit 1.
- `examples/bad-norway.yaml` — the Norway problem: a country
  code `NO`, a language code `no`, and `y` as values. Fails
  with exit 1.
- `examples/configs/app.yaml` — one unquoted `off`, in a
  subfolder. Fails with exit 1.
- `sh examples/run-example.sh` runs the checker on the whole
  `examples/` folder. Its output is in
  `examples/sample-output.md`.

## How it is tested

```sh
python3 tests/test_yaml_bool_checker.py
```

The tests cover: comment stripping (trailing comments, hashes
inside quotes), key parsing (plain, quoted, spaced keys, URLs,
lines that are not keys), value kinds (empty, block, folded,
flow, quoted, scalar, anchored), the boolean words themselves
(all six words, every case form, the exact boolean each one
becomes), clean files (quoted values, true/false, keys named
`on`/`yes`, longer words like `yesterday`/`none`/`on-demand`,
explicit `!!str`/`!!bool` tags, anchors on non-boolean values),
flagged values (mapping values, list items, bare document
scalars, every bad line reported with its exact line number,
the Norway case), flow collections (single-line and
multi-line, mappings inside flow, quoted words inside flow
passing, flow keys not flagged), skipped lines (block and
folded scalars, multi-line quoted scalars, blank and comment
lines, document markers, wrapped plain values), file errors
(missing, non-UTF-8, null byte, CRLF), folder walking
(`.yaml`/`.yml` only, `.git` skipped, `--no-recursive`,
`--exclude`, direct files, missing paths), exit codes 0/1/2,
`--stdin`, `--json`, `--version`, running from any working
directory (the tests pass from the repo root, from /tmp, and
from anywhere else), and the bundled examples (the sample
output is compared byte-for-byte against a fresh run, and the
outputs quoted in this README are checked against real runs).

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## Licence

MIT — see [LICENSE](LICENSE).

## Original work

This tool was written from scratch for this repo. The scanner
is hand-rolled because the Python standard library has no YAML
parser; the boolean-word problem it solves is the same silent
failure family as repo #57 (yaml-duplicate-key-checker-cli) and
repo #71 (yaml-indent-checker-cli), a different check on the
same files. The code, the wording, and the tests are original.
