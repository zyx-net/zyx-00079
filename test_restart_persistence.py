import requests
import time
import os
import json
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


def check_service():
    try:
        r = requests.get(f"{BASE_URL}/health", timeout=5)
        return r.status_code == 200
    except:
        return False


def create_test_box(box_code):
    payload = {
        "box_code": box_code,
        "site_code": "CP001",
        "customer_code": "CUST001",
        "temperature_zone": "REFRIGERATED",
        "status": "CREATED",
        "created_by": "admin"
    }
    r = requests.post(f"{BASE_URL}/api/boxes", json=payload)
    if r.status_code == 200:
        r2 = requests.post(f"{BASE_URL}/api/boxes/seal", json={"box_code": box_code, "operator": "admin"})
        return r2.status_code == 200
    return False


def get_future_scheduled_date(hours=5):
    return (datetime.utcnow() + timedelta(hours=hours)).isoformat()


def main():
    print("=" * 80)
    print("  RESERVATION MODULE - RESTART PERSISTENCE TEST")
    print("=" * 80)
    print(f"  Service is running: {check_service()}")

    results = []

    print_test_header("Step 1: Create Test Data Before Restart")
    
    box_code = f"RES-RESTART-{int(time.time())}"
    if not create_test_box(box_code):
        print("  Failed to create test box")
        return
    
    scheduled_date = get_future_scheduled_date(5)
    create_payload = {
        "site_code": "CP001",
        "customer_code": "CUST001",
        "temperature_zone": "REFRIGERATED",
        "vehicle_no": "京RESTART001",
        "scheduled_date": scheduled_date,
        "box_codes": [box_code],
        "created_by": "admin"
    }
    
    r1 = requests.post(f"{BASE_URL}/api/reservations", json=create_payload)
    print(f"  Create reservation: {r1.status_code}")
    if r1.status_code != 200:
        print(f"  Failed: {r1.text}")
        return
    
    reservation_no = r1.json()["reservation_no"]
    rule_version_before = r1.json()["rule_version"]
    print(f"  Reservation No: {reservation_no}")
    print(f"  Rule Version: {rule_version_before}")
    
    confirm_payload = {"reservation_no": reservation_no, "operator": "admin"}
    r2 = requests.post(f"{BASE_URL}/api/reservations/confirm", json=confirm_payload)
    print(f"  Confirm reservation: {r2.status_code}")
    
    lp_payload = {
        "reservation_no": reservation_no,
        "vehicle_no": "京RESTART001",
        "operator": "admin"
    }
    r3 = requests.post(f"{BASE_URL}/api/reservations/loading-plans", json=lp_payload)
    print(f"  Create loading plan: {r3.status_code}")
    plan_no = r3.json()["plan_no"]
    
    load_payload = {"plan_no": plan_no, "box_code": box_code, "operator": "admin"}
    r4 = requests.post(f"{BASE_URL}/api/reservations/loading-plans/load-box", json=load_payload)
    print(f"  Load box: {r4.status_code}")
    
    confirm_lp_payload = {"plan_no": plan_no, "operator": "admin"}
    r5 = requests.post(f"{BASE_URL}/api/reservations/loading-plans/confirm", json=confirm_lp_payload)
    print(f"  Confirm loading plan: {r5.status_code}")
    
    export_payload = {
        "scheduled_date": datetime.now().strftime("%Y-%m-%d"),
        "site_code": "CP001",
        "operator": "admin"
    }
    r6 = requests.post(f"{BASE_URL}/api/reservations/loading-plans/export", json=export_payload)
    print(f"  Export CSV: {r6.status_code}")
    export_file = r6.json().get("file_name", "")
    print(f"  Export file: {export_file}")
    
    results.append(("Create Test Data", r6.status_code == 200))
    
    print_test_header("Step 2: Verify Data Before Restart")
    
    r7 = requests.get(f"{BASE_URL}/api/reservations/{reservation_no}")
    if r7.status_code == 200:
        data = r7.json()
        print(f"  Reservation status: {data['status']}")
        print(f"  Has rule_snapshot: {data.get('rule_snapshot') is not None}")
        print(f"  Has loading_plans: {len(data.get('loading_plans', [])) > 0}")
        results.append(("Verify Before Restart", data['status'] == 'LOADED'))
    
    r8 = requests.get(f"{BASE_URL}/api/audit-logs?entity_type=RESERVATION&entity_id={reservation_no}")
    if r8.status_code == 200:
        logs = r8.json()
        print(f"  Audit logs count: {len(logs)}")
        results.append(("Audit Logs Exist", len(logs) > 0))
    
    r9 = requests.get(f"{BASE_URL}/api/config/reservations/active")
    if r9.status_code == 200:
        config_data = r9.json()
        print(f"  Active config version: {config_data.get('version')}")
        results.append(("Config Version Exist", config_data.get('version') is not None))
    
    exports_dir = os.path.join(os.path.dirname(__file__), "exports")
    export_exists = os.path.exists(os.path.join(exports_dir, export_file)) if export_file else False
    print(f"  Export file exists: {export_exists}")
    results.append(("Export File Exist", export_exists))
    
    print("\n" + "=" * 80)
    print("  Step 3: Please restart the service now")
    print("  After restarting, press Enter to continue...")
    print("=" * 80)
    input()
    
    print_test_header("Step 4: Verify Data After Restart")
    
    max_wait = 30
    waited = 0
    while not check_service() and waited < max_wait:
        print(f"  Waiting for service to start... ({waited}s)")
        time.sleep(2)
        waited += 2
    
    if not check_service():
        print("  Service did not start within 30 seconds!")
        return
    
    print("  Service is running after restart")
    
    r10 = requests.get(f"{BASE_URL}/api/reservations/{reservation_no}")
    print(f"  Get reservation after restart: {r10.status_code}")
    if r10.status_code == 200:
        data = r10.json()
        print(f"  Reservation status: {data['status']}")
        print(f"  Rule version: {data['rule_version']}")
        print(f"  Has rule_snapshot: {data.get('rule_snapshot') is not None}")
        print(f"  Has loading_plans: {len(data.get('loading_plans', [])) > 0}")
        
        checks = [
            ("Reservation Status", data['status'] == 'LOADED'),
            ("Rule Version Preserved", data['rule_version'] == rule_version_before),
            ("Rule Snapshot Preserved", data.get('rule_snapshot') is not None),
            ("Loading Plans Preserved", len(data.get('loading_plans', [])) > 0)
        ]
        for name, passed in checks:
            results.append((name, passed))
    
    r11 = requests.get(f"{BASE_URL}/api/audit-logs?entity_type=RESERVATION&entity_id={reservation_no}")
    print(f"  Get audit logs after restart: {r11.status_code}")
    if r11.status_code == 200:
        logs = r11.json()
        print(f"  Audit logs count after restart: {len(logs)}")
        results.append(("Audit Logs Persisted", len(logs) > 0))
    
    r12 = requests.get(f"{BASE_URL}/api/config/reservations/active")
    print(f"  Get config after restart: {r12.status_code}")
    if r12.status_code == 200:
        config_data = r12.json()
        print(f"  Active config version after restart: {config_data.get('version')}")
        results.append(("Config Version Persisted", config_data.get('version') == rule_version_before))
    
    export_exists_after = os.path.exists(os.path.join(exports_dir, export_file)) if export_file else False
    print(f"  Export file exists after restart: {export_exists_after}")
    results.append(("Export File Persisted", export_exists_after))
    
    r13 = requests.get(f"{BASE_URL}/health")
    if r13.status_code == 200:
        health_data = r13.json()
        print(f"  Health check reservation config version: {health_data.get('reservation_config_version')}")
        results.append(("Startup Recovery Works", health_data.get('reservation_config_version') == rule_version_before))
    
    print("\n" + "=" * 80)
    print("  TEST SUMMARY")
    print("=" * 80)
    
    passed_count = sum(1 for _, p in results if p)
    total_count = len(results)
    
    for name, passed in results:
        status = "[OK] PASS" if passed else "[XX] FAIL"
        print(f"  {status}: {name}")
    
    print(f"\n  Passed: {passed_count}/{total_count}")
    
    if passed_count == total_count:
        print("\n  ALL TESTS PASSED! [OK]")
    else:
        print(f"\n  {total_count - passed_count} TEST(S) FAILED! [XX]")
    
    print("=" * 80 + "\n")


if __name__ == "__main__":
    main()
