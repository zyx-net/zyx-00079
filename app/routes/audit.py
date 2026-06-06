from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from typing import List, Optional
from ..database import get_db
from ..schemas import AuditLogResponse
from ..audit import audit_logger

router = APIRouter(prefix="/api/audit", tags=["audit"])


@router.get(
    "",
    response_model=List[AuditLogResponse],
    summary="查询审计日志"
)
def get_audit_logs(
    entity_type: Optional[str] = None,
    entity_id: Optional[int] = None,
    action: Optional[str] = None,
    custodian: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
    db: Session = Depends(get_db)
):
    """
    查询审计日志，支持多维度筛选。

    - **entity_type**: 实体类型（SAMPLE/BOX/TRANSFER）
    - **entity_id**: 实体ID
    - **action**: 操作类型（CREATE/STATUS_CHANGE/TRANSFER/ISOLATE/ARCHIVE等）
    - **custodian**: 保管人
    - **limit**: 返回条数，默认100
    - **offset**: 偏移量，默认0
    """
    return audit_logger.get_audit_logs(
        db=db,
        entity_type=entity_type,
        entity_id=entity_id,
        action=action,
        custodian=custodian,
        limit=limit,
        offset=offset
    )


@router.get(
    "/sample/{barcode}",
    response_model=List[AuditLogResponse],
    summary="查询样本的审计日志"
)
def get_sample_audit_logs(
    barcode: str,
    limit: int = 100,
    db: Session = Depends(get_db)
):
    """
    根据样本条码查询其完整审计追踪。
    """
    from ..models import Sample
    sample = db.query(Sample).filter(Sample.barcode == barcode).first()
    if not sample:
        return []
    return audit_logger.get_audit_logs(
        db=db,
        entity_type="SAMPLE",
        entity_id=sample.id,
        limit=limit
    )


@router.get(
    "/box/{box_code}",
    response_model=List[AuditLogResponse],
    summary="查询转运箱的审计日志"
)
def get_box_audit_logs(
    box_code: str,
    limit: int = 100,
    db: Session = Depends(get_db)
):
    """
    根据箱号查询转运箱的完整审计追踪。
    """
    from ..models import Box
    box = db.query(Box).filter(Box.box_code == box_code).first()
    if not box:
        return []
    return audit_logger.get_audit_logs(
        db=db,
        entity_type="BOX",
        entity_id=box.id,
        limit=limit
    )
