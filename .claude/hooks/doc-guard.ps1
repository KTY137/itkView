# itkFlow doc-discipline guard (Stop hook).
# Nudges the agent to update docs when product source changed without any docs
# change. Fail-open and loop-safe: any error, or a second pass (stop_hook_active),
# exits 0 (allow stop). See docs/00-doc-map.md and CLAUDE.md rule 6.

try {
    $raw = [Console]::In.ReadToEnd()
} catch {
    exit 0
}

# Loop guard: if we are already continuing from a previous Stop hook, allow stop.
if ($raw) {
    try {
        $payload = $raw | ConvertFrom-Json
        if ($payload.stop_hook_active) { exit 0 }
    } catch { }
}

$proj = $env:CLAUDE_PROJECT_DIR
if (-not $proj) {
    try { $proj = (git rev-parse --show-toplevel 2>$null) } catch { exit 0 }
}
if (-not $proj) { exit 0 }

try {
    # --untracked-files=all so brand-new files are listed individually with their
    # full path (plain --porcelain collapses a wholly-untracked dir to "dir/").
    $lines = git -C "$proj" status --porcelain=v1 --untracked-files=all 2>$null
} catch {
    exit 0
}
if (-not $lines) { exit 0 }

$srcChanged = $false
$docChanged = $false
foreach ($line in $lines) {
    if ($line.Length -lt 4) { continue }
    $path = $line.Substring(3)
    if ($path -match ' -> ') { $path = ($path -split ' -> ')[-1] }
    $path = $path.Trim('"').Replace('\', '/')

    if ($path -match '^(backend/app/|frontend/src/)' -and
        $path -notmatch '(test_|\.test\.|\.spec\.|/__tests__/)') {
        $srcChanged = $true
    }
    if ($path -match '^docs/' -or $path -eq 'CLAUDE.md' -or $path -match '^[^/]+\.md$') {
        $docChanged = $true
    }
}

if ($srcChanged -and -not $docChanged) {
    $msg = @(
        "Doc-Guard: product source under backend/app or frontend/src changed, but no docs/ file did.",
        "Update the owning doc (see docs/00-doc-map.md) and the 'Aktueller Stand' bullet in",
        "docs/04-roadmap.md as part of this change, or launch the 'tenjin' subagent to do it.",
        "If this change has no behavior or contract impact (pure refactor / test wiring),",
        "say so in one line and stop."
    ) -join " "
    [Console]::Error.WriteLine($msg)
    exit 2
}

exit 0
