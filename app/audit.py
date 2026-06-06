from sqlalchemy.orm import Session
from datetime import datetime
from typing import Optional, Dict, Any
from .models import AuditLog, Sample, Box, TransferRecord
from .config_manager import config_manager


class AuditLogger:
    @staticmethod
    def log(
        db: Session,
        entity_type: str,
        entity_id: int,
        action: str,
        custodian: str,
        old_status: Optional[str] = None,
        new_status: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None
    ) -> AuditLog:
        rule_version = config_manager.get_current_version() or "UNKNOWN"

        import json
        details_str = json.dumps(details, ensure_ascii=False) if details else None

        audit_log = AuditLog(
            entity_type=entity_type,
            entity_id=entity_id,
            action=action,
            old_status=old_status,
            new_status=new_status,
            custodian=custodian,
            rule_version=rule_version,
            details=details_str
        )
        db.add(audit_log)
        db.flush()
        return audit_log

    @staticmethod
    def log_sample_create(
        db: Session,
        sample: Sample,
        custodian: str,
        details: Optional[Dict[str, Any]] = None
    ) -> AuditLog:
        return AuditLogger.log(
            db=db,
            entity_type="SAMPLE",
            entity_id=sample.id,
            action="CREATE",
            custodian=custodian,
            old_status=None,
            new_status=sample.status,
            details=details or {"barcode": sample.barcode, "sample_type": sample.sample_type}
        )

    @staticmethod
    def log_sample_status_change(
        db: Session,
        sample: Sample,
        old_status: str,
        new_status: str,
        custodian: str,
        action: str = "STATUS_CHANGE",
        details: Optional[Dict[str, Any]] = None
    ) -> AuditLog:
        return AuditLogger.log(
            db=db,
            entity_type="SAMPLE",
            entity_id=sample.id,
            action=action,
            custodian=custodian,
            old_status=old_status,
            new_status=new_status,
            details=details or {"barcode": sample.barcode}
        )

    @staticmethod
    def log_box_create(
        db: Session,
        box: Box,
        custodian: str,
        details: Optional[Dict[str, Any]] = None
    ) -> AuditLog:
        return AuditLogger.log(
            db=db,
            entity_type="BOX",
            entity_id=box.id,
            action="CREATE",
            custodian=custodian,
            old_status=None,
            new_status=box.status,
            details=details or {"box_code": box.box_code, "destination": box.destination}
        )

    @staticmethod
    def log_box_status_change(
        db: Session,
        box: Box,
        old_status: str,
        new_status: str,
        custodian: str,
        action: str = "STATUS_CHANGE",
        details: Optional[Dict[str, Any]] = None
    ) -> AuditLog:
        return AuditLogger.log(
            db=db,
            entity_type="BOX",
            entity_id=box.id,
            action=action,
            custodian=custodian,
            old_status=old_status,
            new_status=new_status,
            details=details or {"box_code": box.box_code}
        )

    @staticmethod
    def log_transfer(
        db: Session,
        transfer: TransferRecord,
        custodian: str,
        details: Optional[Dict[str, Any]] = None
    ) -> AuditLog:
        return AuditLogger.log(
            db=db,
            entity_type="TRANSFER",
            entity_id=transfer.id,
            action="TRANSFER",
            custodian=custodian,
            old_status=None,
            new_status=transfer.status,
            details=details or {
                "box_id": transfer.box_id,
                "sample_id": transfer.sample_id,
                "from_point": transfer.from_point,
                "to_point": transfer.to_point,
                "from_custodian": transfer.from_custodian,
                "to_custodian": transfer.to_custodian
            }
        )

    @staticmethod
    def log_isolation(
        db: Session,
        sample: Sample,
        custodian: str,
        reason: str
    ) -> AuditLog:
        return AuditLogger.log(
            db=db,
            entity_type="SAMPLE",
            entity_id=sample.id,
            action="ISOLATE",
            custodian=custodian,
            old_status=sample.status,
            new_status="ISOLATED",
            details={"barcode": sample.barcode, "isolation_reason": reason}
        )

    @staticmethod
    def log_archive(
        db: Session,
        sample: Sample,
        custodian: str,
        test_result: str
    ) -> AuditLog:
        return AuditLogger.log(
            db=db,
            entity_type="SAMPLE",
            entity_id=sample.id,
            action="ARCHIVE",
            custodian=custodian,
            old_status=sample.status,
            new_status="ARCHIVED",
            details={"barcode": sample.barcode, "test_result": test_result}
        )

    @staticmethod
    def get_audit_logs(
        db: Session,
        entity_type: Optional[str] = None,
        entity_id: Optional[int] = None,
        action: Optional[str] = None,
        custodian: Optional[str] = None,
        limit: int = 100,
        offset: int = 0
    ):
        query = db.query(AuditLog)
        if entity_type:
            query = query.filter(AuditLog.entity_type == entity_type)
        if entity_id:
            query = query.filter(AuditLog.entity_id == entity_id)
        if action:
            query = query.filter(AuditLog.action == action)
        if custodian:
            query = query.filter(AuditLog.custodian == custodian)
        return query.order_by(AuditLog.created_at.desc()).offset(offset).limit(limit).all()


audit_logger = AuditLogger()
