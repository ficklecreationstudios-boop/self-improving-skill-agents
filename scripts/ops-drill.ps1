# D9 operations drill (docs/OPERATIONS_ACCEPTANCE.md) for a disposable, clean Windows machine.
# It writes to the real per-user revocation registry, whose path comes from the OS and cannot be redirected, so it
# refuses to run outside CI. Live-model and Linux-container steps are not here: a hosted runner has neither.
# Every step's command output and exit code go to drill.log. The drill stops at the first unexpected result.
param([Parameter(Mandatory)][string]$Commit, [Parameter(Mandatory)][string]$PrevCommit,
      [Parameter(Mandatory)][string]$Source, [Parameter(Mandatory)][string]$OutDir)
# 'Continue': in Windows PowerShell 5.1, 'Stop' turns any native stderr line into a terminating error.
$ErrorActionPreference = 'Continue'
if ($env:GITHUB_ACTIONS -ne 'true') { throw 'ops-drill.ps1 changes per-user state; it runs only on a disposable CI machine' }
New-Item -ItemType Directory -Force $OutDir | Out-Null
$D = (Resolve-Path $OutDir).Path
$log = "$D\drill.log"
function Log($text) { $text | Out-File -Append -Encoding utf8 $log }
function Step($name, [scriptblock]$body, [int[]]$okCodes = @(0)) {
    Log "`n===== $name  ($((Get-Date).ToUniversalTime().ToString('s'))Z)"
    $global:LASTEXITCODE = 0
    $out = & $body 2>&1 | Out-String
    $code = $LASTEXITCODE
    Log $out.TrimEnd()
    Log "exit=$code"
    if ($okCodes -notcontains $code) { Log "STEP FAILED: $name"; throw "step failed: $name (exit $code)" }
    return $out
}
function Expect($cond, $what) { if (-not $cond) { Log "EXPECTATION FAILED: $what"; throw "expectation failed: $what" } else { Log "OK: $what" } }
function Hash($path) { (Get-FileHash -Algorithm SHA256 $path).Hash }

$src = "$D\clone"; $venv = "$D\venv"; $data = "$D\data"
$py = "$venv\Scripts\python.exe"; $sa = "$venv\Scripts\skill-agents.exe"
$audit = "$data\audit.jsonl"; $archive = "$data\skill-archive"
$key1 = "$D\keys\drill-1.approval-key"; $key2 = "$D\keys\drill-2.approval-key"
Remove-Item Env:OLLAMA_MODEL -ErrorAction SilentlyContinue

Step 'environment' { Get-CimInstance Win32_OperatingSystem | Select-Object Caption, Version, OSArchitecture | Format-List; python --version; whoami }
Step 'clone at candidate commit' { git -c core.autocrlf=false clone --no-hardlinks --quiet $Source $src; git -C $src -c core.autocrlf=false checkout --quiet --detach $Commit; git -C $src rev-parse HEAD; git -C $src status --porcelain }
Step 'lock hash' { Hash "$src\requirements-test.lock" }

# Clean install
Step 'create venv' { python -m venv $venv }
Step 'install lock' { & $py -m pip install --disable-pip-version-check -q -r "$src\requirements-test.lock" }
Step 'install package' { & $py -m pip install --disable-pip-version-check -q --no-build-isolation -e $src }
$help = Step 'cli help' { & $sa --help }
foreach ($cmd in 'ask','agent','evaluate-quality','verify-audit','anchor-audit','recover-audit','recover','benchmark','propose','learn-from-feedback','init-approval-key','init-revocation-registry','add-approver','list-approvers','approve-proposal','revoke-approval-key','apply-proposal') {
    Expect ($help -match $cmd) "command present: $cmd"
}

# Offline / no-model behaviour
New-Item -ItemType Directory "$data" | Out-Null
$nomodel = Step 'ask without a model' { & $sa ask "Summarize this sentence: the build is green." --skills "$src\skills" --audit $audit } @(0, 1, 2)
Expect ($nomodel -match 'no model inference was performed') 'no-model task is not executed and says so'
Expect ((Get-Content $audit -Raw) -match 'task_not_executed') 'audit records task_not_executed'
Expect ((Step 'verify audit after no-model task' { & $sa verify-audit --audit $audit }).Trim() -eq 'VALID') 'audit VALID'

# First-run configuration and governance lifecycle on disposable skills
Step 'init revocation registry' { & $sa init-revocation-registry }
Copy-Item -Recurse "$src\skills" "$data\skills"
$skill = "$data\skills\general\SKILL.md"
$before = Hash $skill
(Get-Content -Raw $skill) + "`nPrefer short numbered steps." | Out-File -Encoding utf8 -NoNewline "$D\proposed-1.md"
$k1 = (Step 'init first approval key' { & $sa init-approval-key $key1 }) | ConvertFrom-Json
Step 'first key ACL' { icacls $key1 }
Step 'list the first key as an approver' { & $sa add-approver --key-file $key1 --name drill-owner }
Step 'propose' { & $sa propose general "$D\proposed-1.md" --rationale drill --skills "$data\skills" --output "$data\proposals\p1.json" }
Expect ((Hash $skill) -eq $before) 'proposal is inert: skill unchanged'
Step 'an unlisted name cannot sign' { 'general' | & $sa approve-proposal "$data\proposals\p1.json" --key-file $key1 --approver someone-else --reason drill --approve --approval-output "$data\approvals\denied.json" --audit $audit --archive $archive --skills "$data\skills" } @(1, 2)
Expect (-not (Test-Path "$data\approvals\denied.json")) 'approver policy refused an unlisted name'
Step 'approve' { 'general' | & $sa approve-proposal "$data\proposals\p1.json" --key-file $key1 --approver drill-owner --reason drill --approve --approval-output "$data\approvals\p1.json" --audit $audit --archive $archive --skills "$data\skills" }
Step 'apply' { & $sa apply-proposal "$data\proposals\p1.json" "$data\approvals\p1.json" --key-file $key1 --skills "$data\skills" --archive $archive --audit $audit }
$after = Hash $skill
Expect ($after -ne $before) 'approved proposal changed the skill'
Step 'replay the same approval' { & $sa apply-proposal "$data\proposals\p1.json" "$data\approvals\p1.json" --key-file $key1 --skills "$data\skills" --archive $archive --audit $audit } @(1, 2)
Expect ((Hash $skill) -eq $after) 'replayed approval rejected; skill unchanged'

# Key rotation: list a new key, revoke the old one, confirm which can sign
$k2 = (Step 'init replacement key' { & $sa init-approval-key $key2 }) | ConvertFrom-Json
Step 'list the replacement key' { & $sa add-approver --key-file $key2 --name drill-owner }
Step 'revoke the old key' { & $sa revoke-approval-key $k1.key_id --reason "drill rotation" --audit $audit --archive $archive }
(Get-Content -Raw $skill) + "`nName each step." | Out-File -Encoding utf8 -NoNewline "$D\proposed-2.md"
Step 'propose after rotation' { & $sa propose general "$D\proposed-2.md" --rationale rotation --skills "$data\skills" --output "$data\proposals\p2.json" }
Step 'sign with the revoked key' { 'general' | & $sa approve-proposal "$data\proposals\p2.json" --key-file $key1 --approver drill-owner --reason drill --approve --approval-output "$data\approvals\revoked.json" --audit $audit --archive $archive --skills "$data\skills" } @(1, 2)
Expect (-not (Test-Path "$data\approvals\revoked.json")) 'revoked key cannot sign'
Step 'sign with the replacement key' { 'general' | & $sa approve-proposal "$data\proposals\p2.json" --key-file $key2 --approver drill-owner --reason rotation --approve --approval-output "$data\approvals\p2.json" --audit $audit --archive $archive --skills "$data\skills" }
Step 'apply with the replacement key' { & $sa apply-proposal "$data\proposals\p2.json" "$data\approvals\p2.json" --key-file $key2 --skills "$data\skills" --archive $archive --audit $audit }
Expect ((Hash $skill) -ne $after) 'replacement key changed the skill'
$after = Hash $skill
Expect ((Step 'verify audit after governance' { & $sa verify-audit --audit $audit }).Trim() -eq 'VALID') 'audit VALID'

# Audit anchor: a rewritten ledger verifies by itself, but not against the anchor
$anchor = (Step 'anchor the audit' { & $sa anchor-audit --audit $audit }) | ConvertFrom-Json
Copy-Item -Recurse $data "$D\pre-tamper"
$forged = "$data\forged.jsonl"
Step 'build a forged chain' { & $sa ask "forged" --skills "$src\skills" --audit $forged } @(0, 1, 2)
Copy-Item $forged $audit -Force
$bad = Step 'verify the rewritten audit' { & $sa verify-audit --audit $audit } @(2)
Expect ($bad -match 'INVALID') 'anchor exposes a full rewrite'
Copy-Item "$D\pre-tamper\audit.jsonl" $audit -Force
Remove-Item $forged
Expect ((Step 'verify after restoring the audit' { & $sa verify-audit --audit $audit --anchor-seq $anchor.seq --anchor-hash $anchor.event_hash }).Trim() -eq 'VALID') 'restored audit matches its anchor'

# Backup and restore
$bk = "$D\backup"; $rs = "$D\restore"
Copy-Item -Recurse $data $bk
function Manifest($root) { Get-ChildItem -Recurse -File $root | Sort-Object FullName | ForEach-Object { "$(Hash $_.FullName)  $($_.FullName.Substring($root.Length))" } }
$orig = Manifest $data
$orig | Out-File -Encoding utf8 "$D\backup-manifest.txt"
Copy-Item -Recurse $bk $rs
Expect (($orig -join "`n") -eq ((Manifest $rs) -join "`n")) 'restored files hash-identical to the original'
Expect ((Step 'verify restored audit' { & $sa verify-audit --audit "$rs\audit.jsonl" --anchor-seq $anchor.seq --anchor-hash $anchor.event_hash }).Trim() -eq 'VALID') 'restored audit VALID against the noted hash'
Step 'recover on restore (1)' { & $sa recover --skills "$rs\skills" --archive "$rs\skill-archive" --audit "$rs\audit.jsonl" }
$r2 = (Step 'recover on restore (2, idempotent)' { & $sa recover --skills "$rs\skills" --archive "$rs\skill-archive" --audit "$rs\audit.jsonl" }) | ConvertFrom-Json
Expect ($r2.recovered.Count -eq 0 -and $r2.audit_valid) 'second recovery is a no-op with a valid audit'
Expect ((Hash "$rs\skills\general\SKILL.md") -eq $after) 'restored skill digest equals the original'

# Interrupted update recovery (fault-injection suites) and upgrade/rollback
$env:PYTHONDONTWRITEBYTECODE = '1'
Step 'fault-injection and recovery tests' { Push-Location $src; & "$venv\Scripts\pytest.exe" -q -p no:cacheprovider --basetemp "$D\bt-fault" tests/test_governance_fault_injection.py tests/test_governance_recovery.py tests/test_audit_tail_recovery.py; Pop-Location }
Step 'rollback to previous commit' { git -C $src -c core.autocrlf=false checkout --quiet --detach $PrevCommit; git -C $src rev-parse HEAD }
Expect ((Step 'previous code verifies the audit' { & $sa verify-audit --audit "$rs\audit.jsonl" }).Trim() -eq 'VALID') 'previous code: audit VALID'
Step 'previous code: governance tests' { Push-Location $src; & "$venv\Scripts\pytest.exe" -q -p no:cacheprovider --basetemp "$D\bt-prev" tests/test_governance.py; Pop-Location }
Step 'upgrade back to candidate' { git -C $src -c core.autocrlf=false checkout --quiet --detach $Commit; git -C $src rev-parse HEAD; git -C $src status --porcelain }
Expect ((Step 'candidate verifies the audit after the round trip' { & $sa verify-audit --audit "$rs\audit.jsonl" }).Trim() -eq 'VALID') 'audit VALID after rollback and upgrade'

# Uninstall
Step 'uninstall' { & $py -m pip uninstall -y -q self-improving-skill-agents }
Expect (-not (Test-Path $sa)) 'skill-agents entry point removed'
Log "`nDRILL COMPLETE: all steps and expectations passed"
