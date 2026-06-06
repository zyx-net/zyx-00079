import json
import os
from typing import Dict, Any, Optional, List, Tuple
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from .models import ReservationRuleVersion, Reservation


class ReservationConfigValidationError(Exception):
    def __init__(self, message: str, error_code: str, details: Optional[Dict[str, Any]] = None):
        self.message = message
        self.error_code = error_code
        self.details = details or {}
        super().__init__(self.message)


class ReservationConfigManager:
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
            raise ReservationConfigValidationError(
                f"配置文件不存在: {config_path}",
                "RES_CONFIG_FILE_NOT_FOUND",
                {"path": config_path}
            )

        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                config_content = f.read()
        except Exception as e:
            raise ReservationConfigValidationError(
                f"读取配置文件失败: {str(e)}",
                "RES_CONFIG_READ_ERROR",
                {"path": config_path}
            )

        try:
            config = json.loads(config_content)
        except json.JSONDecodeError as e:
            raise ReservationConfigValidationError(
                f"配置文件JSON格式错误: {str(e)}",
                "RES_INVALID_JSON_FORMAT",
                {"path": config_path, "error_position": e.pos}
            )

        self.validate_config(config)

        version = config.get("version")
        if not version:
            raise ReservationConfigValidationError(
                "配置缺少version字段",
                "RES_MISSING_VERSION",
                {"path": config_path}
            )

        existing = db.query(ReservationRuleVersion).filter(ReservationRuleVersion.version == version).first()
        if existing:
            existing.is_active = True
            db.commit()
            db.refresh(existing)
        else:
            db.query(ReservationRuleVersion).update({ReservationRuleVersion.is_active: False})
            new_config = ReservationRuleVersion(
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
            "version", "sites", "customers", "temperature_zones",
            "vehicle_capacities", "reservation_rules", "status_flow",
            "role_site_permissions", "users"
        ]
        for field in required_fields:
            if field not in config:
                raise ReservationConfigValidationError(
                    f"配置缺少必填字段: {field}",
                    "RES_MISSING_REQUIRED_FIELD",
                    {"missing_field": field}
                )

        sites = config.get("sites", [])
        if not isinstance(sites, list) or len(sites) == 0:
            raise ReservationConfigValidationError(
                "sites必须是非空列表",
                "RES_INVALID_SITES",
                {"sites": sites}
            )

        site_codes = [s.get("code") for s in sites if isinstance(s, dict)]
        if len(site_codes) != len(set(site_codes)):
            raise ReservationConfigValidationError(
                "sites中存在重复的站点编码",
                "RES_DUPLICATE_SITE_CODE"
            )

        customers = config.get("customers", [])
        if not isinstance(customers, list) or len(customers) == 0:
            raise ReservationConfigValidationError(
                "customers必须是非空列表",
                "RES_INVALID_CUSTOMERS",
                {"customers": customers}
            )

        temp_zones = config.get("temperature_zones", [])
        if not isinstance(temp_zones, list) or len(temp_zones) == 0:
            raise ReservationConfigValidationError(
                "temperature_zones必须是非空列表",
                "RES_INVALID_TEMPERATURE_ZONES",
                {"temperature_zones": temp_zones}
            )

        temp_zone_codes = [z.get("code") for z in temp_zones if isinstance(z, dict)]
        if len(temp_zone_codes) != len(set(temp_zone_codes)):
            raise ReservationConfigValidationError(
                "temperature_zones中存在重复的温区编码",
                "RES_DUPLICATE_TEMP_ZONE"
            )

        vehicle_capacities = config.get("vehicle_capacities", {})
        if not isinstance(vehicle_capacities, dict) or "default" not in vehicle_capacities:
            raise ReservationConfigValidationError(
                "vehicle_capacities必须是包含default的字典",
                "RES_INVALID_VEHICLE_CAPACITIES",
                {"vehicle_capacities": vehicle_capacities}
            )

        for key, value in vehicle_capacities.items():
            if not isinstance(value, int) or value <= 0:
                raise ReservationConfigValidationError(
                    f"车辆容量 {key} 必须是正整数",
                    "RES_INVALID_CAPACITY_VALUE",
                    {"vehicle_type": key, "value": value}
                )

        reservation_rules = config.get("reservation_rules", {})
        if not isinstance(reservation_rules, dict):
            raise ReservationConfigValidationError(
                "reservation_rules必须是字典",
                "RES_INVALID_RESERVATION_RULES",
                {"reservation_rules": reservation_rules}
            )

        advance_hours = reservation_rules.get("advance_reservation_hours")
        if advance_hours is None or not isinstance(advance_hours, (int, float)) or advance_hours < 0:
            raise ReservationConfigValidationError(
                "advance_reservation_hours必须是非负数字",
                "RES_INVALID_ADVANCE_HOURS",
                {"value": advance_hours}
            )

        cancel_hours = reservation_rules.get("cancellation_limit_hours")
        if cancel_hours is None or not isinstance(cancel_hours, (int, float)) or cancel_hours < 0:
            raise ReservationConfigValidationError(
                "cancellation_limit_hours必须是非负数字",
                "RES_INVALID_CANCEL_HOURS",
                {"value": cancel_hours}
            )

        allow_mixed = reservation_rules.get("allow_mixed_temperature_zones")
        if allow_mixed is None or not isinstance(allow_mixed, bool):
            raise ReservationConfigValidationError(
                "allow_mixed_temperature_zones必须是布尔值",
                "RES_INVALID_ALLOW_MIXED",
                {"value": allow_mixed}
            )

        status_flow = config.get("status_flow", {})
        if not isinstance(status_flow, dict):
            raise ReservationConfigValidationError(
                "status_flow必须是字典",
                "RES_INVALID_STATUS_FLOW",
                {"status_flow": status_flow}
            )

        if "reservation" not in status_flow or "loading_plan" not in status_flow:
            raise ReservationConfigValidationError(
                "status_flow必须包含reservation和loading_plan子项",
                "RES_MISSING_STATUS_FLOW_SECTIONS"
            )

        res_status_flow = status_flow.get("reservation", {})
        if "DRAFT" not in res_status_flow:
            raise ReservationConfigValidationError(
                "reservation状态流转必须包含DRAFT初始状态",
                "RES_MISSING_DRAFT_STATUS"
            )

        role_site_permissions = config.get("role_site_permissions", {})
        if not isinstance(role_site_permissions, dict) or len(role_site_permissions) == 0:
            raise ReservationConfigValidationError(
                "role_site_permissions必须是非空字典",
                "RES_INVALID_ROLE_PERMISSIONS",
                {"role_site_permissions": role_site_permissions}
            )

        users = config.get("users", {})
        if not isinstance(users, dict) or len(users) == 0:
            raise ReservationConfigValidationError(
                "users必须是非空字典",
                "RES_INVALID_USERS",
                {"users": users}
            )

        for username, user_config in users.items():
            if not isinstance(user_config, dict):
                raise ReservationConfigValidationError(
                    f"用户 {username} 配置必须是字典",
                    "RES_INVALID_USER_CONFIG",
                    {"username": username}
                )
            if "role" not in user_config or "sites" not in user_config:
                raise ReservationConfigValidationError(
                    f"用户 {username} 配置缺少role或sites字段",
                    "RES_MISSING_USER_FIELDS",
                    {"username": username}
                )

    def get_current_config(self) -> Optional[Dict[str, Any]]:
        return self._current_config

    def get_current_version(self) -> Optional[str]:
        return self._current_version

    def get_config_file_path(self) -> Optional[str]:
        return self._config_file_path

    def get_rule_snapshot(self) -> str:
        if self._current_config is None:
            raise ReservationConfigValidationError("预约配置未加载", "RES_CONFIG_NOT_LOADED")
        return json.dumps(self._current_config, ensure_ascii=False)

    def can_transition_reservation_status(self, current_status: str, new_status: str) -> bool:
        if self._current_config is None:
            raise ReservationConfigValidationError("预约配置未加载", "RES_CONFIG_NOT_LOADED")

        status_flow = self._current_config.get("status_flow", {})
        res_flow = status_flow.get("reservation", {})
        allowed_next = res_flow.get(current_status, [])
        return new_status in allowed_next

    def can_transition_loading_plan_status(self, current_status: str, new_status: str) -> bool:
        if self._current_config is None:
            raise ReservationConfigValidationError("预约配置未加载", "RES_CONFIG_NOT_LOADED")

        status_flow = self._current_config.get("status_flow", {})
        lp_flow = status_flow.get("loading_plan", {})
        allowed_next = lp_flow.get(current_status, [])
        return new_status in allowed_next

    def is_site_valid(self, site_code: str) -> bool:
        if self._current_config is None:
            return False
        sites = self._current_config.get("sites", [])
        return any(s.get("code") == site_code for s in sites)

    def is_customer_valid(self, customer_code: str) -> bool:
        if self._current_config is None:
            return False
        customers = self._current_config.get("customers", [])
        return any(c.get("code") == customer_code for c in customers)

    def is_temperature_zone_valid(self, temp_zone: str) -> bool:
        if self._current_config is None:
            return False
        zones = self._current_config.get("temperature_zones", [])
        return any(z.get("code") == temp_zone for z in zones)

    def get_vehicle_capacity(self, vehicle_type: Optional[str] = None) -> int:
        if self._current_config is None:
            raise ReservationConfigValidationError("预约配置未加载", "RES_CONFIG_NOT_LOADED")

        capacities = self._current_config.get("vehicle_capacities", {})
        if vehicle_type and vehicle_type in capacities:
            return capacities[vehicle_type]
        return capacities.get("default", 30)

    def get_advance_reservation_hours(self) -> int:
        if self._current_config is None:
            raise ReservationConfigValidationError("预约配置未加载", "RES_CONFIG_NOT_LOADED")

        rules = self._current_config.get("reservation_rules", {})
        return int(rules.get("advance_reservation_hours", 4))

    def get_cancellation_limit_hours(self) -> int:
        if self._current_config is None:
            raise ReservationConfigValidationError("预约配置未加载", "RES_CONFIG_NOT_LOADED")

        rules = self._current_config.get("reservation_rules", {})
        return int(rules.get("cancellation_limit_hours", 2))

    def allow_mixed_temperature_zones(self) -> bool:
        if self._current_config is None:
            raise ReservationConfigValidationError("预约配置未加载", "RES_CONFIG_NOT_LOADED")

        rules = self._current_config.get("reservation_rules", {})
        return rules.get("allow_mixed_temperature_zones", False)

    def get_user_sites(self, username: str) -> List[str]:
        if self._current_config is None:
            raise ReservationConfigValidationError("预约配置未加载", "RES_CONFIG_NOT_LOADED")

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
        except ReservationConfigValidationError:
            return False, "预约配置未加载"

        if not user_sites:
            return False, f"用户 {username} 没有配置任何站点权限"

        if site_code not in user_sites:
            return False, f"用户 {username} 无权访问站点 {site_code}，可访问站点: {', '.join(user_sites)}"

        return True, ""

    def can_user_operate_reservation(self, username: str, reservation: Reservation) -> Tuple[bool, str]:
        return self.can_user_access_site(username, reservation.site_code)

    def validate_reservation_time(self, scheduled_date: datetime) -> Tuple[bool, str]:
        if self._current_config is None:
            raise ReservationConfigValidationError("预约配置未加载", "RES_CONFIG_NOT_LOADED")

        advance_hours = self.get_advance_reservation_hours()
        now = datetime.utcnow()
        min_reservation_time = now + timedelta(hours=advance_hours)

        if scheduled_date < min_reservation_time:
            return False, f"预约时间必须在当前时间 {advance_hours} 小时之后，最早可预约时间: {min_reservation_time.isoformat()}"

        return True, ""

    def can_cancel_reservation(self, scheduled_date: datetime) -> Tuple[bool, str]:
        if self._current_config is None:
            raise ReservationConfigValidationError("预约配置未加载", "RES_CONFIG_NOT_LOADED")

        cancel_limit_hours = self.get_cancellation_limit_hours()
        now = datetime.utcnow()
        cutoff_time = scheduled_date - timedelta(hours=cancel_limit_hours)

        if now > cutoff_time:
            return False, f"取消预约必须在预约时间 {cancel_limit_hours} 小时之前，取消截止时间已过: {cutoff_time.isoformat()}"

        return True, ""

    def generate_reservation_no(self) -> str:
        if self._current_config is None:
            prefix = "RES"
        else:
            prefix = self._current_config.get("reservation_no_prefix", "RES")

        now = datetime.utcnow()
        timestamp = now.strftime("%Y%m%d%H%M%S")
        millis = int(now.microsecond / 1000)
        return f"{prefix}_{timestamp}{millis:03d}"

    def generate_loading_plan_no(self) -> str:
        if self._current_config is None:
            prefix = "LP"
        else:
            prefix = self._current_config.get("loading_plan_no_prefix", "LP")

        now = datetime.utcnow()
        timestamp = now.strftime("%Y%m%d%H%M%S")
        millis = int(now.microsecond / 1000)
        return f"{prefix}_{timestamp}{millis:03d}"

    def get_config_for_version(self, db: Session, version: str) -> Optional[Dict[str, Any]]:
        rule_version = db.query(ReservationRuleVersion).filter(
            ReservationRuleVersion.version == version
        ).first()
        if rule_version and rule_version.config_content:
            try:
                return json.loads(rule_version.config_content)
            except json.JSONDecodeError:
                return None
        return None


reservation_config_manager = ReservationConfigManager()
