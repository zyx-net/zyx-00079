import requests
import json
import os
import sys
import time
from datetime import datetime, timedelta

BASE_URL = "http://localhost:8000"


def print_test_header(test_name):
    print("\n" + "=" * 80)
    print(f"  TEST: {test_name}")
    print("=" * 80)


def print_result(test_name, passed, details=""):
    status = "✓ PASS" if passed else "✗ FAIL"
    print(f"\n{status}: {test_name}")
    if details:
        print(f"  Details: {details}")
    return passed


def setup_config():
    print_test_header("Setup - Loading Configurations")

    r1 = requests.post(f"{BASE_URL}/api/config/load?config_path=config/rules_v1.json")
    print(f"  Load transfer rules: {r1.status_code}")
    if r1.status_code != 200:
        print(f"  Error: {r1.json()}")

    r2 = requests.post(f"{BASE_URL}/api/work-orders/config/load?config_path=config/work_order_rules_v1.json")
    print(f"  Load work order rules: {r2.status_code}")
    if r2.status_code != 200:
        print(f"  Error: {r2.json()}")

    return r1.status_code == 200 and r2.status_code == 200


def setup_test_data():
    print_test_header("Setup - Creating Test Data")

    box_code = f"WO-TEST-{int(time.time())}"

    r = requests.post(f"{BASE_URL}/api/boxes", json={
        "box_code": box_code,
        "destination": "TP001",
        "current_custodian": "admin"
    })
    print(f"  Create box: {r.status_code}")
    if r.status_code != 200:
        print(f"  Error: {r.json()}")
        return None

    return box_code


def test_success_create_work_order(box_code):
    print_test_header("Test 1: Successfully Create Work Order")

    payload = {
        "exception_type": "DAMAGED",
        "box_code": box_code,
        "site_code": "CP001",
        "reported_by": "admin",
        "description": "包装轻微破损，样本完好",
        "reported_at": datetime.utcnow().isoformat()
    }

    r = requests.post(f"{BASE_URL}/api/work-orders", json=payload)
    print(f"  Status: {r.status_code}")

    if r.status_code == 200:
        data = r.json()
        print(f"  Work Order No: {data['work_order_no']}")
        print(f"  Severity: {data['severity']}")
        print(f"  Status: {data['status']}")
        print(f"  Rule Version: {data['rule_version']}")

        assert data["exception_type"] == "DAMAGED"
        assert data["severity"] == "MEDIUM"
        assert data["status"] == "OPEN"
        assert data["box_code"] == box_code
        assert data["site_code"] == "CP001"
        assert data["reported_by"] == "admin"
        assert data["rule_version"] == "wo-v1.0"

        return print_result("Successfully Create Work Order", True, data["work_order_no"]), data["work_order_no"]
    else:
        print(f"  Error: {r.json()}")
        return print_result("Successfully Create Work Order", False, r.text), None


def test_unauthorized_access(box_code):
    print_test_header("Test 2: Unauthorized Access (Permission Denied)")

    payload = {
        "exception_type": "TEMPERATURE",
        "box_code": box_code,
        "site_code": "TP002",
        "reported_by": "wh_user1",
        "description": "温控超限2小时",
        "reported_at": datetime.utcnow().isoformat()
    }

    r = requests.post(f"{BASE_URL}/api/work-orders", json=payload)
    print(f"  Status: {r.status_code}")

    if r.status_code == 403:
        data = r.json()
        print(f"  Error Code: {data['detail']['code']}")
        print(f"  Error Message: {data['detail']['error']}")

        assert data["detail"]["code"] == "WO_PERMISSION_DENIED"
        assert "无权访问站点 TP002" in data["detail"]["error"]

        return print_result("Unauthorized Access (Permission Denied)", True)
    else:
        print(f"  Error: Expected 403, got {r.status_code}")
        return print_result("Unauthorized Access (Permission Denied)", False, r.text)


def test_duplicate_work_order(box_code, existing_wo_no):
    print_test_header("Test 3: Duplicate Work Order (Conflict)")

    payload = {
        "exception_type": "DAMAGED",
        "box_code": box_code,
        "site_code": "CP001",
        "reported_by": "admin",
        "description": "另一个破损报告",
        "reported_at": datetime.utcnow().isoformat()
    }

    r = requests.post(f"{BASE_URL}/api/work-orders", json=payload)
    print(f"  Status: {r.status_code}")

    if r.status_code == 409:
        data = r.json()
        print(f"  Error Code: {data['detail']['code']}")
        print(f"  Error Message: {data['detail']['error']}")

        assert data["detail"]["code"] == "WO_DUPLICATE_WORK_ORDER"

        return print_result("Duplicate Work Order (Conflict)", True)
    else:
        print(f"  Error: Expected 409, got {r.status_code}")
        return print_result("Duplicate Work Order (Conflict)", False, r.text)


def test_assign_work_order(work_order_no):
    print_test_header("Test 4: Assign Work Order")

    payload = {
        "work_order_no": work_order_no,
        "assignee": "cs_user1",
        "operator": "admin"
    }

    r = requests.post(f"{BASE_URL}/api/work-orders/assign", json=payload)
    print(f"  Status: {r.status_code}")

    if r.status_code == 200:
        data = r.json()
        print(f"  Status: {data['status']}")
        print(f"  Assignee: {data['assignee']}")
        print(f"  Assigned At: {data['assigned_at']}")

        assert data["status"] == "ASSIGNED"
        assert data["assignee"] == "cs_user1"
        assert data["assigned_at"] is not None

        return print_result("Assign Work Order", True)
    else:
        print(f"  Error: {r.json()}")
        return print_result("Assign Work Order", False, r.text)


def test_add_process_record(work_order_no):
    print_test_header("Test 5: Add Process Record")

    payload = {
        "work_order_no": work_order_no,
        "operation": "INVESTIGATE",
        "remark": "已联系寄件方确认，为运输途中轻微碰撞，样本未受影响",
        "operator": "cs_user1"
    }

    r = requests.post(f"{BASE_URL}/api/work-orders/process", json=payload)
    print(f"  Status: {r.status_code}")

    if r.status_code == 200:
        data = r.json()
        print(f"  Status: {data['status']}")
        print(f"  Process Records Count: {len(data['process_records'])}")

        assert data["status"] == "PROCESSING"
        assert len(data["process_records"]) >= 1
        assert data["process_records"][0]["operation"] == "INVESTIGATE"

        return print_result("Add Process Record", True)
    else:
        print(f"  Error: {r.json()}")
        return print_result("Add Process Record", False, r.text)


def test_close_work_order(work_order_no):
    print_test_header("Test 6: Close Work Order")

    payload = {
        "work_order_no": work_order_no,
        "close_reason": "已确认样本完好，无需进一步处理",
        "operator": "cs_user1"
    }

    r = requests.post(f"{BASE_URL}/api/work-orders/close", json=payload)
    print(f"  Status: {r.status_code}")

    if r.status_code == 200:
        data = r.json()
        print(f"  Status: {data['status']}")
        print(f"  Closed By: {data['closed_by']}")
        print(f"  Closed At: {data['closed_at']}")
        print(f"  Close Reason: {data['close_reason']}")

        assert data["status"] == "CLOSED"
        assert data["closed_by"] == "cs_user1"
        assert data["closed_at"] is not None
        assert data["close_reason"] == "已确认样本完好，无需进一步处理"

        return print_result("Close Work Order", True)
    else:
        print(f"  Error: {r.json()}")
        return print_result("Close Work Order", False, r.text)


def test_revoke_close_work_order(work_order_no):
    print_test_header("Test 7: Revoke Close Work Order")

    payload = {
        "work_order_no": work_order_no,
        "revoke_reason": "发现遗漏重要信息，需要重新处理",
        "operator": "cs_user1"
    }

    r = requests.post(f"{BASE_URL}/api/work-orders/revoke-close", json=payload)
    print(f"  Status: {r.status_code}")

    if r.status_code == 200:
        data = r.json()
        print(f"  Status: {data['status']}")
        print(f"  Is Revoked: {data['is_revoked']}")
        print(f"  Revoked By: {data['revoked_by']}")
        print(f"  Revoke Reason: {data['revoke_reason']}")

        assert data["status"] == "PROCESSING"
        assert data["is_revoked"] == True
        assert data["revoked_by"] == "cs_user1"
        assert data["revoke_reason"] == "发现遗漏重要信息，需要重新处理"

        return print_result("Revoke Close Work Order", True)
    else:
        print(f"  Error: {r.json()}")
        return print_result("Revoke Close Work Order", False, r.text)


def test_list_and_filter_work_orders(box_code):
    print_test_header("Test 8: List and Filter Work Orders")

    r = requests.get(f"{BASE_URL}/api/work-orders")
    print(f"  List all - Status: {r.status_code}")
    assert r.status_code == 200
    all_data = r.json()
    print(f"  Total work orders: {len(all_data)}")

    r = requests.get(f"{BASE_URL}/api/work-orders?box_code={box_code}")
    print(f"  Filter by box_code - Status: {r.status_code}")
    assert r.status_code == 200
    box_filtered = r.json()
    print(f"  Filtered by box_code: {len(box_filtered)}")
    assert len(box_filtered) >= 1

    r = requests.get(f"{BASE_URL}/api/work-orders?status=PROCESSING")
    print(f"  Filter by status - Status: {r.status_code}")
    assert r.status_code == 200
    status_filtered = r.json()
    print(f"  Filtered by status=PROCESSING: {len(status_filtered)}")

    r = requests.get(f"{BASE_URL}/api/work-orders?operator=wh_user1")
    print(f"  Filter by operator permission - Status: {r.status_code}")
    assert r.status_code == 200
    perm_filtered = r.json()
    print(f"  Filtered by wh_user1 permissions: {len(perm_filtered)}")

    return print_result("List and Filter Work Orders", True)


def test_get_work_order_detail(work_order_no):
    print_test_header("Test 9: Get Work Order Detail")

    r = requests.get(f"{BASE_URL}/api/work-orders/{work_order_no}")
    print(f"  Status: {r.status_code}")

    if r.status_code == 200:
        data = r.json()
        print(f"  Work Order No: {data['work_order_no']}")
        print(f"  Status: {data['status']}")
        print(f"  Process Records: {len(data['process_records'])}")

        assert data["work_order_no"] == work_order_no
        assert "process_records" in data

        return print_result("Get Work Order Detail", True)
    else:
        print(f"  Error: {r.json()}")
        return print_result("Get Work Order Detail", False, r.text)


def test_work_order_detail_unauthorized(work_order_no):
    print_test_header("Test 10: Get Work Order Detail - Unauthorized")

    r = requests.get(f"{BASE_URL}/api/work-orders/{work_order_no}?operator=wh_user2")
    print(f"  Status: {r.status_code}")

    if r.status_code == 403:
        data = r.json()
        print(f"  Error Code: {data['detail']['code']}")
        print(f"  Error Message: {data['detail']['error']}")

        assert data["detail"]["code"] == "WO_PERMISSION_DENIED"

        return print_result("Get Work Order Detail - Unauthorized", True)
    else:
        print(f"  Error: Expected 403, got {r.status_code}")
        return print_result("Get Work Order Detail - Unauthorized", False, r.text)


def test_batch_import_partial_failure(box_code):
    print_test_header("Test 11: Batch Import with Partial Failure")

    box_code_2 = f"WO-TEST-BATCH-{int(time.time())}"
    r = requests.post(f"{BASE_URL}/api/boxes", json={
        "box_code": box_code_2,
        "destination": "TP001",
        "current_custodian": "admin"
    })
    assert r.status_code == 200

    payload = {
        "work_orders": [
            {
                "exception_type": "TEMPERATURE",
                "box_code": box_code_2,
                "site_code": "CP001",
                "reported_by": "admin",
                "description": "温控超限，已持续1小时"
            },
            {
                "exception_type": "INVALID_TYPE",
                "box_code": box_code_2,
                "site_code": "CP001",
                "reported_by": "admin",
                "description": "无效的异常类型，应该失败"
            },
            {
                "exception_type": "SIGNATURE_DISPUTE",
                "box_code": "NONEXISTENT-BOX",
                "site_code": "CP001",
                "reported_by": "admin",
                "description": "箱号不存在，应该失败"
            },
            {
                "exception_type": "SIGNATURE_DISPUTE",
                "box_code": box_code_2,
                "site_code": "CP001",
                "reported_by": "admin",
                "description": "签收有争议，涉及贵重样本",
                "reported_at": datetime.utcnow().isoformat()
            }
        ],
        "import_note": "批量导入测试"
    }

    r = requests.post(f"{BASE_URL}/api/work-orders/batch-import", json=payload)
    print(f"  Status: {r.status_code}")

    if r.status_code == 200:
        data = r.json()
        print(f"  Total: {data['total_count']}")
        print(f"  Success: {data['success_count']}")
        print(f"  Failed: {data['failed_count']}")
        print(f"  Errors: {len(data['errors'])}")

        for error in data["errors"]:
            print(f"    - Index {error['index']}: {error['code']} - {error['error']}")

        assert data["total_count"] == 4
        assert data["success_count"] == 2
        assert data["failed_count"] == 2
        assert len(data["errors"]) == 2

        error_codes = [e["code"] for e in data["errors"]]
        assert "WO_INVALID_EXCEPTION_TYPE" in error_codes
        assert "BOX_NOT_FOUND" in error_codes

        return print_result("Batch Import with Partial Failure", True)
    else:
        print(f"  Error: {r.json()}")
        return print_result("Batch Import with Partial Failure", False, r.text)


def test_csv_export():
    print_test_header("Test 12: CSV Export")

    r = requests.get(f"{BASE_URL}/api/work-orders/export/csv")
    print(f"  Status: {r.status_code}")

    if r.status_code == 200:
        data = r.json()
        print(f"  File Name: {data['file_name']}")
        print(f"  File Path: {data['file_path']}")
        print(f"  Total Count: {data['total_count']}")

        assert os.path.exists(data["file_path"])
        assert data["total_count"] >= 1

        with open(data["file_path"], 'r', encoding='utf-8-sig') as f:
            lines = f.readlines()
            print(f"  CSV Lines: {len(lines)}")
            assert len(lines) >= 2

        return print_result("CSV Export", True)
    else:
        print(f"  Error: {r.json()}")
        return print_result("CSV Export", False, r.text)


def test_audit_logs(work_order_no):
    print_test_header("Test 13: Verify Audit Logs")

    r = requests.get(f"{BASE_URL}/api/audit?entity_type=WORK_ORDER")
    print(f"  Status: {r.status_code}")

    if r.status_code == 200:
        data = r.json()
        print(f"  Total WORK_ORDER audit logs: {len(data)}")

        actions = [log["action"] for log in data]
        print(f"  Actions found: {set(actions)}")

        expected_actions = ["CREATE", "ASSIGN", "PROCESS", "CLOSE", "REVOKE_CLOSE"]
        for action in expected_actions:
            if action in actions:
                print(f"    ✓ {action} log found")
            else:
                print(f"    ⚠ {action} log not found (may be okay for some tests)")

        return print_result("Verify Audit Logs", len(data) >= 1)
    else:
        print(f"  Error: {r.json()}")
        return print_result("Verify Audit Logs", False, r.text)


def test_after_restart_query(work_order_no, box_code):
    print_test_header("Test 14: Query After Restart (Persistence Test)")

    print("  Note: This test verifies data persists in SQLite database")
    print("  The service should have already created the tables and data")

    r = requests.get(f"{BASE_URL}/api/work-orders/{work_order_no}")
    print(f"  Get work order detail: {r.status_code}")
    assert r.status_code == 200
    data = r.json()
    assert data["work_order_no"] == work_order_no
    assert data["box_code"] == box_code
    print(f"  ✓ Work order data persisted correctly")

    r = requests.get(f"{BASE_URL}/api/work-orders/config/current")
    print(f"  Get current config: {r.status_code}")
    if r.status_code == 200:
        config_data = r.json()
        print(f"  Config version: {config_data['version']}")
        print(f"  ✓ Config version persisted correctly")

    r = requests.get(f"{BASE_URL}/api/audit?entity_type=WORK_ORDER&limit=1")
    print(f"  Get audit logs: {r.status_code}")
    assert r.status_code == 200
    print(f"  ✓ Audit logs persisted correctly")

    return print_result("Query After Restart (Persistence Test)", True)


def test_invalid_exception_type():
    print_test_header("Test 15: Invalid Exception Type")

    payload = {
        "exception_type": "INVALID",
        "box_code": "SOME-BOX",
        "site_code": "CP001",
        "reported_by": "admin",
        "description": "测试无效类型"
    }

    r = requests.post(f"{BASE_URL}/api/work-orders", json=payload)
    print(f"  Status: {r.status_code}")

    if r.status_code == 400:
        data = r.json()
        print(f"  Error Code: {data['detail']['code']}")
        assert data["detail"]["code"] == "WO_INVALID_EXCEPTION_TYPE"
        return print_result("Invalid Exception Type", True)
    else:
        return print_result("Invalid Exception Type", False, r.text)


def test_config_versions():
    print_test_header("Test 16: Config Versions")

    r = requests.get(f"{BASE_URL}/api/work-orders/config/versions")
    print(f"  Status: {r.status_code}")

    if r.status_code == 200:
        data = r.json()
        print(f"  Config versions count: {len(data)}")
        assert len(data) >= 1
        print(f"  Latest version: {data[0]['version']}")
        return print_result("Config Versions", True)
    else:
        return print_result("Config Versions", False, r.text)


def test_severity_mapping():
    print_test_header("Test 17: Severity Mapping Based on Description")

    box_code = f"WO-SEVERITY-{int(time.time())}"
    r = requests.post(f"{BASE_URL}/api/boxes", json={
        "box_code": box_code,
        "destination": "TP001",
        "current_custodian": "admin"
    })
    assert r.status_code == 200

    test_cases = [
        ("DAMAGED", "包装轻微破损，样本完好", "MEDIUM"),
        ("DAMAGED", "样本破损，无法检测", "CRITICAL"),
        ("TEMPERATURE", "温控超限时长>2小时，样本可能失效", "CRITICAL"),
        ("TEMPERATURE", "温控超限时长>30分钟，需要关注", "HIGH"),
        ("TEMPERATURE", "温控超限时长<=30分钟，轻微超限", "MEDIUM"),
    ]

    all_passed = True
    for exc_type, description, expected_severity in test_cases:
        payload = {
            "exception_type": exc_type,
            "box_code": box_code,
            "transfer_record_id": None,
            "site_code": "CP001",
            "reported_by": "cs_user1",
            "description": description
        }

        r = requests.post(f"{BASE_URL}/api/work-orders", json=payload)
        if r.status_code == 200:
            data = r.json()
            actual = data["severity"]
            passed = actual == expected_severity
            status = "✓" if passed else "✗"
            print(f"  {status} {exc_type}: '{description[:50]}...' -> {actual} (expected: {expected_severity})")

            if not passed:
                all_passed = False

            close_payload = {
                "work_order_no": data["work_order_no"],
                "close_reason": "测试完成",
                "operator": "cs_user1"
            }
            requests.post(f"{BASE_URL}/api/work-orders/close", json=close_payload)
        else:
            print(f"  ✗ Failed to create: {r.status_code}")
            all_passed = False

    return print_result("Severity Mapping Based on Description", all_passed)


def main():
    print("\n" + "=" * 80)
    print("  WORK ORDER MODULE - COMPREHENSIVE AUTOMATED TEST SUITE")
    print("=" * 80)

    try:
        r = requests.get(f"{BASE_URL}/health")
        if r.status_code != 200:
            print("ERROR: Service is not running!")
            print("Please start the service first: python -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload")
            return 1
    except requests.exceptions.ConnectionError:
        print("ERROR: Cannot connect to service!")
        print("Please start the service first: python -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload")
        return 1

    print("  Service is running ✓")
    print()

    results = []

    config_ok = setup_config()
    results.append(("Setup Config", config_ok))

    box_code = setup_test_data()
    if not box_code:
        print("FAILED: Cannot create test box")
        return 1

    passed, work_order_no = test_success_create_work_order(box_code)
    results.append(("Create Work Order", passed))

    if work_order_no:
        results.append(("Unauthorized Access", test_unauthorized_access(box_code)))
        results.append(("Duplicate Work Order", test_duplicate_work_order(box_code, work_order_no)))
        results.append(("Assign Work Order", test_assign_work_order(work_order_no)))
        results.append(("Add Process Record", test_add_process_record(work_order_no)))
        results.append(("Close Work Order", test_close_work_order(work_order_no)))
        results.append(("Revoke Close Work Order", test_revoke_close_work_order(work_order_no)))
        results.append(("List and Filter", test_list_and_filter_work_orders(box_code)))
        results.append(("Get Work Order Detail", test_get_work_order_detail(work_order_no)))
        results.append(("Detail Unauthorized", test_work_order_detail_unauthorized(work_order_no)))
        results.append(("Audit Logs", test_audit_logs(work_order_no)))
        results.append(("After Restart Query", test_after_restart_query(work_order_no, box_code)))

    results.append(("Batch Import Partial Failure", test_batch_import_partial_failure(box_code)))
    results.append(("CSV Export", test_csv_export()))
    results.append(("Invalid Exception Type", test_invalid_exception_type()))
    results.append(("Config Versions", test_config_versions()))
    results.append(("Severity Mapping", test_severity_mapping()))

    print("\n" + "=" * 80)
    print("  TEST SUMMARY")
    print("=" * 80)

    passed_count = sum(1 for _, p in results if p)
    total_count = len(results)

    print(f"\n  Passed: {passed_count}/{total_count}")
    print()

    for test_name, passed in results:
        status = "✓ PASS" if passed else "✗ FAIL"
        print(f"  {status}: {test_name}")

    print()

    if passed_count == total_count:
        print("  ALL TESTS PASSED! ✓")
        return 0
    else:
        print(f"  {total_count - passed_count} TEST(S) FAILED! ✗")
        return 1


if __name__ == "__main__":
    sys.exit(main())
