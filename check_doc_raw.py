#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
检查 API_DOCUMENTATION.md 的真实内容
"""

# 用二进制方式读取，检查是否有特殊字符
with open('API_DOCUMENTATION.md', 'rb') as f:
    raw = f.read()

# 搜索字节序列
search_str = 'NO_TRANSFER_RECORD'
search_bytes = search_str.encode('utf-8')
pos = raw.find(search_bytes)

print(f'搜索: {search_str}')
print(f'字节长度: {len(search_bytes)}')
print(f'找到位置: {pos}')

if pos >= 0:
    # 显示前后内容
    start = max(0, pos - 20)
    end = min(len(raw), pos + 60)
    context = raw[start:end]
    print(f'上下文字节: {context}')
    try:
        print(f'上下文文本: {context.decode("utf-8")}')
    except Exception as e:
        print(f'解码失败: {e}')
else:
    print('未找到！尝试其他编码...')
    # 尝试 gbk 编码
    try:
        search_bytes_gbk = search_str.encode('gbk')
        pos_gbk = raw.find(search_bytes_gbk)
        print(f'GBK 搜索位置: {pos_gbk}')
    except:
        pass

print()
print('=== 检查错误码汇总表区域 ===')
# 找 '错误码汇总' 的位置
err_pos = raw.find('错误码汇总'.encode('utf-8'))
if err_pos >= 0:
    # 显示后面 800 字节
    section = raw[err_pos:err_pos+800]
    try:
        section_text = section.decode('utf-8')
        print('找到错误码汇总区域，内容:')
        for i, line in enumerate(section_text.split('\n')[:25]):
            print(f'  {i}: {repr(line)}')
    except Exception as e:
        print(f'解码错误码汇总区域失败: {e}')
        print(f'原始字节: {section[:200]}')

print()
print('=== 检查 TRANSFER_ALREADY_REVOKED ===')
search_str2 = 'TRANSFER_ALREADY_REVOKED'
pos2 = raw.find(search_str2.encode('utf-8'))
print(f'找到位置: {pos2}')

print()
print('=== 检查 BOX_INVALID_STATUS ===')
search_str3 = 'BOX_INVALID_STATUS'
pos3 = raw.find(search_str3.encode('utf-8'))
print(f'找到位置: {pos3}')

print()
print('=== 总结 ===')
print(f'NO_TRANSFER_RECORD 存在: {pos >= 0}')
print(f'TRANSFER_ALREADY_REVOKED 存在: {pos2 >= 0}')
print(f'BOX_INVALID_STATUS 存在: {pos3 >= 0}')
