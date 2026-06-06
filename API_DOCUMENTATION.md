# 实验室样本转运管理系统 - API文档

**服务地址**: http://localhost:8000
**交互式文档**: http://localhost:8000/docs

## 目录结构

```
zyx-00079/
├── main.py                    # 服务入口
├── requirements.txt           # Python依赖
├── app/
│   ├── __init__.py
│   ├── database.py           # 数据库连接
│   ├── models.py             # 数据模型
│   ├── schemas.py            # Pydantic模式
│   ├── config_manager.py     # 配置管理与校验
│   ├── audit.py              # 审计日志
│   └── routes/
│       ├── __init__.py
│       ├── config.py         # 配置管理API
│       ├── samples.py        # 样本管理API
│       ├── boxes.py          # 转运箱管理API
│       └── audit.py          # 审计日志API
├── config/
│   ├── rules_v1.json                    # 正确配置
│   ├── rules_bad_invalid_json.json      # 坏配置：无效JSON
│   ├── rules_bad_missing_temp.json      # 坏配置：缺失温度规则
│   ├── rules_bad_temp_range.json        # 坏配置：温度范围错误
│   └── rules_bad_missing_status.json    # 坏配置：缺失状态流转
├── data/
│   └── sample_transport.db   # SQLite数据库（自动生成）
└── exports/                  # 导出文件目录（自动生成）
```

## 状态流转图

```
CREATED → BOXED → SEALED → IN_TRANSIT → DELIVERED → TESTING → COMPLETED → ARCHIVED
                     ↑         ↓            ↓         ↓
                     |     ISOLATED     ISOLATED  ISOLATED
                     └───────┘
                   (撤回交接)
```

**撤回功能说明**：
- 只有 `SEALED` 或 `IN_TRANSIT` 状态的箱子可以撤回
- 撤回后箱子和箱内样本回到 `SEALED` 状态，保管人回滚到原交出人
- 已撤回的交接记录被标记为 `is_revoked = true`，不会被物理删除
- 撤回后再次交接会生成新的交接记录，使用当前规则版本

## 通用响应格式

### 成功响应
```json
{
  "id": 1,
  "barcode": "BLD-2026-0001",
  "status": "CREATED",
  "...": "..."
}
```

### 错误响应
```json
{
  "error": "错误描述信息",
  "code": "错误码",
  "details": {
    "key": "详细错误信息"
  }
}
```

---

## 1. 系统接口

### GET /health
健康检查

**响应示例**:
```json
{
  "status": "healthy",
  "database": "connected",
  "config_loaded": true,
  "config_version": "v1.0"
}
```

---

## 2. 配置管理接口

### POST /api/config/load
加载并验证规则配置

**请求参数**:
- `config_path` (query, required): 配置文件路径

**成功响应** (200):
```json
{
  "id": 1,
  "version": "v1.0",
  "rule_file_path": "d:\\workSpace\\AI__SPACE\\zyx-00079\\config\\rules_v1.json",
  "loaded_at": "2026-06-06T00:00:00",
  "is_active": true
}
```

**失败响应** (400 - 坏配置样例):

1. **无效JSON格式** (`rules_bad_invalid_json.json`):
```json
{
  "error": "配置文件JSON格式错误: Expecting ',' delimiter: line 18 column 1 (char 450)",
  "code": "INVALID_JSON_FORMAT",
  "details": {
    "path": "d:\\workSpace\\AI__SPACE\\zyx-00079\\config\\rules_bad_invalid_json.json",
    "error_position": 450
  }
}
```

2. **缺失温度规则** (`rules_bad_missing_temp.json`):
```json
{
  "error": "样本类型 blood 缺少温度规则配置",
  "code": "MISSING_TEMPERATURE_RULE",
  "details": {
    "sample_type": "blood"
  }
}
```

3. **温度范围无效** (`rules_bad_temp_range.json`):
```json
{
  "error": "样本类型 blood 的温度范围无效: min_temp(10.0) > max_temp(2.0)",
  "code": "INVALID_TEMPERATURE_RANGE",
  "details": {
    "sample_type": "blood",
    "min_temp": 10.0,
    "max_temp": 2.0
  }
}
```

4. **缺失status_flow字段** (`rules_bad_missing_status.json`):
```json
{
  "error": "配置缺少必填字段: status_flow",
  "code": "MISSING_REQUIRED_FIELD",
  "details": {
    "missing_field": "status_flow"
  }
}
```

### GET /api/config/rules
查看当前配置规则

**响应示例**:
```json
{
  "version": "v1.0",
  "description": "实验室样本转运温控与时限规则",
  "temperature_rules": {
    "blood": {
      "min_temp": 2.0,
      "max_temp": 8.0,
      "unit": "celsius"
    }
  },
  "time_limit_rules": {
    "blood": {
      "max_hours_from_collection": 24,
      "max_transfer_minutes": 120
    }
  },
  "sample_types": ["blood", "saliva", "nucleic_acid", "urine"],
  "status_flow": {
    "CREATED": ["BOXED"],
    "BOXED": ["IN_TRANSIT"]
  }
}
```

---

## 3. 样本管理接口

### POST /api/samples
样本建档

**请求体**:
```json
{
  "barcode": "BLD-2026-0001",
  "sample_type": "blood",
  "collection_point": "CP001",
  "collection_time": "2026-06-06T08:00:00Z",
  "patient_info": "{\"name\":\"张三\"}",
  "current_custodian": "张医生"
}
```

**成功响应** (200):
```json
{
  "id": 1,
  "barcode": "BLD-2026-0001",
  "sample_type": "blood",
  "collection_point": "CP001",
  "collection_time": "2026-06-06T08:00:00",
  "patient_info": "{\"name\":\"张三\"}",
  "status": "CREATED",
  "current_custodian": "张医生",
  "box_id": null,
  "created_at": "2026-06-06T08:00:00",
  "updated_at": "2026-06-06T08:00:00",
  "rule_version": "v1.0",
  "is_isolated": false,
  "isolation_reason": null,
  "test_result": null,
  "result_time": null,
  "archived_at": null
}
```

**失败响应** (409 - 条码重复):
```json
{
  "error": "条码 BLD-2026-0001 已存在，不能重复建档",
  "code": "DUPLICATE_BARCODE",
  "details": {
    "existing_barcode": "BLD-2026-0001"
  }
}
```

### POST /api/samples/isolate
异常隔离

**请求体**:
```json
{
  "barcode": "BLD-2026-0001",
  "custodian": "张医生",
  "reason": "样本外观异常，疑似污染"
}
```

**成功响应** (200):
```json
{
  "id": 1,
  "barcode": "BLD-2026-0001",
  "status": "ISOLATED",
  "is_isolated": true,
  "isolation_reason": "样本外观异常，疑似污染",
  "current_custodian": "张医生",
  "rule_version": "v1.0"
}
```

**失败响应** (409 - 已隔离):
```json
{
  "error": "样本 BLD-2026-0001 已处于隔离状态，无需重复隔离",
  "code": "ALREADY_ISOLATED",
  "details": {
    "current_status": "ISOLATED"
  }
}
```

### POST /api/samples/archive
结果归档

**请求体**:
```json
{
  "barcode": "BLD-2026-0001",
  "custodian": "李检验师",
  "test_result": "阴性",
  "result_time": "2026-06-06T12:00:00Z"
}
```

**成功响应** (200):
```json
{
  "id": 1,
  "barcode": "BLD-2026-0001",
  "status": "ARCHIVED",
  "test_result": "阴性",
  "result_time": "2026-06-06T12:00:00",
  "archived_at": "2026-06-06T12:00:00",
  "current_custodian": "李检验师",
  "rule_version": "v1.0"
}
```

**失败响应** (409 - 已隔离样本不能归档):
```json
{
  "error": "样本 BLD-2026-0001 已隔离，不能归档",
  "code": "SAMPLE_ISOLATED",
  "details": {
    "isolation_reason": "样本外观异常，疑似污染"
  }
}
```

---

## 4. 转运箱管理接口

### POST /api/boxes
创建转运箱

**请求体**:
```json
{
  "box_code": "BOX-2026-0001",
  "destination": "TP001",
  "current_custodian": "张医生"
}
```

**成功响应** (200):
```json
{
  "id": 1,
  "box_code": "BOX-2026-0001",
  "destination": "TP001",
  "status": "OPEN",
  "current_custodian": "张医生",
  "temperature_records": null,
  "created_at": "2026-06-06T08:00:00",
  "updated_at": "2026-06-06T08:00:00",
  "sealed_at": null,
  "rule_version": "v1.0",
  "samples": []
}
```

### POST /api/boxes/pack
样本装箱

**请求体**:
```json
{
  "box_code": "BOX-2026-0001",
  "barcodes": ["BLD-2026-0001", "BLD-2026-0002"],
  "custodian": "张医生"
}
```

**成功响应** (200):
```json
{
  "id": 1,
  "box_code": "BOX-2026-0001",
  "status": "OPEN",
  "current_custodian": "张医生",
  "rule_version": "v1.0",
  "samples": [
    {
      "id": 1,
      "barcode": "BLD-2026-0001",
      "status": "BOXED",
      "current_custodian": "张医生"
    },
    {
      "id": 2,
      "barcode": "BLD-2026-0002",
      "status": "BOXED",
      "current_custodian": "张医生"
    }
  ]
}
```

**失败响应** (400 - 非当前保管人):
```json
{
  "error": "当前保管人是 张医生，王医生 无权操作此箱",
  "code": "INVALID_CUSTODIAN",
  "details": {
    "current_custodian": "张医生",
    "operation_custodian": "王医生"
  }
}
```

**失败响应** (409 - 已隔离样本):
```json
{
  "error": "样本 ISO-TEST-0001 已隔离，不能装箱流转",
  "code": "SAMPLE_ISOLATED",
  "details": {
    "barcode": "ISO-TEST-0001",
    "isolation_reason": "样本外观异常，疑似污染"
  }
}
```

### POST /api/boxes/seal
封箱

**请求参数**:
- `box_code` (query, required)
- `custodian` (query, required)

**成功响应** (200):
```json
{
  "id": 1,
  "box_code": "BOX-2026-0001",
  "status": "SEALED",
  "sealed_at": "2026-06-06T08:30:00",
  "current_custodian": "张医生"
}
```

### POST /api/boxes/transfer
交接转运

**请求体**:
```json
{
  "box_code": "BOX-2026-0001",
  "to_point": "TP001",
  "to_custodian": "李检验师",
  "from_custodian": "张医生",
  "temperature": 5.0,
  "temperature_records": "[{\"temperature\": 4.0, \"timestamp\": \"2026-06-06T08:00:00\"}]"
}
```

**成功响应** (200):
```json
{
  "transfer_id": 1,
  "box_code": "BOX-2026-0001",
  "from_point": "CP001",
  "to_point": "TP001",
  "from_custodian": "张医生",
  "to_custodian": "李检验师",
  "transfer_time": "2026-06-06T08:30:00",
  "status": "IN_TRANSIT",
  "temperature": 5.0,
  "rule_version": "v1.0"
}
```

**失败响应** (400 - 非当前保管人提交交接):
```json
{
  "error": "当前保管人是 张医生，王医生 不是当前保管人，无权提交交接",
  "code": "INVALID_CUSTODIAN",
  "details": {
    "current_custodian": "张医生",
    "from_custodian": "王医生"
  }
}
```

**失败响应** (400 - 温度记录格式错误):
```json
{
  "error": "温度记录格式错误",
  "code": "INVALID_TEMPERATURE_FORMAT",
  "details": {
    "errors": [
      "温度记录必须是数组格式",
      "第 1 条记录格式错误，必须是对象"
    ]
  }
}
```

**失败响应** (400 - 温度超出范围):
```json
{
  "error": "温度超出允许范围",
  "code": "TEMPERATURE_VIOLATION",
  "details": {
    "violations": [
      {
        "barcode": "BLD-2026-0001",
        "message": "温度 25.0°C 超出范围 [2.0°C, 8.0°C]"
      }
    ]
  }
}
```

**失败响应** (409 - 箱内有已隔离样本):
```json
{
  "error": "箱内样本 ISO-TEST-0001 已隔离，不能继续流转",
  "code": "SAMPLE_ISOLATED",
  "details": {
    "barcode": "ISO-TEST-0001",
    "isolation_reason": "样本外观异常，疑似污染"
  }
}
```

### POST /api/boxes/accept
到站验收

**请求体**:
```json
{
  "box_code": "BOX-2026-0001",
  "custodian": "李检验师",
  "temperature_records": "[{\"temperature\": 5.0, \"timestamp\": \"2026-06-06T09:00:00\"}]",
  "check_duration": false
}
```

**成功响应** (200):
```json
{
  "id": 1,
  "box_code": "BOX-2026-0001",
  "status": "DELIVERED",
  "current_custodian": "李检验师",
  "temperature_records": "[{\"temperature\": 5.0, \"timestamp\": \"2026-06-06T09:00:00\"}]",
  "rule_version": "v1.0"
}
```

**失败响应** (400 - 超出时限):
```json
{
  "error": "转运时限检查不通过",
  "code": "TIME_LIMIT_VIOLATION",
  "details": {
    "violations": [
      {
        "barcode": "BLD-2026-0001",
        "message": "已过 25.5 小时，超出采集后 24 小时时限"
      }
    ],
    "duration_minutes": 130
  }
}
```

**失败响应** (409 - 箱内有已隔离样本):
```json
{
  "error": "箱内样本 ISO-TRANSIT-0001 已隔离，不能继续流转验收",
  "code": "SAMPLE_ISOLATED",
  "details": {
    "barcode": "ISO-TRANSIT-0001",
    "isolation_reason": "Sample container damaged during transit"
  }
}
```

### POST /api/boxes/revoke-transfer
撤回交接记录

**功能说明**：
已封箱或运输中的转运箱如果发现交接信息录错，当前保管人可以提交撤回原因，把最近一条交接记录标记为撤回，箱子和箱内样本回到可重新交接的稳定状态。

**限制条件**：
- 只有 SEALED 或 IN_TRANSIT 状态的箱子可以撤回
- 已经到站验收(DELIVERED)、隔离(ISOLATED)、检测(TESTING/COMPLETED)或归档(ARCHIVED)的记录不能撤回
- 箱内所有样本状态必须允许撤回
- 不能重复撤回同一条交接记录
- 撤回后再次交接要使用当前规则版本并生成新的交接记录，旧记录不能被覆盖

**请求体**:
```json
{
  "box_code": "BOX-2026-0001",
  "custodian": "Dr. Li",
  "reason": "交接信息录入错误，接收人信息填错"
}
```

**成功响应** (200):
```json
{
  "success": true,
  "message": "交接记录已撤回，箱子和样本已恢复到 SEALED 状态",
  "revoked_transfer_id": 1,
  "box_code": "BOX-2026-0001",
  "old_box_status": "IN_TRANSIT",
  "new_box_status": "SEALED",
  "old_custodian": "Dr. Li",
  "new_custodian": "Dr. Zhang",
  "rule_version": "v1.0"
}
```

**失败响应** (400 - 非当前保管人):
```json
{
  "error": "当前保管人是 Dr. Li，Dr. Wang 无权操作",
  "code": "INVALID_CUSTODIAN",
  "details": {
    "current_custodian": "Dr. Li",
    "operation_custodian": "Dr. Wang"
  }
}
```

**失败响应** (409 - 状态不允许撤回):
```json
{
  "error": "转运箱状态为 DELIVERED，只有 SEALED 或 IN_TRANSIT 状态才能撤回",
  "code": "BOX_INVALID_STATUS",
  "details": {
    "box_status": "DELIVERED"
  }
}
```

**失败响应** (409 - 重复撤回):
```json
{
  "error": "最近一条交接记录已被撤回，无需重复操作",
  "code": "TRANSFER_ALREADY_REVOKED",
  "details": {
    "transfer_id": 1
  }
}
```

**失败响应** (404 - 无交接记录):
```json
{
  "error": "没有可撤回的交接记录",
  "code": "NO_TRANSFER_RECORD",
  "details": {
    "box_code": "BOX-2026-0001"
  }
}
```

### GET /api/boxes/{box_code}/transfer-history
查询转运箱交接记录历史

**功能说明**：查询转运箱的所有交接记录，包括已撤回的记录。

**成功响应** (200):
```json
[
  {
    "id": 2,
    "box_id": 1,
    "from_point": "CP001",
    "to_point": "TP001",
    "from_custodian": "Dr. Zhang",
    "to_custodian": "Dr. Li",
    "transfer_time": "2026-06-06T09:00:00",
    "status": "IN_TRANSIT",
    "temperature": 5.0,
    "duration_minutes": null,
    "rule_version": "v1.0",
    "is_revoked": false,
    "revoked_at": null,
    "revoked_by": null,
    "revoke_reason": null
  },
  {
    "id": 1,
    "box_id": 1,
    "from_point": "CP001",
    "to_point": "TP002",
    "from_custodian": "Dr. Zhang",
    "to_custodian": "Dr. Wang",
    "transfer_time": "2026-06-06T08:30:00",
    "status": "IN_TRANSIT",
    "temperature": 4.5,
    "duration_minutes": null,
    "rule_version": "v1.0",
    "is_revoked": true,
    "revoked_at": "2026-06-06T08:45:00",
    "revoked_by": "Dr. Zhang",
    "revoke_reason": "接收点信息录入错误"
  }
]
```

### GET /api/boxes/{box_code}/handover-form
生成交接单

**成功响应** (200):
```json
{
  "box_code": "BOX-2026-0001",
  "transfer_id": 1,
  "from_point": "CP001",
  "to_point": "TP001",
  "from_custodian": "张医生",
  "to_custodian": "李检验师",
  "transfer_time": "2026-06-06T08:30:00",
  "samples": [
    {
      "barcode": "BLD-2026-0001",
      "sample_type": "blood",
      "collection_point": "CP001",
      "collection_time": "2026-06-06T08:00:00+00:00",
      "status": "DELIVERED"
    }
  ],
  "temperature": 5.0,
  "rule_version": "v1.0"
}
```

**导出文件**: 
- `exports/handover_form_BOX-2026-0001.json` - JSON 格式交接单
- `exports/handover_form_BOX-2026-0001.csv` - CSV 格式交接单

### GET /api/boxes/{box_code}/exception-list
生成异常清单

**成功响应** (200):
```json
{
  "box_code": "BOX-2026-0001",
  "exceptions": [
    {
      "type": "TEMPERATURE_VIOLATION",
      "barcode": "BLD-2026-0001",
      "record_index": 1,
      "temperature": 25.0,
      "message": "温度 25.0°C 超出范围 [2.0°C, 8.0°C]"
    },
    {
      "type": "TIME_LIMIT_VIOLATION",
      "barcode": "BLD-2026-0001",
      "message": "已过 25.5 小时，超出采集后 24 小时时限"
    }
  ],
  "generated_at": "2026-06-06T10:00:00",
  "total_exceptions": 2
}
```

**导出文件**: `exports/exception_list_BOX-2026-0001.json`

---

## 5. 审计日志接口

### GET /api/audit
查询审计日志

**请求参数**:
- `entity_type` (optional): SAMPLE / BOX / TRANSFER
- `entity_id` (optional): 实体ID
- `action` (optional): CREATE / STATUS_CHANGE / TRANSFER / ISOLATE / ARCHIVE
- `custodian` (optional): 保管人

**响应示例**:
```json
[
  {
    "id": 1,
    "entity_type": "SAMPLE",
    "entity_id": 1,
    "action": "CREATE",
    "old_status": null,
    "new_status": "CREATED",
    "custodian": "张医生",
    "rule_version": "v1.0",
    "details": "{\"barcode\": \"BLD-2026-0001\", \"sample_type\": \"blood\"}",
    "created_at": "2026-06-06T08:00:00"
  },
  {
    "id": 2,
    "entity_type": "SAMPLE",
    "entity_id": 1,
    "action": "PACK",
    "old_status": "CREATED",
    "new_status": "BOXED",
    "custodian": "张医生",
    "rule_version": "v1.0",
    "details": "{\"barcode\": \"BLD-2026-0001\"}",
    "created_at": "2026-06-06T08:15:00"
  }
]
```

---

## 错误码汇总

| 错误码 | 描述 |
|--------|------|
| `DUPLICATE_BARCODE` | 条码重复 |
| `DUPLICATE_BOX_CODE` | 箱号重复 |
| `INVALID_SAMPLE_TYPE` | 无效的样本类型 |
| `BOX_NOT_FOUND` | 转运箱不存在 |
| `SAMPLE_NOT_FOUND` | 样本不存在 |
| `BOX_NOT_OPEN` | 转运箱不是OPEN状态 |
| `BOX_NOT_SEALED` | 转运箱未封箱 |
| `BOX_NOT_IN_TRANSIT` | 转运箱不在运输中 |
| `BOX_NOT_DELIVERED` | 转运箱未验收 |
| `INVALID_CUSTODIAN` | 非当前保管人操作 |
| `SAMPLE_ALREADY_BOXED` | 样本已装箱 |
| `SAMPLE_ISOLATED` | 样本已隔离 |
| `ALREADY_ISOLATED` | 样本已处于隔离状态 |
| `SAMPLE_INVALID_STATUS` | 样本状态不允许操作 |
| `INVALID_STATUS_TRANSITION` | 状态流转不合法 |
| `INVALID_TEMPERATURE_FORMAT` | 温度记录格式错误 |
| `TEMPERATURE_VIOLATION` | 温度超出范围 |
| `TIME_LIMIT_VIOLATION` | 超出时限 |
| `CONFIG_NOT_LOADED` | 配置未加载 |
| `NO_ACTIVE_CONFIG` | 无活动配置 |
| `NO_TRANSFER_RECORD` | 没有可撤回的交接记录 |
| `TRANSFER_ALREADY_REVOKED` | 最近一条交接记录已被撤回，重复撤回 |
| `CONCURRENT_CONFLICT` | 并发冲突，该交接记录已被其他请求撤回 |
| `BOX_INVALID_STATUS` | 箱子状态不允许当前操作 |

---

## 配置校验错误码汇总

| 错误码 | 触发场景 |
|--------|----------|
| `CONFIG_FILE_NOT_FOUND` | 配置文件不存在 |
| `CONFIG_READ_ERROR` | 读取配置文件失败 |
| `INVALID_JSON_FORMAT` | 无效JSON格式（对应 `rules_bad_invalid_json.json`） |
| `MISSING_VERSION` | 配置缺少version字段 |
| `MISSING_REQUIRED_FIELD` | 缺少必填字段（对应 `rules_bad_missing_status.json`） |
| `INVALID_SAMPLE_TYPES` | sample_types格式错误 |
| `MISSING_TEMPERATURE_RULE` | 样本类型缺少温度规则（对应 `rules_bad_missing_temp.json`） |
| `MISSING_TEMPERATURE_FIELD` | 温度规则缺少字段 |
| `INVALID_TEMPERATURE_VALUE` | 温度值不是数字 |
| `INVALID_TEMPERATURE_RANGE` | 温度范围min > max（对应 `rules_bad_temp_range.json`） |
| `MISSING_TIME_LIMIT_RULE` | 样本类型缺少时限规则 |
| `MISSING_TIME_LIMIT_FIELD` | 时限规则缺少字段 |
| `INVALID_TIME_LIMIT_VALUE` | 时限值不是正数 |
| `INVALID_STATUS_FLOW` | status_flow格式错误 |
| `MISSING_CREATED_STATUS` | 状态流转缺少CREATED初始状态 |

---

## 服务重启数据核对清单

服务重启后，请核对以下数据：

1. **数据库文件**: `data/sample_transport.db` 必须存在
2. **配置版本**:
   ```bash
   curl http://localhost:8000/api/config/current
   ```
   应返回最后加载的配置版本

3. **样本状态**:
   ```bash
   curl http://localhost:8000/api/samples?status=ARCHIVED
   ```
   应返回所有已归档样本

4. **审计日志**:
   ```bash
   curl http://localhost:8000/api/audit?entity_type=SAMPLE&entity_id=1
   ```
   应返回该样本的完整审计追踪

5. **导出文件**:
   - `exports/handover_form_*.json` - 交接单
   - `exports/exception_list_*.json` - 异常清单

---

## 快速开始

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 启动服务
python main.py

# 3. 加载配置
curl -X POST "http://localhost:8000/api/config/load?config_path=d:\workSpace\AI__SPACE\zyx-00079\config\rules_v1.json"

# 4. 运行测试
.\test_complete_flow.ps1
.\test_failure_scenarios.ps1

# 5. 查看文档
# 浏览器访问: http://localhost:8000/docs
```
