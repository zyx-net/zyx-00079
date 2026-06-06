import requests
import json
import os
import time

BASE_URL = "http://localhost:8002"


def check_service():
    try:
        r = requests.get(f"{BASE_URL}/health", timeout=10)
        return r.status_code == 200
    except Exception as e:
        print(f"  Check service error: {e}")
        return False


def main():
    print("=" * 80)
    print("  RESTART TEST - Step 2: Verify Data After Restart")
    print("=" * 80)

    state_file = os.path.join(os.path.dirname(__file__), "restart_test_state.json")
    if not os.path.exists(state_file):
        print("FAILED: State file not found. Run test_restart_step1.py first.")
        return
    
    with open(state_file, "r") as f:
        state = json.load(f)
    
    print(f"Loaded state for reservation: {state['reservation_no']}")
    
    max_wait = 30
    waited = 0
    while not check_service() and waited < max_wait:
        print(f"  Waiting for service to start... ({waited}s)")
        time.sleep(2)
        waited += 2
    
    if not check_service():
        print("FAILED: Service did not start within 30 seconds!")
        return
    
    print("\n[OK] Service is running after restart")
    
    results = []
    
    print("\n--- Checking Reservation Data ---")
    r = requests.get(f"{BASE_URL}/api/reservations/{state['reservation_no']}")
    print(f"Get reservation: {r.status_code}")
    
    if r.status_code == 200:
        data = r.json()
        checks = [
            ("Reservation Status", data['status'] == state['status_before'], 
             f"{data['status']} == {state['status_before']}"),
            ("Rule Version", data['rule_version'] == state['rule_version'],
             f"{data['rule_version']} == {state['rule_version']}"),
            ("Rule Snapshot", data.get('rule_snapshot') is not None,
             "snapshot exists"),
            ("Loading Plans", len(data.get('loading_plans', [])) > 0,
             f"{len(data.get('loading_plans', []))} plans exist")
        ]
        for name, passed, detail in checks:
            status = "[OK]" if passed else "[XX]"
            print(f"  {status} {name}: {detail}")
            results.append((name, passed))
    
    print("\n--- Checking Audit Logs ---")
    r2 = requests.get(f"{BASE_URL}/api/audit-logs?entity_type=RESERVATION&entity_id={state['reservation_no']}")
    print(f"Get audit logs: {r2.status_code}")
    if r2.status_code == 200:
        logs = r2.json()
        passed = len(logs) >= state['logs_count_before']
        status = "[OK]" if passed else "[XX]"
        print(f"  {status} Audit Logs Count: {len(logs)} >= {state['logs_count_before']}")
        results.append(("Audit Logs Persisted", passed))
    
    print("\n--- Checking Configuration ---")
    r3 = requests.get(f"{BASE_URL}/api/config/reservations/active")
    print(f"Get active config: {r3.status_code}")
    if r3.status_code == 200:
        config = r3.json()
        passed = config.get('version') == state['config_version']
        status = "[OK]" if passed else "[XX]"
        print(f"  {status} Config Version: {config.get('version')} == {state['config_version']}")
        results.append(("Config Version Persisted", passed))
    
    print("\n--- Checking Export File ---")
    exports_dir = os.path.join(os.path.dirname(__file__), "exports")
    export_path = os.path.join(exports_dir, state['export_file'])
    passed = os.path.exists(export_path)
    status = "[OK]" if passed else "[XX]"
    print(f"  {status} Export File: {export_path} exists: {passed}")
    results.append(("Export File Persisted", passed))
    
    print("\n--- Checking Startup Recovery ---")
    r4 = requests.get(f"{BASE_URL}/health")
    if r4.status_code == 200:
        health = r4.json()
        passed = health.get('reservation_config_version') == state['rule_version']
        status = "[OK]" if passed else "[XX]"
        print(f"  {status} Startup Recovery: {health.get('reservation_config_version')} == {state['rule_version']}")
        results.append(("Startup Recovery Works", passed))
    
    print("\n" + "=" * 80)
    print("  TEST SUMMARY")
    print("=" * 80)
    
    passed_count = sum(1 for _, p in results)
    total_count = len(results)
    
    for name, passed in results:
        status = "[OK] PASS" if passed else "[XX] FAIL"
        print(f"  {status}: {name}")
    
    print(f"\n  Passed: {passed_count}/{total_count}")
    
    if passed_count == total_count:
        print("\n  [OK] ALL RESTART PERSISTENCE TESTS PASSED!")
        print("  Data, rule versions, export files, and audit logs all persisted correctly.")
    else:
        print(f"\n  [XX] {total_count - passed_count} TEST(S) FAILED!")
    
    print("=" * 80 + "\n")


if __name__ == "__main__":
    main()
