"""只保留物理字典嵌套的静态解析；不执行OpenFOAM、include或表达式。"""
from __future__ import annotations

from bisect import bisect_right
from collections import defaultdict
import re


def component(value):
    """Render components without treating a slash inside a quoted key as nesting."""
    return value.replace("~", "~0").replace("/", "~1").replace("@", "~2")


def dictionary(text, lexer):
    """Return physical blocks/statements and diagnostics, never effective values.

    `lexer` is the identity-pinned knowledge.lex component. Unlike its older
    leaf-only parser, this retains parent header/closing locations and unresolved
    statements. Multiline plain values are conservative candidates, not asserted
    syntax errors: a missing semicolon may otherwise swallow the next key.
    """
    tokens = lexer(text)
    starts = [0] + [m.end() for m in re.finditer("\n", text)]
    line = lambda offset: bisect_right(starts, max(0, offset))
    records, issues, conditions = [], [], []
    pairs = {"(": ")", "[": "]", "{": "}"}
    unsafe = [line(a) for word, a, z in tokens if word.startswith("/*")
              or (word.startswith("#{") and not word.endswith("#}"))
              or (word.startswith('"') and (len(word) < 2 or not word.endswith('"')))]

    def create(kind, key, raw_key, start, parent):
        parents = records[parent]["components"] if parent is not None else []
        record = {"ordinal": len(records), "kind": kind, "key": key, "raw_key": raw_key,
            "parent": parent, "components": parents + [key], "start_offset": start,
            "line_start": line(start), "conditional_context": [dict(c) for c in conditions], "flags": []}
        if conditions:
            record["flags"].append("conditional_branch_not_evaluated")
        records.append(record)
        return record

    def finish(record, end, flags=()):
        record.update(end_offset=end, line_end=line(max(record["start_offset"], end - 1)),
                      raw=text[record["start_offset"]:end])
        record["flags"].extend(flags)

    def directive(i, parent):
        word, start, end = tokens[i]
        record = create("directive", word, word, start, parent)
        record["flags"].append("directive_not_evaluated")
        i += 1
        arg_start = tokens[i][1] if i < len(tokens) else end
        if i < len(tokens) and tokens[i][0] == "{":
            depth = 0
            while i < len(tokens):
                token, _, end = tokens[i]
                depth += token == "{"
                depth -= token == "}"
                i += 1
                if depth == 0:
                    break
            if depth:
                record["flags"].append("unclosed_directive_block")
        else:
            # Directives are physical-line records, not evaluation of their args.
            while i < len(tokens) and line(tokens[i][1]) == line(start):
                token, _, end = tokens[i]
                i += 1
                if token == ";":
                    break
        record["argument_text"] = text[arg_start:end].strip().rstrip(";").strip() if end > arg_start else ""
        finish(record, end)
        if word in ("#if", "#ifdef", "#ifndef", "#ifeq", "#ifneq"):
            conditions.append({"directive": word, "line": record["line_start"], "branch": "if"})
        elif word in ("#else", "#elif"):
            if conditions:
                conditions[-1] = {**conditions[-1], "branch": word[1:], "branch_line": record["line_start"]}
            else:
                record["flags"].append("conditional_without_if")
        elif word == "#endif":
            if conditions:
                conditions.pop()
            else:
                record["flags"].append("conditional_without_if")
        return i

    def walk(i, parent=None):
        while i < len(tokens):
            word, start, end = tokens[i]
            if word == "}":
                if parent is None:
                    issues.append({"line": line(start), "reason": "unmatched_closing_dictionary"})
                    i += 1
                    continue
                finish(records[parent], end)
                records[parent]["closed"] = True
                return i + 1
            if word == ";":
                i += 1
                continue
            if word.startswith("#"):
                i = directive(i, parent)
                continue
            raw_key = word
            # Adjacent parentheses belong to unquoted operator keys, e.g.
            # div(phi,U); whitespace before '(' denotes a list value instead.
            if i + 1 < len(tokens) and tokens[i + 1][0] == "(" and tokens[i + 1][1] == end:
                j, depth = i + 1, 0
                while j < len(tokens):
                    token, _, close = tokens[j]
                    if token in (";", "{", "}"):
                        break
                    depth += token == "("
                    depth -= token == ")"
                    if depth == 0:
                        raw_key, end, i = text[start:close], close, j
                        break
                    j += 1
            key = raw_key[1:-1] if raw_key.startswith('"') and raw_key.endswith('"') else raw_key
            i += 1
            if i < len(tokens) and tokens[i][0] == "{":
                record = create("block", key, raw_key, start, parent)
                record.update(open_line=line(tokens[i][1]), header_end_offset=tokens[i][2], closed=False)
                i = walk(i + 1, record["ordinal"])
                if not record["closed"]:
                    finish(record, len(text), ["unclosed_dictionary"])
                continue
            record = create("entry", key, raw_key, start, parent)
            value_start = tokens[i][1] if i < len(tokens) else end
            stack, plain_lines, flags = [], set(), []
            terminated = False
            had_value = False
            while i < len(tokens):
                token, pos, finish_at = tokens[i]
                if token == "}" and not stack:
                    break
                if token == ";" and not stack:
                    end, i, terminated = finish_at, i + 1, True
                    break
                had_value = True
                if token in pairs:
                    stack.append(pairs[token])
                    if token == "{":
                        flags.append("embedded_dictionary_value_not_expanded")
                elif token in (")", "]", "}"):
                    if not stack or token != stack[-1]:
                        flags.append("mismatched_value_delimiter")
                    if stack:
                        stack.pop()
                elif not stack:
                    plain_lines.add(line(pos))
                end, i = finish_at, i + 1
            if not terminated:
                flags.append("unterminated_statement")
                record["kind"] = "unresolved_statement"
            if stack:
                flags.append("unclosed_value_delimiter")
            if not had_value:
                flags.append("empty_or_splice_statement")
            if len(plain_lines) > 1:
                flags.append("multiline_plain_value_needs_syntax_check")
            value_end = end - 1 if terminated else end
            record["value_text"] = text[value_start:max(value_start, value_end)].strip()
            if re.search(r"[$#]", key + record["value_text"]):
                flags.append("expansion_not_evaluated")
            if key in pairs or key in (")", "]") or re.fullmatch(r"[0-9.+-]+", key):
                flags.append("list_root_or_nonword_key_not_interpreted")
            finish(record, end, flags)
        return i

    walk(0)
    if conditions:
        issues.append({"reason": "unclosed_conditional", "contexts": conditions})
    siblings = defaultdict(list)
    for record in records:
        siblings[record["parent"], record["key"]].append(record)
    for selected in siblings.values():
        for occurrence, record in enumerate(selected, 1):
            record["occurrence"] = occurrence
            if len(selected) > 1 and record["kind"] != "directive":
                record["flags"].append("duplicate_sibling_name_not_resolved")
    for record in records:
        parent = records[record["parent"]] if record["parent"] is not None else None
        if parent is not None:
            if parent["flags"]:
                record["flags"].append("ancestor_scope_requires_check")
            record["physical_components"] = parent["physical_components"] + [
                {"key": record["key"], "occurrence": record["occurrence"]}]
        else:
            record["physical_components"] = [{"key": record["key"], "occurrence": record["occurrence"]}]
        if unsafe:
            record["flags"].append("source_lexical_issue_requires_check")
        record["dictionary_path"] = "/".join(component(c["key"]) +
            (f"@{c['occurrence']}" if c["occurrence"] > 1 else "") for c in record["physical_components"])
        record["flags"] = sorted(set(record["flags"]))
        record["status"] = "unresolved_static_source" if record["flags"] else "literal_physical_structure"
        if record["flags"]:
            issues.append({"line": record["line_start"], "ordinal": record["ordinal"], "reasons": record["flags"]})
    if unsafe:
        issues.append({"reason": "unsafe_lexical_tokens", "lines": unsafe})
    return {"records": records, "issues": issues,
            "limits": ["Physical source structure only, not solver parsing or effective include/override semantics.",
                       "Lists containing dictionaries remain opaque; multiline plain values require source checking."]}
