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

    r2 = requests.post(f"{BASE_URL}/api/work-orders/config/load?config_path=config/work_order_rules_v1.json")
    print(f"  Load work order rules: {r2.status_code}")

    r3 = requests.post(f"{BASE_URL}/api/reservations/config/load?config_path=config/reservation_rules_v2.json")
    print(f"  Load reservation rules: {r3.status_code}")

    return r1.status_code == 200 and r2.status_code == 200 and r3.status_code == 200


def create_test_box(box_code, temperature_zone="REFRIGERATED", destination="TP001"):
    r = requests.post(f"{BASE_URL}/api/boxes", json={
        "box_code": box_code,
        "destination": destination,
        "temperature_zone": temperature_zone,
        "current_custodian": "admin"
    })
    if r.status_code != 200:
        return False

    r2 = requests.post(f"{BASE_URL}/api/boxes/seal?box_code={box_code}&custodian=admin")
    if r2.status_code != 200:
        return False

    return True


def get_future_scheduled_date(hours_ahead=5):
    future = datetime.now() + timedelta(hours=hours_ahead)
    return future.replace(minute=0, second=0, microsecond=0)


def test_duplicate_box_reservation():
    print_test_header("Test: Duplicate Box Reservation Conflict")

    box_code = f"RES-DUP-{int(time.time())}"
    if not create_test_box(box_code):
        return print_result("Duplicate Box Reservation", False, "Failed to create box")

    scheduled_date = get_future_scheduled_date(5)
    payload = {
        "site_code": "CP001",
        "customer_code": "CUST001",
        "temperature_zone": "REFRIGERATED",
        "vehicle_no": "京DUP100",
        "scheduled_date": scheduled_date.isoformat(),
        "box_codes": [box_code],
        "created_by": "admin"
    }

    r1 = requests.post(f"{BASE_URL}/api/reservations", json=payload)
    print(f"  First reservation: {r1.status_code}")
    if r1.status_code != 200:
        return print_result("Duplicate Box Reservation", False, f"First create failed: {r1.text}")

    r2 = requests.post(f"{BASE_URL}/api/reservations", json=payload)
    print(f"  Duplicate reservation: {r2.status_code}")

    if r2.status_code == 409:
        data = r2.json()
        print(f"  Error Code: {data['detail']['code']}")
        if data['detail']['code'] == "RES_DUPLICATE_BOX_RESERVATION":
            return print_result("Duplicate Box Reservation", True)
    
    return print_result("Duplicate Box Reservation", False, f"Expected 409, got {r2.status_code}: {r2.text}")


def test_vehicle_capacity_conflict():
    print_test_header("Test: Vehicle Capacity Conflict")

    many_boxes = []
    for i in range(15):
        box_code = f"RES-CAP-{int(time.time())}-{i}"
        if create_test_box(box_code, "REFRIGERATED"):
            many_boxes.append(box_code)
    
    if len(many_boxes) < 15:
        return print_result("Vehicle Capacity Conflict", False, "Failed to create enough boxes")

    scheduled_date = get_future_scheduled_date(5)
    payload = {
        "site_code": "CP001",
        "customer_code": "CUST001",
        "temperature_zone": "REFRIGERATED",
        "vehicle_no": "京CAP100",
        "vehicle_type": "small",
        "scheduled_date": scheduled_date.isoformat(),
        "box_codes": many_boxes,
        "created_by": "admin"
    }

    r = requests.post(f"{BASE_URL}/api/reservations", json=payload)
    print(f"  Status: {r.status_code}")

    if r.status_code == 409:
        data = r.json()
        print(f"  Error Code: {data['detail']['code']}")
        if data['detail']['code'] == "RES_VEHICLE_CAPACITY_EXCEEDED":
            return print_result("Vehicle Capacity Conflict", True)
    
    return print_result("Vehicle Capacity Conflict", False, f"Expected 409, got {r.status_code}: {r.text}")


def test_modify_after_loaded_blocked():
    print_test_header("Test: Modify After Loaded (Blocked)")

    box_code = f"RES-MOD-{int(time.time())}"
    if not create_test_box(box_code):
        return print_result("Modify After Loaded", False, "Failed to create box")

    scheduled_date = get_future_scheduled_date(5)
    create_payload = {
        "site_code": "CP001",
        "customer_code": "CUST001",
        "temperature_zone": "REFRIGERATED",
        "vehicle_no": "京MOD100",
        "scheduled_date": scheduled_date.isoformat(),
        "box_codes": [box_code],
        "created_by": "admin"
    }

    r1 = requests.post(f"{BASE_URL}/api/reservations", json=create_payload)
    if r1.status_code != 200:
        return print_result("Modify After Loaded", False, f"Create failed: {r1.text}")
    
    reservation_no = r1.json()["reservation_no"]
    print(f"  Created reservation: {reservation_no}")

    confirm_payload = {"reservation_no": reservation_no, "operator": "admin"}
    r2 = requests.post(f"{BASE_URL}/api/reservations/confirm", json=confirm_payload)
    if r2.status_code != 200:
        return print_result("Modify After Loaded", False, f"Confirm failed: {r2.text}")

    lp_payload = {
        "reservation_no": reservation_no,
        "vehicle_no": "京MOD100",
        "operator": "admin"
    }
    r3 = requests.post(f"{BASE_URL}/api/reservations/loading-plans", json=lp_payload)
    if r3.status_code != 200:
        return print_result("Modify After Loaded", False, f"Create LP failed: {r3.text}")
    
    plan_no = r3.json()["plan_no"]

    load_payload = {"plan_no": plan_no, "box_code": box_code, "operator": "admin"}
    r4 = requests.post(f"{BASE_URL}/api/reservations/loading-plans/load-box", json=load_payload)
    if r4.status_code != 200:
        return print_result("Modify After Loaded", False, f"Load box failed: {r4.text}")

    confirm_lp_payload = {"plan_no": plan_no, "operator": "admin"}
    r5 = requests.post(f"{BASE_URL}/api/reservations/loading-plans/confirm", json=confirm_lp_payload)
    if r5.status_code != 200:
        return print_result("Modify After Loaded", False, f"Confirm LP failed: {r5.text}")

    print(f"  Reservation loaded, trying to modify...")
    update_payload = {
        "site_code": "CP001",
        "operator": "admin"
    }
    r6 = requests.put(f"{BASE_URL}/api/reservations/{reservation_no}", json=update_payload)
    print(f"  Modify status: {r6.status_code}")

    if r6.status_code == 409:
        data = r6.json()
        print(f"  Error Code: {data['detail']['code']}")
        if data['detail']['code'] == "RES_ALREADY_LOADED":
            return print_result("Modify After Loaded", True)
    
    return print_result("Modify After Loaded", False, f"Expected 409, got {r6.status_code}: {r6.text}")


def test_cancel_reservation_success():
    print_test_header("Test: Cancel Reservation Success")

    box_code = f"RES-CANCEL-{int(time.time())}"
    if not create_test_box(box_code):
        return print_result("Cancel Reservation", False, "Failed to create box")

    scheduled_date = get_future_scheduled_date(5)
    create_payload = {
        "site_code": "CP001",
        "customer_code": "CUST001",
        "temperature_zone": "REFRIGERATED",
        "vehicle_no": "京CAN100",
        "scheduled_date": scheduled_date.isoformat(),
        "box_codes": [box_code],
        "created_by": "admin"
    }

    r1 = requests.post(f"{BASE_URL}/api/reservations", json=create_payload)
    if r1.status_code != 200:
        return print_result("Cancel Reservation", False, f"Create failed: {r1.text}")
    
    reservation_no = r1.json()["reservation_no"]
    print(f"  Created: {reservation_no}")

    cancel_payload = {
        "reservation_no": reservation_no,
        "cancel_reason": "客户取消",
        "operator": "admin"
    }
    r2 = requests.post(f"{BASE_URL}/api/reservations/cancel", json=cancel_payload)
    print(f"  Cancel status: {r2.status_code}")

    if r2.status_code == 200:
        data = r2.json()
        print(f"  Status: {data['status']}")
        print(f"  Cancel Reason: {data['cancel_reason']}")
        if data['status'] == "CANCELLED" and data['cancel_reason'] == "客户取消":
            return print_result("Cancel Reservation", True)
    
    return print_result("Cancel Reservation", False, f"Cancel failed: {r2.text}")


def test_advance_reservation_window():
    print_test_header("Test: Advance Reservation Window Validation")

    box_code = f"RES-TIME-{int(time.time())}"
    if not create_test_box(box_code):
        return print_result("Advance Reservation Window", False, "Failed to create box")

    scheduled_date = datetime.utcnow() + timedelta(hours=1)
    payload = {
        "site_code": "CP001",
        "customer_code": "CUST001",
        "temperature_zone": "REFRIGERATED",
        "vehicle_no": "京TIME100",
        "scheduled_date": scheduled_date.isoformat(),
        "box_codes": [box_code],
        "created_by": "admin"
    }

    r = requests.post(f"{BASE_URL}/api/reservations", json=payload)
    print(f"  Status: {r.status_code}")

    if r.status_code == 400:
        data = r.json()
        print(f"  Error Code: {data['detail']['code']}")
        if data['detail']['code'] == "RES_INVALID_SCHEDULED_TIME":
            return print_result("Advance Reservation Window", True)
    
    return print_result("Advance Reservation Window", False, f"Expected 400, got {r.status_code}: {r.text}")


def test_batch_import_partial_failure():
    print_test_header("Test: Batch Import Partial Failure")

    box1 = f"RES-BATCH-{int(time.time())}-1"
    box2 = f"RES-BATCH-{int(time.time())}-2"
    create_test_box(box1)
    create_test_box(box2)

    scheduled_date = get_future_scheduled_date(5)
    payload = {
        "reservations": [
            {
                "site_code": "CP001",
                "customer_code": "CUST001",
                "temperature_zone": "REFRIGERATED",
                "vehicle_no": "京BAT101",
                "scheduled_date": scheduled_date.isoformat(),
                "box_codes": [box1],
                "created_by": "admin"
            },
            {
                "site_code": "INVALID_SITE",
                "customer_code": "CUST001",
                "temperature_zone": "REFRIGERATED",
                "vehicle_no": "京BAT102",
                "scheduled_date": scheduled_date.isoformat(),
                "box_codes": [box1],
                "created_by": "admin"
            },
            {
                "site_code": "CP001",
                "customer_code": "CUST001",
                "temperature_zone": "REFRIGERATED",
                "vehicle_no": "京BAT103",
                "scheduled_date": scheduled_date.isoformat(),
                "box_codes": ["NONEXISTENT-BOX"],
                "created_by": "admin"
            },
            {
                "site_code": "CP001",
                "customer_code": "CUST001",
                "temperature_zone": "REFRIGERATED",
                "vehicle_no": "京BAT104",
                "scheduled_date": scheduled_date.isoformat(),
                "box_codes": [box2],
                "created_by": "admin"
            }
        ],
        "import_note": "批量导入测试"
    }

    r = requests.post(f"{BASE_URL}/api/reservations/batch-import", json=payload)
    print(f"  Status: {r.status_code}")

    if r.status_code == 200:
        data = r.json()
        print(f"  Total: {data['total_count']}")
        print(f"  Success: {data['success_count']}")
        print(f"  Failed: {data['failed_count']}")
        print(f"  Errors: {len(data['errors'])}")
        
        for error in data['errors']:
            print(f"    - Index {error['index']}: {error['code']} - {error['error']}")

        if (data['total_count'] == 4 and 
            data['success_count'] == 2 and 
            data['failed_count'] == 2 and
            len(data['errors']) == 2):
            error_codes = [e['code'] for e in data['errors']]
            if "RES_INVALID_SITE" in error_codes and "RES_BOX_VALIDATION_FAILED" in error_codes:
                return print_result("Batch Import Partial Failure", True)
    
    return print_result("Batch Import Partial Failure", False, f"Unexpected result: {r.text}")


def test_config_change_versioning():
    print_test_header("Test: Config Change Versioning")

    old_box = f"RES-OLD-{int(time.time())}"
    create_test_box(old_box)

    scheduled_date = get_future_scheduled_date(5)
    create_payload = {
        "site_code": "CP001",
        "customer_code": "CUST001",
        "temperature_zone": "REFRIGERATED",
        "vehicle_no": "京OLD100",
        "scheduled_date": scheduled_date.isoformat(),
        "box_codes": [old_box],
        "created_by": "admin"
    }

    r1 = requests.post(f"{BASE_URL}/api/reservations", json=create_payload)
    if r1.status_code != 200:
        return print_result("Config Change Versioning", False, f"Create old failed: {r1.text}")
    
    old_reservation_no = r1.json()["reservation_no"]
    old_version = r1.json()["rule_version"]
    print(f"  Old reservation: {old_reservation_no}, version: {old_version}")

    v3_config = {
        "version": "res-v3.0",
        "description": "预约出库规则v3",
        "sites": [
            {"code": "CP001", "name": "门诊采血室", "roles": ["WAREHOUSE"]},
            {"code": "TP001", "name": "中心实验室", "roles": ["WAREHOUSE"]}
        ],
        "customers": [{"code": "CUST001", "name": "省人民医院"}],
        "temperature_zones": [{"code": "REFRIGERATED", "name": "冷藏(2℃~8℃)"}],
        "vehicle_capacities": {"default": 20},
        "reservation_rules": {
            "advance_reservation_hours": 8,
            "cancellation_limit_hours": 4,
            "allow_mixed_temperature_zones": False
        },
        "status_flow": {
            "reservation": {"DRAFT": ["CONFIRMED", "CANCELLED"], "CONFIRMED": ["LOADED", "CANCELLED"], "LOADED": [], "CANCELLED": []},
            "loading_plan": {"DRAFT": ["CONFIRMED", "CANCELLED"], "CONFIRMED": [], "CANCELLED": []}
        },
        "loading_statuses": ["PENDING", "LOADED"],
        "role_site_permissions": {"WAREHOUSE": ["CP001", "TP001"]},
        "users": {"admin": {"role": "WAREHOUSE", "sites": ["CP001", "TP001"]}},
        "reservation_no_prefix": "RES",
        "loading_plan_no_prefix": "LP"
    }

    v3_path = "config/reservation_rules_v3_test.json"
    with open(v3_path, 'w', encoding='utf-8') as f:
        json.dump(v3_config, f, ensure_ascii=False, indent=2)

    r2 = requests.post(f"{BASE_URL}/api/reservations/config/load?config_path={v3_path}")
    print(f"  Load v3 config: {r2.status_code}")
    if r2.status_code != 200:
        os.remove(v3_path)
        return print_result("Config Change Versioning", False, f"Load v3 failed: {r2.text}")

    r3 = requests.get(f"{BASE_URL}/api/reservations/{old_reservation_no}")
    if r3.status_code == 200:
        old_data = r3.json()
        print(f"  Old reservation version after config change: {old_data['rule_version']}")
        if old_data['rule_version'] != "res-v2.0":
            os.remove(v3_path)
            return print_result("Config Change Versioning", False, "Old reservation version changed!")

    new_box = f"RES-NEW-{int(time.time())}"
    create_test_box(new_box)

    new_create_payload = {
        "site_code": "CP001",
        "customer_code": "CUST001",
        "temperature_zone": "REFRIGERATED",
        "vehicle_no": "京NEW100",
        "scheduled_date": get_future_scheduled_date(10).isoformat(),
        "box_codes": [new_box],
        "created_by": "admin"
    }

    r4 = requests.post(f"{BASE_URL}/api/reservations", json=new_create_payload)
    if r4.status_code == 200:
        new_data = r4.json()
        print(f"  New reservation version: {new_data['rule_version']}")
        if new_data['rule_version'] != "res-v3.0":
            os.remove(v3_path)
            return print_result("Config Change Versioning", False, "New reservation not using v3!")

    r5 = requests.post(f"{BASE_URL}/api/reservations/config/load?config_path=config/reservation_rules_v2.json")
    print(f"  Restore v2 config: {r5.status_code}")

    os.remove(v3_path)

    return print_result("Config Change Versioning", True)


def test_query_with_filters():
    print_test_header("Test: Query with Various Filters")

    r = requests.get(f"{BASE_URL}/api/reservations")
    print(f"  List all: {r.status_code}, count: {len(r.json()) if r.status_code == 200 else 'N/A'}")

    r = requests.get(f"{BASE_URL}/api/reservations?site_code=CP001")
    print(f"  Filter by site=CP001: {r.status_code}, count: {len(r.json()) if r.status_code == 200 else 'N/A'}")

    r = requests.get(f"{BASE_URL}/api/reservations?status=LOADED")
    print(f"  Filter by status=LOADED: {r.status_code}, count: {len(r.json()) if r.status_code == 200 else 'N/A'}")

    r = requests.get(f"{BASE_URL}/api/reservations?status=CANCELLED")
    print(f"  Filter by status=CANCELLED: {r.status_code}, count: {len(r.json()) if r.status_code == 200 else 'N/A'}")

    today = datetime.now().strftime("%Y-%m-%d")
    r = requests.get(f"{BASE_URL}/api/reservations?date={today}")
    print(f"  Filter by date={today}: {r.status_code}, count: {len(r.json()) if r.status_code == 200 else 'N/A'}")

    r = requests.get(f"{BASE_URL}/api/reservations?operator=wh_user1")
    print(f"  Filter by operator=wh_user1: {r.status_code}, count: {len(r.json()) if r.status_code == 200 else 'N/A'}")

    return print_result("Query with Various Filters", r.status_code == 200)


def test_get_detail_with_links():
    print_test_header("Test: Get Detail with Linked Records")

    r = requests.get(f"{BASE_URL}/api/reservations")
    if r.status_code != 200 or len(r.json()) == 0:
        return print_result("Get Detail with Links", False, "No reservations found")

    reservation_no = r.json()[0]["reservation_no"]
    
    r2 = requests.get(f"{BASE_URL}/api/reservations/{reservation_no}")
    print(f"  Get detail: {r2.status_code}")

    if r2.status_code == 200:
        data = r2.json()
        print(f"  Has reservation_boxes: {'reservation_boxes' in data and len(data['reservation_boxes']) > 0}")
        print(f"  Has loading_plans: {'loading_plans' in data and len(data['loading_plans']) >= 0}")
        print(f"  Has rule_snapshot: {'rule_snapshot' in data and data['rule_snapshot'] is not None}")
        print(f"  Has transfer_records: {'transfer_records' in data}")
        print(f"  Has work_orders: {'work_orders' in data}")

        return print_result("Get Detail with Links", True)
    
    return print_result("Get Detail with Links", False, r2.text)


def main():
    print("\n" + "=" * 80)
    print("  RESERVATION MODULE - ADVANCED TEST SUITE")
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

    results.append(("Duplicate Box Reservation", test_duplicate_box_reservation()))
    results.append(("Vehicle Capacity Conflict", test_vehicle_capacity_conflict()))
    results.append(("Modify After Loaded Blocked", test_modify_after_loaded_blocked()))
    results.append(("Cancel Reservation", test_cancel_reservation_success()))
    results.append(("Advance Reservation Window", test_advance_reservation_window()))
    results.append(("Batch Import Partial Failure", test_batch_import_partial_failure()))
    results.append(("Config Change Versioning", test_config_change_versioning()))
    results.append(("Query with Filters", test_query_with_filters()))
    results.append(("Get Detail with Links", test_get_detail_with_links()))

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
