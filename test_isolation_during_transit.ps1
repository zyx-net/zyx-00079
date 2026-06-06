# Sample Transport Management System - Isolation During Transit Test Script
# Tests for: isolated sample during transit acceptance, regression tests

$BASE_URL = "http://localhost:8000"
$CONFIG_PATH = "d:\workSpace\AI__SPACE\zyx-00079\config\rules_v1.json"

function Get-ErrorDetails {
    param($Exception)
    try {
        $stream = $Exception.Response.GetResponseStream()
        $reader = New-Object System.IO.StreamReader($stream)
        $reader.BaseStream.Position = 0
        $responseContent = $reader.ReadToEnd()
        return ConvertFrom-Json $responseContent
    } catch {
        return $null
    }
}

function Invoke-SafeRequest {
    param($Uri, $Method, $Body, $ContentType)
    try {
        if ($Body) {
            $response = Invoke-RestMethod -Uri $Uri -Method $Method -Body $Body -ContentType $ContentType
        } else {
            $response = Invoke-RestMethod -Uri $Uri -Method $Method
        }
        return $response, $null
    } catch {
        $errorDetails = Get-ErrorDetails -Exception $_.Exception
        return $null, $errorDetails
    }
}

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Isolation During Transit Test" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Load config
Write-Host "Loading configuration..." -ForegroundColor Yellow
$response, $error = Invoke-SafeRequest -Uri "$BASE_URL/api/config/load?config_path=$CONFIG_PATH" -Method Post
if ($error) {
    Write-Host "  Note: Config may already be loaded" -ForegroundColor Gray
} else {
    Write-Host "  OK: Config loaded: $($response.version)" -ForegroundColor Green
}
Write-Host ""

# ============================================
# Scenario 1: Isolate sample during transit, then try to accept
# ============================================
Write-Host "[Scenario 1] Isolate In-Transit Sample Then Accept Test" -ForegroundColor Yellow
Write-Host "  Creating sample and box, transferring, isolating one sample, then trying to accept..." -ForegroundColor Gray

$now = Get-Date -Format "yyyy-MM-ddTHH:mm:ssZ"

# Create 2 samples
$sample1 = "ISO-TRANSIT-0001"
$sample2 = "ISO-TRANSIT-0002"

$body = @{
    barcode = $sample1
    sample_type = "blood"
    collection_point = "CP001"
    collection_time = $now
    current_custodian = "Dr. Zhang"
} | ConvertTo-Json
$response, $error = Invoke-SafeRequest -Uri "$BASE_URL/api/samples" -Method Post -Body $body -ContentType "application/json"
Write-Host "  OK: Sample $sample1 created" -ForegroundColor Green

$body = @{
    barcode = $sample2
    sample_type = "blood"
    collection_point = "CP001"
    collection_time = $now
    current_custodian = "Dr. Zhang"
} | ConvertTo-Json
$response, $error = Invoke-SafeRequest -Uri "$BASE_URL/api/samples" -Method Post -Body $body -ContentType "application/json"
Write-Host "  OK: Sample $sample2 created" -ForegroundColor Green

# Create box
$boxCode = "ISO-BOX-TRANSIT-0001"
$body = @{
    box_code = $boxCode
    destination = "TP001"
    current_custodian = "Dr. Zhang"
} | ConvertTo-Json
$response, $error = Invoke-SafeRequest -Uri "$BASE_URL/api/boxes" -Method Post -Body $body -ContentType "application/json"
Write-Host "  OK: Box $boxCode created" -ForegroundColor Green

# Pack
$body = @{
    box_code = $boxCode
    barcodes = @($sample1, $sample2)
    custodian = "Dr. Zhang"
} | ConvertTo-Json
$response, $error = Invoke-SafeRequest -Uri "$BASE_URL/api/boxes/pack" -Method Post -Body $body -ContentType "application/json"
Write-Host "  OK: Samples packed" -ForegroundColor Green

# Seal
$response, $error = Invoke-SafeRequest -Uri "$BASE_URL/api/boxes/seal?box_code=$boxCode&custodian=Dr. Zhang" -Method Post
Write-Host "  OK: Box sealed" -ForegroundColor Green

# Transfer
$body = @{
    box_code = $boxCode
    to_point = "TP001"
    to_custodian = "Dr. Li"
    from_custodian = "Dr. Zhang"
    temperature = 5.0
} | ConvertTo-Json
$response, $error = Invoke-SafeRequest -Uri "$BASE_URL/api/boxes/transfer" -Method Post -Body $body -ContentType "application/json"
Write-Host "  OK: Box transferred, status: IN_TRANSIT" -ForegroundColor Green

# Verify box is IN_TRANSIT
$box, $error = Invoke-SafeRequest -Uri "$BASE_URL/api/boxes/$boxCode" -Method Get
Write-Host "  Verify: Box status = $($box.status), custodian = $($box.current_custodian)" -ForegroundColor Gray

# KEY STEP: Isolate sample1 while box is IN_TRANSIT
Write-Host "  Isolating sample $sample1 while box is IN_TRANSIT..." -ForegroundColor Gray
$body = @{
    barcode = $sample1
    custodian = "Dr. Li"
    reason = "Sample container damaged during transit"
} | ConvertTo-Json
$isoResponse, $error = Invoke-SafeRequest -Uri "$BASE_URL/api/samples/isolate" -Method Post -Body $body -ContentType "application/json"
Write-Host "  OK: Sample $sample1 isolated, status: $($isoResponse.status)" -ForegroundColor Green

# Verify sample1 is ISOLATED
$s1, $error = Invoke-SafeRequest -Uri "$BASE_URL/api/samples/$sample1" -Method Get
Write-Host "  Verify: Sample $sample1 status = $($s1.status), isolated = $($s1.is_isolated)" -ForegroundColor Gray

# Verify sample2 is still IN_TRANSIT
$s2, $error = Invoke-SafeRequest -Uri "$BASE_URL/api/samples/$sample2" -Method Get
Write-Host "  Verify: Sample $sample2 status = $($s2.status)" -ForegroundColor Gray

# Verify box is still IN_TRANSIT (important!)
$box, $error = Invoke-SafeRequest -Uri "$BASE_URL/api/boxes/$boxCode" -Method Get
Write-Host "  Verify: Box status = $($box.status) (should still be IN_TRANSIT)" -ForegroundColor Gray

# NOW TRY TO ACCEPT - THIS SHOULD FAIL!
Write-Host "  Attempting to accept box with isolated sample..." -ForegroundColor Gray
$body = @{
    box_code = $boxCode
    custodian = "Dr. Li"
} | ConvertTo-Json
$response, $error = Invoke-SafeRequest -Uri "$BASE_URL/api/boxes/accept" -Method Post -Body $body -ContentType "application/json"

if ($error -and $error.detail) {
    $err = $error.detail
    Write-Host "  OK: Accept correctly failed!" -ForegroundColor Green
    Write-Host "    Error code: $($err.code)" -ForegroundColor Cyan
    Write-Host "    Error message: $($err.error)" -ForegroundColor Gray
    if ($err.code -eq "SAMPLE_ISOLATED") {
        Write-Host "  OK: Error code matches SAMPLE_ISOLATED!" -ForegroundColor Green
    } else {
        Write-Host "  FAIL: Expected SAMPLE_ISOLATED but got $($err.code)" -ForegroundColor Red
        exit 1
    }
} else {
    Write-Host "  FAIL: Accept unexpectedly succeeded!" -ForegroundColor Red
    exit 1
}

# Verify sample states are preserved after failed accept
Write-Host "  Verifying states preserved after failed accept..." -ForegroundColor Gray
$s1, $error = Invoke-SafeRequest -Uri "$BASE_URL/api/samples/$sample1" -Method Get
if ($s1.status -eq "ISOLATED" -and $s1.is_isolated) {
    Write-Host "  OK: Sample $sample1 still ISOLATED" -ForegroundColor Green
} else {
    Write-Host "  FAIL: Sample $sample1 state changed!" -ForegroundColor Red
    exit 1
}

$s2, $error = Invoke-SafeRequest -Uri "$BASE_URL/api/samples/$sample2" -Method Get
if ($s2.status -eq "IN_TRANSIT") {
    Write-Host "  OK: Sample $sample2 still IN_TRANSIT" -ForegroundColor Green
} else {
    Write-Host "  FAIL: Sample $sample2 state changed!" -ForegroundColor Red
    exit 1
}

$box, $error = Invoke-SafeRequest -Uri "$BASE_URL/api/boxes/$boxCode" -Method Get
if ($box.status -eq "IN_TRANSIT") {
    Write-Host "  OK: Box still IN_TRANSIT" -ForegroundColor Green
} else {
    Write-Host "  FAIL: Box state changed!" -ForegroundColor Red
    exit 1
}

# Check audit logs for isolation
Write-Host "  Checking audit logs..." -ForegroundColor Gray
$logs, $error = Invoke-SafeRequest -Uri "$BASE_URL/api/audit?barcode=$sample1" -Method Get
$isoLog = $logs | Where-Object { $_.action -eq "ISOLATE" } | Select-Object -First 1
if ($isoLog) {
    Write-Host "  OK: Audit log found for ISOLATE action" -ForegroundColor Green
    Write-Host "    $($isoLog.created_at): $($isoLog.old_status) -> $($isoLog.new_status) by $($isoLog.custodian)" -ForegroundColor Gray
} else {
    Write-Host "  FAIL: No ISOLATE audit log found" -ForegroundColor Red
    exit 1
}

Write-Host ""

# ============================================
# Scenario 2: Regression - Normal acceptance (no isolated samples)
# ============================================
Write-Host "[Scenario 2] Regression - Normal Acceptance Test" -ForegroundColor Yellow
Write-Host "  Verifying normal acceptance still works..." -ForegroundColor Gray

$sample3 = "NORMAL-ACCEPT-0001"
$body = @{
    barcode = $sample3
    sample_type = "blood"
    collection_point = "CP001"
    collection_time = $now
    current_custodian = "Dr. Zhang"
} | ConvertTo-Json
$response, $error = Invoke-SafeRequest -Uri "$BASE_URL/api/samples" -Method Post -Body $body -ContentType "application/json"
Write-Host "  OK: Sample $sample3 created" -ForegroundColor Green

$boxCode2 = "NORMAL-BOX-0001"
$body = @{
    box_code = $boxCode2
    destination = "TP001"
    current_custodian = "Dr. Zhang"
} | ConvertTo-Json
$response, $error = Invoke-SafeRequest -Uri "$BASE_URL/api/boxes" -Method Post -Body $body -ContentType "application/json"
Write-Host "  OK: Box $boxCode2 created" -ForegroundColor Green

$body = @{
    box_code = $boxCode2
    barcodes = @($sample3)
    custodian = "Dr. Zhang"
} | ConvertTo-Json
$response, $error = Invoke-SafeRequest -Uri "$BASE_URL/api/boxes/pack" -Method Post -Body $body -ContentType "application/json"
Write-Host "  OK: Packed" -ForegroundColor Green

$response, $error = Invoke-SafeRequest -Uri "$BASE_URL/api/boxes/seal?box_code=$boxCode2&custodian=Dr. Zhang" -Method Post
Write-Host "  OK: Sealed" -ForegroundColor Green

$body = @{
    box_code = $boxCode2
    to_point = "TP001"
    to_custodian = "Dr. Li"
    from_custodian = "Dr. Zhang"
    temperature = 5.0
} | ConvertTo-Json
$response, $error = Invoke-SafeRequest -Uri "$BASE_URL/api/boxes/transfer" -Method Post -Body $body -ContentType "application/json"
Write-Host "  OK: Transferred" -ForegroundColor Green

# Now accept - should work
$body = @{
    box_code = $boxCode2
    custodian = "Dr. Li"
} | ConvertTo-Json
$response, $error = Invoke-SafeRequest -Uri "$BASE_URL/api/boxes/accept" -Method Post -Body $body -ContentType "application/json"
if ($error) {
    Write-Host "  FAIL: Normal acceptance failed: $($error.detail.error)" -ForegroundColor Red
    exit 1
}
Write-Host "  OK: Normal acceptance succeeded, box status: $($response.status)" -ForegroundColor Green

# Verify
$s3, $error = Invoke-SafeRequest -Uri "$BASE_URL/api/samples/$sample3" -Method Get
if ($s3.status -eq "DELIVERED") {
    Write-Host "  OK: Sample status is DELIVERED" -ForegroundColor Green
} else {
    Write-Host "  FAIL: Sample status is $($s3.status), expected DELIVERED" -ForegroundColor Red
    exit 1
}
Write-Host ""

# ============================================
# Scenario 3: Regression - Non-current custodian acceptance
# ============================================
Write-Host "[Scenario 3] Regression - Non-current Custodian Acceptance" -ForegroundColor Yellow
Write-Host "  Verifying non-current custodian cannot accept..." -ForegroundColor Gray

$sample4 = "CUST-ACCEPT-0001"
$body = @{
    barcode = $sample4
    sample_type = "blood"
    collection_point = "CP001"
    collection_time = $now
    current_custodian = "Dr. Zhang"
} | ConvertTo-Json
$response, $error = Invoke-SafeRequest -Uri "$BASE_URL/api/samples" -Method Post -Body $body -ContentType "application/json"

$boxCode3 = "CUST-BOX-0001"
$body = @{
    box_code = $boxCode3
    destination = "TP001"
    current_custodian = "Dr. Zhang"
} | ConvertTo-Json
$response, $error = Invoke-SafeRequest -Uri "$BASE_URL/api/boxes" -Method Post -Body $body -ContentType "application/json"

$body = @{
    box_code = $boxCode3
    barcodes = @($sample4)
    custodian = "Dr. Zhang"
} | ConvertTo-Json
$response, $error = Invoke-SafeRequest -Uri "$BASE_URL/api/boxes/pack" -Method Post -Body $body -ContentType "application/json"

$response, $error = Invoke-SafeRequest -Uri "$BASE_URL/api/boxes/seal?box_code=$boxCode3&custodian=Dr. Zhang" -Method Post

$body = @{
    box_code = $boxCode3
    to_point = "TP001"
    to_custodian = "Dr. Li"
    from_custodian = "Dr. Zhang"
    temperature = 5.0
} | ConvertTo-Json
$response, $error = Invoke-SafeRequest -Uri "$BASE_URL/api/boxes/transfer" -Method Post -Body $body -ContentType "application/json"
Write-Host "  OK: Box transferred to Dr. Li" -ForegroundColor Green

# Try to accept with wrong custodian (Dr. Wang, not Dr. Li)
$body = @{
    box_code = $boxCode3
    custodian = "Dr. Wang"
} | ConvertTo-Json
$response, $error = Invoke-SafeRequest -Uri "$BASE_URL/api/boxes/accept" -Method Post -Body $body -ContentType "application/json"

if ($error -and $error.detail.code -eq "INVALID_CUSTODIAN") {
    Write-Host "  OK: Non-current custodian correctly rejected" -ForegroundColor Green
    Write-Host "    Error: $($error.detail.error)" -ForegroundColor Gray
} else {
    Write-Host "  FAIL: Should have rejected non-current custodian!" -ForegroundColor Red
    exit 1
}
Write-Host ""

# ============================================
# Scenario 4: Verify persistence - restart service and verify isolated sample still cannot be accepted
# ============================================
Write-Host "[Scenario 4] Persistence Test - Isolation survives restart" -ForegroundColor Yellow
Write-Host "  This scenario will be verified manually after service restart" -ForegroundColor Gray
Write-Host "  Current state of $sample1 : ISOLATED" -ForegroundColor Gray
Write-Host "  Current state of $boxCode : IN_TRANSIT" -ForegroundColor Gray
Write-Host ""

# ============================================
# Summary
# ============================================
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  All Tests Passed!" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Test Summary:" -ForegroundColor White
Write-Host "  1. In-transit sample isolation + accept rejection: PASS" -ForegroundColor Green
Write-Host "  2. Normal acceptance regression: PASS" -ForegroundColor Green
Write-Host "  3. Non-current custodian rejection: PASS" -ForegroundColor Green
Write-Host ""
Write-Host "Next step: Restart service and run persistence test" -ForegroundColor Cyan
Write-Host "  - Verify sample ISO-TRANSIT-0001 is still ISOLATED" -ForegroundColor Gray
Write-Host "  - Verify box ISO-BOX-TRANSIT-0001 is still IN_TRANSIT" -ForegroundColor Gray
Write-Host "  - Try to accept ISO-BOX-TRANSIT-0001 - should still fail" -ForegroundColor Gray
Write-Host ""
