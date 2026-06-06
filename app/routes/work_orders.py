from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import datetime, timezone
import json
import os
import csv

from ..database import get_db
from ..models import Box, TransferRecord, ExceptionWorkOrder, WorkOrderProcessRecord, WorkOrderRuleVersion
from ..schemas import (
    ErrorResponse,
    WorkOrderCreate,
    WorkOrderResponse,
    WorkOrderAssignRequest,
    WorkOrderProcessRequest,
    WorkOrderCloseRequest,
    WorkOrderRevokeCloseRequest,
    WorkOrderBatchImportRequest,
    WorkOrderBatchImportResponse,
    WorkOrderBatchImportError,
    WorkOrderExportResponse,
    ConfigVersionResponse
)
from ..work_order_config import (
    work_order_config_manager,
    WorkOrderConfigValidationError
)
from ..audit import audit_logger


router = APIRouter(prefix="/api/work-orders", tags=["work-orders"])

EXPORTS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "exports")


def _check_wo_config_loaded():
    rule_version = work_order_config_manager.get_current_version()
    if not rule_version:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": "工单配置未加载，请先加载工单规则配置",
                "code": "WO_CONFIG_NOT_LOADED"
            }
        )
    return rule_version


def _check_user_site_permission(username: str, site_code: str):
    can_access, error_msg = work_order_config_manager.can_user_access_site(username, site_code)
    if not can_access:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": error_msg,
                "code": "WO_PERMISSION_DENIED",
                "details": {
                    "username": username,
                    "site_code": site_code
                }
            }
        )


def _check_work_order_permission(username: str, work_order: ExceptionWorkOrder):
    can_operate, error_msg = work_order_config_manager.can_user_operate_work_order(username, work_order)
    if not can_operate:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": error_msg,
                "code": "WO_PERMISSION_DENIED",
                "details": {
                    "username": username,
                    "work_order_no": work_order.work_order_no,
                    "site_code": work_order.site_code
                }
            }
        )


@router.post(
    "/config/load",
    response_model=ConfigVersionResponse,
    responses={
        400: {"model": ErrorResponse, "description": "配置校验失败"},
        404: {"model": ErrorResponse, "description": "配置文件不存在"},
        500: {"model": ErrorResponse, "description": "服务器错误"}
    },
    summary="加载工单规则配置"
)
def load_work_order_config(config_path: str, db: Session = Depends(get_db)):
    """
    加载并验证工单规则配置文件。

    - **config_path**: 配置文件路径
    """
    try:
        config, version = work_order_config_manager.load_config(config_path, db)
        active_config = db.query(WorkOrderRuleVersion).filter(WorkOrderRuleVersion.is_active == True).first()
        return active_config
    except WorkOrderConfigValidationError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": e.message,
                "code": e.error_code,
                "details": e.details
            }
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": f"加载工单配置失败: {str(e)}",
                "code": "WO_LOAD_CONFIG_ERROR"
            }
        )


@router.get(
    "/config/versions",
    response_model=List[ConfigVersionResponse],
    summary="查询工单配置版本列表"
)
def get_work_order_config_versions(db: Session = Depends(get_db)):
    return db.query(WorkOrderRuleVersion).order_by(WorkOrderRuleVersion.loaded_at.desc()).all()


@router.get(
    "/config/current",
    response_model=ConfigVersionResponse,
    responses={404: {"model": ErrorResponse, "description": "无活动配置"}},
    summary="获取当前活动工单配置"
)
def get_current_work_order_config(db: Session = Depends(get_db)):
    active_config = db.query(WorkOrderRuleVersion).filter(WorkOrderRuleVersion.is_active == True).first()
    if not active_config:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "没有活动的工单配置",
                "code": "WO_NO_ACTIVE_CONFIG"
            }
        )
    return active_config


@router.get(
    "/config/rules",
    summary="查看当前工单配置规则详情"
)
def get_current_work_order_rules():
    config = work_order_config_manager.get_current_config()
    if not config:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "工单配置未加载",
                "code": "WO_CONFIG_NOT_LOADED"
            }
        )
    return config


@router.post(
    "",
    response_model=WorkOrderResponse,
    responses={
        400: {"model": ErrorResponse, "description": "请求参数错误"},
        403: {"model": ErrorResponse, "description": "权限不足"},
        404: {"model": ErrorResponse, "description": "箱号或交接记录不存在"},
        409: {"model": ErrorResponse, "description": "重复工单或状态冲突"},
        500: {"model": ErrorResponse, "description": "服务器错误"}
    },
    summary="创建异常工单"
)
def create_work_order(work_order_data: WorkOrderCreate, db: Session = Depends(get_db)):
    """
    创建异常工单。

    - **exception_type**: 异常类型：DAMAGED（破损）、TEMPERATURE（温控超限）、SIGNATURE_DISPUTE（签收争议）
    - **box_code**: 关联箱号
    - **transfer_record_id**: 关联交接记录ID（可选）
    - **site_code**: 站点编码
    - **reported_by**: 上报人
    - **description**: 异常描述
    - **reported_at**: 上报时间

    错误码：
    - `WO_CONFIG_NOT_LOADED`: 工单配置未加载
    - `WO_PERMISSION_DENIED`: 权限不足
    - `WO_INVALID_EXCEPTION_TYPE`: 无效的异常类型
    - `WO_INVALID_SITE`: 无效的站点编码
    - `BOX_NOT_FOUND`: 箱号不存在
    - `WO_TRANSFER_RECORD_NOT_FOUND`: 交接记录不存在
    - `WO_DUPLICATE_WORK_ORDER`: 重复工单
    """
    rule_version = _check_wo_config_loaded()

    if not work_order_config_manager.is_exception_type_valid(work_order_data.exception_type):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": f"无效的异常类型: {work_order_data.exception_type}",
                "code": "WO_INVALID_EXCEPTION_TYPE",
                "details": {"exception_type": work_order_data.exception_type}
            }
        )

    if not work_order_config_manager.is_site_valid(work_order_data.site_code):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": f"无效的站点编码: {work_order_data.site_code}",
                "code": "WO_INVALID_SITE",
                "details": {"site_code": work_order_data.site_code}
            }
        )

    _check_user_site_permission(work_order_data.reported_by, work_order_data.site_code)

    box = db.query(Box).filter(Box.box_code == work_order_data.box_code).first()
    if not box:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": f"箱号 {work_order_data.box_code} 不存在",
                "code": "BOX_NOT_FOUND",
                "details": {"box_code": work_order_data.box_code}
            }
        )

    transfer_record = None
    if work_order_data.transfer_record_id:
        transfer_record = db.query(TransferRecord).filter(
            TransferRecord.id == work_order_data.transfer_record_id
        ).first()
        if not transfer_record:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "error": f"交接记录 {work_order_data.transfer_record_id} 不存在",
                    "code": "WO_TRANSFER_RECORD_NOT_FOUND",
                    "details": {"transfer_record_id": work_order_data.transfer_record_id}
                }
            )
        if transfer_record.box_id != box.id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail={
                        "error": "交接记录与箱号不匹配",
                        "code": "WO_TRANSFER_BOX_MISMATCH",
                        "details": {
                            "transfer_record_id": work_order_data.transfer_record_id,
                            "box_code": work_order_data.box_code
                        }
                    }
                )

    existing_wo = db.query(ExceptionWorkOrder).filter(
        ExceptionWorkOrder.box_code == work_order_data.box_code,
        ExceptionWorkOrder.exception_type == work_order_data.exception_type,
        ExceptionWorkOrder.status != "CLOSED",
        ExceptionWorkOrder.is_revoked == False
    ).first()
    if existing_wo:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": f"箱号 {work_order_data.box_code} 已有未关闭的同类型异常工单",
                "code": "WO_DUPLICATE_WORK_ORDER",
                "details": {
                    "box_code": work_order_data.box_code,
                    "existing_work_order_no": existing_wo.work_order_no,
                    "exception_type": work_order_data.exception_type
                }
            }
        )

    severity = work_order_config_manager.get_severity(
        work_order_data.exception_type,
        work_order_data.description
    )

    work_order_no = work_order_config_manager.generate_work_order_no()
    reported_at = work_order_data.reported_at or datetime.now(timezone.utc)

    work_order = ExceptionWorkOrder(
        work_order_no=work_order_no,
        exception_type=work_order_data.exception_type,
        severity=severity,
        box_code=work_order_data.box_code,
        box_id=box.id,
        transfer_record_id=transfer_record.id if transfer_record else None,
        site_code=work_order_data.site_code,
        reported_by=work_order_data.reported_by,
        reported_at=reported_at,
        description=work_order_data.description,
        status="OPEN",
        rule_version=rule_version
    )
    db.add(work_order)
    db.flush()

    audit_logger.log_work_order_create(db, work_order, work_order_data.reported_by)

    db.commit()
    db.refresh(work_order)

    return work_order


@router.get(
    "",
    response_model=List[WorkOrderResponse],
    summary="查询工单列表（带筛选）"
)
def get_work_orders(
    status: Optional[str] = None,
    exception_type: Optional[str] = None,
    severity: Optional[str] = None,
    box_code: Optional[str] = None,
    site_code: Optional[str] = None,
    reported_by: Optional[str] = None,
    assignee: Optional[str] = None,
    is_revoked: Optional[bool] = None,
    skip: int = 0,
    limit: int = 100,
    operator: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """
    查询工单列表，支持多条件筛选。

    - **status**: 工单状态筛选
    - **exception_type**: 异常类型筛选
    - **severity**: 严重等级筛选
    - **box_code**: 箱号筛选
    - **site_code**: 站点筛选
    - **reported_by**: 上报人筛选
    - **assignee**: 处理人筛选
    - **is_revoked**: 是否已撤销关闭筛选
    - **operator**: 操作人（用于权限过滤）
    """
    _check_wo_config_loaded()

    query = db.query(ExceptionWorkOrder)

    if operator:
        user_sites = work_order_config_manager.get_user_sites(operator)
        if user_sites:
            query = query.filter(ExceptionWorkOrder.site_code.in_(user_sites))

    if status:
        query = query.filter(ExceptionWorkOrder.status == status)
    if exception_type:
        query = query.filter(ExceptionWorkOrder.exception_type == exception_type)
    if severity:
        query = query.filter(ExceptionWorkOrder.severity == severity)
    if box_code:
        query = query.filter(ExceptionWorkOrder.box_code.ilike(f"%{box_code}%"))
    if site_code:
        query = query.filter(ExceptionWorkOrder.site_code == site_code)
    if reported_by:
        query = query.filter(ExceptionWorkOrder.reported_by == reported_by)
    if assignee:
        query = query.filter(ExceptionWorkOrder.assignee == assignee)
    if is_revoked is not None:
        query = query.filter(ExceptionWorkOrder.is_revoked == is_revoked)

    return query.order_by(ExceptionWorkOrder.created_at.desc()).offset(skip).limit(limit).all()


@router.get(
    "/{work_order_no}",
    response_model=WorkOrderResponse,
    responses={
        403: {"model": ErrorResponse, "description": "权限不足"},
        404: {"model": ErrorResponse, "description": "工单不存在"}
    },
    summary="查询工单详情"
)
def get_work_order(work_order_no: str, operator: Optional[str] = None, db: Session = Depends(get_db)):
    work_order = db.query(ExceptionWorkOrder).filter(
        ExceptionWorkOrder.work_order_no == work_order_no
    ).first()
    if not work_order:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": f"工单 {work_order_no} 不存在",
                "code": "WO_NOT_FOUND"
            }
        )

    if operator:
        _check_work_order_permission(operator, work_order)

    return work_order


@router.post(
    "/assign",
    response_model=WorkOrderResponse,
    responses={
        400: {"model": ErrorResponse, "description": "请求错误或状态冲突"},
        403: {"model": ErrorResponse, "description": "权限不足"},
        404: {"model": ErrorResponse, "description": "工单不存在"},
        409: {"model": ErrorResponse, "description": "状态冲突"}
    },
    summary="认领/分配工单"
)
def assign_work_order(request: WorkOrderAssignRequest, db: Session = Depends(get_db)):
    """
    分配工单给处理人。

    - **work_order_no**: 工单号
    - **assignee**: 处理人
    - **operator**: 操作人
    """
    _check_wo_config_loaded()

    work_order = db.query(ExceptionWorkOrder).filter(
        ExceptionWorkOrder.work_order_no == request.work_order_no
    ).with_for_update().first()
    if not work_order:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": f"工单 {request.work_order_no} 不存在",
                "code": "WO_NOT_FOUND"
            }
        )

    _check_work_order_permission(request.operator, work_order)

    if work_order.status == "CLOSED" and not work_order.is_revoked:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "工单已关闭，无法分配",
                "code": "WO_ALREADY_CLOSED"
            }
        )

    if not work_order_config_manager.can_transition_status(work_order.status, "ASSIGNED"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": f"工单状态 {work_order.status} 无法转为 ASSIGNED",
                "code": "WO_INVALID_STATUS_TRANSITION"
            }
        )

    _check_user_site_permission(request.assignee, work_order.site_code)

    old_assignee = work_order.assignee
    old_status = work_order.status

    work_order.assignee = request.assignee
    work_order.assigned_at = datetime.now(timezone.utc)
    work_order.status = "ASSIGNED"

    audit_logger.log_work_order_assign(
        db, work_order, old_assignee, request.assignee, request.operator
    )

    db.commit()
    db.refresh(work_order)

    return work_order


@router.post(
    "/process",
    response_model=WorkOrderResponse,
    responses={
        400: {"model": ErrorResponse, "description": "请求错误或状态冲突"},
        403: {"model": ErrorResponse, "description": "权限不足"},
        404: {"model": ErrorResponse, "description": "工单不存在"},
        409: {"model": ErrorResponse, "description": "状态冲突"}
    },
    summary="补充处理记录"
)
def process_work_order(request: WorkOrderProcessRequest, db: Session = Depends(get_db)):
    """
    添加工单处理记录。

    - **work_order_no**: 工单号
    - **operation**: 操作类型
    - **remark**: 处理备注
    - **operator**: 操作人
    """
    _check_wo_config_loaded()

    work_order = db.query(ExceptionWorkOrder).filter(
        ExceptionWorkOrder.work_order_no == request.work_order_no
    ).with_for_update().first()
    if not work_order:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": f"工单 {request.work_order_no} 不存在",
                "code": "WO_NOT_FOUND"
            }
        )

    _check_work_order_permission(request.operator, work_order)

    if work_order.status == "CLOSED" and not work_order.is_revoked:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "工单已关闭，无法添加处理记录",
                "code": "WO_ALREADY_CLOSED"
            }
        )

    process_record = WorkOrderProcessRecord(
        work_order_id=work_order.id,
        operator=request.operator,
        operation=request.operation,
        remark=request.remark
    )
    db.add(process_record)
    db.flush()

    old_status = work_order.status
    work_order.status = "PROCESSING"

    audit_logger.log_work_order_process(
        db, work_order, process_record, request.operator
    )

    db.commit()
    db.refresh(work_order)

    return work_order


@router.post(
    "/close",
    response_model=WorkOrderResponse,
    responses={
        400: {"model": ErrorResponse, "description": "请求错误或状态冲突"},
        403: {"model": ErrorResponse, "description": "权限不足"},
        404: {"model": ErrorResponse, "description": "工单不存在"},
        409: {"model": ErrorResponse, "description": "状态冲突"}
    },
    summary="关闭工单"
)
def close_work_order(request: WorkOrderCloseRequest, db: Session = Depends(get_db)):
    """
    关闭工单。

    - **work_order_no**: 工单号
    - **close_reason**: 关闭原因
    - **operator**: 操作人
    """
    _check_wo_config_loaded()

    work_order = db.query(ExceptionWorkOrder).filter(
        ExceptionWorkOrder.work_order_no == request.work_order_no
    ).with_for_update().first()
    if not work_order:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": f"工单 {request.work_order_no} 不存在",
                "code": "WO_NOT_FOUND"
            }
        )

    _check_work_order_permission(request.operator, work_order)

    if work_order.status == "CLOSED" and not work_order.is_revoked:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "工单已关闭，无法重复关闭",
                "code": "WO_ALREADY_CLOSED"
            }
        )

    if not work_order_config_manager.can_transition_status(work_order.status, "CLOSED"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": f"工单状态 {work_order.status} 无法转为 CLOSED",
                "code": "WO_INVALID_STATUS_TRANSITION"
            }
        )

    old_status = work_order.status

    work_order.status = "CLOSED"
    work_order.closed_at = datetime.now(timezone.utc)
    work_order.closed_by = request.operator
    work_order.close_reason = request.close_reason

    audit_logger.log_work_order_close(
        db, work_order, request.operator, request.close_reason
    )

    db.commit()
    db.refresh(work_order)

    return work_order


@router.post(
    "/revoke-close",
    response_model=WorkOrderResponse,
    responses={
        400: {"model": ErrorResponse, "description": "请求错误或状态冲突"},
        403: {"model": ErrorResponse, "description": "权限不足"},
        404: {"model": ErrorResponse, "description": "工单不存在"},
        409: {"model": ErrorResponse, "description": "状态冲突"}
    },
    summary="撤销关闭工单"
)
def revoke_close_work_order(request: WorkOrderRevokeCloseRequest, db: Session = Depends(get_db)):
    """
    撤销关闭工单。

    - **work_order_no**: 工单号
    - **revoke_reason**: 撤销原因
    - **operator**: 操作人
    """
    _check_wo_config_loaded()

    work_order = db.query(ExceptionWorkOrder).filter(
        ExceptionWorkOrder.work_order_no == request.work_order_no
    ).with_for_update().first()
    if not work_order:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": f"工单 {request.work_order_no} 不存在",
                "code": "WO_NOT_FOUND"
            }
        )

    _check_work_order_permission(request.operator, work_order)

    can_revoke, error_msg = work_order_config_manager.can_revoke_close(work_order)
    if not can_revoke:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": error_msg,
                "code": "WO_CANNOT_REVOKE_CLOSE",
                "details": {
                    "work_order_no": work_order.work_order_no,
                    "status": work_order.status,
                    "is_revoked": work_order.is_revoked,
                    "closed_at": work_order.closed_at.isoformat() if work_order.closed_at else None
                }
            }
        )

    work_order.is_revoked = True
    work_order.revoked_at = datetime.now(timezone.utc)
    work_order.revoked_by = request.operator
    work_order.revoke_reason = request.revoke_reason
    work_order.status = "PROCESSING"

    audit_logger.log_work_order_revoke_close(
        db, work_order, request.operator, request.revoke_reason
    )

    db.commit()
    db.refresh(work_order)

    return work_order


def _validate_single_work_order(
    db: Session,
    item,
    index: int,
    processed_boxes: dict
) -> tuple[bool, Optional[WorkOrderBatchImportError], Optional[ExceptionWorkOrder]]:
    rule_version = work_order_config_manager.get_current_version()
    if not rule_version:
        return False, WorkOrderBatchImportError(
            index=index,
            box_code=item.box_code,
            error="工单配置未加载，请先加载工单规则配置",
            code="WO_CONFIG_NOT_LOADED"
        ), None

    if not work_order_config_manager.is_exception_type_valid(item.exception_type):
        return False, WorkOrderBatchImportError(
            index=index,
            box_code=item.box_code,
            error=f"无效的异常类型: {item.exception_type}",
            code="WO_INVALID_EXCEPTION_TYPE",
            details={"exception_type": item.exception_type}
        ), None

    if not work_order_config_manager.is_site_valid(item.site_code):
        return False, WorkOrderBatchImportError(
            index=index,
            box_code=item.box_code,
            error=f"无效的站点编码: {item.site_code}",
            code="WO_INVALID_SITE",
            details={"site_code": item.site_code}
        ), None

    can_access, error_msg = work_order_config_manager.can_user_access_site(item.reported_by, item.site_code)
    if not can_access:
        return False, WorkOrderBatchImportError(
            index=index,
            box_code=item.box_code,
            error=error_msg,
            code="WO_PERMISSION_DENIED",
            details={
                "username": item.reported_by,
                "site_code": item.site_code
            }
        ), None

    box = db.query(Box).filter(Box.box_code == item.box_code).first()
    if not box:
        return False, WorkOrderBatchImportError(
            index=index,
            box_code=item.box_code,
            error=f"箱号 {item.box_code} 不存在",
            code="BOX_NOT_FOUND",
            details={"box_code": item.box_code}
        ), None

    transfer_record = None
    if item.transfer_record_id:
        transfer_record = db.query(TransferRecord).filter(
            TransferRecord.id == item.transfer_record_id
        ).first()
        if not transfer_record:
            return False, WorkOrderBatchImportError(
                index=index,
                box_code=item.box_code,
                error=f"交接记录 {item.transfer_record_id} 不存在",
                code="WO_TRANSFER_RECORD_NOT_FOUND",
                details={"transfer_record_id": item.transfer_record_id}
            ), None
        if transfer_record.box_id != box.id:
            return False, WorkOrderBatchImportError(
                index=index,
                box_code=item.box_code,
                error="交接记录与箱号不匹配",
                code="WO_TRANSFER_BOX_MISMATCH",
                details={
                    "transfer_record_id": item.transfer_record_id,
                    "box_code": item.box_code
                }
            ), None

    existing_wo = db.query(ExceptionWorkOrder).filter(
        ExceptionWorkOrder.box_code == item.box_code,
        ExceptionWorkOrder.exception_type == item.exception_type,
        ExceptionWorkOrder.status != "CLOSED",
        ExceptionWorkOrder.is_revoked == False
    ).first()
    if existing_wo:
        return False, WorkOrderBatchImportError(
            index=index,
            box_code=item.box_code,
            error=f"箱号 {item.box_code} 已有未关闭的同类型异常工单",
            code="WO_DUPLICATE_WORK_ORDER",
            details={
                "box_code": item.box_code,
                "existing_work_order_no": existing_wo.work_order_no,
                "exception_type": item.exception_type
            }
        ), None

    box_key = f"{item.box_code}_{item.exception_type}"
    if box_key in processed_boxes:
        return False, WorkOrderBatchImportError(
            index=index,
            box_code=item.box_code,
            error=f"同一箱子 {item.box_code} 在本次批量导入中已存在同类型异常工单",
            code="WO_DUPLICATE_IN_BATCH",
            details={
                "previous_index": processed_boxes[box_key],
                "exception_type": item.exception_type
            }
        ), None

    severity = work_order_config_manager.get_severity(
        item.exception_type,
        item.description
    )

    work_order_no = work_order_config_manager.generate_work_order_no()
    reported_at = item.reported_at or datetime.now(timezone.utc)

    work_order = ExceptionWorkOrder(
        work_order_no=work_order_no,
        exception_type=item.exception_type,
        severity=severity,
        box_code=item.box_code,
        box_id=box.id,
        transfer_record_id=transfer_record.id if transfer_record else None,
        site_code=item.site_code,
        reported_by=item.reported_by,
        reported_at=reported_at,
        description=item.description,
        status="OPEN",
        rule_version=rule_version
    )

    return True, None, work_order


@router.post(
    "/batch-import",
    response_model=WorkOrderBatchImportResponse,
    responses={
        400: {"model": ErrorResponse, "description": "配置未加载"},
        500: {"model": ErrorResponse, "description": "服务器错误"}
    },
    summary="JSON批量导入工单"
)
def batch_import_work_orders(import_request: WorkOrderBatchImportRequest, db: Session = Depends(get_db)):
    """
    批量导入异常工单。

    导入时逐条校验：
    - 箱号存在
    - 站点有效
    - 责任人有权限
    - 无重复工单
    - 状态无冲突

    失败项不写库，成功项写入并返回。
    """
    rule_version = _check_wo_config_loaded()

    items = import_request.work_orders
    total_count = len(items)
    success_count = 0
    failed_count = 0
    imported_work_orders = []
    errors = []
    processed_boxes = {}

    for index, item in enumerate(items):
        is_valid, error, work_order = _validate_single_work_order(db, item, index, processed_boxes)

        if not is_valid and error:
            errors.append(error)
            failed_count += 1
            continue

        if work_order:
            db.add(work_order)
            db.flush()
            audit_logger.log_work_order_create(db, work_order, item.reported_by)
            imported_work_orders.append(work_order)
            success_count += 1
            box_key = f"{item.box_code}_{item.exception_type}"
            processed_boxes[box_key] = index

    db.commit()

    for wo in imported_work_orders:
        db.refresh(wo)

    return WorkOrderBatchImportResponse(
        success=failed_count == 0,
        total_count=total_count,
        success_count=success_count,
        failed_count=failed_count,
        imported_work_orders=imported_work_orders,
        errors=errors,
        import_time=datetime.now(timezone.utc),
        rule_version=rule_version
    )


@router.get(
    "/export/csv",
    response_model=WorkOrderExportResponse,
    responses={
        400: {"model": ErrorResponse, "description": "配置未加载"},
        403: {"model": ErrorResponse, "description": "权限不足"},
        500: {"model": ErrorResponse, "description": "服务器错误"}
    },
    summary="CSV导出工单列表"
)
def export_work_orders_csv(
    status: Optional[str] = None,
    exception_type: Optional[str] = None,
    severity: Optional[str] = None,
    box_code: Optional[str] = None,
    site_code: Optional[str] = None,
    reported_by: Optional[str] = None,
    operator: Optional[str] = None,
    db: Session = Depends(get_db)):
    """
    导出工单列表为CSV文件。

    参数同列表筛选接口。
    """
    _check_wo_config_loaded()

    query = db.query(ExceptionWorkOrder)

    if operator:
        user_sites = work_order_config_manager.get_user_sites(operator)
        if user_sites:
            query = query.filter(ExceptionWorkOrder.site_code.in_(user_sites))

    if status:
        query = query.filter(ExceptionWorkOrder.status == status)
    if exception_type:
        query = query.filter(ExceptionWorkOrder.exception_type == exception_type)
    if severity:
        query = query.filter(ExceptionWorkOrder.severity == severity)
    if box_code:
        query = query.filter(ExceptionWorkOrder.box_code.ilike(f"%{box_code}%"))
    if site_code:
        query = query.filter(ExceptionWorkOrder.site_code == site_code)
    if reported_by:
        query = query.filter(ExceptionWorkOrder.reported_by == reported_by)

    work_orders = query.order_by(ExceptionWorkOrder.created_at.desc()).all()

    os.makedirs(EXPORTS_DIR, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    file_name = f"work_orders_{timestamp}.csv"
    file_path = os.path.join(EXPORTS_DIR, file_name)

    with open(file_path, 'w', encoding='utf-8-sig', newline='') as f:
        writer = csv.writer(f)
        writer.writerow([
            "工单号", "异常类型", "严重等级", "箱号", "站点编码",
            "上报人", "上报时间", "描述", "状态", "处理人",
            "分配时间", "关闭时间", "关闭人", "关闭原因",
            "是否已撤销", "撤销时间", "撤销人", "撤销原因",
            "规则版本", "创建时间", "更新时间"
        ])

        for wo in work_orders:
            writer.writerow([
                wo.work_order_no,
                wo.exception_type,
                wo.severity,
                wo.box_code,
                wo.site_code,
                wo.reported_by,
                wo.reported_at.isoformat() if wo.reported_at else "",
                wo.description,
                wo.status,
                wo.assignee or "",
                wo.assigned_at.isoformat() if wo.assigned_at else "",
                wo.closed_at.isoformat() if wo.closed_at else "",
                wo.closed_by or "",
                wo.close_reason or "",
                wo.is_revoked,
                wo.revoked_at.isoformat() if wo.revoked_at else "",
                wo.revoked_by or "",
                wo.revoke_reason or "",
                wo.rule_version,
                wo.created_at.isoformat() if wo.created_at else "",
                wo.updated_at.isoformat() if wo.updated_at else ""
            ])

    return WorkOrderExportResponse(
        file_path=file_path,
        file_name=file_name,
        total_count=len(work_orders),
        exported_at=datetime.now(timezone.utc)
    )
