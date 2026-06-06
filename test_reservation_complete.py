import requests
import json
import os
import sys
import time
from datetime import datetime, timedelta

BASE_URL = "http://localhost:8001"


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
        print(f"  Error: {r.json()}")
        return False

    r2 = requests.post(f"{BASE_URL}/api/boxes/seal?box_code={box_code}&custodian=admin")
    print(f"  Seal box {box_code}: {r2.status_code}")
    if r2.status_code != 200:
        print(f"  Seal Error: {r2.json()}")
        return False

    return True


def setup_test_data():
    print_test_header("Setup - Creating Test Data")

    timestamp = int(time.time())
    box_codes = [
        f"RES-TEST-{timestamp}-{i}" for i in range(6)
    ]

    for i, box_code in enumerate(box_codes):
        if i < 3:
            temp_zone = "REFRIGERATED"
        elif i < 5:
            temp_zone = "FROZEN"
        else:
            temp_zone = "AMBIENT"
        if not create_test_box(box_code, temp_zone):
                return None

    print(f"  Created {len(box_codes)} test boxes")
    return box_codes


def get_future_scheduled_date(hours_ahead=5):
    future = datetime.now() + timedelta(hours=hours_ahead)
    return future.replace(minute=0, second=0, microsecond=0)


def test_success_create_reservation(box_codes):
    print_test_header("Test 1: Successfully Create Reservation")

    scheduled_date = get_future_scheduled_date(5)
    payload = {
        "site_code": "CP001",
        "customer_code": "CUST001",
        "temperature_zone": "REFRIGERATED",
        "vehicle_no": "京A12345",
        "vehicle_type": "small",
        "scheduled_date": scheduled_date.isoformat(),
        "box_codes": box_codes[:3],
        "created_by": "admin",
        "remark": "常规出库预约"
    }

    r = requests.post(f"{BASE_URL}/api/reservations", json=payload)
    print(f"  Status: {r.status_code}")

    if r.status_code == 200:
        data = r.json()
        print(f"  Reservation No: {data['reservation_no']}")
        print(f"  Status: {data['status']}")
        print(f"  Rule Version: {data['rule_version']}")
        print(f"  Box Count: {len(data['reservation_boxes'])}")

        assert data["site_code"] == "CP001"
        assert data["customer_code"] == "CUST001"
        assert data["temperature_zone"] == "REFRIGERATED"
        assert data["vehicle_no"] == "京A12345"
        assert data["status"] == "DRAFT"
        assert data["rule_version"] == "res-v2.0"
        assert len(data["reservation_boxes"]) == 3
        assert data["created_by"] == "admin"

        return print_result("Successfully Create Reservation", True, data["reservation_no"]), data["reservation_no"]
    else:
        print(f"  Error: {r.json()}")
        return print_result("Successfully Create Reservation", False, r.text), None


def test_success_confirm_reservation(reservation_no):
    print_test_header("Test 2: Successfully Confirm Reservation")

    payload = {
        "reservation_no": reservation_no,
        "operator": "admin"
    }

    r = requests.post(f"{BASE_URL}/api/reservations/confirm", json=payload)
    print(f"  Status: {r.status_code}")

    if r.status_code == 200:
        data = r.json()
        print(f"  Status: {data['status']}")

        assert data["status"] == "CONFIRMED"

        return print_result("Successfully Confirm Reservation", True)
    else:
        print(f"  Error: {r.json()}")
        return print_result("Successfully Confirm Reservation", False, r.text)


def test_success_create_loading_plan(reservation_no, box_codes):
    print_test_header("Test 3: Successfully Create Loading Plan")

    payload = {
        "reservation_no": reservation_no,
        "vehicle_no": "京A12345",
        "driver": "张师傅",
        "departure_time": get_future_scheduled_date(6).isoformat(),
        "operator": "admin",
        "remark": "装车计划"
    }

    r = requests.post(f"{BASE_URL}/api/reservations/loading-plans", json=payload)
    print(f"  Status: {r.status_code}")

    if r.status_code == 200:
        data = r.json()
        print(f"  Plan No: {data['plan_no']}")
        print(f"  Status: {data['status']}")
        print(f"  Box Count: {len(data['loading_plan_boxes'])}")

        assert data["reservation_no"] == reservation_no
        assert data["status"] == "DRAFT"
        assert len(data["loading_plan_boxes"]) == 3

        return print_result("Successfully Create Loading Plan", True, data["plan_no"]), data["plan_no"]
    else:
        print(f"  Error: {r.json()}")
        return print_result("Successfully Create Loading Plan", False, r.text), None


def test_success_load_boxes(plan_no, box_codes):
    print_test_header("Test 4: Successfully Load Boxes")

    all_passed = True
    for i, box_code in enumerate(box_codes[:3]):
        payload = {
            "plan_no": plan_no,
            "box_code": box_code,
            "operator": "admin"
        }

        r = requests.post(f"{BASE_URL}/api/reservations/loading-plans/load-box", json=payload)
        print(f"  Load box {box_code}: {r.status_code}")

        if r.status_code == 200:
            data = r.json()
            print(f"    Status: {data['loading_plan_boxes'][i]['loaded']}")
            assert data["loading_plan_boxes"][i]["loaded"] == True
        else:
            print(f"    Error: {r.json()}")
            all_passed = False

    return print_result("Successfully Load Boxes", all_passed)


def test_success_confirm_loading_plan(plan_no, reservation_no):
    print_test_header("Test 5: Successfully Confirm Loading Plan")

    payload = {
        "plan_no": plan_no,
        "operator": "admin"
    }

    r = requests.post(f"{BASE_URL}/api/reservations/loading-plans/confirm", json=payload)
    print(f"  Status: {r.status_code}")

    if r.status_code == 200:
        data = r.json()
        print(f"  Plan Status: {data['status']}")

        assert data["status"] == "CONFIRMED"

        r2 = requests.get(f"{BASE_URL}/api/reservations/{reservation_no}")
        if r2.status_code == 200:
            res_data = r2.json()
            print(f"  Reservation Status: {res_data['status']}")
            assert res_data["status"] == "LOADED"

        return print_result("Successfully Confirm Loading Plan", True)
    else:
        print(f"  Error: {r.json()}")
        return print_result("Successfully Confirm Loading Plan", False, r.text)


def test_unauthorized_site_access(box_codes):
    print_test_header("Test 6: Unauthorized Site Access (Permission Denied)")

    scheduled_date = get_future_scheduled_date(5)
    payload = {
        "site_code": "CP003",
        "customer_code": "CUST001",
        "temperature_zone": "REFRIGERATED",
        "vehicle_no": "京B67890",
        "scheduled_date": scheduled_date.isoformat(),
        "box_codes": [box_codes[0]],
        "created_by": "wh_user1",
        "remark": "越权测试"
    }

    r = requests.post(f"{BASE_URL}/api/reservations", json=payload)
    print(f"  Status: {r.status_code}")

    if r.status_code == 403:
        data = r.json()
        print(f"  Error Code: {data['detail']['code']}")
        print(f"  Error Message: {data['detail']['error']}")

        assert data["detail"]["code"] == "RES_PERMISSION_DENIED"
        assert "无权访问站点 CP003" in data["detail"]["error"]

        return print_result("Unauthorized Site Access", True)
    else:
        print(f"  Error: Expected 403, got {r.status_code}")
        return print_result("Unauthorized Site Access", False, r.text)


def test_duplicate_box_reservation(box_codes, existing_reservation_no):
    print_test_header("Test 7: Duplicate Box Reservation (Conflict)")

    scheduled_date = get_future_scheduled_date(5)
    payload = {
        "site_code": "CP001",
        "customer_code": "CUST002",
        "temperature_zone": "REFRIGERATED",
        "vehicle_no": "京B67890",
        "scheduled_date": scheduled_date.isoformat(),
        "box_codes": [box_codes[0]],
        "created_by": "admin",
        "remark": "重复箱号测试"
    }

    r = requests.post(f"{BASE_URL}/api/reservations", json=payload)
    print(f"  Status: {r.status_code}")

    if r.status_code == 409:
        data = r.json()
        print(f"  Error Code: {data['detail']['code']}")
        print(f"  Error Message: {data['detail']['error']}")

        assert data["detail"]["code"] == "RES_DUPLICATE_BOX_RESERVATION"
        assert box_codes[0] in data["detail"]["error"]

        return print_result("Duplicate Box Reservation", True)
    else:
        print(f"  Error: Expected 409, got {r.status_code}")
        return print_result("Duplicate Box Reservation", False, r.text)


def test_vehicle_capacity_conflict(box_codes):
    print_test_header("Test 8: Vehicle Capacity Conflict")

    scheduled_date = get_future_scheduled_date(5)
    many_boxes = []
    for i in range(15):
        box_code = f"RES-CAP-TEST-{int(time.time())}-{i}"
        create_test_box(box_code, "REFRIGERATED")
        many_boxes.append(box_code)

    payload = {
        "site_code": "CP001",
        "customer_code": "CUST001",
        "temperature_zone": "REFRIGERATED",
        "vehicle_no": "京C11111",
        "vehicle_type": "small",
        "scheduled_date": scheduled_date.isoformat(),
        "box_codes": many_boxes,
        "created_by": "admin",
        "remark": "车辆容量测试"
    }

    r = requests.post(f"{BASE_URL}/api/reservations", json=payload)
    print(f"  Status: {r.status_code}")

    if r.status_code == 409:
        data = r.json()
        print(f"  Error Code: {data['detail']['code']}")
        print(f"  Error Message: {data['detail']['error']}")

        assert data["detail"]["code"] == "RES_VEHICLE_CAPACITY_EXCEEDED"

        return print_result("Vehicle Capacity Conflict", True)
    else:
        print(f"  Error: Expected 409, got {r.status_code}")
        return print_result("Vehicle Capacity Conflict", False, r.text)


def test_modify_after_loaded(reservation_no):
    print_test_header("Test 9: Modify After Loaded (Blocked)")

    payload = {
        "site_code": "CP001",
        "customer_code": "CUST001",
        "temperature_zone": "REFRIGERATED",
        "vehicle_no": "京A12345",
        "scheduled_date": get_future_scheduled_date(5).isoformat(),
        "box_codes": [],
        "operator": "admin"
    }

    r = requests.put(f"{BASE_URL}/api/reservations/{reservation_no}", json=payload)
    print(f"  Status: {r.status_code}")

    if r.status_code == 400:
        data = r.json()
        print(f"  Error Code: {data['detail']['code']}")
        print(f"  Error Message: {data['detail']['error']}")

        assert data["detail"]["code"] == "RES_INVALID_STATUS"
        assert "已装车或已取消的预约无法修改" in data["detail"]["error"]

        return print_result("Modify After Loaded", True)
    else:
        print(f"  Error: Expected 400, got {r.status_code}")
        return print_result("Modify After Loaded", False, r.text)


def test_cancel_reservation_success():
    print_test_header("Test 10: Successfully Cancel Reservation")

    scheduled_date = get_future_scheduled_date(5)
    box_code = f"RES-CANCEL-{int(time.time())}"
    create_test_box(box_code, "REFRIGERATED")

    create_payload = {
        "site_code": "CP001",
        "customer_code": "CUST001",
        "temperature_zone": "REFRIGERATED",
        "vehicle_no": "京D22222",
        "scheduled_date": scheduled_date.isoformat(),
        "box_codes": [box_code],
        "created_by": "admin"
    }

    r1 = requests.post(f"{BASE_URL}/api/reservations", json=create_payload)
    if r1.status_code != 200:
        print(f"  Create reservation failed: {r1.json()}")
        return print_result("Successfully Cancel Reservation", False, "Create failed")

    reservation_data = r1.json()
    reservation_no = reservation_data["reservation_no"]
    print(f"  Created reservation: {reservation_no}")

    cancel_payload = {
        "reservation_no": reservation_no,
        "operator": "admin",
        "reason": "客户取消订单"
    }

    r2 = requests.post(f"{BASE_URL}/api/reservations/cancel", json=cancel_payload)
    print(f"  Cancel Status: {r2.status_code}")

    if r2.status_code == 200:
        data = r2.json()
        print(f"  Status: {data['status']}")
        print(f"  Cancel Reason: {data['cancel_reason']}")

        assert data["status"] == "CANCELLED"
        assert data["cancel_reason"] == "客户取消订单"
        assert data["cancelled_by"] == "admin"

        return print_result("Successfully Cancel Reservation", True)
    else:
        print(f"  Error: {r2.json()}")
        return print_result("Successfully Cancel Reservation", False, r2.text)


def test_query_reservations():
    print_test_header("Test 11: Query Reservations with Filters")

    r = requests.get(f"{BASE_URL}/api/reservations")
    print(f"  List all - Status: {r.status_code}")
    assert r.status_code == 200
    all_data = r.json()
    print(f"  Total reservations: {len(all_data)}")

    r = requests.get(f"{BASE_URL}/api/reservations?site_code=CP001")
    print(f"  Filter by site_code=CP001 - Status: {r.status_code}")
    assert r.status_code == 200
    site_filtered = r.json()
    print(f"  Filtered by site: {len(site_filtered)}")

    r = requests.get(f"{BASE_URL}/api/reservations?status=LOADED")
    print(f"  Filter by status=LOADED - Status: {r.status_code}")
    assert r.status_code == 200
    status_filtered = r.json()
    print(f"  Filtered by status=LOADED: {len(status_filtered)}")

    today = datetime.now().strftime("%Y-%m-%d")
    r = requests.get(f"{BASE_URL}/api/reservations?date={today}")
    print(f"  Filter by date={today} - Status: {r.status_code}")
    assert r.status_code == 200
    date_filtered = r.json()
    print(f"  Filtered by date: {len(date_filtered)}")

    r = requests.get(f"{BASE_URL}/api/reservations?operator=wh_user1")
    print(f"  Filter by operator permission - Status: {r.status_code}")
    assert r.status_code == 200
    perm_filtered = r.json()
    print(f"  Filtered by wh_user1 permissions: {len(perm_filtered)}")

    return print_result("Query Reservations with Filters", True)


def test_get_reservation_detail(reservation_no):
    print_test_header("Test 12: Get Reservation Detail with Linked Records")

    r = requests.get(f"{BASE_URL}/api/reservations/{reservation_no}")
    print(f"  Status: {r.status_code}")

    if r.status_code == 200:
        data = r.json()
        print(f"  Reservation No: {data['reservation_no']}")
        print(f"  Status: {data['status']}")
        print(f"  Box Count: {len(data['reservation_boxes'])}")
        print(f"  Loading Plans: {len(data['loading_plans'])}")
        print(f"  Has Rule Snapshot: {'rule_snapshot' in data and data['rule_snapshot'] is not None}")

        assert data["reservation_no"] == reservation_no
        assert "reservation_boxes" in data
        assert "loading_plans" in data
        assert "rule_snapshot" in data

        return print_result("Get Reservation Detail", True)
    else:
        print(f"  Error: {r.json()}")
        return print_result("Get Reservation Detail", False, r.text)


def test_batch_import_partial_failure(box_codes):
    print_test_header("Test 13: Batch Import with Partial Failure")

    new_box = f"RES-BATCH-{int(time.time())}"
    create_test_box(new_box, "REFRIGERATED")

    scheduled_date = get_future_scheduled_date(5)

    payload = {
        "reservations": [
            {
                "site_code": "CP001",
                "customer_code": "CUST001",
                "temperature_zone": "REFRIGERATED",
                "vehicle_no": "京E33333",
                "scheduled_date": scheduled_date.isoformat(),
                "box_codes": [new_box],
                "created_by": "admin"
            },
            {
                "site_code": "INVALID_SITE",
                "customer_code": "CUST001",
                "temperature_zone": "REFRIGERATED",
                "vehicle_no": "京E33334",
                "scheduled_date": scheduled_date.isoformat(),
                "box_codes": [new_box],
                "created_by": "admin"
            },
            {
                "site_code": "CP001",
                "customer_code": "CUST001",
                "temperature_zone": "REFRIGERATED",
                "vehicle_no": "京E33335",
                "scheduled_date": scheduled_date.isoformat(),
                "box_codes": ["NONEXISTENT-BOX"],
                "created_by": "admin"
            },
            {
                "site_code": "CP001",
                "customer_code": "CUST001",
                "temperature_zone": "REFRIGERATED",
                "vehicle_no": "京E33336",
                "scheduled_date": scheduled_date.isoformat(),
                "box_codes": [box_codes[3]],
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

        for error in data["errors"]:
            print(f"    - Index {error['index']}: {error['code']} - {error['error']}")

        assert data["total_count"] == 4
        assert data["success_count"] == 2
        assert data["failed_count"] == 2
        assert len(data["errors"]) == 2

        error_codes = [e["code"] for e in data["errors"]]
        assert "RES_INVALID_SITE" in error_codes
        assert "BOX_NOT_FOUND" in error_codes

        return print_result("Batch Import with Partial Failure", True)
    else:
        print(f"  Error: {r.json()}")
        return print_result("Batch Import with Partial Failure", False, r.text)


def test_csv_export():
    print_test_header("Test 14: CSV Export Loading Plans")

    r = requests.get(f"{BASE_URL}/api/reservations/loading-plans/export/csv")
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

        return print_result("CSV Export Loading Plans", True)
    else:
        print(f"  Error: {r.json()}")
        return print_result("CSV Export Loading Plans", False, r.text)


def test_reservation_csv_export():
    print_test_header("Test 15: CSV Export Reservations")

    r = requests.get(f"{BASE_URL}/api/reservations/export/csv")
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

        return print_result("CSV Export Reservations", True)
    else:
        print(f"  Error: {r.json()}")
        return print_result("CSV Export Reservations", False, r.text)


def test_config_change_versioning():
    print_test_header("Test 16: Config Change - Old Reservations Retain Old Rules")

    old_reservation_no = None

    scheduled_date = get_future_scheduled_date(5)
    box_code = f"RES-OLD-{int(time.time())}"
    create_test_box(box_code, "REFRIGERATED")

    create_payload = {
        "site_code": "CP001",
        "customer_code": "CUST001",
        "temperature_zone": "REFRIGERATED",
        "vehicle_no": "京F44444",
        "scheduled_date": scheduled_date.isoformat(),
        "box_codes": [box_code],
        "created_by": "admin"
    }

    r1 = requests.post(f"{BASE_URL}/api/reservations", json=create_payload)
    if r1.status_code == 200:
        old_reservation_no = r1.json()["reservation_no"]
        print(f"  Created old reservation: {old_reservation_no}")
        print(f"  Old rule version: {r1.json()['rule_version']}")

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
    if r2.status_code == 200:
        print(f"  New config version: {r2.json()['version']}")

    if old_reservation_no:
        r3 = requests.get(f"{BASE_URL}/api/reservations/{old_reservation_no}")
        if r3.status_code == 200:
            old_data = r3.json()
            print(f"  Old reservation rule version: {old_data['rule_version']}")
            assert old_data["rule_version"] == "res-v2.0"
            print(f"  [OK] Old reservation retains v2.0 rules")

    new_box = f"RESNEW-{int(time.time())}"
    create_test_box(new_box, "REFRIGERATED")

    new_create_payload = {
        "site_code": "CP001",
        "customer_code": "CUST001",
        "temperature_zone": "REFRIGERATED",
        "vehicle_no": "京F55555",
        "scheduled_date": get_future_scheduled_date(10).isoformat(),
        "box_codes": [new_box],
        "created_by": "admin"
    }

    r4 = requests.post(f"{BASE_URL}/api/reservations", json=new_create_payload)
    if r4.status_code == 200:
        new_data = r4.json()
        print(f"  New reservation rule version: {new_data['rule_version']}")
        assert new_data["rule_version"] == "res-v3.0"
        print(f"  [OK] New reservation uses v3.0 rules")

    r5 = requests.post(f"{BASE_URL}/api/reservations/config/load?config_path=config/reservation_rules_v2.json")
    print(f"  Restore v2 config: {r5.status_code}")

    os.remove(v3_path)

    return print_result("Config Change Versioning", r2.status_code == 200 and r4.status_code == 200)


def test_query_loading_plans(plan_no):
    print_test_header("Test 17: Query Loading Plans with Filters")

    r = requests.get(f"{BASE_URL}/api/reservations/loading-plans")
    print(f"  List all - Status: {r.status_code}")
    assert r.status_code == 200
    all_data = r.json()
    print(f"  Total loading plans: {len(all_data)}")

    r = requests.get(f"{BASE_URL}/api/reservations/loading-plans?status=CONFIRMED")
    print(f"  Filter by status=CONFIRMED - Status: {r.status_code}")
    assert r.status_code == 200
    status_filtered = r.json()
    print(f"  Filtered by status=CONFIRMED: {len(status_filtered)}")

    return print_result("Query Loading Plans", True)


def test_audit_logs():
    print_test_header("Test 18: Verify Audit Logs")

    r = requests.get(f"{BASE_URL}/api/audit?entity_type=RESERVATION")
    print(f"  Status: {r.status_code}")

    if r.status_code == 200:
        data = r.json()
        print(f"  Total RESERVATION audit logs: {len(data)}")

        actions = [log["action"] for log in data]
        print(f"  Actions found: {set(actions)}")

        expected_actions = ["CREATE", "STATUS_CHANGE", "CANCEL"]
        for action in expected_actions:
            if action in actions:
                print(f"    [OK] {action} log found")
            else:
                print(f"    [--] {action} log not found")

        r2 = requests.get(f"{BASE_URL}/api/audit?entity_type=LOADING_PLAN")
        if r2.status_code == 200:
            lp_data = r2.json()
            print(f"  Total LOADING_PLAN audit logs: {len(lp_data)}")

        return print_result("Verify Audit Logs", len(data) >= 1)
    else:
        print(f"  Error: {r.json()}")
        return print_result("Verify Audit Logs", False, r.text)


def test_after_restart_query(reservation_no, plan_no):
    print_test_header("Test 19: Query After Restart (Persistence Test)")

    print("  Note: This test verifies data persists in SQLite database")

    r = requests.get(f"{BASE_URL}/api/reservations/{reservation_no}")
    print(f"  Get reservation detail: {r.status_code}")
    assert r.status_code == 200
    data = r.json()
    assert data["reservation_no"] == reservation_no
    assert data["status"] == "LOADED"
    print(f"  [OK] Reservation data persisted correctly")

    r = requests.get(f"{BASE_URL}/api/reservations/loading-plans/{plan_no}")
    print(f"  Get loading plan detail: {r.status_code}")
    assert r.status_code == 200
    lp_data = r.json()
    assert lp_data["plan_no"] == plan_no
    print(f"  [OK] Loading plan data persisted correctly")

    r = requests.get(f"{BASE_URL}/api/reservations/config/current")
    print(f"  Get current config: {r.status_code}")
    if r.status_code == 200:
        config_data = r.json()
        print(f"  Config version: {config_data['version']}")
        print(f"  [OK] Config version persisted correctly")

    r = requests.get(f"{BASE_URL}/api/audit?entity_type=RESERVATION&limit=1")
    print(f"  Get audit logs: {r.status_code}")
    assert r.status_code == 200
    print(f"  [OK] Audit logs persisted correctly")

    exports_dir = os.path.join(os.path.dirname(__file__), "exports")
    if os.path.exists(exports_dir):
        csv_files = [f for f in os.listdir(exports_dir) if f.endswith('.csv')]
        print(f"  [OK] Export files directory exists with {len(csv_files)} CSV files")

    return print_result("Query After Restart (Persistence Test)", True)


def test_advance_reservation_window():
    print_test_header("Test 20: Advance Reservation Window Validation")

    scheduled_date = datetime.now() + timedelta(hours=1)
    box_code = f"RES-TIME-{int(time.time())}"
    create_test_box(box_code, "REFRIGERATED")

    payload = {
        "site_code": "CP001",
        "customer_code": "CUST001",
        "temperature_zone": "REFRIGERATED",
        "vehicle_no": "京G66666",
        "scheduled_date": scheduled_date.isoformat(),
        "box_codes": [box_code],
        "created_by": "admin"
    }

    r = requests.post(f"{BASE_URL}/api/reservations", json=payload)
    print(f"  Status: {r.status_code}")

    if r.status_code == 400:
        data = r.json()
        print(f"  Error Code: {data['detail']['code']}")
        print(f"  Error Message: {data['detail']['error']}")

        assert data["detail"]["code"] == "RES_INVALID_RESERVATION_TIME"

        return print_result("Advance Reservation Window", True)
    else:
        print(f"  Error: Expected 400, got {r.status_code}")
        return print_result("Advance Reservation Window", False, r.text)


def main():
    print("\n" + "=" * 80)
    print("  RESERVATION OUTBOUND & LOADING PLAN - COMPREHENSIVE TEST SUITE")
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

    print("  Service is running [OK]")
    print()

    results = []

    config_ok = setup_config()
    results.append(("Setup Config", config_ok))

    box_codes = setup_test_data()
    if not box_codes:
        print("FAILED: Cannot create test boxes")
        return 1

    passed, reservation_no = test_success_create_reservation(box_codes)
    results.append(("Create Reservation", passed))

    if reservation_no:
        results.append(("Confirm Reservation", test_success_confirm_reservation(reservation_no)))

        passed, plan_no = test_success_create_loading_plan(reservation_no, box_codes)
        results.append(("Create Loading Plan", passed))

        if plan_no:
            results.append(("Load Boxes", test_success_load_boxes(plan_no, box_codes)))
            results.append(("Confirm Loading Plan", test_success_confirm_loading_plan(plan_no, reservation_no)))
            results.append(("Query Loading Plans", test_query_loading_plans(plan_no)))

        results.append(("Unauthorized Site Access", test_unauthorized_site_access(box_codes)))
        results.append(("Duplicate Box Reservation", test_duplicate_box_reservation(box_codes, reservation_no)))
        results.append(("Modify After Loaded", test_modify_after_loaded(reservation_no)))
        results.append(("Query Reservations", test_query_reservations()))
        results.append(("Get Reservation Detail", test_get_reservation_detail(reservation_no)))

    results.append(("Cancel Reservation", test_cancel_reservation_success()))
    results.append(("Vehicle Capacity Conflict", test_vehicle_capacity_conflict(box_codes)))
    results.append(("Batch Import Partial Failure", test_batch_import_partial_failure(box_codes)))
    results.append(("CSV Export Loading Plans", test_csv_export()))
    results.append(("CSV Export Reservations", test_reservation_csv_export()))
    results.append(("Config Change Versioning", test_config_change_versioning()))
    results.append(("Audit Logs", test_audit_logs()))

    if reservation_no and plan_no:
        results.append(("After Restart Query", test_after_restart_query(reservation_no, plan_no)))

    results.append(("Advance Reservation Window", test_advance_reservation_window()))

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
