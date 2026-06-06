#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
撤回交接 - 服务重启后持久化验证（自动重启）
验证：重复撤回、验收后撤回的错误码在服务重启后保持一致
"""

import requests
import json
import subprocess
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

BASE_URL = "http://localhost:8000"
HEALTH_URL = "http://localhost:8000/health"

def now_iso():
    return datetime.now(timezone.utc).isoformat()

def get_error_code(response):
    try:
        return response.json()["detail"]["code"]
    except:
        return None

def print_test_result(test_name, passed, details=""):
    status = "[PASS]" if passed else "[FAIL]"
    color = "\033[92m" if passed else "\033[91m"
    reset = "\033[0m"
    print(f"  {color}{status}{reset} {test_name}")
    if details:
        print(f"         {details}")
    return passed

def stop_server():
    """停止服务"""
    print("[Step 1] 停止服务...")
    try:
        # 查找并终止 uvicorn 进程
        result = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq python.exe", "/V", "/FO", "CSV"],
            capture_output=True, text=True, encoding="utf-8", errors="replace"
        )
        lines = result.stdout.strip().split("\n")
        for line in lines:
            if "uvicorn" in line.lower():
                parts = line.split(",")
                if len(parts) >= 2:
                    pid = parts[1].strip('"')
                    subprocess.run(["taskkill", "/F", "/PID", pid], check=True)
                    print(f"  已停止服务进程 PID={pid}")
        time.sleep(3)
        return True
    except Exception as e:
        print(f"  停止进程失败: {e}")
        return False

def start_server():
    """启动服务"""
    print("\n[Step 3] 启动服务...")
    try:
        process = subprocess.Popen(
            ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"],
            cwd=os.getcwd(),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        # 等待服务启动
        max_wait = 15
        for i in range(max_wait):
            try:
                r = requests.get(HEALTH_URL, timeout=2)
                if r.status_code == 200:
                    print(f"  服务已启动，PID={process.pid}")
                    time.sleep(1)
                    return process
            except:
                pass
            time.sleep(1)
        print(f"  警告: {max_wait}秒内服务未就绪，继续尝试...")
        return process
    except Exception as e:
        print(f"  启动服务失败: {e}")
        return None

def create_test_data(box_code):
    """创建测试数据：样本、箱子、装样、封箱、交接、撤回"""
    now = now_iso()
    print(f"\n[Step 2] 创建测试数据: {box_code}")
    
    # 创建样本
    samples = []
    for i in range(2):
        r = requests.post(f"{BASE_URL}/api/samples", json={
            "barcode": f"SAMP-RESTART-{now[:19].replace(':', '')}-{i}",
            "sample_type": "urine",
            "collection_point": "CP001",
            "collection_time": now,
            "current_custodian": "Dr. Zhang",
            "patient_info": json.dumps({"name": "Test Patient"}, ensure_ascii=False)
        })
        samples.append(r.json())
    
    # 创建箱子
    r = requests.post(f"{BASE_URL}/api/boxes", json={
        "box_code": box_code,
        "destination": "TP001",
        "current_custodian": "Dr. Zhang"
    })
    
    # 装样本
    barcodes = [s["barcode"] for s in samples]
    r = requests.post(f"{BASE_URL}/api/boxes/pack", json={
        "box_code": box_code,
        "barcodes": barcodes,
        "custodian": "Dr. Zhang"
    })
    
    # 封箱
    r = requests.post(f"{BASE_URL}/api/boxes/seal",
        params={"box_code": box_code, "custodian": "Dr. Zhang"})
    
    # 交接
    temp_records = json.dumps([
        {"temperature": 4.5, "timestamp": now},
        {"temperature": 5.0, "timestamp": now}
    ], ensure_ascii=False)
    r = requests.post(f"{BASE_URL}/api/boxes/transfer", json={
        "box_code": box_code,
        "to_point": "TP001",
        "to_custodian": "Dr. Li",
        "from_custodian": "Dr. Zhang",
        "temperature": 4.8,
        "temperature_records": temp_records
    })
    transfer_id = r.json()["transfer_id"]
    print(f"  已交接，交接ID={transfer_id}")
    
    # 撤回
    r = requests.post(f"{BASE_URL}/api/boxes/revoke-transfer", json={
        "box_code": box_code,
        "custodian": "Dr. Li",
        "reason": "重启验证-第一次撤回"
    })
    assert r.status_code == 200 and r.json()["success"] == True, "第一次撤回失败"
    revoked_transfer_id = r.json()["revoked_transfer_id"]
    print(f"  已撤回，撤回交接ID={revoked_transfer_id}")
    
    return samples, revoked_transfer_id

def verify_after_restart(box_code, samples, revoked_transfer_id):
    """服务重启后验证"""
    print(f"\n[Step 5] 服务重启后验证: {box_code}")
    all_passed = True
    
    # 1. 验证重复撤回返回 409/TRANSFER_ALREADY_REVOKED
    print("\n  [5.1] 验证重复撤回返回 409/TRANSFER_ALREADY_REVOKED...")
    r = requests.post(f"{BASE_URL}/api/boxes/revoke-transfer", json={
        "box_code": box_code,
        "custodian": "Dr. Zhang",
        "reason": "重启验证-重复撤回"
    })
    error_code = get_error_code(r)
    passed = (r.status_code == 409 and error_code == "TRANSFER_ALREADY_REVOKED")
    all_passed &= print_test_result("重复撤回错误码正确", passed,
        f"HTTP {r.status_code}, code={error_code}")
    
    # 2. 重新交接并验收，然后验证验收后撤回返回 409/BOX_INVALID_STATUS
    print("\n  [5.2] 重新交接并验收...")
    now = now_iso()
    temp_records = json.dumps([
        {"temperature": 4.5, "timestamp": now},
        {"temperature": 5.0, "timestamp": now}
    ], ensure_ascii=False)
    r = requests.post(f"{BASE_URL}/api/boxes/transfer", json={
        "box_code": box_code,
        "to_point": "TP001",
        "to_custodian": "Dr. Li",
        "from_custodian": "Dr. Zhang",
        "temperature": 4.8,
        "temperature_records": temp_records
    })
    assert r.status_code == 200, "重新交接失败"
    new_transfer_id = r.json()["transfer_id"]
    print(f"  已重新交接，交接ID={new_transfer_id}")
    
    r = requests.post(f"{BASE_URL}/api/boxes/accept", json={
        "box_code": box_code,
        "custodian": "Dr. Li",
        "check_duration": False
    })
    assert r.status_code == 200 and r.json()["status"] == "DELIVERED", "验收失败"
    print(f"  已验收，状态={r.json()['status']}")
    
    print("\n  [5.3] 验证验收后撤回返回 409/BOX_INVALID_STATUS...")
    r = requests.post(f"{BASE_URL}/api/boxes/revoke-transfer", json={
        "box_code": box_code,
        "custodian": "Dr. Li",
        "reason": "重启验证-验收后撤回"
    })
    error_code = get_error_code(r)
    passed = (r.status_code == 409 and error_code == "BOX_INVALID_STATUS")
    all_passed &= print_test_result("验收后撤回错误码正确", passed,
        f"HTTP {r.status_code}, code={error_code}")
    
    # 3. 验证文档总表包含两项（文件层面，重启不影响，但为了完整性）
    print("\n  [5.4] 验证文档总表包含两项错误码...")
    doc_file = Path("API_DOCUMENTATION.md")
    doc_bytes = doc_file.read_bytes()
    has_transfer = b"TRANSFER_ALREADY_REVOKED" in doc_bytes
    has_box = b"BOX_INVALID_STATUS" in doc_bytes
    has_no_transfer = b"NO_TRANSFER_RECORD" in doc_bytes
    passed = (has_transfer and has_box and has_no_transfer)
    all_passed &= print_test_result("文档总表包含所有错误码", passed,
        f"TRANSFER_ALREADY_REVOKED: {has_transfer}, BOX_INVALID_STATUS: {has_box}, NO_TRANSFER_RECORD: {has_no_transfer}")
    
    # 4. 验证导出 JSON 包含撤回历史
    print("\n  [5.5] 验证导出 JSON 包含撤回历史...")
    r = requests.get(f"{BASE_URL}/api/boxes/{box_code}/handover-form")
    handover_data = r.json()
    r = requests.get(f"{BASE_URL}/api/boxes/{box_code}/exception-list")
    exception_data = r.json()
    
    revoked_history = handover_data.get("revoked_transfer_history", [])
    revoke_exceptions = [e for e in exception_data.get("exceptions", []) if e.get("type") == "TRANSFER_REVOKED"]
    passed = (len(revoked_history) >= 1 and len(revoke_exceptions) >= 1)
    all_passed &= print_test_result("导出 JSON 包含撤回历史", passed,
        f"handover_form撤回历史: {len(revoked_history)} 条, exception_list TRANSFER_REVOKED: {len(revoke_exceptions)} 条")
    
    # 保存导出文件
    os.makedirs("exports", exist_ok=True)
    with open(f"exports/handover_form_{box_code}_restart.json", "w", encoding="utf-8") as f:
        json.dump(handover_data, f, ensure_ascii=False, indent=2)
    with open(f"exports/exception_list_{box_code}_restart.json", "w", encoding="utf-8") as f:
        json.dump(exception_data, f, ensure_ascii=False, indent=2)
    
    # 5. 验证审计日志口径一致性
    print("\n  [5.6] 验证审计日志口径一致性...")
    r = requests.get(f"{BASE_URL}/api/audit", params={"action": "REVOKE_TRANSFER"})
    logs = r.json()
    transfer_logs = [l for l in logs if l["entity_type"] == "TRANSFER" and l["entity_id"] == revoked_transfer_id]
    box_logs = [l for l in logs if l["entity_type"] == "BOX"]
    sample_logs = [l for l in logs if l["entity_type"] == "SAMPLE"]
    
    passed = (len(transfer_logs) >= 1 and len(box_logs) >= 1 and len(sample_logs) >= 2)
    all_passed &= print_test_result("审计日志完整保留", passed,
        f"TRANSFER:{len(transfer_logs)}, BOX:{len(box_logs)}, SAMPLE:{len(sample_logs)}")
    
    # 6. 验证 OpenAPI 文档仍然包含错误码描述
    print("\n  [5.7] 验证 OpenAPI 文档包含错误码描述...")
    r = requests.get(f"{BASE_URL}/openapi.json")
    openapi_data = r.json()
    paths = openapi_data.get("paths", {})
    revoke_path = paths.get("/api/boxes/revoke-transfer", {})
    post_op = revoke_path.get("post", {})
    responses = post_op.get("responses", {})
    
    resp_409 = responses.get("409", {})
    desc_409 = resp_409.get("description", "")
    has_transfer_revoked = "TRANSFER_ALREADY_REVOKED" in desc_409
    has_box_invalid = "BOX_INVALID_STATUS" in desc_409
    
    resp_404 = responses.get("404", {})
    desc_404 = resp_404.get("description", "")
    has_no_transfer = "NO_TRANSFER_RECORD" in desc_404
    
    passed = (has_transfer_revoked and has_box_invalid and has_no_transfer)
    all_passed &= print_test_result("OpenAPI 文档包含错误码描述", passed,
        f"409_TRANSFER: {has_transfer_revoked}, 409_BOX: {has_box_invalid}, 404_NO_TRANSFER: {has_no_transfer}")
    
    return all_passed

def main():
    print("=" * 70)
    print("  撤回交接 - 服务重启后持久化验证（自动执行）")
    print("=" * 70)
    print()
    
    # 检查服务是否运行
    try:
        r = requests.get(HEALTH_URL, timeout=3)
        if r.status_code != 200:
            print("服务未正常运行，请先启动服务")
            return 1
    except:
        print("服务未运行，请先启动服务")
        return 1
    
    box_code = f"BOX-RESTART-{now_iso()[:19].replace(':', '')}"
    server_process = None
    
    try:
        # Step 1: 停止服务
        stop_server()
        
        # Step 2: 重新启动服务
        server_process = start_server()
        if not server_process:
            print("无法启动服务")
            return 1
        
        # Step 3: 创建测试数据并撤回
        samples, revoked_transfer_id = create_test_data(box_code)
        
        # Step 4: 停止服务（模拟重启）
        print("\n[Step 4] 停止服务（模拟重启）...")
        if server_process and server_process.poll() is None:
            server_process.terminate()
            try:
                server_process.wait(timeout=10)
            except:
                server_process.kill()
            print("  服务已停止")
        else:
            stop_server()
        time.sleep(3)
        
        # Step 5: 重启服务
        server_process = start_server()
        if not server_process:
            print("无法重新启动服务")
            return 1
        
        # Step 6: 验证数据
        all_passed = verify_after_restart(box_code, samples, revoked_transfer_id)
        
        print("\n" + "=" * 70)
        if all_passed:
            print("  \033[92m所有持久化验证通过!\033[0m")
            print(f"  测试箱号: {box_code}")
            print(f"  导出文件: exports/handover_form_{box_code}_restart.json")
            print(f"           exports/exception_list_{box_code}_restart.json")
            ret = 0
        else:
            print("  \033[91m部分验证失败!\033[0m")
            ret = 1
        print("=" * 70)
        
        # 保存测试结果
        with open(f"restart_test_result_{box_code}.json", "w", encoding="utf-8") as f:
            json.dump({
                "box_code": box_code,
                "all_passed": all_passed,
                "revoked_transfer_id": revoked_transfer_id
            }, f, ensure_ascii=False, indent=2)
        
        return ret
            
    except Exception as e:
        print(f"\n\033[91m测试执行失败: {e}\033[0m")
        import traceback
        traceback.print_exc()
        return 1
    finally:
        # 确保服务保持运行
        print("\n[Cleanup] 重新启动服务...")
        subprocess.Popen(
            ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"],
            cwd=os.getcwd()
        )
        print("  服务已重新启动")

if __name__ == "__main__":
    sys.exit(main())
