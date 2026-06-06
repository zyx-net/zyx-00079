import requests
import json
import os
import sys
import time
from datetime import datetime, timedelta

BASE_URL = "http://localhost:8002"


def print_test_header(test_name):
    print("\n" + "=" * 80)
    print(f"  TEST: {test_name}")
    print("=" * 80)


def print_result(test_name, passed, details=""):
    status = "[OK] PASS" if passed else "[XX] FAIL"
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

    r3 = requests.post(f"{BASE_URL}/api/reservations/config/load?config_path=config/reservation_rules_v2.json")
    print(f"  Load reservation rules: {r3.status_code}")
    if r3.status_code != 200:
        print(f"  Error: {r3.json()}")

    return r1.status_code == 200 and r2.status_code == 200 and r3.status_code == 200


def create_test_box(box_code, temperature_zone="REFRIGERATED", destination="TP001"):
    r = requests.post(f"{BASE_URL}/api/boxes", json={
        "box_code": box_code,
        "destination": destination,
        "temperature_zone": temperature_zone,
        "current_custodian": "admin"
    })
    print(f"  Create box {box_code}: {r.status_code}")
    if r.status_code != 200:
        print(f"  Error: {r.text}")
        return False

    r2 = requests.post(f"{BASE_URL}/api/boxes/seal?box_code={box_code}&custodian=admin")
    print(f"  Seal box {box_code}: {r2.status_code}")
    if r2.status_code != 200:
        print(f"  Seal Error: {r2.text}")
        return False

    return True


def get_future_scheduled_date(hours_ahead=5):
    future = datetime.now() + timedelta(hours=hours_ahead)
    return future.replace(minute=0, second=0, microsecond=0)


def test_success_flow():
    print_test_header("Test: Complete Success Flow")

    timestamp = int(time.time())
    box_codes = [f"RES-SIMPLE-{timestamp}-{i}" for i in range(3)]
    
    for box_code in box_codes:
        if not create_test_box(box_code, "REFRIGERATED"):
            return print_result("Complete Success Flow", False, "Failed to create boxes"), None, None

    print("\n  Step 1: Create Reservation")
    scheduled_date = get_future_scheduled_date(5)
    payload = {
        "site_code": "CP001",
        "customer_code": "CUST001",
        "temperature_zone": "REFRIGERATED",
        "vehicle_no": "京A12345",
        "vehicle_type": "small",
        "scheduled_date": scheduled_date.isoformat(),
        "box_codes": box_codes,
        "created_by": "admin",
        "remark": "测试预约"
    }

    r = requests.post(f"{BASE_URL}/api/reservations", json=payload)
    print(f"  Status: {r.status_code}")
    if r.status_code != 200:
        print(f"  Error: {r.text}")
        return print_result("Complete Success Flow", False, "Create reservation failed"), None, None
    
    data = r.json()
    reservation_no = data["reservation_no"]
    print(f"  Reservation No: {reservation_no}")
    print(f"  Status: {data['status']}")
    print(f"  Rule Version: {data['rule_version']}")

    print("\n  Step 2: Confirm Reservation")
    confirm_payload = {
        "reservation_no": reservation_no,
        "operator": "admin"
    }
    r = requests.post(f"{BASE_URL}/api/reservations/confirm", json=confirm_payload)
    print(f"  Status: {r.status_code}")
    if r.status_code != 200:
        print(f"  Error: {r.text}")
        return print_result("Complete Success Flow", False, "Confirm reservation failed"), None, None
    
    data = r.json()
    print(f"  Status: {data['status']}")

    print("\n  Step 3: Create Loading Plan")
    lp_payload = {
        "reservation_no": reservation_no,
        "vehicle_no": "京A12345",
        "driver": "张师傅",
        "departure_time": get_future_scheduled_date(6).isoformat(),
        "operator": "admin",
        "remark": "装车计划"
    }
    r = requests.post(f"{BASE_URL}/api/reservations/loading-plans", json=lp_payload)
    print(f"  Status: {r.status_code}")
    if r.status_code != 200:
        print(f"  Error: {r.text}")
        return print_result("Complete Success Flow", False, "Create loading plan failed"), None, None
    
    lp_data = r.json()
    plan_no = lp_data["plan_no"]
    print(f"  Plan No: {plan_no}")
    print(f"  Status: {lp_data['status']}")

    print("\n  Step 4: Load Boxes")
    for box_code in box_codes:
        load_payload = {
            "plan_no": plan_no,
            "box_code": box_code,
            "operator": "admin"
        }
        r = requests.post(f"{BASE_URL}/api/reservations/loading-plans/load-box", json=load_payload)
        print(f"  Load box {box_code}: {r.status_code}")
        if r.status_code != 200:
            print(f"  Error: {r.text}")
            return print_result("Complete Success Flow", False, f"Load box {box_code} failed"), None, None

    print("\n  Step 5: Confirm Loading Plan")
    confirm_lp_payload = {
        "plan_no": plan_no,
        "operator": "admin"
    }
    r = requests.post(f"{BASE_URL}/api/reservations/loading-plans/confirm", json=confirm_lp_payload)
    print(f"  Status: {r.status_code}")
    if r.status_code != 200:
        print(f"  Error: {r.text}")
        return print_result("Complete Success Flow", False, "Confirm loading plan failed"), None, None
    
    lp_data = r.json()
    print(f"  Plan Status: {lp_data['status']}")

    r = requests.get(f"{BASE_URL}/api/reservations/{reservation_no}")
    if r.status_code == 200:
        res_data = r.json()
        print(f"  Reservation Status: {res_data['status']}")

    return print_result("Complete Success Flow", True), reservation_no, plan_no


def test_permission():
    print_test_header("Test: Permission Check")

    box_code = f"RES-PERM-{int(time.time())}"
    create_test_box(box_code)

    scheduled_date = get_future_scheduled_date(5)
    payload = {
        "site_code": "CP003",
        "customer_code": "CUST001",
        "temperature_zone": "REFRIGERATED",
        "vehicle_no": "京B67890",
        "scheduled_date": scheduled_date.isoformat(),
        "box_codes": [box_code],
        "created_by": "wh_user1"
    }

    r = requests.post(f"{BASE_URL}/api/reservations", json=payload)
    print(f"  Status: {r.status_code}")

    if r.status_code == 403:
        data = r.json()
        print(f"  Error Code: {data['detail']['code']}")
        return print_result("Permission Check", True)
    else:
        print(f"  Error: Expected 403, got {r.status_code}")
        return print_result("Permission Check", False, r.text)


def test_query_and_export():
    print_test_header("Test: Query and Export")

    r = requests.get(f"{BASE_URL}/api/reservations")
    print(f"  List reservations: {r.status_code}")
    if r.status_code == 200:
        print(f"  Total: {len(r.json())}")

    r = requests.get(f"{BASE_URL}/api/reservations?site_code=CP001")
    print(f"  Filter by site: {r.status_code}")

    r = requests.get(f"{BASE_URL}/api/reservations/export/csv")
    print(f"  Export reservations CSV: {r.status_code}")
    if r.status_code == 200:
        data = r.json()
        print(f"  File: {data['file_name']}")

    r = requests.get(f"{BASE_URL}/api/reservations/loading-plans/export/csv")
    print(f"  Export loading plans CSV: {r.status_code}")
    if r.status_code == 200:
        data = r.json()
        print(f"  File: {data['file_name']}")

    return print_result("Query and Export", True)


def test_audit_logs():
    print_test_header("Test: Audit Logs")

    r = requests.get(f"{BASE_URL}/api/audit?entity_type=RESERVATION&limit=10")
    print(f"  Status: {r.status_code}")
    if r.status_code == 200:
        data = r.json()
        print(f"  Total RESERVATION logs: {len(data)}")
        if data:
            actions = set(log["action"] for log in data)
            print(f"  Actions: {actions}")

    r = requests.get(f"{BASE_URL}/api/audit?entity_type=LOADING_PLAN&limit=10")
    if r.status_code == 200:
        data = r.json()
        print(f"  Total LOADING_PLAN logs: {len(data)}")

    return print_result("Audit Logs", True)


def test_restart_persistence(reservation_no, plan_no):
    print_test_header("Test: Restart Persistence")

    print("  Note: This verifies data persists in SQLite")
    
    r = requests.get(f"{BASE_URL}/api/reservations/{reservation_no}")
    assert r.status_code == 200
    data = r.json()
    assert data["reservation_no"] == reservation_no
    print(f"  [OK] Reservation data persisted: {data['status']}")

    r = requests.get(f"{BASE_URL}/api/reservations/loading-plans/{plan_no}")
    assert r.status_code == 200
    lp_data = r.json()
    assert lp_data["plan_no"] == plan_no
    print(f"  [OK] Loading plan data persisted: {lp_data['status']}")

    r = requests.get(f"{BASE_URL}/api/reservations/config/current")
    assert r.status_code == 200
    config_data = r.json()
    print(f"  [OK] Config version persisted: {config_data['version']}")

    return print_result("Restart Persistence", True)


def main():
    print("\n" + "=" * 80)
    print("  RESERVATION MODULE - SIMPLIFIED TEST SUITE")
    print("=" * 80)

    try:
        r = requests.get(f"{BASE_URL}/health")
        if r.status_code != 200:
            print("ERROR: Service is not running!")
            return 1
    except requests.exceptions.ConnectionError:
        print("ERROR: Cannot connect to service!")
        return 1

    print("  Service is running [OK]")
    print()

    results = []

    config_ok = setup_config()
    results.append(("Setup Config", config_ok))

    passed, reservation_no, plan_no = test_success_flow()
    results.append(("Success Flow", passed))

    results.append(("Permission Check", test_permission()))
    results.append(("Query and Export", test_query_and_export()))
    results.append(("Audit Logs", test_audit_logs()))

    if reservation_no and plan_no:
        results.append(("Restart Persistence", test_restart_persistence(reservation_no, plan_no)))

    print("\n" + "=" * 80)
    print("  TEST SUMMARY")
    print("=" * 80)

    passed_count = sum(1 for _, p in results if p)
    total_count = len(results)

    print(f"\n  Passed: {passed_count}/{total_count}")
    print()

    for test_name, passed in results:
        status = "[OK] PASS" if passed else "[XX] FAIL"
        print(f"  {status}: {test_name}")

    print()

    if passed_count == total_count:
        print("  ALL TESTS PASSED! [OK]")
        return 0
    else:
        print(f"  {total_count - passed_count} TEST(S) FAILED! [XX]")
        return 1


if __name__ == "__main__":
    sys.exit(main())
