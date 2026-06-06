# Sample Transport Management System - Transfer Revoke Flow Test Script
# Tests: revoke transfer, re-transfer, acceptance after revoke, export consistency, etc.

$BASE_URL = "http://localhost:8000"
$CONFIG_PATH = "d:\workSpace\AI__SPACE\zyx-00079\config\rules_v1.json"
$TEST_RESULTS = @()

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Sample Transport Management System" -ForegroundColor Cyan
Write-Host "  Transfer Revoke Flow Test" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

$timestamp = Get-Date -Format "yyyyMMddHHmmss"
$boxCodeRevoke = "BOX-REVOKE-$timestamp"
$barcode1 = "BLD-REVOKE-$timestamp-01"
$barcode2 = "BLD-REVOKE-$timestamp-02"

function Write-TestResult {
    param(
        [string]$TestName,
        [bool]$Passed,
        [string]$Details
    )
    $result = @{
        TestName = $TestName; Passed = $Passed; Details = $Details }
    $TEST_RESULTS += $result
    if ($Passed) {
        Write-Host "  [PASS] $TestName" -ForegroundColor Green
        if ($Details) { Write-Host "         $Details" -ForegroundColor Gray }
    } else {
        Write-Host "  [FAIL] $TestName" -ForegroundColor Red
        if ($Details) { Write-Host "         $Details" -ForegroundColor Gray }
    }
}

# 1. Check service health
Write-Host "[1/15] Checking service health..." -ForegroundColor Yellow
try {
    $response = Invoke-RestMethod -Uri "$BASE_URL/health" -Method Get
    Write-Host "  OK: Service is running" -ForegroundColor Green
    Write-Host "    Config version: $($response.config_version)"
} catch {
    Write-Host "  ERROR: Service not running, please run: python main.py" -ForegroundColor Red
    exit 1
}
Write-Host ""

# 2. Load configuration
Write-Host "[2/15] Loading configuration..." -ForegroundColor Yellow
try {
    $response = Invoke-RestMethod -Uri "$BASE_URL/api/config/load?config_path=$CONFIG_PATH" -Method Post
    Write-Host "  OK: Config loaded successfully" -ForegroundColor Green
    Write-Host "    Version: $($response.version)"
} catch {
    $errorMsg = $_.Exception.Message
    Write-Host "  ERROR: Failed to load config: $errorMsg" -ForegroundColor Red
    exit 1
}
Write-Host ""

# 3. Create samples
Write-Host "[3/15] Creating test samples..." -ForegroundColor Yellow
$now = Get-Date -Format "yyyy-MM-ddTHH:mm:ssZ"
$barcodes = @($barcode1, $barcode2)

foreach ($barcode in $barcodes) {
    $patientInfo = @{
        name = "Test Patient"
        id = $barcode
    } | ConvertTo-Json -Compress

    $body = @{
        barcode = $barcode
        sample_type = "blood"
        collection_point = "CP001"
        collection_time = $now
        patient_info = $patientInfo
        current_custodian = "Dr. Zhang"
    } | ConvertTo-Json

    try {
        $response = Invoke-RestMethod -Uri "$BASE_URL/api/samples" -Method Post -Body $body -ContentType "application/json"
        Write-Host "  OK: Sample $barcode created" -ForegroundColor Green
    } catch {
        $errorMsg = $_.Exception.Message
        Write-Host "  ERROR: Failed to create sample $barcode : $errorMsg" -ForegroundColor Red
        exit 1
    }
}
Write-Host ""

# 4. Create transport box
Write-Host "[4/15] Creating transport box..." -ForegroundColor Yellow
$body = @{
    box_code = $boxCodeRevoke
    destination = "TP001"
    current_custodian = "Dr. Zhang"
} | ConvertTo-Json

try {
    $response = Invoke-RestMethod -Uri "$BASE_URL/api/boxes" -Method Post -Body $body -ContentType "application/json"
    Write-Host "  OK: Box $boxCodeRevoke created" -ForegroundColor Green
    Write-Host "    Status: $($response.status)"
} catch {
    $errorMsg = $_.Exception.Message
    Write-Host "  ERROR: Failed to create box: $errorMsg" -ForegroundColor Red
    exit 1
}
Write-Host ""

# 5. Pack samples into box
Write-Host "[5/15] Packing samples into box..." -ForegroundColor Yellow
$body = @{
    box_code = $boxCodeRevoke
    barcodes = $barcodes
    custodian = "Dr. Zhang"
} | ConvertTo-Json

try {
    $response = Invoke-RestMethod -Uri "$BASE_URL/api/boxes/pack" -Method Post -Body $body -ContentType "application/json"
    Write-Host "  OK: Packing successful" -ForegroundColor Green
} catch {
    $errorMsg = $_.Exception.Message
    Write-Host "  ERROR: Packing failed: $errorMsg" -ForegroundColor Red
    exit 1
}
Write-Host ""

# 6. Seal the box
Write-Host "[6/15] Sealing the box..." -ForegroundColor Yellow
try {
    $response = Invoke-RestMethod -Uri "$BASE_URL/api/boxes/seal?box_code=$boxCodeRevoke&custodian=Dr. Zhang" -Method Post
    Write-Host "  OK: Box sealed" -ForegroundColor Green
    Write-Host "    Status: $($response.status)"
} catch {
    $errorMsg = $_.Exception.Message
    Write-Host "  ERROR: Seal failed: $errorMsg" -ForegroundColor Red
    exit 1
}
Write-Host ""

# 7. Transfer
Write-Host "[7/15] Transferring box..." -ForegroundColor Yellow
$tempRecords = @(
    @{ temperature = 4.0; timestamp = $now },
    @{ temperature = 5.5; timestamp = $now }
) | ConvertTo-Json -Compress

$body = @{
    box_code = $boxCodeRevoke
    to_point = "TP001"
    to_custodian = "Dr. Li"
    from_custodian = "Dr. Zhang"
    temperature = 5.0
    temperature_records = $tempRecords
} | ConvertTo-Json

try {
    $response = Invoke-RestMethod -Uri "$BASE_URL/api/boxes/transfer" -Method Post -Body $body -ContentType "application/json"
    $global:firstTransferId = $response.transfer_id
    Write-Host "  OK: Transfer successful" -ForegroundColor Green
    Write-Host "    Transfer ID: $firstTransferId"
    Write-Host "    Custodian: $($response.from_custodian) -> $($response.to_custodian)"
} catch {
    $errorMsg = $_.Exception.Message
    Write-Host "  ERROR: Transfer failed: $errorMsg" -ForegroundColor Red
    exit 1
}
Write-Host ""

# Test 1: Non-custodian revoke (should fail)
Write-Host "[Test 1] Testing non-custodian revoke (should fail)..." -ForegroundColor Yellow
$body = @{
    box_code = $boxCodeRevoke
    custodian = "Dr. Wang"
    reason = "Test non-custodian revoke"
} | ConvertTo-Json

try {
    $response = Invoke-RestMethod -Uri "$BASE_URL/api/boxes/revoke-transfer" -Method Post -Body $body -ContentType "application/json"
    Write-TestResult -TestName "Non-custodian revoke should fail" -Passed $false -Details "Should have rejected non-custodian but succeeded"
} catch {
    $errorResponse = $_.ErrorDetails.Message | ConvertFrom-Json
    if ($errorResponse.code -eq "INVALID_CUSTODIAN") {
        Write-TestResult -TestName "Non-custodian revoke" -Passed $true -Details "Correctly rejected with INVALID_CUSTODIAN"
    } else {
        Write-TestResult -TestName "Non-custodian revoke" -Passed $false -Details "Wrong error code: $($errorResponse.code)"
    }
}
Write-Host ""

# 8. Verify state before revoke
Write-Host "[8/15] Verifying state before revoke..." -ForegroundColor Yellow
try {
    $boxBefore = Invoke-RestMethod -Uri "$BASE_URL/api/boxes/$boxCodeRevoke" -Method Get
    Write-Host "  Box status before revoke: $($boxBefore.status), custodian: $($boxBefore.current_custodian)" -ForegroundColor Gray
    $sampleBefore = Invoke-RestMethod -Uri "$BASE_URL/api/samples/$barcode1" -Method Get
    Write-Host "  Sample status before revoke: $($sampleBefore.status), custodian: $($sampleBefore.current_custodian)" -ForegroundColor Gray
} catch {
    $errorMsg = $_.Exception.Message
    Write-Host "  ERROR: $errorMsg" -ForegroundColor Red
}
Write-Host ""

# 9. Revoke transfer - SUCCESS
Write-Host "[9/15] Revoking transfer..." -ForegroundColor Yellow
$body = @{
    box_code = $boxCodeRevoke
    custodian = "Dr. Li"
    reason = "交接信息录入错误，接收人信息填错"
} | ConvertTo-Json

try {
    $response = Invoke-RestMethod -Uri "$BASE_URL/api/boxes/revoke-transfer" -Method Post -Body $body -ContentType "application/json"
    $revokedTransferId = $response.revoked_transfer_id
    Write-Host "  OK: Transfer revoked successfully" -ForegroundColor Green
    Write-Host "    Revoked transfer ID: $revokedTransferId"
    Write-Host "    Box status: $($response.old_box_status) -> $($response.new_box_status)"
    Write-Host "    Custodian: $($response.old_custodian) -> $($response.new_custodian)"
    Write-TestResult -TestName "Revoke transfer" -Passed $true -Details "Successfully revoked transfer #$revokedTransferId"
} catch {
    $errorMsg = $_.Exception.Message
    Write-TestResult -TestName "Revoke transfer" -Passed $false -Details $errorMsg
}
Write-Host ""

# 10. Verify state after revoke
Write-Host "[10/15] Verifying state after revoke..." -ForegroundColor Yellow
try {
    $boxAfter = Invoke-RestMethod -Uri "$BASE_URL/api/boxes/$boxCodeRevoke" -Method Get
    $sampleAfter = Invoke-RestMethod -Uri "$BASE_URL/api/samples/$barcode1" -Method Get

    $boxPassed = ($boxAfter.status -eq "SEALED") -and ($boxAfter.current_custodian -eq "Dr. Zhang")
    $samplePassed = ($sampleAfter.status -eq "SEALED") -and ($sampleAfter.current_custodian -eq "Dr. Zhang")

    if ($boxPassed -and $samplePassed) {
        Write-TestResult -TestName "State after revoke" -Passed $true -Details "Box and sample correctly rolled back to SEALED with original custodian"
    } else {
        Write-TestResult -TestName "State after revoke" -Passed $false -Details "Box status: $($boxAfter.status)/SEALED, custodian: $($boxAfter.current_custodian); Sample status: $($sampleAfter.status), custodian: $($sampleAfter.current_custodian)"
    }

    Write-Host "  Box status: $($boxAfter.status), custodian: $($boxAfter.current_custodian)" -ForegroundColor Gray
    Write-Host "  Sample status: $($sampleAfter.status), custodian: $($sampleAfter.current_custodian)" -ForegroundColor Gray
} catch {
    $errorMsg = $_.Exception.Message
    Write-TestResult -TestName "State after revoke" -Passed $false -Details $errorMsg
}
Write-Host ""

# Test 2: Duplicate revoke (should fail)
Write-Host "[Test 2] Testing duplicate revoke (should fail)..." -ForegroundColor Yellow
$body = @{
    box_code = $boxCodeRevoke
    custodian = "Dr. Zhang"
    reason = "Trying to revoke again"
} | ConvertTo-Json

try {
    $response = Invoke-RestMethod -Uri "$BASE_URL/api/boxes/revoke-transfer" -Method Post -Body $body -ContentType "application/json"
    Write-TestResult -TestName "Duplicate revoke should fail" -Passed $false -Details "Should have rejected duplicate revoke but succeeded"
} catch {
    $errorResponse = $_.ErrorDetails.Message | ConvertFrom-Json
    if ($errorResponse.code -eq "TRANSFER_ALREADY_REVOKED") {
        Write-TestResult -TestName "Duplicate revoke" -Passed $true -Details "Correctly rejected with $($errorResponse.code)"
    } else {
        Write-TestResult -TestName "Duplicate revoke" -Passed $false -Details "Wrong error code: $($errorResponse.code)"
    }
}
Write-Host ""

# 11. Transfer again after revoke
Write-Host "[11/15] Re-transferring after revoke..." -ForegroundColor Yellow
$tempRecords2 = @(
    @{ temperature = 4.5; timestamp = $now },
    @{ temperature = 5.0; timestamp = $now }
) | ConvertTo-Json -Compress

$body = @{
    box_code = $boxCodeRevoke
    to_point = "TP001"
    to_custodian = "Dr. Li"
    from_custodian = "Dr. Zhang"
    temperature = 4.8
    temperature_records = $tempRecords2
} | ConvertTo-Json

try {
    $response = Invoke-RestMethod -Uri "$BASE_URL/api/boxes/transfer" -Method Post -Body $body -ContentType "application/json"
    $newTransferId = $response.transfer_id
    Write-Host "  OK: Re-transfer successful" -ForegroundColor Green
    Write-Host "    New transfer ID: $newTransferId"
    Write-Host "    Rule version: $($response.rule_version)"
    Write-TestResult -TestName "Re-transfer after revoke" -Passed $true -Details "Created new transfer #$newTransferId, old #$firstTransferId preserved"
} catch {
    $errorMsg = $_.Exception.Message
    Write-TestResult -TestName "Re-transfer after revoke" -Passed $false -Details $errorMsg
}
Write-Host ""

# 12. Verify transfer history
Write-Host "[12/15] Verifying transfer history..." -ForegroundColor Yellow
try {
    $history = Invoke-RestMethod -Uri "$BASE_URL/api/boxes/$boxCodeRevoke/transfer-history" -Method Get
    Write-Host "  Transfer history count: $($history.Count)" -ForegroundColor Gray

    $revokedCount = ($history | Where-Object { $_.is_revoked -eq $true }).Count
    $activeCount = ($history | Where-Object { $_.is_revoked -eq $false }).Count

    Write-Host "  Revoked records: $revokedCount, Active records: $activeCount" -ForegroundColor Gray

    if ($history.Count -ge 2 -and $revokedCount -ge 1 -and $activeCount -ge 1) {
        Write-TestResult -TestName "Transfer history" -Passed $true -Details "History shows both revoked and active records, old records not overwritten"
    } else {
        Write-TestResult -TestName "Transfer history" -Passed $false -Details "Expected >=2 records, got $($history.Count). Revoked: $revokedCount, Active: $activeCount"
    }

    foreach ($t in $history) {
        Write-Host "    [$($t.id)] $($t.from_custodian) -> $($t.to_custodian), revoked: $($t.is_revoked)" -ForegroundColor Gray
    }
} catch {
    $errorMsg = $_.Exception.Message
    Write-TestResult -TestName "Transfer history" -Passed $false -Details $errorMsg
}
Write-Host ""

# 13. Acceptance after re-transfer
Write-Host "[13/15] Accepting box at destination after re-transfer..." -ForegroundColor Yellow
$body = @{
    box_code = $boxCodeRevoke
    custodian = "Dr. Li"
    check_duration = $false
} | ConvertTo-Json

try {
    $response = Invoke-RestMethod -Uri "$BASE_URL/api/boxes/accept" -Method Post -Body $body -ContentType "application/json"
    Write-Host "  OK: Acceptance successful after re-transfer" -ForegroundColor Green
    Write-Host "    Box status: $($response.status)"
    Write-TestResult -TestName "Acceptance after re-transfer" -Passed $true -Details "Successfully accepted after revoke and re-transfer"
} catch {
    $errorMsg = $_.Exception.Message
    Write-TestResult -TestName "Acceptance after re-transfer" -Passed $false -Details $errorMsg
}
Write-Host ""

# Test 3: Revoke after acceptance (should fail)
Write-Host "[Test 3] Testing revoke after acceptance (should fail)..." -ForegroundColor Yellow
$body = @{
    box_code = $boxCodeRevoke
    custodian = "Dr. Li"
    reason = "Trying to revoke after acceptance"
} | ConvertTo-Json

try {
    $response = Invoke-RestMethod -Uri "$BASE_URL/api/boxes/revoke-transfer" -Method Post -Body $body -ContentType "application/json"
    Write-TestResult -TestName "Revoke after acceptance" -Passed $false -Details "Should have rejected revoke after acceptance but succeeded"
} catch {
    $errorResponse = $_.ErrorDetails.Message | ConvertFrom-Json
    if ($errorResponse.code -eq "BOX_INVALID_STATUS") {
        Write-TestResult -TestName "Revoke after acceptance" -Passed $true -Details "Correctly rejected with BOX_INVALID_STATUS (DELIVERED state cannot be revoked)"
    } else {
        Write-TestResult -TestName "Revoke after acceptance" -Passed $false -Details "Wrong error code: $($errorResponse.code)"
    }
}
Write-Host ""

# 14. Generate handover form and verify revoke history
Write-Host "[14/15] Generating handover form with revoke history..." -ForegroundColor Yellow
try {
    $form = Invoke-RestMethod -Uri "$BASE_URL/api/boxes/$boxCodeRevoke/handover-form" -Method Get
    Write-Host "  OK: Handover form generated" -ForegroundColor Green

    $hasRevokedHistory = $form.revoked_transfer_history -ne $null
    $exportPath = "d:\workSpace\AI__SPACE\zyx-00079\exports\handover_form_$boxCodeRevoke.json"
    $exportContent = Get-Content $exportPath -Raw | ConvertFrom-Json

    if ($hasRevokedHistory -and $exportContent.revoked_transfer_history) {
        Write-TestResult -TestName "Handover form revoke history" -Passed $true -Details "Handover form contains revoked transfer history in both API and exported JSON"
        Write-Host "  Revoked history count: $($form.revoked_transfer_history.Count)" -ForegroundColor Gray
    } else {
        Write-TestResult -TestName "Handover form revoke history" -Passed $false -Details "Missing revoked transfer history"
    }
} catch {
    $errorMsg = $_.Exception.Message
    Write-TestResult -TestName "Handover form revoke history" -Passed $false -Details $errorMsg
}
Write-Host ""

# 15. Generate exception list and verify consistency
Write-Host "[15/15] Generating exception list and audit logs..." -ForegroundColor Yellow
try {
    $exceptionList = Invoke-RestMethod -Uri "$BASE_URL/api/boxes/$boxCodeRevoke/exception-list" -Method Get
    Write-Host "  OK: Exception list generated" -ForegroundColor Green
    $revokeExceptions = ($exceptionList.exceptions | Where-Object { $_.type -eq "TRANSFER_REVOKED" }).Count
    Write-Host "  Revoke exceptions: $revokeExceptions" -ForegroundColor Gray

    $auditLogs = Invoke-RestMethod -Uri "$BASE_URL/api/audit?entity_type=TRANSFER&action=REVOKE_TRANSFER" -Method Get
    Write-Host "  REVOKE_TRANSFER audit logs: $($auditLogs.Count)" -ForegroundColor Gray

    $auditLogsBox = Invoke-RestMethod -Uri "$BASE_URL/api/audit?entity_type=BOX&action=REVOKE_TRANSFER" -Method Get
    $auditLogsSample = Invoke-RestMethod -Uri "$BASE_URL/api/audit?entity_type=SAMPLE&action=REVOKE_TRANSFER" -Method Get

    $transferAuditPassed = $auditLogs.Count -ge 1
    $boxAuditPassed = $auditLogsBox.Count -ge 1
    $sampleAuditPassed = $auditLogsSample.Count -ge 2

    $allAuditPassed = $transferAuditPassed -and $boxAuditPassed -and $sampleAuditPassed

    if ($allAuditPassed) {
        Write-TestResult -TestName "Audit log consistency" -Passed $true -Details "Audit logs present for TRANSFER, BOX, and SAMPLE entities"
    } else {
        Write-TestResult -TestName "Audit log consistency" -Passed $false -Details "Missing audit logs: Transfer=$transferAuditPassed, Box=$boxAuditPassed, Sample=$sampleAuditPassed"
    }

    Write-Host "  Transfer audit logs: $($auditLogs.Count), Box: $($auditLogsBox.Count), Sample: $($auditLogsSample.Count)" -ForegroundColor Gray
} catch {
    $errorMsg = $_.Exception.Message
    Write-TestResult -TestName "Audit log consistency" -Passed $false -Details $errorMsg
}
Write-Host ""

# Test persistence (manual verification section)
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Service Restart Persistence Test" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Please perform the following manual test:" -ForegroundColor Yellow
Write-Host "  1. Restart the service (stop and start main.py)" -ForegroundColor Gray
Write-Host "  2. Run the following commands to verify data persistence:" -ForegroundColor Gray
Write-Host "     curl ""$BASE_URL/api/boxes/$boxCodeRevoke" -ForegroundColor Gray
Write-Host "     curl ""$BASE_URL/api/boxes/$boxCodeRevoke/transfer-history" -ForegroundColor Gray
Write-Host "     curl ""$BASE_URL/api/audit?action=REVOKE_TRANSFER" -ForegroundColor Gray
Write-Host "  3. Verify that:" -ForegroundColor Gray
Write-Host "     - Box status is DELIVERED" -ForegroundColor Gray
Write-Host "     - Transfer history shows both revoked and active records" -ForegroundColor Gray
Write-Host "     - Audit logs are preserved" -ForegroundColor Gray
Write-Host ""

# Summary
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Test Summary" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

$passed = ($TEST_RESULTS | Where-Object { $_.Passed -eq $true }).Count
$failed = $TEST_RESULTS.Count - $passed

Write-Host "  Total Tests: $($TEST_RESULTS.Count)" -ForegroundColor White
Write-Host "  Passed: $passed" -ForegroundColor Green
Write-Host "  Failed: $failed" -ForegroundColor $(if ($failed -eq 0) { "Green" } else { "Red" })
Write-Host ""

if ($failed -eq 0) {
    Write-Host "  All tests passed!" -ForegroundColor Green
} else {
    Write-Host "  Some tests failed. Please review the results above." -ForegroundColor Red
    Write-Host ""
    Write-Host "  Failed tests:" -ForegroundColor Red
    $TEST_RESULTS | Where-Object { $_.Passed -eq $false } | ForEach-Object {
        Write-Host "    - $($_.TestName): $($_.Details)" -ForegroundColor Red
    }
    exit 1
}

Write-Host ""
Write-Host "  Test box code: $boxCodeRevoke" -ForegroundColor Gray
Write-Host "  Please check exports\handover_form_$boxCodeRevoke.json" -ForegroundColor Gray
Write-Host "  Please check exports\exception_list_$boxCodeRevoke.json" -ForegroundColor Gray
Write-Host ""
