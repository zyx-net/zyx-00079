#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
转运交接撤回 - 服务重启持久化验证
自动停止服务 -> 创建数据并撤回 -> 停止服务 -> 重启服务 -> 验证数据
"""

import requests
import json
import time
import subprocess
import os
import sys
from datetime import datetime, timezone

BASE_URL = "http://localhost:8000"
HEALTH_URL = "http://localhost:8000/health"

def now_iso():
    return datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")

def find_server_process():
    """查找 uvicorn 服务进程"""
    try:
        result = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq python.exe", "/V", "/FO", "CSV"],
            capture_output=True, text=True, encoding="utf-8"
        )
        lines = result.stdout.strip().split("\n")
        for line in lines:
            if "uvicorn" in line.lower():
                parts = line.split(",")
                if len(parts) >= 2:
                    pid = parts[1].strip('"')
                    return pid
    except Exception as e:
        print(f"查找进程失败: {e}")
    return None

def stop_server():
    """停止服务"""
    print("[Step 1] 停止服务...")
    pid = find_server_process()
    if pid:
        try:
            subprocess.run(["taskkill", "/F", "/PID", pid], check=True)
            print(f"  已停止服务进程 PID={pid}")
            time.sleep(2)
            return True
        except Exception as e:
            print(f"  停止进程失败: {e}")
    else:
        print("  未找到运行中的服务进程")
    return False

def start_server():
    """启动服务"""
    print("\n[Step 4] 启动服务...")
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

def create_test_data():
    """创建测试数据：箱子、样本、交接、撤回"""
    box_code = f"BOX-REV-PERSIST-{now_iso()}"
    print(f"\n[Step 2] 创建测试数据: {box_code}")
    
    # 创建样本
    samples = []
    for i in range(2):
        r = requests.post(f"{BASE_URL}/api/samples", json={
            "barcode": f"SAMP-REV-PERSIST-{now_iso()}-{i}",
            "sample_type": "urine",
            "collection_point": "CP001",
            "collection_time": datetime.now(timezone.utc).isoformat(),
            "current_custodian": "Dr. Zhang",
            "patient_info": json.dumps({"name": "Test Patient"}, ensure_ascii=False)
        })
        samples.append(r.json())
        assert r.status_code in [200, 201], f"创建样本失败: {r.text}"
    print(f"  已创建 {len(samples)} 个样本")
    
    # 创建箱子
    r = requests.post(f"{BASE_URL}/api/boxes", json={
        "box_code": box_code,
        "destination": "TP001",
        "current_custodian": "Dr. Zhang"
    })
    assert r.status_code in [200, 201], f"创建箱子失败: {r.text}"
    print("  已创建箱子")
    
    # 装样本
    barcodes = [s["barcode"] for s in samples]
    r = requests.post(f"{BASE_URL}/api/boxes/pack", json={
        "box_code": box_code,
        "barcodes": barcodes,
        "custodian": "Dr. Zhang"
    })
    assert r.status_code == 200, f"装样本失败: {r.text}"
    print("  已装样本")
    
    # 封箱
    r = requests.post(f"{BASE_URL}/api/boxes/seal",
        params={"box_code": box_code, "custodian": "Dr. Zhang"})
    assert r.status_code == 200, f"封箱失败: {r.text}"
    print("  已封箱")
    
    # 交接
    now = datetime.now(timezone.utc).isoformat()
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
    assert r.status_code == 200, f"交接失败: {r.text}"
    transfer_id = r.json()["transfer_id"]
    print(f"  已交接，交接ID={transfer_id}")
    
    # 撤回
    r = requests.post(f"{BASE_URL}/api/boxes/revoke-transfer", json={
        "box_code": box_code,
        "custodian": "Dr. Li",
        "reason": "持久化测试-交接信息录入错误"
    })
    assert r.status_code == 200, f"撤回失败: {r.text}"
    data = r.json()
    assert data["success"] == True
    assert data["new_box_status"] == "SEALED"
    assert data["new_custodian"] == "Dr. Zhang"
    revoked_transfer_id = data["revoked_transfer_id"]
    print(f"  已撤回，撤回交接ID={revoked_transfer_id}")
    
    # 验证当前状态
    r = requests.get(f"{BASE_URL}/api/boxes/{box_code}")
    box_data = r.json()
    assert box_data["status"] == "SEALED"
    assert box_data["current_custodian"] == "Dr. Zhang"
    print(f"  撤回后状态验证: status=SEALED, custodian=Dr. Zhang")
    
    return box_code, samples, revoked_transfer_id

def verify_after_restart(box_code, samples, revoked_transfer_id):
    """服务重启后验证数据"""
    print(f"\n[Step 5] 服务重启后验证数据: {box_code}")
    all_passed = True
    
    # Test 1: 箱子状态
    print("\n  [5.1] 验证箱子状态...")
    r = requests.get(f"{BASE_URL}/api/boxes/{box_code}")
    box_data = r.json()
    if box_data["status"] == "SEALED" and box_data["current_custodian"] == "Dr. Zhang":
        print(f"    [PASS] 箱子状态: {box_data['status']}, 保管人: {box_data['current_custodian']}")
    else:
        print(f"    [FAIL] 箱子状态错误: status={box_data['status']}, custodian={box_data['current_custodian']}")
        all_passed = False
    
    # Test 2: 样本状态
    print("\n  [5.2] 验证样本状态...")
    for i, s in enumerate(samples):
        r = requests.get(f"{BASE_URL}/api/samples/{s['barcode']}")
        sample_data = r.json()
        if sample_data["status"] == "SEALED" and sample_data["current_custodian"] == "Dr. Zhang":
            print(f"    [PASS] 样本[{i}] {s['barcode']}: status=SEALED, custodian=Dr. Zhang")
        else:
            print(f"    [FAIL] 样本[{i}] {s['barcode']}状态错误: status={sample_data['status']}, custodian={sample_data['current_custodian']}")
            all_passed = False
    
    # Test 3: 交接历史
    print("\n  [5.3] 验证交接历史...")
    r = requests.get(f"{BASE_URL}/api/boxes/{box_code}/transfer-history")
    history = r.json()
    total = len(history)
    revoked_count = len([t for t in history if t.get("is_revoked") == True])
    
    if total >= 1 and revoked_count >= 1:
        print(f"    [PASS] 共 {total} 条记录，已撤回 {revoked_count} 条")
    else:
        print(f"    [FAIL] 交接历史不完整: total={total}, revoked={revoked_count}")
        all_passed = False
    
    # 验证撤回记录字段
    revoked_records = [t for t in history if t.get("id") == revoked_transfer_id]
    if revoked_records:
        rec = revoked_records[0]
        if (rec.get("is_revoked") == True and 
            rec.get("revoked_by") == "Dr. Li" and
            "持久化测试" in rec.get("revoke_reason", "")):
            print(f"    [PASS] 撤回记录字段完整: revoked_by={rec['revoked_by']}, reason={rec['revoke_reason']}")
        else:
            print(f"    [FAIL] 撤回记录字段错误: is_revoked={rec.get('is_revoked')}, revoked_by={rec.get('revoked_by')}")
            all_passed = False
    else:
        print(f"    [FAIL] 未找到撤回记录 ID={revoked_transfer_id}")
        all_passed = False
    
    # Test 4: 重复撤回（应该返回 409/TRANSFER_ALREADY_REVOKED）
    print("\n  [5.4] 验证重复撤回返回 409/TRANSFER_ALREADY_REVOKED...")
    r = requests.post(f"{BASE_URL}/api/boxes/revoke-transfer", json={
        "box_code": box_code,
        "custodian": "Dr. Zhang",
        "reason": "重启后尝试重复撤回"
    })
    try:
        error_code = r.json()["detail"]["code"]
        if r.status_code == 409 and error_code == "TRANSFER_ALREADY_REVOKED":
            print(f"    [PASS] HTTP {r.status_code}, code={error_code}")
        else:
            print(f"    [FAIL] HTTP {r.status_code}, code={error_code} (预期 409/TRANSFER_ALREADY_REVOKED)")
            all_passed = False
    except Exception as e:
        print(f"    [FAIL] 解析响应失败: {e}, 响应: {r.text}")
        all_passed = False
    
    # Test 5: 审计日志
    print("\n  [5.5] 验证审计日志...")
    r = requests.get(f"{BASE_URL}/api/audit", params={"action": "REVOKE_TRANSFER"})
    logs = r.json()
    transfer_logs = [l for l in logs if l["entity_type"] == "TRANSFER" and l["entity_id"] == revoked_transfer_id]
    box_logs = [l for l in logs if l["entity_type"] == "BOX"]
    sample_logs = [l for l in logs if l["entity_type"] == "SAMPLE"]
    
    if len(transfer_logs) >= 1 and len(box_logs) >= 1 and len(sample_logs) >= 2:
        print(f"    [PASS] 审计日志完整: TRANSFER={len(transfer_logs)}, BOX={len(box_logs)}, SAMPLE={len(sample_logs)}")
    else:
        print(f"    [FAIL] 审计日志不完整: TRANSFER={len(transfer_logs)}, BOX={len(box_logs)}, SAMPLE={len(sample_logs)}")
        all_passed = False
    
    # Test 6: 导出 JSON
    print("\n  [5.6] 验证导出 JSON 包含撤回历史...")
    r = requests.get(f"{BASE_URL}/api/boxes/{box_code}/handover-form")
    handover_data = r.json()
    
    r = requests.get(f"{BASE_URL}/api/boxes/{box_code}/exception-list")
    exception_data = r.json()
    
    has_revoked_history = handover_data.get("revoked_transfer_history") is not None
    revoke_exceptions = [e for e in exception_data.get("exceptions", []) if e.get("type") == "TRANSFER_REVOKED"]
    
    if has_revoked_history and len(revoke_exceptions) >= 1:
        print(f"    [PASS] 导出文件包含撤回历史: handover_form有{len(handover_data.get('revoked_transfer_history', []))}条, exception_list有{len(revoke_exceptions)}条TRANSFER_REVOKED")
    else:
        print(f"    [FAIL] 导出文件缺少撤回历史: handover_has_revoked={has_revoked_history}, revoke_exceptions={len(revoke_exceptions)}")
        all_passed = False
    
    # 保存导出文件
    os.makedirs("exports", exist_ok=True)
    with open(f"exports/handover_form_{box_code}.json", "w", encoding="utf-8") as f:
        json.dump(handover_data, f, ensure_ascii=False, indent=2)
    with open(f"exports/exception_list_{box_code}.json", "w", encoding="utf-8") as f:
        json.dump(exception_data, f, ensure_ascii=False, indent=2)
    
    return all_passed

def main():
    print("=" * 70)
    print("  转运交接撤回 - 服务重启持久化验证（自动执行）")
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
    
    box_code = None
    samples = None
    revoked_transfer_id = None
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
        box_code, samples, revoked_transfer_id = create_test_data()
        
        # Step 4: 停止服务（模拟重启）
        print("\n[Step 3] 停止服务（模拟重启）...")
        if server_process:
            server_process.terminate()
            server_process.wait(timeout=10)
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
            print(f"  导出文件: exports/handover_form_{box_code}.json")
            print(f"           exports/exception_list_{box_code}.json")
            print("=" * 70)
            return 0
        else:
            print("  \033[91m部分验证失败!\033[0m")
            print("=" * 70)
            return 1
            
    except Exception as e:
        print(f"\n\033[91m测试执行失败: {e}\033[0m")
        import traceback
        traceback.print_exc()
        return 1
    finally:
        # 确保服务保持运行
        if server_process and server_process.poll() is not None:
            print("\n[Cleanup] 重新启动服务...")
            subprocess.Popen(
                ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"],
                cwd=os.getcwd()
            )
            print("  服务已重新启动")

if __name__ == "__main__":
    sys.exit(main())
