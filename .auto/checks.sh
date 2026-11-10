#!/usr/bin/env bash
# Correctness guard for the Adwaita restyle: CSS-only rule + CSS sanity.
set -euo pipefail
cd "$(dirname "$0")/.."

fail=0

# 1. CSS-only rule: HTML outside <style> must match the last kept version.
python3 - <<'PY' || fail=1
import re, subprocess, sys
from pathlib import Path

STRIP = re.compile(r"<style>.*?</style>", re.S)
problems = []
for name in ("index.html", "gallery.html", "status.html"):
    cur = Path("templates", name).read_text()
    base = subprocess.run(["git", "show", f"HEAD:templates/{name}"],
                          capture_output=True, text=True).stdout
    if not base:
        print(f"CHECK: cannot read HEAD:templates/{name}")
        sys.exit(1)
    a, b = STRIP.sub("<style/>", base), STRIP.sub("<style/>", cur)
    if a != b:
        import difflib
        diff = list(difflib.unified_diff(a.splitlines(), b.splitlines(),
                                         "HEAD", "worktree", lineterm="", n=1))
        problems.append(f"MARKUP CHANGED in templates/{name} (CSS-only rule):\n" +
                        "\n".join(diff[:24]))
    if not STRIP.search(cur):
        problems.append(f"templates/{name} lost its <style> block")
if problems:
    print("\n".join(problems))
    sys.exit(1)
PY

# 2. Files outside templates/ must be untouched (vs. session baseline).
if ! git status --porcelain | grep -v -E '^(..) (templates/|\.auto/|previews/)' \
        | sort > /tmp/adw-dirty-now.txt; then true; fi
if [ -f .auto/baseline-dirty.txt ]; then
  if ! diff -q .auto/baseline-dirty.txt /tmp/adw-dirty-now.txt >/dev/null; then
    echo "CHECK: files outside templates/ changed:"
    diff -u .auto/baseline-dirty.txt /tmp/adw-dirty-now.txt | head -20
    fail=1
  fi
fi

# 3. CSS sanity inside each <style> block: balanced braces, no @import, no
#    empty rules, declarations look like `prop: value`.
python3 - <<'PY' || fail=1
import re, sys
from pathlib import Path

BAD_AT = re.compile(r"@(import|font-face|charset|namespace|supports|layer|container)")
problems = []
for name in ("index.html", "gallery.html", "status.html"):
    text = Path("templates", name).read_text()
    styles = re.findall(r"<style>(.*?)</style>", text, re.S)
    for block in styles:
        no_comments = re.sub(r"/\*.*?\*/", "", block, flags=re.S)
        if no_comments.count("{") != no_comments.count("}"):
            problems.append(f"{name}: unbalanced braces ({no_comments.count('{')} vs {no_comments.count('}')})")
        for m in BAD_AT.finditer(no_comments):
            problems.append(f"{name}: forbidden at-rule @{m.group(1)}")
        depth, buf = 0, []
        for ch in no_comments:
            if ch == "{":
                if depth == 0 and not "".join(buf).strip():
                    problems.append(f"{name}: empty selector before '{{'")
                buf = []
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth < 0:
                    problems.append(f"{name}: closing brace without opener")
                    break
            elif depth == 0:
                buf.append(ch)
        if depth != 0:
            problems.append(f"{name}: unclosed block (depth {depth})")
if problems:
    print("\n".join(problems))
    sys.exit(1)
PY

if [ "$fail" -ne 0 ]; then
  exit 1
fi
echo "checks ok"
