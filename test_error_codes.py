#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
测试接口实际返回的错误码
"""

import requests
import json
from datetime import datetime, timezone

now = datetime.now(timezone.utc).isoformat()
box_code = f'BOX-TEST-ALIGN-{now[:19].replace(":", "")}'
print(f'测试箱号: {box_code}')
print()

# 创建样本
for i in range(2):
    r = requests.post('http://localhost:8000/api/samples', json={
        'barcode': f'SAMP-ALIGN-{now[:19].replace(":", "")}-{i}',
        'sample_type': 'urine',
        'collection_point': 'CP001',
        'collection_time': now,
        'current_custodian': 'Dr. Zhang',
        'patient_info': json.dumps({'name': 'Test'}, ensure_ascii=False)
    })

# 创建箱子
r = requests.post('http://localhost:8000/api/boxes', json={
    'box_code': box_code,
    'destination': 'TP001',
    'current_custodian': 'Dr. Zhang'
})

# 装样本
barcodes = [f'SAMP-ALIGN-{now[:19].replace(":", "")}-{i}' for i in range(2)]
r = requests.post('http://localhost:8000/api/boxes/pack', json={
    'box_code': box_code,
    'barcodes': barcodes,
    'custodian': 'Dr. Zhang'
})

# 封箱
r = requests.post('http://localhost:8000/api/boxes/seal',
    params={'box_code': box_code, 'custodian': 'Dr. Zhang'})

# 交接
temp_records = json.dumps([{'temperature': 4.5, 'timestamp': now}, {'temperature': 5.0, 'timestamp': now}], ensure_ascii=False)
r = requests.post('http://localhost:8000/api/boxes/transfer', json={
    'box_code': box_code,
    'to_point': 'TP001',
    'to_custodian': 'Dr. Li',
    'from_custodian': 'Dr. Zhang',
    'temperature': 4.8,
    'temperature_records': temp_records
})
print(f'交接成功: transfer_id={r.json()["transfer_id"]}')

# 第一次撤回
r = requests.post('http://localhost:8000/api/boxes/revoke-transfer', json={
    'box_code': box_code,
    'custodian': 'Dr. Li',
    'reason': '测试-第一次撤回'
})
print(f'第一次撤回: status={r.status_code}, success={r.json().get("success")}')

# 重复撤回
print()
print('=== 测试重复撤回 ===')
r = requests.post('http://localhost:8000/api/boxes/revoke-transfer', json={
    'box_code': box_code,
    'custodian': 'Dr. Zhang',
    'reason': '测试-重复撤回'
})
print(f'HTTP 状态码: {r.status_code}')
print(f'响应内容: {json.dumps(r.json(), ensure_ascii=False, indent=2)}')
duplicate_code = r.json()['detail']['code']
print(f'错误码: {duplicate_code}')

# 重新交接
r = requests.post('http://localhost:8000/api/boxes/transfer', json={
    'box_code': box_code,
    'to_point': 'TP001',
    'to_custodian': 'Dr. Li',
    'from_custodian': 'Dr. Zhang',
    'temperature': 4.8,
    'temperature_records': temp_records
})
print(f'重新交接成功: transfer_id={r.json()["transfer_id"]}')

# 验收
r = requests.post('http://localhost:8000/api/boxes/accept', json={
    'box_code': box_code,
    'custodian': 'Dr. Li',
    'check_duration': False
})
print(f'验收成功: status={r.json()["status"]}')

# 验收后撤回
print()
print('=== 测试验收后撤回 ===')
r = requests.post('http://localhost:8000/api/boxes/revoke-transfer', json={
    'box_code': box_code,
    'custodian': 'Dr. Li',
    'reason': '测试-验收后撤回'
})
print(f'HTTP 状态码: {r.status_code}')
print(f'响应内容: {json.dumps(r.json(), ensure_ascii=False, indent=2)}')
accept_code = r.json()['detail']['code']
print(f'错误码: {accept_code}')

print()
print('=== 总结 ===')
print(f'重复撤回: {duplicate_code} (预期: TRANSFER_ALREADY_REVOKED)')
print(f'验收后撤回: {accept_code} (预期: BOX_INVALID_STATUS)')
aligned = (duplicate_code == 'TRANSFER_ALREADY_REVOKED' and accept_code == 'BOX_INVALID_STATUS')
print(f'接口对齐状态: {"OK" if aligned else "FAIL"}')

# 保存结果供后续测试使用
with open('last_error_codes.json', 'w', encoding='utf-8') as f:
    json.dump({
        'box_code': box_code,
        'duplicate_code': duplicate_code,
        'accept_code': accept_code,
        'aligned': aligned
    }, f, ensure_ascii=False, indent=2)
