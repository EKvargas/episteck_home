param(
    [Parameter(Mandatory)] [string] $Project,
    [Parameter(Mandatory)] [string] $Region,
    [Parameter(Mandatory)] [string] $OldWriter,
    [Parameter(Mandatory)] [string] $Bucket,
    [Parameter(Mandatory)] [string] $Output
)

$ErrorActionPreference = 'Stop'
$ring = 'kap2-probe-20261008'
$base = "projects/$Project/locations/$Region/keyRings/$ring/cryptoKeys"
$result = [ordered]@{ region = $Region; method = 'same_preissued_token_after_revoke'; checks = @(); rounds = @() }
$granted = $false

function Invoke-Sign([string] $bearer, [string] $key) {
    $data = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes('KAP2_JOURNAL_V1 synthetic-takeover'))
    $body = @{ data = $data } | ConvertTo-Json -Compress
    try {
        $response = Invoke-WebRequest -Uri "https://cloudkms.googleapis.com/v1/$base/$key/cryptoKeyVersions/1`:asymmetricSign" `
            -Method Post -Headers @{ Authorization = "Bearer $bearer" } -ContentType 'application/json' `
            -Body $body -UseBasicParsing
        return [int] $response.StatusCode
    } catch {
        if ($_.Exception.Response) { return [int] $_.Exception.Response.StatusCode }
        throw
    }
}

function Invoke-Create([string] $bearer, [int] $round) {
    $name = [uri]::EscapeDataString("kap2-takeover-denial/$Region/$round.json")
    $uri = "https://storage.googleapis.com/upload/storage/v1/b/$Bucket/o?uploadType=media&name=$name&ifGenerationMatch=0"
    try {
        $response = Invoke-WebRequest -Uri $uri -Method Post -Headers @{ Authorization = "Bearer $bearer" } `
            -ContentType 'application/json' -Body '{"synthetic":true}' -UseBasicParsing
        return [int] $response.StatusCode
    } catch {
        if ($_.Exception.Response) { return [int] $_.Exception.Response.StatusCode }
        throw
    }
}

try {
    gcloud kms keys add-iam-policy-binding epoch1 --project=$Project --location=$Region --keyring=$ring `
        --member="serviceAccount:$OldWriter" --role=roles/cloudkms.signer --quiet --format=none | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'temporary signer grant failed' }
    $granted = $true
    $bearer = gcloud --verbosity=error auth print-access-token --impersonate-service-account=$OldWriter
    if ($LASTEXITCODE -ne 0 -or -not $bearer) { throw 'old token mint failed' }
    for ($attempt = 1; $attempt -le 4; $attempt++) {
        $baseline = Invoke-Sign $bearer 'epoch1'
        if ($baseline -eq 200) { break }
        Start-Sleep -Seconds 10
    }
    $result.baseline_sign_http = $baseline
    if ($baseline -ne 200) { throw 'preissued token never demonstrated signing access' }
    $result.token_minted_before_revoke = $true
    gcloud kms keys remove-iam-policy-binding epoch1 --project=$Project --location=$Region --keyring=$ring `
        --member="serviceAccount:$OldWriter" --role=roles/cloudkms.signer --quiet --format=none | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'signer revoke failed' }
    $granted = $false
    $result.revoked_at_utc = (Get-Date).ToUniversalTime().ToString('o')
    $started = Get-Date
    $denied = $false
    for ($attempt = 1; $attempt -le 8; $attempt++) {
        $status = Invoke-Sign $bearer 'epoch1'
        $elapsed = [math]::Round(((Get-Date) - $started).TotalSeconds, 1)
        $result.checks += @{ seconds_after_revoke = $elapsed; old_key_http = $status }
        if ($status -eq 403) { $denied = $true; break }
        if ($status -ne 200) { throw "unexpected signing response: $status" }
        Start-Sleep -Seconds 20
    }
    if (-not $denied) { throw 'old token retained signing through the bounded propagation probe' }
    for ($round = 1; $round -le 3; $round++) {
        $old = Invoke-Sign $bearer 'epoch1'
        $new = Invoke-Sign $bearer 'epoch2'
        $create = Invoke-Create $bearer $round
        $result.rounds += @{ old_key_http = $old; new_key_http = $new; journal_create_http = $create }
        if ($old -ne 403 -or $new -ne 403 -or $create -ne 403) {
            throw 'old issued token retained access after propagation'
        }
        if ($round -lt 3) { Start-Sleep -Seconds 2 }
    }
    $result.outcome = 'three_rounds_denied_before_new_admission'
} catch {
    $result.outcome = 'failed'
    $result.error = $_.Exception.Message
    throw
} finally {
    if ($granted) {
        gcloud kms keys remove-iam-policy-binding epoch1 --project=$Project --location=$Region --keyring=$ring `
            --member="serviceAccount:$OldWriter" --role=roles/cloudkms.signer --quiet --format=none | Out-Null
        $result.temporary_signer_grant_removed = ($LASTEXITCODE -eq 0)
    } else {
        $result.temporary_signer_grant_removed = $true
    }
    $result | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $Output -Encoding UTF8
}
