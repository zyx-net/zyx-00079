from sqlalchemy.orm import Session
from datetime import datetime
from typing import Optional, Dict, Any
from .models import AuditLog, Sample, Box, TransferRecord, ExceptionWorkOrder, WorkOrderProcessRecord
from .config_manager import config_manager
from .work_order_config import work_order_config_manager


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
    def log_transfer_revoke(
        db: Session,
        transfer: TransferRecord,
        custodian: str,
        reason: str
    ) -> AuditLog:
        return AuditLogger.log(
            db=db,
            entity_type="TRANSFER",
            entity_id=transfer.id,
            action="REVOKE_TRANSFER",
            custodian=custodian,
            old_status=transfer.status,
            new_status="REVOKED",
            details={
                "transfer_id": transfer.id,
                "box_id": transfer.box_id,
                "from_custodian": transfer.from_custodian,
                "to_custodian": transfer.to_custodian,
                "from_point": transfer.from_point,
                "to_point": transfer.to_point,
                "rule_version": transfer.rule_version,
                "revoke_reason": reason
            }
        )

    @staticmethod
    def log_re_transfer(
        db: Session,
        transfer: TransferRecord,
        custodian: str,
        prev_transfer_id: int,
        revoked_count: int
    ) -> AuditLog:
        return AuditLogger.log(
            db=db,
            entity_type="TRANSFER",
            entity_id=transfer.id,
            action="RE_TRANSFER",
            custodian=custodian,
            old_status=None,
            new_status=transfer.status,
            details={
                "transfer_id": transfer.id,
                "prev_transfer_id": prev_transfer_id,
                "box_id": transfer.box_id,
                "from_custodian": transfer.from_custodian,
                "to_custodian": transfer.to_custodian,
                "from_point": transfer.from_point,
                "to_point": transfer.to_point,
                "rule_version": transfer.rule_version,
                "revoked_count_before": revoked_count
            }
        )

    @staticmethod
    def log_box_revoke_transfer(
        db: Session,
        box: Box,
        old_status: str,
        new_status: str,
        old_custodian: str,
        new_custodian: str,
        custodian: str,
        revoked_transfer_id: int,
        reason: str
    ) -> AuditLog:
        return AuditLogger.log(
            db=db,
            entity_type="BOX",
            entity_id=box.id,
            action="REVOKE_TRANSFER",
            custodian=custodian,
            old_status=old_status,
            new_status=new_status,
            details={
                "box_code": box.box_code,
                "revoked_transfer_id": revoked_transfer_id,
                "old_custodian": old_custodian,
                "new_custodian": new_custodian,
                "rule_version": box.rule_version,
                "revoke_reason": reason
            }
        )

    @staticmethod
    def log_sample_revoke_transfer(
        db: Session,
        sample: Sample,
        old_status: str,
        new_status: str,
        old_custodian: str,
        new_custodian: str,
        custodian: str,
        revoked_transfer_id: int,
        reason: str
    ) -> AuditLog:
        return AuditLogger.log(
            db=db,
            entity_type="SAMPLE",
            entity_id=sample.id,
            action="REVOKE_TRANSFER",
            custodian=custodian,
            old_status=old_status,
            new_status=new_status,
            details={
                "barcode": sample.barcode,
                "revoked_transfer_id": revoked_transfer_id,
                "old_custodian": old_custodian,
                "new_custodian": new_custodian,
                "rule_version": sample.rule_version,
                "revoke_reason": reason
            }
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

    @staticmethod
    def log_work_order_create(
        db: Session,
        work_order: ExceptionWorkOrder,
        custodian: str,
        details: Optional[Dict[str, Any]] = None
    ) -> AuditLog:
        return AuditLogger.log(
            db=db,
            entity_type="WORK_ORDER",
            entity_id=work_order.id,
            action="CREATE",
            custodian=custodian,
            old_status=None,
            new_status=work_order.status,
            details=details or {
                "work_order_no": work_order.work_order_no,
                "exception_type": work_order.exception_type,
                "severity": work_order.severity,
                "box_code": work_order.box_code,
                "site_code": work_order.site_code
            }
        )

    @staticmethod
    def log_work_order_status_change(
        db: Session,
        work_order: ExceptionWorkOrder,
        old_status: str,
        new_status: str,
        custodian: str,
        action: str = "STATUS_CHANGE",
        details: Optional[Dict[str, Any]] = None
    ) -> AuditLog:
        return AuditLogger.log(
            db=db,
            entity_type="WORK_ORDER",
            entity_id=work_order.id,
            action=action,
            custodian=custodian,
            old_status=old_status,
            new_status=new_status,
            details=details or {"work_order_no": work_order.work_order_no}
        )

    @staticmethod
    def log_work_order_assign(
        db: Session,
        work_order: ExceptionWorkOrder,
        old_assignee: Optional[str],
        new_assignee: str,
        custodian: str
    ) -> AuditLog:
        return AuditLogger.log(
            db=db,
            entity_type="WORK_ORDER",
            entity_id=work_order.id,
            action="ASSIGN",
            custodian=custodian,
            old_status=work_order.status,
            new_status="ASSIGNED",
            details={
                "work_order_no": work_order.work_order_no,
                "old_assignee": old_assignee,
                "new_assignee": new_assignee
            }
        )

    @staticmethod
    def log_work_order_process(
        db: Session,
        work_order: ExceptionWorkOrder,
        process_record: WorkOrderProcessRecord,
        custodian: str
    ) -> AuditLog:
        return AuditLogger.log(
            db=db,
            entity_type="WORK_ORDER",
            entity_id=work_order.id,
            action="PROCESS",
            custodian=custodian,
            old_status=work_order.status,
            new_status="PROCESSING",
            details={
                "work_order_no": work_order.work_order_no,
                "process_record_id": process_record.id,
                "operation": process_record.operation,
                "remark": process_record.remark
            }
        )

    @staticmethod
    def log_work_order_close(
        db: Session,
        work_order: ExceptionWorkOrder,
        custodian: str,
        close_reason: str
    ) -> AuditLog:
        return AuditLogger.log(
            db=db,
            entity_type="WORK_ORDER",
            entity_id=work_order.id,
            action="CLOSE",
            custodian=custodian,
            old_status=work_order.status,
            new_status="CLOSED",
            details={
                "work_order_no": work_order.work_order_no,
                "close_reason": close_reason
            }
        )

    @staticmethod
    def log_work_order_revoke_close(
        db: Session,
        work_order: ExceptionWorkOrder,
        custodian: str,
        revoke_reason: str
    ) -> AuditLog:
        return AuditLogger.log(
            db=db,
            entity_type="WORK_ORDER",
            entity_id=work_order.id,
            action="REVOKE_CLOSE",
            custodian=custodian,
            old_status="CLOSED",
            new_status=work_order.status,
            details={
                "work_order_no": work_order.work_order_no,
                "revoke_reason": revoke_reason
            }
        )


audit_logger = AuditLogger()
