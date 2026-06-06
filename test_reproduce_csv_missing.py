"""
复现测试：验证 CSV 导出缺失问题

BUG 现象：
- 交接单导出只生成 .json 文件，没有 .csv 文件
- 异常清单导出只生成 .json 文件，没有 .csv 文件
- API 文档只提到 JSON 导出，没有提到 CSV
"""
import requests
import os
import json
from datetime import datetime, timezone

BASE_URL = "http://localhost:8000"
TIMESTAMP = datetime.now().strftime("%Y%m%d%H%M%S")
BOX_CODE = f"BOX-CSV-REPRODUCE-{TIMESTAMP}"
EXPORTS_DIR = os.path.join(os.path.dirname(__file__), "exports")

def log(step, message):
    print(f"[{step:2d}] {message}")

def now_iso():
    return datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")

def create_test_data(box_code):
    """创建测试箱、样本、交接数据"""
    for i in range(2):
        r = requests.post(f"{BASE_URL}/api/samples", json={
            "barcode": f"SAMP-CSV-{now_iso()}-{i}",
            "sample_type": "blood",
            "collection_point": "CP001",
            "collection_time": datetime.now(timezone.utc).isoformat(),
            "current_custodian": "Dr. Zhang",
            "patient_info": json.dumps({"name": "张三", "id": f"P{now_iso()}"}, ensure_ascii=False)
        })
        assert r.status_code in [200, 201], f"创建样本失败: {r.text}"
    
    r = requests.post(f"{BASE_URL}/api/boxes", json={
        "box_code": box_code,
        "destination": "TP001",
        "current_custodian": "Dr. Zhang"
    })
    assert r.status_code in [200, 201], f"创建箱子失败: {r.text}"
    
    r = requests.post(f"{BASE_URL}/api/boxes/seal",
        params={"box_code": box_code, "custodian": "Dr. Zhang"})
    assert r.status_code == 200, f"封箱失败: {r.text}"

def do_transfer(box_code):
    now = datetime.now(timezone.utc).isoformat()
    temp_records = json.dumps([
        {"temperature": 4.2, "timestamp": now}
    ], ensure_ascii=False)
    r = requests.post(f"{BASE_URL}/api/boxes/transfer", json={
        "box_code": box_code,
        "to_point": "TP001",
        "to_custodian": "Dr. Li",
        "from_custodian": "Dr. Zhang",
        "temperature": 4.3,
        "temperature_records": temp_records
    })
    assert r.status_code == 200, f"交接失败: {r.text}"

def main():
    print("=" * 80)
    print("  复现测试：CSV 导出缺失问题")
    print(f"  测试箱号: {BOX_CODE}")
    print("=" * 80)
    print()

    # 检查服务
    try:
        requests.get(f"{BASE_URL}/health", timeout=5)
        log(0, "✅ 服务运行正常")
    except:
        log(0, "❌ 服务未运行")
        return False

    # 创建测试数据
    log(1, "创建测试数据...")
    create_test_data(BOX_CODE)
    do_transfer(BOX_CODE)
    log(1, "✅ 测试数据创建完成")

    # 先清理可能存在的旧文件
    json_path = os.path.join(EXPORTS_DIR, f"handover_form_{BOX_CODE}.json")
    csv_path = os.path.join(EXPORTS_DIR, f"handover_form_{BOX_CODE}.csv")
    for p in [json_path, csv_path]:
        if os.path.exists(p):
            os.remove(p)
            log(1, f"🧹 清理旧文件: {os.path.basename(p)}")

    # 导出交接单
    print()
    log(2, "导出交接单...")
    r = requests.get(f"{BASE_URL}/api/boxes/{BOX_CODE}/handover-form")
    assert r.status_code == 200, f"导出失败: {r.text}"
    log(2, "✅ 接口返回正常")

    # 检查文件
    print()
    log(3, "检查 exports 目录文件...")
    json_exists = os.path.exists(json_path)
    csv_exists = os.path.exists(csv_path)
    log(3, f"   JSON 文件: {os.path.basename(json_path)} {'✅ 存在' if json_exists else '❌ 缺失'}")
    log(3, f"   CSV 文件:  {os.path.basename(csv_path)} {'✅ 存在' if csv_exists else '❌ 缺失 (这就是BUG)'}")

    # 导出异常清单
    print()
    log(4, "导出异常清单...")
    r = requests.get(f"{BASE_URL}/api/boxes/{BOX_CODE}/exception-list")
    assert r.status_code == 200, f"导出失败: {r.text}"
    log(4, "✅ 接口返回正常")

    # 检查异常清单文件
    print()
    log(5, "检查 exports 目录文件...")
    json_path_ex = os.path.join(EXPORTS_DIR, f"exception_list_{BOX_CODE}.json")
    csv_path_ex = os.path.join(EXPORTS_DIR, f"exception_list_{BOX_CODE}.csv")
    json_exists_ex = os.path.exists(json_path_ex)
    csv_exists_ex = os.path.exists(csv_path_ex)
    log(5, f"   JSON 文件: {os.path.basename(json_path_ex)} {'✅ 存在' if json_exists_ex else '❌ 缺失'}")
    log(5, f"   CSV 文件:  {os.path.basename(csv_path_ex)} {'✅ 存在' if csv_exists_ex else '❌ 缺失 (这就是BUG)'}")

    # 检查 API 文档
    print()
    log(6, "检查 API 文档...")
    doc_path = os.path.join(os.path.dirname(__file__), "API_DOCUMENTATION.md")
    with open(doc_path, "r", encoding="utf-8") as f:
        doc_content = f.read()
    
    mentions_csv = "csv" in doc_content.lower()
    log(6, f"   文档提到 CSV: {'✅ 有' if mentions_csv else '❌ 没有 (这就是BUG)'}")

    # 总结
    print()
    print("=" * 80)
    print("  BUG 验证结果：")
    print("=" * 80)
    
    bugs_found = []
    if not csv_exists:
        bugs_found.append("❌ 交接单 CSV 文件缺失")
    if not csv_exists_ex:
        bugs_found.append("❌ 异常清单 CSV 文件缺失")
    if not mentions_csv:
        bugs_found.append("❌ API 文档未提到 CSV 导出")
    
    if bugs_found:
        print("\n  🐛 确认 BUG 存在：")
        for bug in bugs_found:
            print(f"  {bug}")
        print(f"\n  测试箱号: {BOX_CODE}")
        print("  BUG 已复现，可以开始修复！")
        result = False
    else:
        print("\n  ✅ BUG 已修复")
        result = True
    
    print("=" * 80)
    return result

if __name__ == "__main__":
    try:
        bug_exists = not main()
        exit(0 if bug_exists else 1)  # BUG存在返回0（预期），不存在返回1
    except Exception as e:
        print(f"\n❌ 测试异常: {e}")
        import traceback
        traceback.print_exc()
        exit(2)
