# Sample Transport Management System - Complete Flow Test Script
# Full lifecycle: sample creation -> boxing -> transfer -> acceptance -> testing -> archive

$BASE_URL = "http://localhost:8000"
$CONFIG_PATH = "d:\workSpace\AI__SPACE\zyx-00079\config\rules_v1.json"

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Sample Transport Management System" -ForegroundColor Cyan
Write-Host "  Complete Flow Test" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# 1. Check service health
Write-Host "[1/12] Checking service health..." -ForegroundColor Yellow
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
Write-Host "[2/12] Loading configuration..." -ForegroundColor Yellow
try {
    $response = Invoke-RestMethod -Uri "$BASE_URL/api/config/load?config_path=$CONFIG_PATH" -Method Post
    Write-Host "  OK: Config loaded successfully" -ForegroundColor Green
    Write-Host "    Version: $($response.version)"
    Write-Host "    File: $($response.rule_file_path)"
} catch {
    $errorMsg = $_.Exception.Message
    Write-Host "  ERROR: Failed to load config: $errorMsg" -ForegroundColor Red
}
Write-Host ""

# 3. Create samples - 3 blood samples
Write-Host "[3/12] Creating 3 blood samples..." -ForegroundColor Yellow
$now = Get-Date -Format "yyyy-MM-ddTHH:mm:ssZ"
$barcodes = @("BLD-2026-0001", "BLD-2026-0002", "BLD-2026-0003")

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
        Write-Host "    Status: $($response.status)"
    } catch {
        $errorMsg = $_.Exception.Message
        Write-Host "  ERROR: Failed to create sample $barcode : $errorMsg" -ForegroundColor Red
    }
}
Write-Host ""

# 4. Create transport box
Write-Host "[4/12] Creating transport box..." -ForegroundColor Yellow
$boxCode = "BOX-2026-0001"
$body = @{
    box_code = $boxCode
    destination = "TP001"
    current_custodian = "Dr. Zhang"
} | ConvertTo-Json

try {
    $response = Invoke-RestMethod -Uri "$BASE_URL/api/boxes" -Method Post -Body $body -ContentType "application/json"
    Write-Host "  OK: Box $boxCode created" -ForegroundColor Green
    Write-Host "    Status: $($response.status)"
} catch {
    $errorMsg = $_.Exception.Message
    Write-Host "  ERROR: Failed to create box: $errorMsg" -ForegroundColor Red
}
Write-Host ""

# 5. Pack samples into box
Write-Host "[5/12] Packing samples into box..." -ForegroundColor Yellow
$body = @{
    box_code = $boxCode
    barcodes = $barcodes
    custodian = "Dr. Zhang"
} | ConvertTo-Json

try {
    $response = Invoke-RestMethod -Uri "$BASE_URL/api/boxes/pack" -Method Post -Body $body -ContentType "application/json"
    Write-Host "  OK: Packing successful" -ForegroundColor Green
    Write-Host "    Samples in box: $($response.samples.Count)"
    foreach ($s in $response.samples) {
        Write-Host "      - $($s.barcode): $($s.status)"
    }
} catch {
    $errorMsg = $_.Exception.Message
    Write-Host "  ERROR: Packing failed: $errorMsg" -ForegroundColor Red
}
Write-Host ""

# 6. Seal the box
Write-Host "[6/12] Sealing the box..." -ForegroundColor Yellow
try {
    $response = Invoke-RestMethod -Uri "$BASE_URL/api/boxes/seal?box_code=$boxCode&custodian=Dr. Zhang" -Method Post
    Write-Host "  OK: Box sealed" -ForegroundColor Green
    Write-Host "    Status: $($response.status)"
    Write-Host "    Sealed at: $($response.sealed_at)"
} catch {
    $errorMsg = $_.Exception.Message
    Write-Host "  ERROR: Seal failed: $errorMsg" -ForegroundColor Red
}
Write-Host ""

# 7. Transfer
Write-Host "[7/12] Transferring box..." -ForegroundColor Yellow
$tempRecords = @(
    @{ temperature = 4.0; timestamp = $now },
    @{ temperature = 5.5; timestamp = $now }
) | ConvertTo-Json -Compress

$body = @{
    box_code = $boxCode
    to_point = "TP001"
    to_custodian = "Dr. Li"
    from_custodian = "Dr. Zhang"
    temperature = 5.0
    temperature_records = $tempRecords
} | ConvertTo-Json

try {
    $response = Invoke-RestMethod -Uri "$BASE_URL/api/boxes/transfer" -Method Post -Body $body -ContentType "application/json"
    Write-Host "  OK: Transfer successful" -ForegroundColor Green
    Write-Host "    Transfer ID: $($response.transfer_id)"
    Write-Host "    Custodian: $($response.from_custodian) -> $($response.to_custodian)"
    Write-Host "    Temperature: $($response.temperature)°C"
} catch {
    $errorMsg = $_.Exception.Message
    Write-Host "  ERROR: Transfer failed: $errorMsg" -ForegroundColor Red
}
Write-Host ""

# 8. Acceptance
Write-Host "[8/12] Accepting box at destination..." -ForegroundColor Yellow
$body = @{
    box_code = $boxCode
    custodian = "Dr. Li"
    check_duration = $false
} | ConvertTo-Json

try {
    $response = Invoke-RestMethod -Uri "$BASE_URL/api/boxes/accept" -Method Post -Body $body -ContentType "application/json"
    Write-Host "  OK: Acceptance successful" -ForegroundColor Green
    Write-Host "    Status: $($response.status)"
    Write-Host "    Current custodian: $($response.current_custodian)"
} catch {
    $errorMsg = $_.Exception.Message
    Write-Host "  ERROR: Acceptance failed: $errorMsg" -ForegroundColor Red
}
Write-Host ""

# 9. Complete testing
Write-Host "[9/12] Completing testing..." -ForegroundColor Yellow
try {
    $response = Invoke-RestMethod -Uri "$BASE_URL/api/boxes/$boxCode/complete-testing?custodian=Dr. Li" -Method Post
    Write-Host "  OK: Testing completed" -ForegroundColor Green
    Write-Host "    Box status: $($response.status)"
    foreach ($s in $response.samples) {
        Write-Host "      - $($s.barcode): $($s.status)"
    }
} catch {
    $errorMsg = $_.Exception.Message
    Write-Host "  ERROR: Testing failed: $errorMsg" -ForegroundColor Red
}
Write-Host ""

# 10. Archive results
Write-Host "[10/12] Archiving results..." -ForegroundColor Yellow
$results = @("Negative", "Positive", "Negative")
for ($i = 0; $i -lt $barcodes.Length; $i++) {
    $body = @{
        barcode = $barcodes[$i]
        custodian = "Dr. Li"
        test_result = $results[$i]
    } | ConvertTo-Json

    try {
        $response = Invoke-RestMethod -Uri "$BASE_URL/api/samples/archive" -Method Post -Body $body -ContentType "application/json"
        Write-Host "  OK: Sample $($barcodes[$i]) archived" -ForegroundColor Green
        Write-Host "    Result: $($response.test_result)"
        Write-Host "    Status: $($response.status)"
    } catch {
        $errorMsg = $_.Exception.Message
        Write-Host "  ERROR: Failed to archive sample $($barcodes[$i]): $errorMsg" -ForegroundColor Red
    }
}
Write-Host ""

# 11. Generate handover form and exception list
Write-Host "[11/12] Generating handover form and exception list..." -ForegroundColor Yellow
try {
    $response = Invoke-RestMethod -Uri "$BASE_URL/api/boxes/$boxCode/handover-form" -Method Get
    Write-Host "  OK: Handover form generated" -ForegroundColor Green
    Write-Host "    Export file: exports/handover_form_$boxCode.json"
} catch {
    $errorMsg = $_.Exception.Message
    Write-Host "  ERROR: Handover form generation failed: $errorMsg" -ForegroundColor Red
}

try {
    $response = Invoke-RestMethod -Uri "$BASE_URL/api/boxes/$boxCode/exception-list" -Method Get
    Write-Host "  OK: Exception list generated" -ForegroundColor Green
    Write-Host "    Exceptions found: $($response.total_exceptions)"
    Write-Host "    Export file: exports/exception_list_$boxCode.json"
} catch {
    $errorMsg = $_.Exception.Message
    Write-Host "  ERROR: Exception list generation failed: $errorMsg" -ForegroundColor Red
}
Write-Host ""

# 12. Check audit logs
Write-Host "[12/12] Checking audit logs..." -ForegroundColor Yellow
try {
    $response = Invoke-RestMethod -Uri "$BASE_URL/api/audit/box/$boxCode" -Method Get
    Write-Host "  OK: Audit logs retrieved" -ForegroundColor Green
    Write-Host "    Record count: $($response.Count)"
    foreach ($log in $response | Select-Object -First 5) {
        Write-Host "      [$($log.created_at)] $($log.action): $($log.old_status) -> $($log.new_status) by $($log.custodian)"
    }
} catch {
    $errorMsg = $_.Exception.Message
    Write-Host "  ERROR: Failed to retrieve audit logs: $errorMsg" -ForegroundColor Red
}
Write-Host ""

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Complete Flow Test Finished" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Please verify:" -ForegroundColor Yellow
Write-Host "  - exports/ directory for handover forms and exception lists" -ForegroundColor Gray
Write-Host "  - data/sample_transport.db database file" -ForegroundColor Gray
Write-Host "  - /docs for interactive API documentation" -ForegroundColor Gray
