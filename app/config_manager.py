import json
import os
from typing import Dict, Any, Optional, List, Tuple
from datetime import datetime
from sqlalchemy.orm import Session
from .models import ConfigVersion


class ConfigValidationError(Exception):
    def __init__(self, message: str, error_code: str, details: Optional[Dict[str, Any]] = None):
        self.message = message
        self.error_code = error_code
        self.details = details or {}
        super().__init__(self.message)


class ConfigManager:
    _instance = None
    _current_config: Optional[Dict[str, Any]] = None
    _current_version: Optional[str] = None
    _config_file_path: Optional[str] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    @classmethod
    def reset_instance(cls):
        cls._instance = None
        cls._current_config = None
        cls._current_version = None
        cls._config_file_path = None

    def load_config(self, config_path: str, db: Session) -> Tuple[Dict[str, Any], str]:
        self.reset_instance()

        if not os.path.exists(config_path):
            raise ConfigValidationError(
                f"配置文件不存在: {config_path}",
                "CONFIG_FILE_NOT_FOUND",
                {"path": config_path}
            )

        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                config_content = f.read()
        except Exception as e:
            raise ConfigValidationError(
                f"读取配置文件失败: {str(e)}",
                "CONFIG_READ_ERROR",
                {"path": config_path}
            )

        try:
            config = json.loads(config_content)
        except json.JSONDecodeError as e:
            raise ConfigValidationError(
                f"配置文件JSON格式错误: {str(e)}",
                "INVALID_JSON_FORMAT",
                {"path": config_path, "error_position": e.pos}
            )

        self.validate_config(config)

        version = config.get("version")
        if not version:
            raise ConfigValidationError(
                "配置缺少version字段",
                "MISSING_VERSION",
                {"path": config_path}
            )

        existing = db.query(ConfigVersion).filter(ConfigVersion.version == version).first()
        if existing:
            existing.is_active = True
            db.commit()
            db.refresh(existing)
        else:
            db.query(ConfigVersion).update({ConfigVersion.is_active: False})
            new_config = ConfigVersion(
                version=version,
                rule_file_path=config_path,
                config_content=config_content,
                is_active=True
            )
            db.add(new_config)
            db.commit()
            db.refresh(new_config)

        self._current_config = config
        self._current_version = version
        self._config_file_path = config_path

        return config, version

    def validate_config(self, config: Dict[str, Any]) -> None:
        required_fields = ["version", "temperature_rules", "time_limit_rules", "sample_types", "status_flow"]
        for field in required_fields:
            if field not in config:
                raise ConfigValidationError(
                    f"配置缺少必填字段: {field}",
                    "MISSING_REQUIRED_FIELD",
                    {"missing_field": field}
                )

        sample_types = config.get("sample_types", [])
        if not isinstance(sample_types, list) or len(sample_types) == 0:
            raise ConfigValidationError(
                "sample_types必须是非空列表",
                "INVALID_SAMPLE_TYPES",
                {"sample_types": sample_types}
            )

        temp_rules = config.get("temperature_rules", {})
        time_rules = config.get("time_limit_rules", {})

        for sample_type in sample_types:
            if sample_type not in temp_rules:
                raise ConfigValidationError(
                    f"样本类型 {sample_type} 缺少温度规则配置",
                    "MISSING_TEMPERATURE_RULE",
                    {"sample_type": sample_type}
                )

            temp_rule = temp_rules[sample_type]
            required_temp_fields = ["min_temp", "max_temp", "unit"]
            for field in required_temp_fields:
                if field not in temp_rule:
                    raise ConfigValidationError(
                        f"样本类型 {sample_type} 的温度规则缺少字段: {field}",
                        "MISSING_TEMPERATURE_FIELD",
                        {"sample_type": sample_type, "missing_field": field}
                    )

            if not isinstance(temp_rule["min_temp"], (int, float)):
                raise ConfigValidationError(
                    f"样本类型 {sample_type} 的min_temp必须是数字",
                    "INVALID_TEMPERATURE_VALUE",
                    {"sample_type": sample_type, "value": temp_rule["min_temp"]}
                )

            if not isinstance(temp_rule["max_temp"], (int, float)):
                raise ConfigValidationError(
                    f"样本类型 {sample_type} 的max_temp必须是数字",
                    "INVALID_TEMPERATURE_VALUE",
                    {"sample_type": sample_type, "value": temp_rule["max_temp"]}
                )

            if temp_rule["min_temp"] > temp_rule["max_temp"]:
                raise ConfigValidationError(
                    f"样本类型 {sample_type} 的温度范围无效: min_temp({temp_rule['min_temp']}) > max_temp({temp_rule['max_temp']})",
                    "INVALID_TEMPERATURE_RANGE",
                    {"sample_type": sample_type, "min_temp": temp_rule["min_temp"], "max_temp": temp_rule["max_temp"]}
                )

            if sample_type not in time_rules:
                raise ConfigValidationError(
                    f"样本类型 {sample_type} 缺少时限规则配置",
                    "MISSING_TIME_LIMIT_RULE",
                    {"sample_type": sample_type}
                )

            time_rule = time_rules[sample_type]
            required_time_fields = ["max_hours_from_collection", "max_transfer_minutes"]
            for field in required_time_fields:
                if field not in time_rule:
                    raise ConfigValidationError(
                        f"样本类型 {sample_type} 的时限规则缺少字段: {field}",
                        "MISSING_TIME_LIMIT_FIELD",
                        {"sample_type": sample_type, "missing_field": field}
                    )

                if not isinstance(time_rule[field], (int, float)) or time_rule[field] <= 0:
                    raise ConfigValidationError(
                        f"样本类型 {sample_type} 的 {field} 必须是正数",
                        "INVALID_TIME_LIMIT_VALUE",
                        {"sample_type": sample_type, "field": field, "value": time_rule[field]}
                    )

        status_flow = config.get("status_flow", {})
        if not isinstance(status_flow, dict) or len(status_flow) == 0:
            raise ConfigValidationError(
                "status_flow必须是非空字典",
                "INVALID_STATUS_FLOW",
                {"status_flow": status_flow}
            )

        if "CREATED" not in status_flow:
            raise ConfigValidationError(
                "status_flow必须包含CREATED状态",
                "MISSING_CREATED_STATUS"
            )

    def get_current_config(self) -> Optional[Dict[str, Any]]:
        return self._current_config

    def get_current_version(self) -> Optional[str]:
        return self._current_version

    def get_config_file_path(self) -> Optional[str]:
        return self._config_file_path

    def check_temperature(self, sample_type: str, temperature: float) -> Tuple[bool, str]:
        if self._current_config is None:
            raise ConfigValidationError("配置未加载", "CONFIG_NOT_LOADED")

        temp_rules = self._current_config.get("temperature_rules", {})
        rule = temp_rules.get(sample_type)
        if rule is None:
            return False, f"未知样本类型: {sample_type}"

        if temperature < rule["min_temp"] or temperature > rule["max_temp"]:
            return False, f"温度 {temperature}°C 超出范围 [{rule['min_temp']}°C, {rule['max_temp']}°C]"

        return True, "温度符合要求"

    def check_collection_time_limit(self, sample_type: str, collection_time: datetime, current_time: Optional[datetime] = None) -> Tuple[bool, str]:
        if self._current_config is None:
            raise ConfigValidationError("配置未加载", "CONFIG_NOT_LOADED")

        if current_time is None:
            current_time = datetime.utcnow()

        time_rules = self._current_config.get("time_limit_rules", {})
        rule = time_rules.get(sample_type)
        if rule is None:
            return False, f"未知样本类型: {sample_type}"

        hours_passed = (current_time - collection_time).total_seconds() / 3600
        if hours_passed > rule["max_hours_from_collection"]:
            return False, f"已过 {hours_passed:.1f} 小时，超出采集后 {rule['max_hours_from_collection']} 小时时限"

        return True, f"已过 {hours_passed:.1f} 小时，在时限内"

    def check_transfer_duration(self, sample_type: str, duration_minutes: int) -> Tuple[bool, str]:
        if self._current_config is None:
            raise ConfigValidationError("配置未加载", "CONFIG_NOT_LOADED")

        time_rules = self._current_config.get("time_limit_rules", {})
        rule = time_rules.get(sample_type)
        if rule is None:
            return False, f"未知样本类型: {sample_type}"

        if duration_minutes > rule["max_transfer_minutes"]:
            return False, f"转运耗时 {duration_minutes} 分钟，超出 {rule['max_transfer_minutes']} 分钟时限"

        return True, f"转运耗时 {duration_minutes} 分钟，在时限内"

    def validate_temperature_records(self, temperature_records: str, sample_type: str) -> Tuple[bool, List[str]]:
        errors = []
        try:
            records = json.loads(temperature_records)
        except json.JSONDecodeError as e:
            return False, [f"温度记录JSON格式错误: {str(e)}"]

        if not isinstance(records, list):
            return False, ["温度记录必须是数组格式"]

        for i, record in enumerate(records):
            if not isinstance(record, dict):
                errors.append(f"第 {i+1} 条记录格式错误，必须是对象")
                continue

            if "temperature" not in record:
                errors.append(f"第 {i+1} 条记录缺少temperature字段")
                continue

            if not isinstance(record["temperature"], (int, float)):
                errors.append(f"第 {i+1} 条记录的temperature必须是数字")
                continue

            temp = float(record["temperature"])
            is_valid, msg = self.check_temperature(sample_type, temp)
            if not is_valid:
                errors.append(f"第 {i+1} 条记录: {msg}")

            if "timestamp" in record:
                try:
                    datetime.fromisoformat(str(record["timestamp"]).replace('Z', '+00:00'))
                except ValueError:
                    errors.append(f"第 {i+1} 条记录的timestamp格式错误")

        return len(errors) == 0, errors

    def can_transition_status(self, current_status: str, new_status: str) -> bool:
        if self._current_config is None:
            raise ConfigValidationError("配置未加载", "CONFIG_NOT_LOADED")

        status_flow = self._current_config.get("status_flow", {})
        allowed_next = status_flow.get(current_status, [])
        return new_status in allowed_next

    def is_sample_type_valid(self, sample_type: str) -> bool:
        if self._current_config is None:
            return False
        return sample_type in self._current_config.get("sample_types", [])


config_manager = ConfigManager()
