# Sample Transport Management System - Failure Scenarios Test Script
# Covers: duplicate barcode, invalid temperature format, invalid custodian, isolated sample flow

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

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Sample Transport Management System" -ForegroundColor Cyan
Write-Host "  Failure Scenarios Test" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Make sure config is loaded first
Write-Host "Loading correct configuration..." -ForegroundColor Yellow
try {
    $response = Invoke-RestMethod -Uri "$BASE_URL/api/config/load?config_path=$CONFIG_PATH" -Method Post
    Write-Host "  OK: Config loaded: $($response.version)" -ForegroundColor Green
} catch {
    Write-Host "  Note: Config may already be loaded" -ForegroundColor Gray
}
Write-Host ""

# ============================================
# Scenario 1: Duplicate Barcode
# ============================================
Write-Host "[Scenario 1] Duplicate Barcode Test" -ForegroundColor Yellow
Write-Host "  Attempting to create sample with duplicate barcode..." -ForegroundColor Gray

$now = Get-Date -Format "yyyy-MM-ddTHH:mm:ssZ"
$duplicateBarcode = "DUP-TEST-0001"

# First creation
$body = @{
    barcode = $duplicateBarcode
    sample_type = "blood"
    collection_point = "CP001"
    collection_time = $now
    current_custodian = "Dr. Zhang"
} | ConvertTo-Json

$first = Invoke-RestMethod -Uri "$BASE_URL/api/samples" -Method Post -Body $body -ContentType "application/json"
Write-Host "  OK: First creation successful" -ForegroundColor Green

# Second creation (should fail)
try {
    $second = Invoke-RestMethod -Uri "$BASE_URL/api/samples" -Method Post -Body $body -ContentType "application/json"
    Write-Host "  FAIL: Second creation unexpectedly succeeded!" -ForegroundColor Red
} catch {
    $errorDetails = Get-ErrorDetails -Exception $_.Exception
    if ($errorDetails -and $errorDetails.detail) {
        $errorDetails = $errorDetails.detail
    }
    Write-Host "  OK: Second creation correctly failed" -ForegroundColor Green
    Write-Host "    Error code: $($errorDetails.code)" -ForegroundColor Cyan
    Write-Host "    Error message: $($errorDetails.error)" -ForegroundColor Gray
    Write-Host "    Expected: DUPLICATE_BARCODE" -ForegroundColor Gray
    if ($errorDetails.code -eq "DUPLICATE_BARCODE") {
        Write-Host "  OK: Error code matches!" -ForegroundColor Green
    } else {
        Write-Host "  FAIL: Error code does not match!" -ForegroundColor Red
    }
}
Write-Host ""

# ============================================
# Scenario 2: Invalid Temperature Record Format
# ============================================
Write-Host "[Scenario 2] Invalid Temperature Format Test" -ForegroundColor Yellow
Write-Host "  Submitting temperature records in invalid format..." -ForegroundColor Gray

# Create sample and box first
$sampleBarcode = "TEMP-TEST-0001"
$body = @{
    barcode = $sampleBarcode
    sample_type = "blood"
    collection_point = "CP001"
    collection_time = $now
    current_custodian = "Dr. Zhang"
} | ConvertTo-Json
$s = Invoke-RestMethod -Uri "$BASE_URL/api/samples" -Method Post -Body $body -ContentType "application/json"

$boxCode = "TEMP-BOX-0001"
$body = @{
    box_code = $boxCode
    destination = "TP001"
    current_custodian = "Dr. Zhang"
} | ConvertTo-Json
$b = Invoke-RestMethod -Uri "$BASE_URL/api/boxes" -Method Post -Body $body -ContentType "application/json"

# Pack
$body = @{
    box_code = $boxCode
    barcodes = @($sampleBarcode)
    custodian = "Dr. Zhang"
} | ConvertTo-Json
$b = Invoke-RestMethod -Uri "$BASE_URL/api/boxes/pack" -Method Post -Body $body -ContentType "application/json"

# Seal
$b = Invoke-RestMethod -Uri "$BASE_URL/api/boxes/seal?box_code=$boxCode&custodian=Dr. Zhang" -Method Post

# Submit invalid format (not an array)
$invalidTempRecords = '{"temperature": 5.0, "not": "an array"}'
$body = @{
    box_code = $boxCode
    to_point = "TP001"
    to_custodian = "Dr. Li"
    from_custodian = "Dr. Zhang"
    temperature = 5.0
    temperature_records = $invalidTempRecords
} | ConvertTo-Json

try {
    $response = Invoke-RestMethod -Uri "$BASE_URL/api/boxes/transfer" -Method Post -Body $body -ContentType "application/json"
    Write-Host "  FAIL: Transfer unexpectedly succeeded!" -ForegroundColor Red
} catch {
    $errorDetails = Get-ErrorDetails -Exception $_.Exception
    if ($errorDetails -and $errorDetails.detail) {
        $errorDetails = $errorDetails.detail
    }
    Write-Host "  OK: Transfer correctly failed (not an array)" -ForegroundColor Green
    Write-Host "    Error code: $($errorDetails.code)" -ForegroundColor Cyan
    Write-Host "    Error message: $($errorDetails.error)" -ForegroundColor Gray
    if ($errorDetails.code -eq "INVALID_TEMPERATURE_FORMAT") {
        Write-Host "  OK: Error code matches!" -ForegroundColor Green
    } else {
        Write-Host "  FAIL: Error code does not match!" -ForegroundColor Red
    }
}

# Submit invalid JSON
$invalidJson = '[{"temperature": "not-a-number"}'
$body = @{
    box_code = $boxCode
    to_point = "TP001"
    to_custodian = "Dr. Li"
    from_custodian = "Dr. Zhang"
    temperature = 5.0
    temperature_records = $invalidJson
} | ConvertTo-Json

try {
    $response = Invoke-RestMethod -Uri "$BASE_URL/api/boxes/transfer" -Method Post -Body $body -ContentType "application/json"
    Write-Host "  FAIL: Transfer unexpectedly succeeded!" -ForegroundColor Red
} catch {
    $errorDetails = Get-ErrorDetails -Exception $_.Exception
    if ($errorDetails -and $errorDetails.detail) {
        $errorDetails = $errorDetails.detail
    }
    Write-Host "  OK: Transfer correctly failed (invalid JSON)" -ForegroundColor Green
    Write-Host "    Error code: $($errorDetails.code)" -ForegroundColor Cyan
    if ($errorDetails.code -eq "INVALID_TEMPERATURE_FORMAT") {
        Write-Host "  OK: Error code matches!" -ForegroundColor Green
    } else {
        Write-Host "  FAIL: Error code does not match!" -ForegroundColor Red
    }
}
Write-Host ""

# ============================================
# Scenario 3: Non-current Custodian Submitting Transfer
# ============================================
Write-Host "[Scenario 3] Non-current Custodian Transfer Test" -ForegroundColor Yellow
Write-Host "  Attempting transfer by non-current custodian..." -ForegroundColor Gray

$sampleBarcode2 = "CUST-TEST-0001"
$body = @{
    barcode = $sampleBarcode2
    sample_type = "blood"
    collection_point = "CP001"
    collection_time = $now
    current_custodian = "Dr. Zhang"
} | ConvertTo-Json
$s = Invoke-RestMethod -Uri "$BASE_URL/api/samples" -Method Post -Body $body -ContentType "application/json"

$boxCode2 = "CUST-BOX-0001"
$body = @{
    box_code = $boxCode2
    destination = "TP001"
    current_custodian = "Dr. Zhang"
} | ConvertTo-Json
$b = Invoke-RestMethod -Uri "$BASE_URL/api/boxes" -Method Post -Body $body -ContentType "application/json"

$body = @{
    box_code = $boxCode2
    barcodes = @($sampleBarcode2)
    custodian = "Dr. Zhang"
} | ConvertTo-Json
$b = Invoke-RestMethod -Uri "$BASE_URL/api/boxes/pack" -Method Post -Body $body -ContentType "application/json"

$b = Invoke-RestMethod -Uri "$BASE_URL/api/boxes/seal?box_code=$boxCode2&custodian=Dr. Zhang" -Method Post

# Attempt transfer by non-current custodian (Dr. Wang)
$body = @{
    box_code = $boxCode2
    to_point = "TP001"
    to_custodian = "Dr. Li"
    from_custodian = "Dr. Wang"
    temperature = 5.0
} | ConvertTo-Json

try {
    $response = Invoke-RestMethod -Uri "$BASE_URL/api/boxes/transfer" -Method Post -Body $body -ContentType "application/json"
    Write-Host "  FAIL: Transfer unexpectedly succeeded!" -ForegroundColor Red
} catch {
    $errorDetails = Get-ErrorDetails -Exception $_.Exception
    if ($errorDetails -and $errorDetails.detail) {
        $errorDetails = $errorDetails.detail
    }
    Write-Host "  OK: Transfer correctly failed (non-current custodian)" -ForegroundColor Green
    Write-Host "    Error code: $($errorDetails.code)" -ForegroundColor Cyan
    Write-Host "    Error message: $($errorDetails.error)" -ForegroundColor Gray
    Write-Host "    Expected: INVALID_CUSTODIAN" -ForegroundColor Gray
    if ($errorDetails.code -eq "INVALID_CUSTODIAN") {
        Write-Host "  OK: Error code matches!" -ForegroundColor Green
    } else {
        Write-Host "  FAIL: Error code does not match!" -ForegroundColor Red
    }
}
Write-Host ""

# ============================================
# Scenario 4: Isolated Sample Continuing Flow
# ============================================
Write-Host "[Scenario 4] Isolated Sample Continuing Flow Test" -ForegroundColor Yellow
Write-Host "  Attempting to pack/archive an isolated sample..." -ForegroundColor Gray

$sampleBarcode3 = "ISO-TEST-0001"
$body = @{
    barcode = $sampleBarcode3
    sample_type = "blood"
    collection_point = "CP001"
    collection_time = $now
    current_custodian = "Dr. Zhang"
} | ConvertTo-Json
$s = Invoke-RestMethod -Uri "$BASE_URL/api/samples" -Method Post -Body $body -ContentType "application/json"
Write-Host "  OK: Sample created" -ForegroundColor Green

# Isolate the sample first
$body = @{
    barcode = $sampleBarcode3
    custodian = "Dr. Zhang"
    reason = "Sample appears contaminated"
} | ConvertTo-Json
try {
    $iso = Invoke-RestMethod -Uri "$BASE_URL/api/samples/isolate" -Method Post -Body $body -ContentType "application/json"
    Write-Host "  OK: Sample isolated, status: $($iso.status)" -ForegroundColor Green
} catch {
    $errorDetails = Get-ErrorDetails -Exception $_.Exception
    if ($errorDetails -and $errorDetails.detail) {
        $errorDetails = $errorDetails.detail
    }
    Write-Host "  FAIL: Isolation failed: $($errorDetails.error)" -ForegroundColor Red
}

# Try to pack the isolated sample
$boxCode3 = "ISO-BOX-0001"
$body = @{
    box_code = $boxCode3
    destination = "TP001"
    current_custodian = "Dr. Zhang"
} | ConvertTo-Json
$b = Invoke-RestMethod -Uri "$BASE_URL/api/boxes" -Method Post -Body $body -ContentType "application/json"

$body = @{
    box_code = $boxCode3
    barcodes = @($sampleBarcode3)
    custodian = "Dr. Zhang"
} | ConvertTo-Json

try {
    $response = Invoke-RestMethod -Uri "$BASE_URL/api/boxes/pack" -Method Post -Body $body -ContentType "application/json"
    Write-Host "  FAIL: Packing unexpectedly succeeded!" -ForegroundColor Red
} catch {
    $errorDetails = Get-ErrorDetails -Exception $_.Exception
    if ($errorDetails -and $errorDetails.detail) {
        $errorDetails = $errorDetails.detail
    }
    Write-Host "  OK: Packing correctly failed (sample is isolated)" -ForegroundColor Green
    Write-Host "    Error code: $($errorDetails.code)" -ForegroundColor Cyan
    Write-Host "    Error message: $($errorDetails.error)" -ForegroundColor Gray
    if ($errorDetails.code -eq "SAMPLE_ISOLATED") {
        Write-Host "  OK: Error code matches!" -ForegroundColor Green
    } else {
        Write-Host "  FAIL: Error code does not match!" -ForegroundColor Red
    }
}

# Also test: trying to archive an isolated sample
$body = @{
    barcode = $sampleBarcode3
    custodian = "Dr. Li"
    test_result = "Negative"
} | ConvertTo-Json

try {
    $response = Invoke-RestMethod -Uri "$BASE_URL/api/samples/archive" -Method Post -Body $body -ContentType "application/json"
    Write-Host "  FAIL: Archive unexpectedly succeeded!" -ForegroundColor Red
} catch {
    $errorDetails = Get-ErrorDetails -Exception $_.Exception
    if ($errorDetails -and $errorDetails.detail) {
        $errorDetails = $errorDetails.detail
    }
    Write-Host "  OK: Archive correctly failed (sample is isolated)" -ForegroundColor Green
    Write-Host "    Error code: $($errorDetails.code)" -ForegroundColor Cyan
    if ($errorDetails.code -eq "SAMPLE_ISOLATED") {
        Write-Host "  OK: Error code matches!" -ForegroundColor Green
    } else {
        Write-Host "  FAIL: Error code does not match!" -ForegroundColor Red
    }
}
Write-Host ""

# ============================================
# Scenario 5: Bad Configuration Validation Failures
# ============================================
Write-Host "[Scenario 5] Bad Configuration Validation Test" -ForegroundColor Yellow
Write-Host "  Testing various bad config files..." -ForegroundColor Gray

$badConfigs = @(
    @{
        path = "d:\workSpace\AI__SPACE\zyx-00079\config\rules_bad_invalid_json.json"
        expectedCode = "INVALID_JSON_FORMAT"
        description = "Invalid JSON format"
    },
    @{
        path = "d:\workSpace\AI__SPACE\zyx-00079\config\rules_bad_missing_temp.json"
        expectedCode = "MISSING_TEMPERATURE_RULE"
        description = "Missing temperature rule for blood"
    },
    @{
        path = "d:\workSpace\AI__SPACE\zyx-00079\config\rules_bad_temp_range.json"
        expectedCode = "INVALID_TEMPERATURE_RANGE"
        description = "Invalid temp range (min > max)"
    },
    @{
        path = "d:\workSpace\AI__SPACE\zyx-00079\config\rules_bad_missing_status.json"
        expectedCode = "MISSING_REQUIRED_FIELD"
        description = "Missing status_flow field"
    }
)

foreach ($badConfig in $badConfigs) {
    Write-Host ""
    Write-Host "  Testing: $($badConfig.description)" -ForegroundColor Gray
    Write-Host "    File: $($badConfig.path)" -ForegroundColor Gray
    Write-Host "    Expected code: $($badConfig.expectedCode)" -ForegroundColor Gray

    try {
        $response = Invoke-RestMethod -Uri "$BASE_URL/api/config/load?config_path=$($badConfig.path)" -Method Post
        Write-Host "    FAIL: Config loading unexpectedly succeeded!" -ForegroundColor Red
    } catch {
        $errorDetails = Get-ErrorDetails -Exception $_.Exception
        if ($errorDetails -and $errorDetails.detail) {
            $errorDetails = $errorDetails.detail
        }
        Write-Host "    OK: Config loading correctly failed" -ForegroundColor Green
        Write-Host "      Actual code: $($errorDetails.code)" -ForegroundColor Cyan
        Write-Host "      Error message: $($errorDetails.error)" -ForegroundColor Gray
        if ($errorDetails.code -eq $badConfig.expectedCode) {
            Write-Host "      OK: Error code matches!" -ForegroundColor Green
        } else {
            Write-Host "      FAIL: Error code does not match!" -ForegroundColor Red
        }
    }
}

Write-Host ""
Write-Host "  Reloading correct config..." -ForegroundColor Gray
$response = Invoke-RestMethod -Uri "$BASE_URL/api/config/load?config_path=$CONFIG_PATH" -Method Post
Write-Host "  OK: Correct config restored: $($response.version)" -ForegroundColor Green
Write-Host ""

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Failure Scenarios Test Finished" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "  All failure scenarios return readable error messages" -ForegroundColor Green
Write-Host "  for easy tracing and troubleshooting" -ForegroundColor Gray
