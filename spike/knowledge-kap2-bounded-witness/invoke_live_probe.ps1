param([switch]$Preflight, [switch]$Smoke, [switch]$Resume, [switch]$FaultReads, [switch]$StaleCas)

$ErrorActionPreference = 'Stop'
$probeProject = 'episteck-kap2-bnd-261009'
$suffix = '@episteck-kap2-bnd-261009.iam.gserviceaccount.com'
$keyPrefix = "projects/$probeProject/locations/us-east4/keyRings/kap2-bnd-261009/cryptoKeys"
$prefix = if ($Smoke -or $FaultReads) {
    'home-auth/v1/partitions/SYNTHETIC-KAP2-SMOKE-261009'
} else {
    'home-auth/v1/partitions/SYNTHETIC-KAP2-BOUNDED-261009'
}

function Get-ProbeToken([string]$account) {
    $value = if ($account -eq 'operator') {
        gcloud auth print-access-token --project=$probeProject
    } else {
        gcloud auth print-access-token --project=$probeProject --impersonate-service-account="$account$suffix"
    }
    if ($LASTEXITCODE -ne 0 -or -not $value) { throw "Token acquisition failed for $account" }
    return $value.Trim()
}

$tokens = @{
    operator = Get-ProbeToken 'operator'
    old = Get-ProbeToken 'kap2-old-writer'
    new = Get-ProbeToken 'kap2-new-writer'
    head = Get-ProbeToken 'kap2-head-publisher'
    journal = Get-ProbeToken 'kap2-journal-publisher'
    verifier = Get-ProbeToken 'kap2-verifier'
}
$bundle = @{
    project = $probeProject
    project_number = '771685799600'
    head_bucket = 'kap2-bnd-head-771685799600'
    journal_bucket = 'kap2-bnd-journal-771685799600'
    prefix = $prefix
    head_key = "$prefix/head/current.json"
    versions = @{
        old = "$keyPrefix/old-epoch/cryptoKeyVersions/1"
        new = "$keyPrefix/new-epoch/cryptoKeyVersions/1"
        checkpoint = "$keyPrefix/checkpoint/cryptoKeyVersions/1"
    }
    tokens = $tokens
}
$mode = if ($Preflight) { '--preflight' } elseif ($Smoke) { '--smoke' } elseif ($Resume) { '--resume' } elseif ($FaultReads) { '--fault-reads' } elseif ($StaleCas) { '--stale-cas' } else { '' }
$evidenceName = if ($Preflight) { 'preflight.jsonl' } elseif ($Smoke) { 'smoke.jsonl' } elseif ($FaultReads) { 'fault-reads.jsonl' } elseif ($StaleCas) { 'stale-cas.jsonl' } else { 'events.jsonl' }
$json = ConvertTo-Json $bundle -Compress -Depth 6
$json | ssh -o BatchMode=yes episteck-home "/home/frappe/frappe-bench/env/bin/python /tmp/kap2-bounded-261009/live_bounded_probe.py --socket /tmp/kap2-bounded-261009/mysql.sock --evidence /tmp/kap2-bounded-261009/evidence/$evidenceName $mode"
if ($LASTEXITCODE -ne 0) { throw "Ashburn probe exited $LASTEXITCODE" }
