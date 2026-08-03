#!/usr/bin/env bash
# Pre-publish audit: nothing personal, nothing pointing at private infrastructure,
# and every file a public HACS repository needs.
#
# grep exits 1 when it finds nothing, so this judges on OUTPUT, not exit status —
# testing the exit code reports every clean check as a finding.
set -uo pipefail
cd "$(dirname "$0")/.."

findings=0
# This script necessarily contains the very strings it searches for, so it
# excludes itself — otherwise every check reports itself as a finding.
EXCLUDES=(--exclude-dir=.git --exclude-dir=.pytest_cache --exclude-dir=__pycache__
          --exclude-dir=.venv --exclude=audit.sh)

check() {
  local label="$1"; shift
  local out
  out="$("$@" 2>/dev/null)"
  if [ -z "$out" ]; then
    printf '  \033[32m✓\033[0m %s\n' "$label"
  else
    printf '  \033[31m✗\033[0m %s\n' "$label"
    printf '%s\n' "$out" | head -8 | sed 's/^/        /'
    findings=$((findings + 1))
  fi
}

echo "Content"
check "no account-holder details" \
  grep -rniE "holden|salomon|arch\.fyi|garden ln|decatur|\(678|30030" "${EXCLUDES[@]}" .
check "no private infrastructure URLs" \
  grep -rniE "onetick|truenas|192\.168\.|ha-box" "${EXCLUDES[@]}" .
check "no real cart identifiers" \
  grep -rnE "2772590|2778336" "${EXCLUDES[@]}" .
check "no live account figures in docs" \
  grep -rnE "109\.06|105\.88|72\.88" README.md CHANGELOG.md
check "no hardcoded secrets" \
  grep -rniE "api[_-]?key\s*[:=]\s*[\"'][^\"']{8,}|access_token\s*[:=]\s*[\"'][^\"']{8,}" \
  "${EXCLUDES[@]}" --include=*.py --include=*.json --include=*.yaml .

echo "Required files"
for f in LICENSE hacs.json README.md CHANGELOG.md NOTICE \
         .github/workflows/validate.yml \
         custom_components/freshharvest/manifest.json \
         custom_components/freshharvest/translations/en.json; do
  if [ -e "$f" ]; then
    printf '  \033[32m✓\033[0m %s\n' "$f"
  else
    printf '  \033[31m✗\033[0m missing %s\n' "$f"
    findings=$((findings + 1))
  fi
done

echo "Manifest"
check "manifest URLs are public" \
  grep -nE '"(documentation|issue_tracker)": "(?!https://github\.com/)' -P \
  custom_components/freshharvest/manifest.json

echo
if [ "$findings" -eq 0 ]; then
  printf '\033[32mAudit clean — 0 findings\033[0m\n'
else
  printf '\033[31m%s finding(s)\033[0m\n' "$findings"
fi
exit "$findings"
