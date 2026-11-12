"""Tests for yaml-bool-checker-cli. Standard library only."""

import ast
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SRC = ROOT / "src" / "yaml_bool_checker.py"

sys.path.insert(0, str(ROOT / "src"))
import yaml_bool_checker as ybc
from yaml_bool_checker import (
    Problem, blank_quoted_strings, bool_word, check_file, collect,
    flow_bool_words, has_explicit_tag, parse_key_line, reason_for,
    scan_text, strip_comment, value_kind,
)


def problems_as_tuples(text):
    return [(p.line, p.reason) for p in scan_text(text, "test.yaml")]


def run_cli(*args, stdin_text=None, cwd=None):
    return subprocess.run(
        [sys.executable, str(SRC), *args],
        input=stdin_text, capture_output=True, text=True,
        cwd=cwd or str(ROOT))


class StripCommentTests(unittest.TestCase):
    def test_trailing_comment_removed(self):
        self.assertEqual(strip_comment("a: 1 # note"), "a: 1 ")

    def test_full_line_comment(self):
        self.assertEqual(strip_comment("# full line"), "")

    def test_hash_inside_double_quotes_kept(self):
        self.assertEqual(strip_comment('a: "x # y"'), 'a: "x # y"')

    def test_hash_inside_single_quotes_kept(self):
        self.assertEqual(strip_comment("a: 'x # y'"), "a: 'x # y'")

    def test_hash_without_space_kept(self):
        self.assertEqual(strip_comment("url: http://x#y"),
                         "url: http://x#y")

    def test_comment_with_bool_word_stripped(self):
        # A "yes" in a comment is not a value.
        self.assertEqual(problems_as_tuples("a: 1 # yes\n"), [])


class ParseKeyLineTests(unittest.TestCase):
    def test_plain(self):
        self.assertEqual(parse_key_line("name: value"), ("name", "value"))

    def test_spaced_key(self):
        self.assertEqual(parse_key_line("my key: 1"), ("my key", "1"))

    def test_space_before_colon(self):
        self.assertEqual(parse_key_line("key : 1"), ("key", "1"))

    def test_empty_value(self):
        self.assertEqual(parse_key_line("key:"), ("key", ""))

    def test_double_quoted_key(self):
        self.assertEqual(parse_key_line('"name": 1'), ("name", "1"))

    def test_single_quoted_key(self):
        self.assertEqual(parse_key_line("'name': 1"), ("name", "1"))

    def test_not_a_key(self):
        self.assertIsNone(parse_key_line("just some text"))

    def test_url_value(self):
        self.assertEqual(parse_key_line("url: http://x"),
                         ("url", "http://x"))


class ValueKindTests(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(value_kind("")[0], "empty")

    def test_block_literal(self):
        self.assertEqual(value_kind("|")[0], "block")

    def test_block_folded(self):
        self.assertEqual(value_kind(">")[0], "block")

    def test_flow(self):
        self.assertEqual(value_kind("[a, b]")[0], "flow")

    def test_quoted(self):
        self.assertEqual(value_kind('"x"')[0], "quoted")

    def test_scalar(self):
        self.assertEqual(value_kind("plain")[0], "scalar")

    def test_anchor_then_block(self):
        self.assertEqual(value_kind("&a |")[0], "block")

    def test_tag_then_scalar(self):
        self.assertEqual(value_kind("!!str yes"), ("scalar", "yes"))


class BoolWordTests(unittest.TestCase):
    def test_all_six_words(self):
        for word in ("yes", "no", "on", "off", "y", "n"):
            self.assertEqual(bool_word(word), word)

    def test_case_does_not_matter(self):
        self.assertEqual(bool_word("YES"), "YES")
        self.assertEqual(bool_word("No"), "No")
        self.assertEqual(bool_word("ON"), "ON")
        self.assertEqual(bool_word("Y"), "Y")
        self.assertEqual(bool_word("N"), "N")

    def test_surrounding_space_ignored(self):
        self.assertEqual(bool_word("  yes  "), "yes")

    def test_longer_word_is_not_a_bool_word(self):
        self.assertIsNone(bool_word("yesterday"))
        self.assertIsNone(bool_word("none"))
        self.assertIsNone(bool_word("on-demand"))
        self.assertIsNone(bool_word("yesman"))
        self.assertIsNone(bool_word("nope"))

    def test_value_with_more_after_it_is_not_a_bool_word(self):
        self.assertIsNone(bool_word("yes please"))
        self.assertIsNone(bool_word("yes#x"))

    def test_true_and_false_are_not_bool_words(self):
        self.assertIsNone(bool_word("true"))
        self.assertIsNone(bool_word("false"))

    def test_reason_true(self):
        self.assertIn("boolean true", reason_for("yes"))
        self.assertIn('"yes"', reason_for("yes"))

    def test_reason_false(self):
        self.assertIn("boolean false", reason_for("NO"))
        self.assertIn('"NO"', reason_for("NO"))

    def test_reason_says_yaml_11(self):
        self.assertIn("YAML 1.1", reason_for("on"))


class ExplicitTagTests(unittest.TestCase):
    def test_str_tag_is_explicit(self):
        self.assertTrue(has_explicit_tag("!!str yes"))

    def test_bool_tag_is_explicit(self):
        self.assertTrue(has_explicit_tag("!!bool yes"))

    def test_custom_tag_is_explicit(self):
        self.assertTrue(has_explicit_tag("!mytag yes"))

    def test_anchor_is_not_a_tag(self):
        self.assertFalse(has_explicit_tag("&a yes"))

    def test_plain_value_has_no_tag(self):
        self.assertFalse(has_explicit_tag("yes"))

    def test_anchor_then_tag_is_explicit(self):
        self.assertTrue(has_explicit_tag("&a !!str yes"))


class CleanFileTests(unittest.TestCase):
    def test_quoted_double_values_pass(self):
        text = 'enabled: "yes"\ncountry: "NO"\nanswer: "on"\n'
        self.assertEqual(problems_as_tuples(text), [])

    def test_quoted_single_values_pass(self):
        text = "enabled: 'yes'\nanswer: 'n'\n"
        self.assertEqual(problems_as_tuples(text), [])

    def test_true_and_false_pass(self):
        text = "debug: false\nverbose: true\n"
        self.assertEqual(problems_as_tuples(text), [])

    def test_keys_named_like_bool_words_pass(self):
        text = "on:\n  push:\n    branches: [main]\nyes: 1\nno: 2\n"
        self.assertEqual(problems_as_tuples(text), [])

    def test_longer_words_pass(self):
        text = ("note: yesterday\nstatus: none\nmode: on-demand\n"
                "name: yesman\nreply: nope\n")
        self.assertEqual(problems_as_tuples(text), [])

    def test_explicit_tags_pass(self):
        text = "a: !!str yes\nb: !!bool no\nc: !custom on\n"
        self.assertEqual(problems_as_tuples(text), [])

    def test_empty_file_passes(self):
        self.assertEqual(problems_as_tuples(""), [])

    def test_comments_only_passes(self):
        self.assertEqual(problems_as_tuples("# yes\n# no\n"), [])

    def test_flat_clean_file_passes(self):
        text = "a: 1\nb: two\nc: 3.5\n"
        self.assertEqual(problems_as_tuples(text), [])

    def test_numbers_and_null_pass(self):
        text = "a: 0\nb: 1\nc: null\nd: ~\n"
        self.assertEqual(problems_as_tuples(text), [])

    def test_value_with_more_after_bool_word_passes(self):
        text = "note: yes please\nanswer: yes#x\n"
        self.assertEqual(problems_as_tuples(text), [])

    def test_quoted_list_items_pass(self):
        text = 'flags:\n  - "yes"\n  - \'no\'\n'
        self.assertEqual(problems_as_tuples(text), [])

    def test_bare_scalar_that_is_not_a_bool_word_passes(self):
        self.assertEqual(problems_as_tuples("hello\n"), [])


class FlaggedValueTests(unittest.TestCase):
    def test_each_word_flagged(self):
        for word in ("yes", "no", "on", "off", "y", "n"):
            found = problems_as_tuples(f"key: {word}\n")
            self.assertEqual(len(found), 1, word)
            self.assertEqual(found[0][0], 1)
            self.assertIn(f'"{word}"', found[0][1])

    def test_case_variants_flagged(self):
        for word in ("YES", "No", "ON", "OFF", "Y", "N"):
            found = problems_as_tuples(f"key: {word}\n")
            self.assertEqual(len(found), 1, word)
            self.assertIn(f'"{word}"', found[0][1])

    def test_true_and_false_words_in_reason(self):
        found = problems_as_tuples("a: yes\nb: no\n")
        self.assertIn("boolean true", found[0][1])
        self.assertIn("boolean false", found[1][1])

    def test_every_bad_line_reported(self):
        text = ("app:\n  enabled: on\n  debug: yes\n"
                "  notifications: off\n  answer: n\n  verbose: YES\n")
        found = problems_as_tuples(text)
        self.assertEqual([line for line, _ in found], [2, 3, 4, 5, 6])

    def test_norway_problem(self):
        text = "user:\n  country: NO\n  language: no\n"
        found = problems_as_tuples(text)
        self.assertEqual([line for line, _ in found], [2, 3])
        self.assertIn("boolean false", found[0][1])

    def test_value_with_trailing_comment_flagged(self):
        found = problems_as_tuples("enabled: yes # turn it on\n")
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0][0], 1)

    def test_anchored_value_flagged(self):
        found = problems_as_tuples("enabled: &a yes\n")
        self.assertEqual(len(found), 1)

    def test_list_items_flagged(self):
        text = "flags:\n  - yes\n  - no\n  - maybe\n"
        found = problems_as_tuples(text)
        self.assertEqual([line for line, _ in found], [2, 3])

    def test_nested_list_item_flagged(self):
        found = problems_as_tuples("flags:\n  - one\n  - off\n")
        self.assertEqual([line for line, _ in found], [3])

    def test_bare_document_scalar_flagged(self):
        self.assertEqual([line for line, _ in problems_as_tuples("yes\n")],
                         [1])
        self.assertEqual([line for line, _ in problems_as_tuples("NO\n")],
                         [1])

    def test_nested_mapping_value_flagged(self):
        text = "app:\n  server:\n    tls:\n      enabled: on\n"
        found = problems_as_tuples(text)
        self.assertEqual([line for line, _ in found], [4])

    def test_key_with_bool_word_name_and_bool_value(self):
        # The key "on" passes; the value "yes" is flagged.
        found = problems_as_tuples("on: yes\n")
        self.assertEqual(len(found), 1)
        self.assertIn('"yes"', found[0][1])


class FlowTests(unittest.TestCase):
    def test_flow_list_values_flagged(self):
        found = problems_as_tuples("flags: [yes, no]\n")
        self.assertEqual([line for line, _ in found], [1, 1])
        self.assertEqual(len(found), 2)

    def test_flow_mapping_value_flagged(self):
        found = problems_as_tuples("opts: {mode: on, debug: off}\n")
        self.assertEqual(len(found), 2)

    def test_flow_key_not_flagged(self):
        found = problems_as_tuples("opts: {yes: 1, mode: on}\n")
        self.assertEqual(len(found), 1)
        self.assertIn('"on"', found[0][1])

    def test_flow_quoted_words_pass(self):
        text = 'flags: ["yes", "no"]\n'
        self.assertEqual(problems_as_tuples(text), [])

    def test_flow_single_quoted_words_pass(self):
        text = "flags: ['yes', 'no']\n"
        self.assertEqual(problems_as_tuples(text), [])

    def test_flow_non_bool_values_pass(self):
        text = "flags: [true, false, 1, two]\n"
        self.assertEqual(problems_as_tuples(text), [])

    def test_flow_on_demand_passes(self):
        text = "modes: [on-demand, off-line]\n"
        self.assertEqual(problems_as_tuples(text), [])

    def test_flow_tagged_value_passes(self):
        text = "flags: [!!str yes]\n"
        self.assertEqual(problems_as_tuples(text), [])

    def test_multiline_flow_values_flagged(self):
        text = "flags: [\n  yes,\n  no,\n]\nnext: 1\n"
        found = problems_as_tuples(text)
        self.assertEqual([line for line, _ in found], [2, 3])

    def test_multiline_flow_quoted_passes(self):
        text = 'flags: [\n  "yes",\n  "no",\n]\nnext: 1\n'
        self.assertEqual(problems_as_tuples(text), [])

    def test_flow_closes_and_checking_resumes(self):
        text = "flags: [yes]\nnext: no\n"
        found = problems_as_tuples(text)
        self.assertEqual([line for line, _ in found], [1, 2])

    def test_bare_flow_line_flagged(self):
        found = problems_as_tuples("[yes, no]\n")
        self.assertEqual(len(found), 2)

    def test_flow_bool_words_helper(self):
        self.assertEqual(flow_bool_words("yes, no"), ["yes", "no"])
        self.assertEqual(flow_bool_words("a: yes, b: 1"), ["yes"])
        self.assertEqual(flow_bool_words("yes: 1"), [])
        self.assertEqual(flow_bool_words("on-demand"), [])
        self.assertEqual(flow_bool_words(""), [])


class SkippedLineTests(unittest.TestCase):
    def test_block_scalar_content_skipped(self):
        text = "notes: |\n  yes\n  no\n  on\nnext: 1\n"
        self.assertEqual(problems_as_tuples(text), [])

    def test_folded_scalar_content_skipped(self):
        text = "notes: >\n   yes\n      no\nnext: 1\n"
        self.assertEqual(problems_as_tuples(text), [])

    def test_block_scalar_ends_and_checking_resumes(self):
        text = "notes: |\n  yes\napp:\n  enabled: on\n"
        found = problems_as_tuples(text)
        self.assertEqual([line for line, _ in found], [4])

    def test_multiline_quoted_scalar_skipped(self):
        text = 'text: "yes\n   no\n   on"\nnext: 1\n'
        self.assertEqual(problems_as_tuples(text), [])

    def test_multiline_single_quoted_scalar_skipped(self):
        text = "text: 'yes\n   no'\nnext: 1\n"
        self.assertEqual(problems_as_tuples(text), [])

    def test_blank_and_comment_lines_skipped(self):
        text = "app:\n\n  # yes no on\n  name: x\n"
        self.assertEqual(problems_as_tuples(text), [])

    def test_document_marker_resets_block_state(self):
        text = "notes: |\n  yes\n---\napp:\n  enabled: on\n"
        found = problems_as_tuples(text)
        self.assertEqual([line for line, _ in found], [5])

    def test_document_marker_resets_flow_state(self):
        text = "flags: [yes\n---\nnext: no\n"
        found = problems_as_tuples(text)
        self.assertEqual([line for line, _ in found], [1, 3])

    def test_wrapped_plain_value_continuation_not_flagged(self):
        # An indented continuation line is part of the value above.
        text = "description: some long\n  yes\n"
        self.assertEqual(problems_as_tuples(text), [])

    def test_end_marker_resets_state(self):
        text = "notes: |\n  yes\n...\napp:\n  enabled: on\n"
        found = problems_as_tuples(text)
        self.assertEqual([line for line, _ in found], [5])


class BlankQuotedTests(unittest.TestCase):
    def test_double_quoted_blanked(self):
        self.assertEqual(blank_quoted_strings('"yes"'), "     ")

    def test_single_quoted_blanked(self):
        self.assertEqual(blank_quoted_strings("'yes'"), "     ")

    def test_escaped_quote_kept_inside(self):
        self.assertEqual(blank_quoted_strings('"a\\"yes" b'), "         b")

    def test_doubled_single_quote_kept_inside(self):
        self.assertEqual(blank_quoted_strings("'it''s yes'"), "           ")

    def test_unquoted_text_untouched(self):
        self.assertEqual(blank_quoted_strings("yes, no"), "yes, no")


class CheckFileTests(unittest.TestCase):
    def test_missing_file(self):
        found = check_file(ROOT / "no-such-file.yaml")
        self.assertEqual(len(found), 1)
        self.assertIn("No such file", found[0].reason)

    def test_non_utf8_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.yaml"
            path.write_bytes(b"a: \xff\xfe\n")
            found = check_file(path)
            self.assertEqual(len(found), 1)
            self.assertIn("not valid UTF-8", found[0].reason)

    def test_null_byte_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.yaml"
            path.write_bytes(b"a: 1\n\x00\n")
            found = check_file(path)
            self.assertEqual(len(found), 1)
            self.assertIn("null byte", found[0].reason)

    def test_crlf_line_endings(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "crlf.yaml"
            path.write_bytes(b"app:\r\n  enabled: on\r\n")
            found = check_file(path)
            self.assertEqual([p.line for p in found], [2])


class CollectTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, name, text):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path

    def test_folder_walks_yaml_and_yml_only(self):
        self.write("a.yaml", "x: yes\n")
        self.write("b.yml", "x: 1\n")
        self.write("c.txt", "x: yes\n")
        checked, problems = collect([self.root])
        self.assertEqual({p.name for p in checked}, {"a.yaml", "b.yml"})
        self.assertEqual(len(problems), 1)

    def test_file_given_directly_checked_whatever_its_name(self):
        path = self.write("weird.txt", "x: yes\n")
        checked, problems = collect([path])
        self.assertEqual(checked, [path])
        self.assertEqual(len(problems), 1)

    def test_git_folder_never_walked(self):
        git = self.root / ".git"
        git.mkdir()
        (git / "hooks.yaml").write_text("x: yes\n")
        self.write("a.yaml", "x: 1\n")
        checked, problems = collect([self.root])
        self.assertEqual([p.name for p in checked], ["a.yaml"])
        self.assertEqual(problems, [])

    def test_no_recursive_stops_at_top_level(self):
        self.write("a.yaml", "x: 1\n")
        self.write("sub/b.yaml", "x: yes\n")
        checked, problems = collect([self.root], recursive=False)
        self.assertEqual([p.name for p in checked], ["a.yaml"])
        self.assertEqual(problems, [])

    def test_exclude_skips_matching_files(self):
        self.write("a.yaml", "x: yes\n")
        self.write("b.yaml", "x: yes\n")
        checked, problems = collect([self.root], exclude=["b.yaml"])
        self.assertEqual([p.name for p in checked], ["a.yaml"])
        self.assertEqual(len(problems), 1)

    def test_missing_path_reported(self):
        checked, problems = collect([self.root / "missing.yaml"])
        self.assertEqual(checked, [])
        self.assertEqual(len(problems), 1)
        self.assertIn("no such file or folder", problems[0].reason)


class CliTests(unittest.TestCase):
    def test_clean_file_exit_zero(self):
        result = run_cli("examples/good.yaml")
        self.assertEqual(result.returncode, 0)
        self.assertIn("no unquoted boolean words found", result.stdout)

    def test_bad_file_exit_one(self):
        result = run_cli("examples/bad-bool.yaml")
        self.assertEqual(result.returncode, 1)
        self.assertIn("5 problem(s)", result.stdout)

    def test_norway_file_exit_one(self):
        result = run_cli("examples/bad-norway.yaml")
        self.assertEqual(result.returncode, 1)
        self.assertIn("3 problem(s)", result.stdout)

    def test_no_args_exit_two(self):
        result = run_cli()
        self.assertEqual(result.returncode, 2)

    def test_stdin(self):
        result = run_cli("--stdin",
                         stdin_text="app:\n  enabled: on\n")
        self.assertEqual(result.returncode, 1)
        self.assertIn("<stdin>:2:", result.stdout)

    def test_stdin_with_path_is_error(self):
        result = run_cli("examples/good.yaml", "--stdin")
        self.assertEqual(result.returncode, 2)

    def test_stdin_clean(self):
        result = run_cli("--stdin", stdin_text="app:\n  name: x\n")
        self.assertEqual(result.returncode, 0)
        self.assertIn("no unquoted boolean words found", result.stdout)

    def test_json_output(self):
        result = run_cli("examples/configs/app.yaml", "--json")
        self.assertEqual(result.returncode, 1)
        data = json.loads(result.stdout)
        self.assertEqual(data["files_checked"], 1)
        self.assertEqual(data["files_with_problems"], 1)
        self.assertEqual(len(data["problems"]), 1)
        self.assertEqual(data["problems"][0]["line"], 3)
        self.assertIn('"off"', data["problems"][0]["reason"])
        self.assertIn("examples/configs/app.yaml:3:",
                      result.stderr)

    def test_json_clean(self):
        result = run_cli("examples/good.yaml", "--json")
        self.assertEqual(result.returncode, 0)
        data = json.loads(result.stdout)
        self.assertEqual(data["problems"], [])
        self.assertEqual(data["files_with_problems"], 0)

    def test_version(self):
        result = run_cli("--version")
        self.assertEqual(result.returncode, 0)
        self.assertIn("1.0.0", result.stdout)

    def test_folder_run(self):
        result = run_cli("examples")
        self.assertEqual(result.returncode, 1)
        self.assertIn("Checked 4 file(s), 9 problem(s) in 3 file(s).",
                      result.stdout)


class CwdRobustnessTests(unittest.TestCase):
    """The tests must pass from any working directory, not just the repo root."""

    def test_clean_file_from_tmp(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = run_cli(str(ROOT / "examples" / "good.yaml"), cwd=tmp)
            self.assertEqual(result.returncode, 0)
            self.assertIn("no unquoted boolean words found", result.stdout)

    def test_bad_file_from_tmp_reports_name_and_word(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = run_cli(str(ROOT / "examples" / "bad-bool.yaml"),
                             cwd=tmp)
            self.assertEqual(result.returncode, 1)
            # Assert on the file name suffix and the message, never on
            # the absolute path the CLI echoes.
            self.assertIn("bad-bool.yaml:3:", result.stdout)
            self.assertIn('unquoted value "on"', result.stdout)
            self.assertIn("5 problem(s)", result.stdout)

    def test_folder_run_from_tmp(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = run_cli(str(ROOT / "examples"), cwd=tmp)
            self.assertEqual(result.returncode, 1)
            self.assertIn("bad-norway.yaml:4:", result.stdout)
            self.assertIn("Checked 4 file(s), 9 problem(s) in 3 file(s).",
                          result.stdout)

    def test_stdin_from_tmp(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = run_cli("--stdin", stdin_text="x: no\n", cwd=tmp)
            self.assertEqual(result.returncode, 1)
            self.assertIn("<stdin>:1:", result.stdout)


class ExampleTests(unittest.TestCase):
    def test_sample_output_matches_fresh_run(self):
        expected = (ROOT / "examples" / "sample-output.md").read_text()
        block = re.search(r"```text\n(.*?)```", expected, re.S).group(1)
        result = run_cli("examples")
        self.assertEqual(result.stdout, block)

    def test_run_example_script(self):
        result = subprocess.run(
            ["sh", "examples/run-example.sh"],
            capture_output=True, text=True, cwd=str(ROOT))
        self.assertEqual(result.returncode, 0)
        expected = (ROOT / "examples" / "sample-output.md").read_text()
        block = re.search(r"```text\n(.*?)```", expected, re.S).group(1)
        self.assertEqual(result.stdout, block)

    def test_good_example_passes(self):
        result = run_cli("examples/good.yaml")
        self.assertEqual(result.returncode, 0)

    def test_bad_bool_example_fails(self):
        result = run_cli("examples/bad-bool.yaml")
        self.assertEqual(result.returncode, 1)
        self.assertIn("5 problem(s)", result.stdout)

    def test_bad_norway_example_fails(self):
        result = run_cli("examples/bad-norway.yaml")
        self.assertEqual(result.returncode, 1)
        self.assertIn("3 problem(s)", result.stdout)

    def test_config_example_fails(self):
        result = run_cli("examples/configs/app.yaml")
        self.assertEqual(result.returncode, 1)
        self.assertIn("1 problem(s)", result.stdout)


class ReadmeTests(unittest.TestCase):
    def test_text_blocks_match_live_output(self):
        readme = (ROOT / "README.md").read_text()
        blocks = re.findall(r"```text\n(.*?)```", readme, re.S)
        self.assertTrue(blocks, "no ```text blocks found in README")
        live = []
        live.append(run_cli("examples/good.yaml").stdout)
        live.append(run_cli("examples/bad-bool.yaml").stdout)
        live.append(run_cli("examples/bad-norway.yaml").stdout)
        live.append(run_cli("examples").stdout)
        live.append(run_cli("--stdin",
                            stdin_text="app:\n  enabled: on\n").stdout)
        joined = "\n".join(live)
        for block in blocks:
            self.assertIn(block.strip(), joined,
                          "README text block not in live output")

    def test_json_block_matches_live_output(self):
        readme = (ROOT / "README.md").read_text()
        match = re.search(r"```json\n(.*?)```", readme, re.S)
        self.assertIsNotNone(match, "no ```json block found in README")
        result = run_cli("examples/configs/app.yaml", "--json")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(json.loads(match.group(1)),
                         json.loads(result.stdout))


class HygieneTests(unittest.TestCase):
    BANNED = ("TODO", "FIXME", "coming soon", "lorem", "placeholder")

    def test_no_banned_words_in_repo(self):
        hits = []
        for path in ROOT.rglob("*"):
            if not path.is_file():
                continue
            parts = path.relative_to(ROOT).parts
            if ".git" in parts or "__pycache__" in parts:
                continue
            if "tests" in parts:
                continue
            text = path.read_bytes().decode("utf-8", errors="ignore")
            for word in self.BANNED:
                if word in text:
                    hits.append(f"{path.relative_to(ROOT)}: {word}")
        self.assertEqual(hits, [])

    def test_no_third_party_imports(self):
        tree = ast.parse(SRC.read_text())
        stdlib = set(sys.stdlib_module_names)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self.assertIn(alias.name.split(".")[0], stdlib)
            elif isinstance(node, ast.ImportFrom):
                self.assertIn(node.module.split(".")[0], stdlib)

    def test_gitignore_first_line_is_env(self):
        lines = (ROOT / ".gitignore").read_text().splitlines()
        self.assertEqual(lines[0], ".env")

    def test_license_present(self):
        self.assertTrue((ROOT / "LICENSE").exists())
        self.assertIn("MIT License", (ROOT / "LICENSE").read_text())

    def test_ci_file_present_and_runs_tests(self):
        ci = ROOT / ".github" / "workflows" / "ci.yml"
        self.assertTrue(ci.exists())
        text = ci.read_text()
        self.assertIn("python3 tests/test_yaml_bool_checker.py", text)
        self.assertIn("actions/checkout", text)
        self.assertIn("push", text)
        self.assertIn("pull_request", text)

    def test_no_absolute_local_paths(self):
        home = str(Path.home())
        for path in ROOT.rglob("*"):
            if not path.is_file():
                continue
            parts = path.relative_to(ROOT).parts
            if ".git" in parts or "__pycache__" in parts:
                continue
            if "tests" in parts:
                continue
            text = path.read_bytes().decode("utf-8", errors="ignore")
            self.assertNotIn(home, text, str(path))

    def test_readme_names_what_it_does_not_do(self):
        readme = (ROOT / "README.md").read_text()
        self.assertIn("does NOT do", readme)
        self.assertIn("YAML 1.1", readme)
        self.assertIn("YAML 1.2", readme)
        self.assertIn("PyYAML", readme)


if __name__ == "__main__":
    unittest.main()
