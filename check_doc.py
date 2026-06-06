#!/usr/bin/env python
# -*- coding: utf-8 -*-

with open('API_DOCUMENTATION.md', 'r', encoding='utf-8') as f:
    content = f.read()

print('Checking for NO_TRANSFER_RECORD...')
print('Contains exact string:', 'NO_TRANSFER_RECORD' in content)

search_str = 'NO_TRANSFER_RECORD'
pos = content.find(search_str)
if pos >= 0:
    print(f'Found at position {pos}')
    print(f'Context: {repr(content[pos-20:pos+40])}')
else:
    print('Not found!')
    
print()
print('Checking error code section...')
err_pos = content.find('NO_TRANSFER_RECORD', 780)
if err_pos >= 0:
    print(f'Found in error codes at position {err_pos}')
    print(f'Context: {repr(content[err_pos-20:err_pos+40])}')
