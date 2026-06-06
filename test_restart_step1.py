import requests
import json
import os
from datetime import datetime, timedelta

BASE_URL = "http://localhost:8002"


def create_test_box(box_code):
    payload = {
        "box_code": box_code,
        "destination": "TP001",
        "temperature_zone": "REFRIGERATED",
        "current_custodian": "admin"
    }
    r = requests.post(f"{BASE_URL}/api/boxes", json=payload)
    print(f"  Create box {box_code}: {r.status_code}")
    if r.status_code != 200:
        print(f"    Error: {r.text}")
        return False
    
    r2 = requests.post(f"{BASE_URL}/api/boxes/seal?box_code={box_code}&custodian=admin")
    print(f"  Seal box {box_code}: {r2.status_code}")
    if r2.status_code != 200:
        print(f"    Error: {r2.text}")
        return False
    
    return True


def main():
    print("=" * 80)
    print("  RESTART TEST - Step 1: Create Data and Record State")
    print("=" * 80)

    import time
    box_code = f"RES-RESTART-AUTO-{int(time.time())}"
    if not create_test_box(box_code):
        print("FAILED: Cannot create test box")
        return

    scheduled_date = (datetime.utcnow() + timedelta(hours=5)).isoformat()
    create_payload = {
        "site_code": "CP001",
        "customer_code": "CUST001",
        "temperature_zone": "REFRIGERATED",
        "vehicle_no": "京AUTO001",
        "scheduled_date": scheduled_date,
        "box_codes": [box_code],
        "created_by": "admin"
    }
    
    r1 = requests.post(f"{BASE_URL}/api/reservations", json=create_payload)
    reservation_no = r1.json()["reservation_no"]
    rule_version = r1.json()["rule_version"]
    print(f"Created reservation: {reservation_no} (v{rule_version})")

    requests.post(f"{BASE_URL}/api/reservations/confirm", json={"reservation_no": reservation_no, "operator": "admin"})
    
    lp_payload = {"reservation_no": reservation_no, "vehicle_no": "京AUTO001", "operator": "admin"}
    r3 = requests.post(f"{BASE_URL}/api/reservations/loading-plans", json=lp_payload)
    plan_no = r3.json()["plan_no"]
    
    requests.post(f"{BASE_URL}/api/reservations/loading-plans/load-box", json={"plan_no": plan_no, "box_code": box_code, "operator": "admin"})
    requests.post(f"{BASE_URL}/api/reservations/loading-plans/confirm", json={"plan_no": plan_no, "operator": "admin"})
    
    export_payload = {"scheduled_date": datetime.now().strftime("%Y-%m-%d"), "site_code": "CP001", "operator": "admin"}
    r6 = requests.post(f"{BASE_URL}/api/reservations/loading-plans/export", json=export_payload)
    export_file = r6.json().get("file_name", "")
    
    r_detail = requests.get(f"{BASE_URL}/api/reservations/{reservation_no}")
    detail = r_detail.json()
    
    r_logs = requests.get(f"{BASE_URL}/api/audit-logs?entity_type=RESERVATION&entity_id={reservation_no}")
    logs_count = len(r_logs.json())
    
    r_config = requests.get(f"{BASE_URL}/api/config/reservations/active")
    config_version = r_config.json().get("version")
    
    state = {
        "reservation_no": reservation_no,
        "plan_no": plan_no,
        "rule_version": rule_version,
        "config_version": config_version,
        "export_file": export_file,
        "logs_count_before": logs_count,
        "status_before": detail["status"],
        "has_snapshot_before": detail.get("rule_snapshot") is not None,
        "has_loading_plans_before": len(detail.get("loading_plans", [])) > 0
    }
    
    state_file = os.path.join(os.path.dirname(__file__), "restart_test_state.json")
    with open(state_file, "w") as f:
        json.dump(state, f, indent=2)
    
    print(f"\nState saved to: {state_file}")
    print(json.dumps(state, indent=2))
    print("\nNow stop the service and restart it, then run test_restart_step2.py")


if __name__ == "__main__":
    main()
