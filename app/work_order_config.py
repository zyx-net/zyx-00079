import json
import os
from typing import Dict, Any, Optional, List, Tuple
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from .models import WorkOrderRuleVersion, ExceptionWorkOrder


class WorkOrderConfigValidationError(Exception):
    def __init__(self, message: str, error_code: str, details: Optional[Dict[str, Any]] = None):
        self.message = message
        self.error_code = error_code
        self.details = details or {}
        super().__init__(self.message)


class WorkOrderConfigManager:
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
            raise WorkOrderConfigValidationError(
                f"配置文件不存在: {config_path}",
                "WO_CONFIG_FILE_NOT_FOUND",
                {"path": config_path}
            )

        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                config_content = f.read()
        except Exception as e:
            raise WorkOrderConfigValidationError(
                f"读取配置文件失败: {str(e)}",
                "WO_CONFIG_READ_ERROR",
                {"path": config_path}
            )

        try:
            config = json.loads(config_content)
        except json.JSONDecodeError as e:
            raise WorkOrderConfigValidationError(
                f"配置文件JSON格式错误: {str(e)}",
                "WO_INVALID_JSON_FORMAT",
                {"path": config_path, "error_position": e.pos}
            )

        self.validate_config(config)

        version = config.get("version")
        if not version:
            raise WorkOrderConfigValidationError(
                "配置缺少version字段",
                "WO_MISSING_VERSION",
                {"path": config_path}
            )

        existing = db.query(WorkOrderRuleVersion).filter(WorkOrderRuleVersion.version == version).first()
        if existing:
            existing.is_active = True
            db.commit()
            db.refresh(existing)
        else:
            db.query(WorkOrderRuleVersion).update({WorkOrderRuleVersion.is_active: False})
            new_config = WorkOrderRuleVersion(
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
        required_fields = [
            "version", "exception_types", "severity_mapping",
            "severity_levels", "status_flow", "sites",
            "role_site_permissions", "users"
        ]
        for field in required_fields:
            if field not in config:
                raise WorkOrderConfigValidationError(
                    f"配置缺少必填字段: {field}",
                    "WO_MISSING_REQUIRED_FIELD",
                    {"missing_field": field}
                )

        exception_types = config.get("exception_types", {})
        if not isinstance(exception_types, dict) or len(exception_types) == 0:
            raise WorkOrderConfigValidationError(
                "exception_types必须是非空字典",
                "WO_INVALID_EXCEPTION_TYPES",
                {"exception_types": exception_types}
            )

        severity_levels = config.get("severity_levels", [])
        if not isinstance(severity_levels, list) or len(severity_levels) == 0:
            raise WorkOrderConfigValidationError(
                "severity_levels必须是非空列表",
                "WO_INVALID_SEVERITY_LEVELS",
                {"severity_levels": severity_levels}
            )

        severity_mapping = config.get("severity_mapping", {})
        for exc_type in exception_types.keys():
            if exc_type not in severity_mapping:
                raise WorkOrderConfigValidationError(
                    f"异常类型 {exc_type} 缺少严重等级映射配置",
                    "WO_MISSING_SEVERITY_MAPPING",
                    {"exception_type": exc_type}
                )

        status_flow = config.get("status_flow", {})
        if not isinstance(status_flow, dict) or len(status_flow) == 0:
            raise WorkOrderConfigValidationError(
                "status_flow必须是非空字典",
                "WO_INVALID_STATUS_FLOW",
                {"status_flow": status_flow}
            )

        if "OPEN" not in status_flow:
            raise WorkOrderConfigValidationError(
                "status_flow必须包含OPEN初始状态",
                "WO_MISSING_OPEN_STATUS"
            )

        sites = config.get("sites", [])
        if not isinstance(sites, list) or len(sites) == 0:
            raise WorkOrderConfigValidationError(
                "sites必须是非空列表",
                "WO_INVALID_SITES",
                {"sites": sites}
            )

        site_codes = [s.get("code") for s in sites if isinstance(s, dict)]
        if len(site_codes) != len(set(site_codes)):
            raise WorkOrderConfigValidationError(
                "sites中存在重复的站点编码",
                "WO_DUPLICATE_SITE_CODE"
            )

        auto_close_timeout = config.get("auto_close_timeout_hours", 72)
        if not isinstance(auto_close_timeout, (int, float)) or auto_close_timeout <= 0:
            raise WorkOrderConfigValidationError(
                "auto_close_timeout_hours必须是正数",
                "WO_INVALID_AUTO_CLOSE_TIMEOUT",
                {"value": auto_close_timeout}
            )

        revoke_limit = config.get("revoke_close_limit_hours", 24)
        if not isinstance(revoke_limit, (int, float)) or revoke_limit <= 0:
            raise WorkOrderConfigValidationError(
                "revoke_close_limit_hours必须是正数",
                "WO_INVALID_REVOKE_LIMIT",
                {"value": revoke_limit}
            )

    def get_current_config(self) -> Optional[Dict[str, Any]]:
        return self._current_config

    def get_current_version(self) -> Optional[str]:
        return self._current_version

    def get_config_file_path(self) -> Optional[str]:
        return self._config_file_path

    def get_severity(self, exception_type: str, description: str = "") -> str:
        if self._current_config is None:
            raise WorkOrderConfigValidationError("工单配置未加载", "WO_CONFIG_NOT_LOADED")

        severity_mapping = self._current_config.get("severity_mapping", {})
        type_config = severity_mapping.get(exception_type, {})
        rules = type_config.get("rules", [])

        for rule in rules:
            condition = rule.get("condition", "")
            if condition and condition in description:
                return rule.get("severity", type_config.get("default", "MEDIUM"))

        return type_config.get("default", "MEDIUM")

    def can_transition_status(self, current_status: str, new_status: str) -> bool:
        if self._current_config is None:
            raise WorkOrderConfigValidationError("工单配置未加载", "WO_CONFIG_NOT_LOADED")

        status_flow = self._current_config.get("status_flow", {})
        allowed_next = status_flow.get(current_status, [])
        return new_status in allowed_next

    def is_exception_type_valid(self, exception_type: str) -> bool:
        if self._current_config is None:
            return False
        return exception_type in self._current_config.get("exception_types", {})

    def is_site_valid(self, site_code: str) -> bool:
        if self._current_config is None:
            return False
        sites = self._current_config.get("sites", [])
        return any(s.get("code") == site_code for s in sites)

    def get_user_sites(self, username: str) -> List[str]:
        if self._current_config is None:
            raise WorkOrderConfigValidationError("工单配置未加载", "WO_CONFIG_NOT_LOADED")

        users = self._current_config.get("users", {})
        user_config = users.get(username)
        if user_config:
            return user_config.get("sites", [])
        return []

    def get_user_role(self, username: str) -> Optional[str]:
        if self._current_config is None:
            return None

        users = self._current_config.get("users", {})
        user_config = users.get(username)
        if user_config:
            return user_config.get("role")
        return None

    def can_user_access_site(self, username: str, site_code: str) -> Tuple[bool, str]:
        try:
            user_sites = self.get_user_sites(username)
        except WorkOrderConfigValidationError:
            return False, "工单配置未加载"

        if not user_sites:
            return False, f"用户 {username} 没有配置任何站点权限"

        if site_code not in user_sites:
            return False, f"用户 {username} 无权访问站点 {site_code}，可访问站点: {', '.join(user_sites)}"

        return True, ""

    def can_user_operate_work_order(self, username: str, work_order: ExceptionWorkOrder) -> Tuple[bool, str]:
        return self.can_user_access_site(username, work_order.site_code)

    def can_revoke_close(self, work_order: ExceptionWorkOrder) -> Tuple[bool, str]:
        if self._current_config is None:
            raise WorkOrderConfigValidationError("工单配置未加载", "WO_CONFIG_NOT_LOADED")

        if not work_order.is_revoked and work_order.status != "CLOSED":
            return False, "工单未关闭，无法撤销关闭"

        if work_order.is_revoked:
            return False, "工单关闭已被撤销"

        revoke_limit = self._current_config.get("revoke_close_limit_hours", 24)
        if work_order.closed_at:
            time_passed = datetime.utcnow() - work_order.closed_at
            if time_passed > timedelta(hours=revoke_limit):
                return False, f"工单关闭已超过 {revoke_limit} 小时，无法撤销"

        return True, ""

    def should_auto_close(self, work_order: ExceptionWorkOrder) -> bool:
        if self._current_config is None:
            return False

        if work_order.status == "CLOSED":
            return False

        auto_close_timeout = self._current_config.get("auto_close_timeout_hours", 72)
        time_passed = datetime.utcnow() - work_order.created_at
        return time_passed > timedelta(hours=auto_close_timeout)

    def generate_work_order_no(self) -> str:
        if self._current_config is None:
            prefix = "WO"
        else:
            prefix = self._current_config.get("work_order_no_prefix", "WO")

        now = datetime.utcnow()
        timestamp = now.strftime("%Y%m%d%H%M%S")
        millis = int(now.microsecond / 1000)
        return f"{prefix}-{timestamp}{millis:03d}"

    def get_config_for_version(self, db: Session, version: str) -> Optional[Dict[str, Any]]:
        rule_version = db.query(WorkOrderRuleVersion).filter(
            WorkOrderRuleVersion.version == version
        ).first()
        if rule_version and rule_version.config_content:
            try:
                return json.loads(rule_version.config_content)
            except json.JSONDecodeError:
                return None
        return None


work_order_config_manager = WorkOrderConfigManager()
