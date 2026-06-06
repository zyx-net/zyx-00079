#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Sample Transport Management System - Transfer Revoke Flow Test
Tests: revoke transfer, re-transfer, acceptance after revoke, export consistency, etc.
"""

import requests
import json
import sys
from datetime import datetime

BASE_URL = "http://localhost:8000"
CONFIG_PATH = r"d:\workSpace\AI__SPACE\zyx-00079\config\rules_v1.json"

TEST_RESULTS = []


def print_test_result(test_name, passed, details=""):
    TEST_RESULTS.append({"test_name": test_name, "passed": passed, "details": details})
    if passed:
        print(f"  \033[92m[PASS]\033[0m {test_name}")
        if details:
            print(f"         \033[90m{details}\033[0m")
    else:
        print(f"  \033[91m[FAIL]\033[0m {test_name}")
        if details:
            print(f"         \033[90m{details}\033[0m")


def get_error_code(response):
    """Extract error code from API error response"""
    try:
        data = response.json()
        if "detail" in data and isinstance(data["detail"], dict):
            return data["detail"].get("code")
        return data.get("code")
    except:
        return None


def main():
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    box_code = f"BOX-REVOKE-PY-{timestamp}"
    barcode1 = f"BLD-REVOKE-PY-{timestamp}-01"
    barcode2 = f"BLD-REVOKE-PY-{timestamp}-02"
    now = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")

    print("=" * 40)
    print("  Sample Transport Management System")
    print("  Transfer Revoke Flow Test (Python)")
    print("=" * 40)
    print()

    # 1. Check service health
    print("[1/15] Checking service health...")
    try:
        response = requests.get(f"{BASE_URL}/health")
        response.raise_for_status()
        print(f"  OK: Service is running")
        print(f"    Config version: {response.json().get('config_version')}")
    except Exception as e:
        print(f"  ERROR: Service not running: {e}")
        sys.exit(1)
    print()

    # 2. Load configuration
    print("[2/15] Loading configuration...")
    try:
        response = requests.post(f"{BASE_URL}/api/config/load", params={"config_path": CONFIG_PATH})
        response.raise_for_status()
        print(f"  OK: Config loaded successfully")
        print(f"    Version: {response.json().get('version')}")
    except Exception as e:
        print(f"  ERROR: Failed to load config: {e}")
        sys.exit(1)
    print()

    # 3. Create samples
    print("[3/15] Creating test samples...")
    barcodes = [barcode1, barcode2]
    for barcode in barcodes:
        patient_info = json.dumps({"name": "Test Patient", "id": barcode}, ensure_ascii=False)
        data = {
            "barcode": barcode,
            "sample_type": "blood",
            "collection_point": "CP001",
            "collection_time": now,
            "patient_info": patient_info,
            "current_custodian": "Dr. Zhang"
        }
        try:
            response = requests.post(f"{BASE_URL}/api/samples", json=data)
            response.raise_for_status()
            print(f"  OK: Sample {barcode} created")
        except Exception as e:
            print(f"  ERROR: Failed to create sample {barcode}: {e}")
            if hasattr(e, 'response') and e.response is not None:
                print(f"    Response: {e.response.text}")
            sys.exit(1)
    print()

    # 4. Create transport box
    print("[4/15] Creating transport box...")
    data = {
        "box_code": box_code,
        "destination": "TP001",
        "current_custodian": "Dr. Zhang"
    }
    try:
        response = requests.post(f"{BASE_URL}/api/boxes", json=data)
        response.raise_for_status()
        print(f"  OK: Box {box_code} created")
        print(f"    Status: {response.json().get('status')}")
    except Exception as e:
        print(f"  ERROR: Failed to create box: {e}")
        sys.exit(1)
    print()

    # 5. Pack samples into box
    print("[5/15] Packing samples into box...")
    data = {
        "box_code": box_code,
        "barcodes": barcodes,
        "custodian": "Dr. Zhang"
    }
    try:
        response = requests.post(f"{BASE_URL}/api/boxes/pack", json=data)
        response.raise_for_status()
        print(f"  OK: Packing successful")
    except Exception as e:
        print(f"  ERROR: Packing failed: {e}")
        sys.exit(1)
    print()

    # 6. Seal the box
    print("[6/15] Sealing the box...")
    try:
        response = requests.post(f"{BASE_URL}/api/boxes/seal", 
            params={"box_code": box_code, "custodian": "Dr. Zhang"})
        response.raise_for_status()
        print(f"  OK: Box sealed")
        print(f"    Status: {response.json().get('status')}")
    except Exception as e:
        print(f"  ERROR: Seal failed: {e}")
        sys.exit(1)
    print()

    # 7. Transfer
    print("[7/15] Transferring box...")
    temp_records = json.dumps([
        {"temperature": 4.0, "timestamp": now},
        {"temperature": 5.5, "timestamp": now}
    ], ensure_ascii=False)
    data = {
        "box_code": box_code,
        "to_point": "TP001",
        "to_custodian": "Dr. Li",
        "from_custodian": "Dr. Zhang",
        "temperature": 5.0,
        "temperature_records": temp_records
    }
    try:
        response = requests.post(f"{BASE_URL}/api/boxes/transfer", json=data)
        response.raise_for_status()
        first_transfer_id = response.json()["transfer_id"]
        print(f"  OK: Transfer successful")
        print(f"    Transfer ID: {first_transfer_id}")
        print(f"    Custodian: {response.json()['from_custodian']} -> {response.json()['to_custodian']}")
    except Exception as e:
        print(f"  ERROR: Transfer failed: {e}")
        if hasattr(e, 'response') and e.response is not None:
            print(f"    Response: {e.response.text}")
        sys.exit(1)
    print()

    # Test 1: Non-custodian revoke (should fail)
    print("[Test 1] Testing non-custodian revoke (should fail)...")
    data = {
        "box_code": box_code,
        "custodian": "Dr. Wang",
        "reason": "Test non-custodian revoke"
    }
    try:
        response = requests.post(f"{BASE_URL}/api/boxes/revoke-transfer", json=data)
        if response.status_code >= 400:
            error_code = get_error_code(response)
            if error_code == "INVALID_CUSTODIAN":
                print_test_result("Non-custodian revoke", True, 
                    "Correctly rejected with INVALID_CUSTODIAN")
            else:
                print_test_result("Non-custodian revoke", False, 
                    f"Wrong error code: {error_code}")
        else:
            print_test_result("Non-custodian revoke", False,
                "Should have rejected non-custodian but succeeded")
    except Exception as e:
        print_test_result("Non-custodian revoke", False, f"Exception: {e}")
    print()

    # 8. Verify state before revoke
    print("[8/15] Verifying state before revoke...")
    try:
        box_before = requests.get(f"{BASE_URL}/api/boxes/{box_code}").json()
        sample_before = requests.get(f"{BASE_URL}/api/samples/{barcode1}").json()
        print(f"  Box status before revoke: {box_before['status']}, custodian: {box_before['current_custodian']}")
        print(f"  Sample status before revoke: {sample_before['status']}, custodian: {sample_before['current_custodian']}")
    except Exception as e:
        print(f"  ERROR: {e}")
    print()

    # 9. Revoke transfer - SUCCESS
    print("[9/15] Revoking transfer...")
    data = {
        "box_code": box_code,
        "custodian": "Dr. Li",
        "reason": "交接信息录入错误，接收人信息填错"
    }
    try:
        response = requests.post(f"{BASE_URL}/api/boxes/revoke-transfer", json=data)
        response.raise_for_status()
        revoked_transfer_id = response.json()["revoked_transfer_id"]
        print(f"  OK: Transfer revoked successfully")
        print(f"    Revoked transfer ID: {revoked_transfer_id}")
        print(f"    Box status: {response.json()['old_box_status']} -> {response.json()['new_box_status']}")
        print(f"    Custodian: {response.json()['old_custodian']} -> {response.json()['new_custodian']}")
        print_test_result("Revoke transfer", True, f"Successfully revoked transfer #{revoked_transfer_id}")
    except Exception as e:
        print_test_result("Revoke transfer", False, f"Exception: {e}")
        if hasattr(e, 'response') and e.response is not None:
            print(f"    Response: {e.response.text}")
    print()

    # 10. Verify state after revoke
    print("[10/15] Verifying state after revoke...")
    try:
        box_after = requests.get(f"{BASE_URL}/api/boxes/{box_code}").json()
        sample_after = requests.get(f"{BASE_URL}/api/samples/{barcode1}").json()

        box_passed = (box_after["status"] == "SEALED") and (box_after["current_custodian"] == "Dr. Zhang")
        sample_passed = (sample_after["status"] == "SEALED") and (sample_after["current_custodian"] == "Dr. Zhang")

        if box_passed and sample_passed:
            print_test_result("State after revoke", True,
                "Box and sample correctly rolled back to SEALED with original custodian")
        else:
            print_test_result("State after revoke", False,
                f"Box status: {box_after['status']}/SEALED, custodian: {box_after['current_custodian']}; "
                f"Sample status: {sample_after['status']}, custodian: {sample_after['current_custodian']}")

        print(f"  Box status: {box_after['status']}, custodian: {box_after['current_custodian']}")
        print(f"  Sample status: {sample_after['status']}, custodian: {sample_after['current_custodian']}")
    except Exception as e:
        print_test_result("State after revoke", False, f"Exception: {e}")
    print()

    # Test 2: Duplicate revoke (should fail)
    print("[Test 2] Testing duplicate revoke (should fail)...")
    data = {
        "box_code": box_code,
        "custodian": "Dr. Zhang",
        "reason": "Trying to revoke again"
    }
    try:
        response = requests.post(f"{BASE_URL}/api/boxes/revoke-transfer", json=data)
        if response.status_code >= 400:
            error_code = get_error_code(response)
            if error_code == "TRANSFER_ALREADY_REVOKED" and response.status_code == 409:
                print_test_result("Duplicate revoke", True,
                    f"Correctly rejected with {error_code}")
            else:
                print_test_result("Duplicate revoke", False,
                    f"Wrong error code: {error_code}")
        else:
            print_test_result("Duplicate revoke", False,
                "Should have rejected duplicate revoke but succeeded")
    except Exception as e:
        print_test_result("Duplicate revoke", False, f"Exception: {e}")
    print()

    # 11. Transfer again after revoke
    print("[11/15] Re-transferring after revoke...")
    temp_records2 = json.dumps([
        {"temperature": 4.5, "timestamp": now},
        {"temperature": 5.0, "timestamp": now}
    ], ensure_ascii=False)
    data = {
        "box_code": box_code,
        "to_point": "TP001",
        "to_custodian": "Dr. Li",
        "from_custodian": "Dr. Zhang",
        "temperature": 4.8,
        "temperature_records": temp_records2
    }
    try:
        response = requests.post(f"{BASE_URL}/api/boxes/transfer", json=data)
        response.raise_for_status()
        new_transfer_id = response.json()["transfer_id"]
        print(f"  OK: Re-transfer successful")
        print(f"    New transfer ID: {new_transfer_id}")
        print(f"    Rule version: {response.json()['rule_version']}")
        print_test_result("Re-transfer after revoke", True,
            f"Created new transfer #{new_transfer_id}, old #{first_transfer_id} preserved")
    except Exception as e:
        print_test_result("Re-transfer after revoke", False, f"Exception: {e}")
        if hasattr(e, 'response') and e.response is not None:
            print(f"    Response: {e.response.text}")
    print()

    # 12. Verify transfer history
    print("[12/15] Verifying transfer history...")
    try:
        history = requests.get(f"{BASE_URL}/api/boxes/{box_code}/transfer-history").json()
        print(f"  Transfer history count: {len(history)}")

        revoked_count = len([t for t in history if t.get("is_revoked") == True])
        active_count = len([t for t in history if t.get("is_revoked") == False])

        print(f"  Revoked records: {revoked_count}, Active records: {active_count}")

        if len(history) >= 2 and revoked_count >= 1 and active_count >= 1:
            print_test_result("Transfer history", True,
                "History shows both revoked and active records, old records not overwritten")
        else:
            print_test_result("Transfer history", False,
                f"Expected >=2 records, got {len(history)}. Revoked: {revoked_count}, Active: {active_count}")

        for t in history:
            print(f"    [{t['id']}] {t['from_custodian']} -> {t['to_custodian']}, revoked: {t.get('is_revoked')}")
    except Exception as e:
        print_test_result("Transfer history", False, f"Exception: {e}")
    print()

    # 13. Acceptance after re-transfer
    print("[13/15] Accepting box at destination after re-transfer...")
    data = {
        "box_code": box_code,
        "custodian": "Dr. Li",
        "check_duration": False
    }
    try:
        response = requests.post(f"{BASE_URL}/api/boxes/accept", json=data)
        response.raise_for_status()
        print(f"  OK: Acceptance successful after re-transfer")
        print(f"    Box status: {response.json()['status']}")
        print_test_result("Acceptance after re-transfer", True,
            "Successfully accepted after revoke and re-transfer")
    except Exception as e:
        print_test_result("Acceptance after re-transfer", False, f"Exception: {e}")
        if hasattr(e, 'response') and e.response is not None:
            print(f"    Response: {e.response.text}")
    print()

    # Test 3: Revoke after acceptance (should fail)
    print("[Test 3] Testing revoke after acceptance (should fail)...")
    data = {
        "box_code": box_code,
        "custodian": "Dr. Li",
        "reason": "Trying to revoke after acceptance"
    }
    try:
        response = requests.post(f"{BASE_URL}/api/boxes/revoke-transfer", json=data)
        if response.status_code >= 400:
            error_code = get_error_code(response)
            if error_code == "BOX_INVALID_STATUS":
                print_test_result("Revoke after acceptance", True,
                    "Correctly rejected with BOX_INVALID_STATUS (DELIVERED state cannot be revoked)")
            else:
                print_test_result("Revoke after acceptance", False,
                    f"Wrong error code: {error_code}")
        else:
            print_test_result("Revoke after acceptance", False,
                "Should have rejected revoke after acceptance but succeeded")
    except Exception as e:
        print_test_result("Revoke after acceptance", False, f"Exception: {e}")
    print()

    # 14. Generate handover form and verify revoke history
    print("[14/15] Generating handover form with revoke history...")
    try:
        form = requests.get(f"{BASE_URL}/api/boxes/{box_code}/handover-form").json()
        print(f"  OK: Handover form generated")

        has_revoked_history = form.get("revoked_transfer_history") is not None
        export_path = rf"d:\workSpace\AI__SPACE\zyx-00079\exports\handover_form_{box_code}.json"
        with open(export_path, 'r', encoding='utf-8') as f:
            export_content = json.load(f)

        export_has_revoked = export_content.get("revoked_transfer_history") is not None

        if has_revoked_history and export_has_revoked:
            print_test_result("Handover form revoke history", True,
                "Handover form contains revoked transfer history in both API and exported JSON")
            print(f"  Revoked history count: {len(form['revoked_transfer_history'])}")
        else:
            print_test_result("Handover form revoke history", False,
                f"Missing revoked transfer history (API: {has_revoked_history}, Export: {export_has_revoked})")
    except Exception as e:
        print_test_result("Handover form revoke history", False, f"Exception: {e}")
    print()

    # 15. Generate exception list and verify consistency
    print("[15/15] Generating exception list and audit logs...")
    try:
        exception_list = requests.get(f"{BASE_URL}/api/boxes/{box_code}/exception-list").json()
        print(f"  OK: Exception list generated")
        revoke_exceptions = len([e for e in exception_list["exceptions"] if e.get("type") == "TRANSFER_REVOKED"])
        print(f"  Revoke exceptions: {revoke_exceptions}")

        audit_logs_transfer = requests.get(f"{BASE_URL}/api/audit", 
            params={"entity_type": "TRANSFER", "action": "REVOKE_TRANSFER"}).json()
        print(f"  REVOKE_TRANSFER audit logs (TRANSFER): {len(audit_logs_transfer)}")

        audit_logs_box = requests.get(f"{BASE_URL}/api/audit",
            params={"entity_type": "BOX", "action": "REVOKE_TRANSFER"}).json()
        audit_logs_sample = requests.get(f"{BASE_URL}/api/audit",
            params={"entity_type": "SAMPLE", "action": "REVOKE_TRANSFER"}).json()

        transfer_audit_passed = len(audit_logs_transfer) >= 1
        box_audit_passed = len(audit_logs_box) >= 1
        sample_audit_passed = len(audit_logs_sample) >= 2

        all_audit_passed = transfer_audit_passed and box_audit_passed and sample_audit_passed

        if all_audit_passed:
            print_test_result("Audit log consistency", True,
                "Audit logs present for TRANSFER, BOX, and SAMPLE entities")
        else:
            print_test_result("Audit log consistency", False,
                f"Missing audit logs: Transfer={transfer_audit_passed}, Box={box_audit_passed}, Sample={sample_audit_passed}")

        print(f"  Transfer audit logs: {len(audit_logs_transfer)}, Box: {len(audit_logs_box)}, Sample: {len(audit_logs_sample)}")
    except Exception as e:
        print_test_result("Audit log consistency", False, f"Exception: {e}")
    print()

    # Service restart persistence test (manual)
    print("=" * 40)
    print("  Service Restart Persistence Test")
    print("=" * 40)
    print()
    print("  Please perform the following manual test:")
    print("  1. Restart the service (stop and start main.py)")
    print("  2. Run the following commands to verify data persistence:")
    print(f'     python -c "import requests; r=requests.get(\'{BASE_URL}/api/boxes/{box_code}\'); print(r.json()[\'status\'])"')
    print(f'     python -c "import requests; r=requests.get(\'{BASE_URL}/api/boxes/{box_code}/transfer-history\'); [print(t[\'id\'], t[\'is_revoked\']) for t in r.json()]"')
    print(f'     python -c "import requests; r=requests.get(\'{BASE_URL}/api/audit\', params={{\'action\': \'REVOKE_TRANSFER\'}}); print(len(r.json()), \'audit logs\')"')
    print("  3. Verify that:")
    print("     - Box status is DELIVERED")
    print("     - Transfer history shows both revoked and active records")
    print("     - Audit logs are preserved")
    print()

    # Summary
    print("=" * 40)
    print("  Test Summary")
    print("=" * 40)
    print()

    passed = len([t for t in TEST_RESULTS if t["passed"]])
    failed = len(TEST_RESULTS) - passed

    print(f"  Total Tests: {len(TEST_RESULTS)}")
    print(f"  \033[92mPassed: {passed}\033[0m")
    if failed == 0:
        print(f"  \033[92mFailed: {failed}\033[0m")
    else:
        print(f"  \033[91mFailed: {failed}\033[0m")
    print()

    if failed == 0:
        print("  \033[92mAll tests passed!\033[0m")
    else:
        print("  \033[91mSome tests failed. Please review the results above.\033[0m")
        print()
        print("  Failed tests:")
        for t in TEST_RESULTS:
            if not t["passed"]:
                print(f"    - {t['test_name']}: {t['details']}")
        sys.exit(1)

    print()
    print(f"  Test box code: {box_code}")
    print(f"  Please check exports\\handover_form_{box_code}.json")
    print(f"  Please check exports\\exception_list_{box_code}.json")
    print()


if __name__ == "__main__":
    main()
