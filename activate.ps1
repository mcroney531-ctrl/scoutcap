# Run this at the start of each dev session, from the repo root:  . .\activate.ps1
#
# Syncs the project-local .venv to the committed uv.lock (exactly; never
# upgrades, and fails if uv.lock is out of date with pyproject.toml), then
# activates it. Needs uv on PATH: https://docs.astral.sh/uv/getting-started/installation/
# When the lock is unchanged the sync is a fast no-op.

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Error "uv is not installed or not on PATH. Install it, then re-run: . .\activate.ps1"
    return
}

Push-Location $PSScriptRoot
try {
    uv sync --locked
    $syncExit = $LASTEXITCODE
} finally {
    Pop-Location
}
if ($syncExit -ne 0) {
    Write-Error "uv sync --locked failed. If you changed pyproject.toml, regenerate the lock deliberately with 'uv lock' (see README)."
    return
}

. "$PSScriptRoot\.venv\Scripts\Activate.ps1"
