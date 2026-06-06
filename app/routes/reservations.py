from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import datetime, timezone, date
import json
import os
import csv

from ..database import get_db
from ..models import (
    Box, TransferRecord, ExceptionWorkOrder,
    Reservation, ReservationBox, LoadingPlan, LoadingPlanBox,
    ReservationRuleVersion
)
from ..schemas import (
    ErrorResponse, ConfigVersionResponse,
    ReservationCreate, ReservationUpdate, ReservationResponse,
    ReservationCancelRequest, ReservationConfirmRequest,
    ReservationDetailResponse,
    LoadingPlanCreate, LoadingPlanUpdate, LoadingPlanResponse,
    LoadingPlanConfirmRequest, LoadingPlanCancelRequest,
    LoadingPlanBoxLoadRequest,
    ReservationBatchImportRequest, ReservationBatchImportResponse,
    ReservationBatchImportError,
    LoadingPlanExportResponse
)
from ..reservation_config import (
    reservation_config_manager,
    ReservationConfigValidationError
)
from ..audit import audit_logger

router = APIRouter(prefix="/api/reservations", tags=["reservations"])

EXPORTS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "exports")


def _check_res_config_loaded():
    rule_version = reservation_config_manager.get_current_version()
    if not rule_version:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": "预约配置未加载，请先加载预约规则配置",
                "code": "RES_CONFIG_NOT_LOADED"
            }
        )
    return rule_version


def _check_user_site_permission(username: str, site_code: str):
    can_access, error_msg = reservation_config_manager.can_user_access_site(username, site_code)
    if not can_access:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": error_msg,
                "code": "RES_PERMISSION_DENIED",
                "details": {
                    "username": username,
                    "site_code": site_code
                }
            }
        )


def _check_reservation_permission(username: str, reservation: Reservation):
    can_operate, error_msg = reservation_config_manager.can_user_operate_reservation(username, reservation)
    if not can_operate:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": error_msg,
                "code": "RES_PERMISSION_DENIED",
                "details": {
                    "username": username,
                    "reservation_no": reservation.reservation_no,
                    "site_code": reservation.site_code
                }
            }
        )


def _check_duplicate_box_reservation(db: Session, box_ids: List[int], exclude_reservation_id: Optional[int] = None) -> tuple[bool, Optional[str]]:
    query = db.query(ReservationBox).filter(
        ReservationBox.box_id.in_(box_ids),
        ReservationBox.reservation.has(
            Reservation.status.notin_(["CANCELLED", "LOADED"])
        )
    )
    if exclude_reservation_id:
        query = query.filter(ReservationBox.reservation_id != exclude_reservation_id)

    existing = query.first()
    if existing:
        box = db.query(Box).filter(Box.id == existing.box_id).first()
        res = db.query(Reservation).filter(Reservation.id == existing.reservation_id).first()
        return False, f"箱号 {box.box_code if box else existing.box_id} 已在预约 {res.reservation_no if res else existing.reservation_id} 中"
    return True, None


def _check_vehicle_capacity(db: Session, vehicle_no: str, scheduled_date: datetime, new_box_count: int, vehicle_type: Optional[str] = None, exclude_reservation_id: Optional[int] = None) -> tuple[bool, Optional[str], int, int]:
    capacity = reservation_config_manager.get_vehicle_capacity(vehicle_type)

    day_start = scheduled_date.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = day_start.replace(hour=23, minute=59, second=59, microsecond=999999)

    query = db.query(Reservation).filter(
        Reservation.vehicle_no == vehicle_no,
        Reservation.scheduled_date >= day_start,
        Reservation.scheduled_date <= day_end,
        Reservation.status.notin_(["CANCELLED"])
    )
    if exclude_reservation_id:
        query = query.filter(Reservation.id != exclude_reservation_id)

    existing_reservations = query.all()
    existing_box_count = 0
    for res in existing_reservations:
        existing_box_count += len(res.reservation_boxes)

    total_box_count = existing_box_count + new_box_count
    if total_box_count > capacity:
        return False, f"车辆 {vehicle_no} 在 {scheduled_date.date()} 已预约 {existing_box_count} 箱，新增 {new_box_count} 箱后超出容量 {capacity} 箱", existing_box_count, capacity

    return True, None, existing_box_count, capacity


def _check_temperature_zone_consistency(db: Session, box_ids: List[int], temperature_zone: str) -> tuple[bool, Optional[str]]:
    if reservation_config_manager.allow_mixed_temperature_zones():
        return True, None

    for box_id in box_ids:
        box = db.query(Box).filter(Box.id == box_id).first()
        if box:
            samples = box.samples
            if samples:
                for sample in samples:
                    expected_zone = _get_temperature_zone_for_sample(sample.sample_type)
                    if expected_zone and expected_zone != temperature_zone:
                        return False, f"箱 {box.box_code} 中样本 {sample.barcode} 类型 {sample.sample_type} 需要温区 {expected_zone}，与预约温区 {temperature_zone} 冲突"
    return True, None


def _get_temperature_zone_for_sample(sample_type: str) -> Optional[str]:
    temp_zone_map = {
        "blood": "REFRIGERATED",
        "saliva": "AMBIENT",
        "nucleic_acid": "FROZEN",
        "urine": "REFRIGERATED"
    }
    return temp_zone_map.get(sample_type)


def _validate_boxes_for_reservation(db: Session, box_codes: List[str], reservation: Optional[Reservation] = None) -> tuple[List[Box], List[str]]:
    boxes = []
    errors = []

    seen_codes = set()
    for box_code in box_codes:
        if box_code in seen_codes:
            errors.append(f"箱号 {box_code} 在列表中重复")
            continue
        seen_codes.add(box_code)

        box = db.query(Box).filter(Box.box_code == box_code).first()
        if not box:
            errors.append(f"箱号 {box_code} 不存在")
            continue

        if box.status in ["OPEN"]:
            errors.append(f"箱号 {box_code} 状态为 {box.status}，未封箱不能预约出库")
            continue

        if box.status in ["DELIVERED", "TESTING", "TESTING_COMPLETED", "ARCHIVED"]:
            errors.append(f"箱号 {box_code} 状态为 {box.status}，已完成流转不能预约")
            continue

        boxes.append(box)

    return boxes, errors


@router.post(
    "/config/load",
    response_model=ConfigVersionResponse,
    responses={
        400: {"model": ErrorResponse, "description": "配置校验失败"},
        404: {"model": ErrorResponse, "description": "配置文件不存在"},
        500: {"model": ErrorResponse, "description": "服务器错误"}
    },
    summary="加载预约规则配置"
)
def load_reservation_config(config_path: str, db: Session = Depends(get_db)):
    try:
        config, version = reservation_config_manager.load_config(config_path, db)
        active_config = db.query(ReservationRuleVersion).filter(ReservationRuleVersion.is_active == True).first()
        return active_config
    except ReservationConfigValidationError as e:
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
                "error": f"加载预约配置失败: {str(e)}",
                "code": "RES_LOAD_CONFIG_ERROR"
            }
        )


@router.get(
    "/config/versions",
    response_model=List[ConfigVersionResponse],
    summary="查询预约配置版本列表"
)
def get_reservation_config_versions(db: Session = Depends(get_db)):
    return db.query(ReservationRuleVersion).order_by(ReservationRuleVersion.loaded_at.desc()).all()


@router.get(
    "/config/current",
    response_model=ConfigVersionResponse,
    responses={404: {"model": ErrorResponse, "description": "无活动配置"}},
    summary="获取当前活动预约配置"
)
def get_current_reservation_config(db: Session = Depends(get_db)):
    active_config = db.query(ReservationRuleVersion).filter(ReservationRuleVersion.is_active == True).first()
    if not active_config:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "没有活动的预约配置",
                "code": "RES_NO_ACTIVE_CONFIG"
            }
        )
    return active_config


@router.get(
    "/config/rules",
    summary="查看当前预约配置规则详情"
)
def get_current_reservation_rules():
    config = reservation_config_manager.get_current_config()
    if not config:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "预约配置未加载",
                "code": "RES_CONFIG_NOT_LOADED"
            }
        )
    return config


@router.post(
    "",
    response_model=ReservationResponse,
    responses={
        400: {"model": ErrorResponse, "description": "请求参数错误或验证失败"},
        403: {"model": ErrorResponse, "description": "权限不足"},
        404: {"model": ErrorResponse, "description": "箱号不存在"},
        409: {"model": ErrorResponse, "description": "冲突（重复预约、容量不足等）"},
        500: {"model": ErrorResponse, "description": "服务器错误"}
    },
    summary="创建预约出库单"
)
def create_reservation(reservation_data: ReservationCreate, db: Session = Depends(get_db)):
    rule_version = _check_res_config_loaded()

    if not reservation_config_manager.is_site_valid(reservation_data.site_code):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": f"无效的站点编码: {reservation_data.site_code}",
                "code": "RES_INVALID_SITE",
                "details": {"site_code": reservation_data.site_code}
            }
        )

    if not reservation_config_manager.is_customer_valid(reservation_data.customer_code):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": f"无效的客户编码: {reservation_data.customer_code}",
                "code": "RES_INVALID_CUSTOMER",
                "details": {"customer_code": reservation_data.customer_code}
            }
        )

    if not reservation_config_manager.is_temperature_zone_valid(reservation_data.temperature_zone):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": f"无效的温控要求: {reservation_data.temperature_zone}",
                "code": "RES_INVALID_TEMPERATURE_ZONE",
                "details": {"temperature_zone": reservation_data.temperature_zone}
            }
        )

    _check_user_site_permission(reservation_data.created_by, reservation_data.site_code)

    is_valid_time, msg = reservation_config_manager.validate_reservation_time(reservation_data.scheduled_date)
    if not is_valid_time:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": msg,
                "code": "RES_INVALID_SCHEDULED_TIME",
                "details": {"scheduled_date": reservation_data.scheduled_date.isoformat()}
            }
        )

    if not reservation_data.box_codes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "预约至少需要一个箱号",
                "code": "RES_EMPTY_BOX_LIST"
            }
        )

    boxes, errors = _validate_boxes_for_reservation(db, reservation_data.box_codes)
    if errors:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "箱号验证失败",
                "code": "RES_BOX_VALIDATION_FAILED",
                "details": {"errors": errors}
            }
        )

    box_ids = [box.id for box in boxes]

    is_available, conflict_msg = _check_duplicate_box_reservation(db, box_ids)
    if not is_available:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": conflict_msg,
                "code": "RES_DUPLICATE_BOX_RESERVATION",
                "details": {"box_codes": reservation_data.box_codes}
            }
        )

    is_capacity_ok, capacity_msg, used, capacity = _check_vehicle_capacity(
        db, reservation_data.vehicle_no, reservation_data.scheduled_date,
        len(boxes), reservation_data.vehicle_type
    )
    if not is_capacity_ok:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": capacity_msg,
                "code": "RES_VEHICLE_CAPACITY_EXCEEDED",
                "details": {
                    "vehicle_no": reservation_data.vehicle_no,
                    "scheduled_date": reservation_data.scheduled_date.isoformat(),
                    "used_capacity": used,
                    "new_boxes": len(boxes),
                    "total_capacity": capacity
                }
            }
        )

    is_temp_ok, temp_msg = _check_temperature_zone_consistency(db, box_ids, reservation_data.temperature_zone)
    if not is_temp_ok:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": temp_msg,
                "code": "RES_TEMPERATURE_ZONE_CONFLICT",
                "details": {"temperature_zone": reservation_data.temperature_zone}
            }
        )

    reservation_no = reservation_config_manager.generate_reservation_no()
    rule_snapshot = reservation_config_manager.get_rule_snapshot()

    reservation = Reservation(
        reservation_no=reservation_no,
        site_code=reservation_data.site_code,
        customer_code=reservation_data.customer_code,
        temperature_zone=reservation_data.temperature_zone,
        vehicle_no=reservation_data.vehicle_no,
        vehicle_type=reservation_data.vehicle_type,
        scheduled_date=reservation_data.scheduled_date,
        status="DRAFT",
        created_by=reservation_data.created_by,
        remark=reservation_data.remark,
        rule_version=rule_version,
        rule_snapshot=rule_snapshot
    )
    db.add(reservation)
    db.flush()

    for box in boxes:
        res_box = ReservationBox(
            reservation_id=reservation.id,
            box_id=box.id,
            box_code=box.box_code,
            loading_status="PENDING"
        )
        db.add(res_box)

    db.flush()

    audit_logger.log_reservation_create(db, reservation, reservation_data.created_by)

    db.commit()
    db.refresh(reservation)

    return reservation


@router.get(
    "",
    response_model=List[ReservationResponse],
    summary="查询预约列表（按日期/站点/状态）"
)
def get_reservations(
    scheduled_date: Optional[date] = Query(None, description="预约日期筛选"),
    site_code: Optional[str] = Query(None, description="站点编码筛选"),
    status: Optional[str] = Query(None, description="状态筛选"),
    customer_code: Optional[str] = Query(None, description="客户编码筛选"),
    vehicle_no: Optional[str] = Query(None, description="车牌号筛选"),
    created_by: Optional[str] = Query(None, description="创建人筛选"),
    operator: Optional[str] = Query(None, description="操作人（用于权限过滤）"),
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db)
):
    _check_res_config_loaded()

    query = db.query(Reservation)

    if operator:
        user_sites = reservation_config_manager.get_user_sites(operator)
        if user_sites:
            query = query.filter(Reservation.site_code.in_(user_sites))

    if scheduled_date:
        day_start = datetime.combine(scheduled_date, datetime.min.time())
        day_end = datetime.combine(scheduled_date, datetime.max.time())
        query = query.filter(
            Reservation.scheduled_date >= day_start,
            Reservation.scheduled_date <= day_end
        )
    if site_code:
        query = query.filter(Reservation.site_code == site_code)
    if status:
        query = query.filter(Reservation.status == status)
    if customer_code:
        query = query.filter(Reservation.customer_code == customer_code)
    if vehicle_no:
        query = query.filter(Reservation.vehicle_no.ilike(f"%{vehicle_no}%"))
    if created_by:
        query = query.filter(Reservation.created_by == created_by)

    return query.order_by(Reservation.scheduled_date.desc(), Reservation.created_at.desc()).offset(skip).limit(limit).all()


@router.get(
    "/{reservation_no}",
    response_model=ReservationDetailResponse,
    responses={
        403: {"model": ErrorResponse, "description": "权限不足"},
        404: {"model": ErrorResponse, "description": "预约不存在"}
    },
    summary="查询预约详情"
)
def get_reservation_detail(reservation_no: str, operator: Optional[str] = None, db: Session = Depends(get_db)):
    _check_res_config_loaded()

    reservation = db.query(Reservation).filter(
        Reservation.reservation_no == reservation_no
    ).first()
    if not reservation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": f"预约 {reservation_no} 不存在",
                "code": "RES_NOT_FOUND"
            }
        )

    if operator:
        _check_reservation_permission(operator, reservation)

    box_ids = [rb.box_id for rb in reservation.reservation_boxes]

    transfer_records = db.query(TransferRecord).filter(
        TransferRecord.box_id.in_(box_ids)
    ).order_by(TransferRecord.transfer_time.desc()).all()

    work_orders = db.query(ExceptionWorkOrder).filter(
        ExceptionWorkOrder.box_id.in_(box_ids)
    ).order_by(ExceptionWorkOrder.created_at.desc()).all()

    return ReservationDetailResponse(
        id=reservation.id,
        reservation_no=reservation.reservation_no,
        site_code=reservation.site_code,
        customer_code=reservation.customer_code,
        temperature_zone=reservation.temperature_zone,
        vehicle_no=reservation.vehicle_no,
        vehicle_type=reservation.vehicle_type,
        scheduled_date=reservation.scheduled_date,
        status=reservation.status,
        created_by=reservation.created_by,
        remark=reservation.remark,
        rule_version=reservation.rule_version,
        rule_snapshot=reservation.rule_snapshot,
        cancelled_at=reservation.cancelled_at,
        cancelled_by=reservation.cancelled_by,
        cancel_reason=reservation.cancel_reason,
        created_at=reservation.created_at,
        updated_at=reservation.updated_at,
        reservation_boxes=reservation.reservation_boxes,
        loading_plans=reservation.loading_plans,
        transfer_records=transfer_records,
        work_orders=work_orders
    )


@router.put(
    "/{reservation_no}",
    response_model=ReservationResponse,
    responses={
        400: {"model": ErrorResponse, "description": "请求错误或验证失败"},
        403: {"model": ErrorResponse, "description": "权限不足"},
        404: {"model": ErrorResponse, "description": "预约不存在"},
        409: {"model": ErrorResponse, "description": "状态冲突或已装车后无法修改"}
    },
    summary="调整预约"
)
def update_reservation(reservation_no: str, update_data: ReservationUpdate, db: Session = Depends(get_db)):
    _check_res_config_loaded()

    reservation = db.query(Reservation).filter(
        Reservation.reservation_no == reservation_no
    ).with_for_update().first()
    if not reservation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": f"预约 {reservation_no} 不存在",
                "code": "RES_NOT_FOUND"
            }
        )

    _check_reservation_permission(update_data.operator, reservation)

    if reservation.status in ["LOADED"]:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": f"预约状态为 {reservation.status}，已装车后无法修改",
                "code": "RES_ALREADY_LOADED",
                "details": {"reservation_status": reservation.status}
            }
        )

    if reservation.status in ["CANCELLED"]:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": f"预约状态为 {reservation.status}，已取消无法修改",
                "code": "RES_ALREADY_CANCELLED",
                "details": {"reservation_status": reservation.status}
            }
        )

    changes = {}

    if update_data.site_code is not None:
        if not reservation_config_manager.is_site_valid(update_data.site_code):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "error": f"无效的站点编码: {update_data.site_code}",
                    "code": "RES_INVALID_SITE"
                }
            )
        _check_user_site_permission(update_data.operator, update_data.site_code)
        changes["site_code"] = {"old": reservation.site_code, "new": update_data.site_code}
        reservation.site_code = update_data.site_code

    if update_data.customer_code is not None:
        if not reservation_config_manager.is_customer_valid(update_data.customer_code):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "error": f"无效的客户编码: {update_data.customer_code}",
                    "code": "RES_INVALID_CUSTOMER"
                }
            )
        changes["customer_code"] = {"old": reservation.customer_code, "new": update_data.customer_code}
        reservation.customer_code = update_data.customer_code

    if update_data.temperature_zone is not None:
        if not reservation_config_manager.is_temperature_zone_valid(update_data.temperature_zone):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "error": f"无效的温控要求: {update_data.temperature_zone}",
                    "code": "RES_INVALID_TEMPERATURE_ZONE"
                }
            )
        changes["temperature_zone"] = {"old": reservation.temperature_zone, "new": update_data.temperature_zone}
        reservation.temperature_zone = update_data.temperature_zone

    if update_data.vehicle_no is not None:
        changes["vehicle_no"] = {"old": reservation.vehicle_no, "new": update_data.vehicle_no}
        reservation.vehicle_no = update_data.vehicle_no

    if update_data.vehicle_type is not None:
        changes["vehicle_type"] = {"old": reservation.vehicle_type, "new": update_data.vehicle_type}
        reservation.vehicle_type = update_data.vehicle_type

    if update_data.scheduled_date is not None:
        is_valid_time, msg = reservation_config_manager.validate_reservation_time(update_data.scheduled_date)
        if not is_valid_time:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "error": msg,
                    "code": "RES_INVALID_SCHEDULED_TIME"
                }
            )
        changes["scheduled_date"] = {"old": reservation.scheduled_date.isoformat(), "new": update_data.scheduled_date.isoformat()}
        reservation.scheduled_date = update_data.scheduled_date

    if update_data.remark is not None:
        changes["remark"] = {"old": reservation.remark, "new": update_data.remark}
        reservation.remark = update_data.remark

    if update_data.box_codes is not None:
        if not update_data.box_codes:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "error": "预约至少需要一个箱号",
                    "code": "RES_EMPTY_BOX_LIST"
                }
            )

        boxes, errors = _validate_boxes_for_reservation(db, update_data.box_codes, reservation)
        if errors:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "error": "箱号验证失败",
                    "code": "RES_BOX_VALIDATION_FAILED",
                    "details": {"errors": errors}
                }
            )

        box_ids = [box.id for box in boxes]

        is_available, conflict_msg = _check_duplicate_box_reservation(db, box_ids, reservation.id)
        if not is_available:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "error": conflict_msg,
                    "code": "RES_DUPLICATE_BOX_RESERVATION"
                }
            )

        current_box_ids = set(rb.box_id for rb in reservation.reservation_boxes)
        new_box_ids = set(box_ids)
        added_boxes = new_box_ids - current_box_ids
        removed_boxes = current_box_ids - new_box_ids

        is_capacity_ok, capacity_msg, used, capacity = _check_vehicle_capacity(
            db, reservation.vehicle_no, reservation.scheduled_date,
            len(added_boxes), reservation.vehicle_type, reservation.id
        )
        if not is_capacity_ok:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "error": capacity_msg,
                    "code": "RES_VEHICLE_CAPACITY_EXCEEDED"
                }
            )

        is_temp_ok, temp_msg = _check_temperature_zone_consistency(db, box_ids, reservation.temperature_zone)
        if not is_temp_ok:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "error": temp_msg,
                    "code": "RES_TEMPERATURE_ZONE_CONFLICT"
                }
            )

        old_codes = [rb.box_code for rb in reservation.reservation_boxes]
        new_codes = [b.box_code for b in boxes]
        changes["box_codes"] = {"old": old_codes, "new": new_codes}

        for rb in reservation.reservation_boxes:
            if rb.box_id in removed_boxes:
                db.delete(rb)

        for box in boxes:
            if box.id in added_boxes:
                res_box = ReservationBox(
                    reservation_id=reservation.id,
                    box_id=box.id,
                    box_code=box.box_code,
                    loading_status="PENDING"
                )
                db.add(res_box)

    db.flush()

    if changes:
        audit_logger.log_reservation_update(db, reservation, update_data.operator, changes)

    db.commit()
    db.refresh(reservation)

    return reservation


@router.post(
    "/confirm",
    response_model=ReservationResponse,
    responses={
        400: {"model": ErrorResponse, "description": "状态流转错误"},
        403: {"model": ErrorResponse, "description": "权限不足"},
        404: {"model": ErrorResponse, "description": "预约不存在"},
        409: {"model": ErrorResponse, "description": "状态冲突"}
    },
    summary="确认预约"
)
def confirm_reservation(request: ReservationConfirmRequest, db: Session = Depends(get_db)):
    _check_res_config_loaded()

    reservation = db.query(Reservation).filter(
        Reservation.reservation_no == request.reservation_no
    ).with_for_update().first()
    if not reservation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": f"预约 {request.reservation_no} 不存在",
                "code": "RES_NOT_FOUND"
            }
        )

    _check_reservation_permission(request.operator, reservation)

    old_status = reservation.status

    if not reservation_config_manager.can_transition_reservation_status(old_status, "CONFIRMED"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": f"预约状态 {old_status} 无法转为 CONFIRMED",
                "code": "RES_INVALID_STATUS_TRANSITION",
                "details": {"current_status": old_status}
            }
        )

    reservation.status = "CONFIRMED"

    audit_logger.log_reservation_status_change(
        db, reservation, old_status, "CONFIRMED", request.operator, "CONFIRM"
    )

    db.commit()
    db.refresh(reservation)

    return reservation


@router.post(
    "/cancel",
    response_model=ReservationResponse,
    responses={
        400: {"model": ErrorResponse, "description": "取消时限已过或状态错误"},
        403: {"model": ErrorResponse, "description": "权限不足"},
        404: {"model": ErrorResponse, "description": "预约不存在"},
        409: {"model": ErrorResponse, "description": "已装车无法取消"}
    },
    summary="取消预约"
)
def cancel_reservation(request: ReservationCancelRequest, db: Session = Depends(get_db)):
    _check_res_config_loaded()

    reservation = db.query(Reservation).filter(
        Reservation.reservation_no == request.reservation_no
    ).with_for_update().first()
    if not reservation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": f"预约 {request.reservation_no} 不存在",
                "code": "RES_NOT_FOUND"
            }
        )

    _check_reservation_permission(request.operator, reservation)

    if reservation.status == "LOADED":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "预约已装车，无法取消",
                "code": "RES_ALREADY_LOADED",
                "details": {"reservation_status": reservation.status}
            }
        )

    if reservation.status == "CANCELLED":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "预约已取消",
                "code": "RES_ALREADY_CANCELLED"
            }
        )

    can_cancel, cancel_msg = reservation_config_manager.can_cancel_reservation(reservation.scheduled_date)
    if not can_cancel:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": cancel_msg,
                "code": "RES_CANCEL_LIMIT_EXCEEDED",
                "details": {"scheduled_date": reservation.scheduled_date.isoformat()}
            }
        )

    old_status = reservation.status
    reservation.status = "CANCELLED"
    reservation.cancelled_at = datetime.now(timezone.utc)
    reservation.cancelled_by = request.operator
    reservation.cancel_reason = request.cancel_reason

    for rb in reservation.reservation_boxes:
        rb.loading_status = "CANCELLED"

    for lp in reservation.loading_plans:
        if lp.status != "CANCELLED":
            lp.status = "CANCELLED"
            lp.cancelled_at = datetime.now(timezone.utc)
            lp.cancelled_by = request.operator
            lp.cancel_reason = f"关联预约取消: {request.cancel_reason}"
            audit_logger.log_loading_plan_cancel(
                db, lp, request.operator, f"关联预约取消: {request.cancel_reason}"
            )

    audit_logger.log_reservation_cancel(db, reservation, request.operator, request.cancel_reason)

    db.commit()
    db.refresh(reservation)

    return reservation


@router.post(
    "/loading-plans",
    response_model=LoadingPlanResponse,
    responses={
        400: {"model": ErrorResponse, "description": "请求错误"},
        403: {"model": ErrorResponse, "description": "权限不足"},
        404: {"model": ErrorResponse, "description": "预约不存在"},
        409: {"model": ErrorResponse, "description": "状态冲突"}
    },
    summary="创建装车计划"
)
def create_loading_plan(plan_data: LoadingPlanCreate, db: Session = Depends(get_db)):
    rule_version = _check_res_config_loaded()

    reservation = db.query(Reservation).filter(
        Reservation.reservation_no == plan_data.reservation_no
    ).first()
    if not reservation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": f"预约 {plan_data.reservation_no} 不存在",
                "code": "RES_NOT_FOUND"
            }
        )

    _check_reservation_permission(plan_data.operator, reservation)

    if reservation.status not in ["CONFIRMED"]:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": f"预约状态为 {reservation.status}，只有 CONFIRMED 状态才能创建装车计划",
                "code": "RES_INVALID_STATUS_FOR_LOADING_PLAN",
                "details": {"reservation_status": reservation.status}
            }
        )

    if reservation.status == "LOADED":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "预约已装车，无法创建新的装车计划",
                "code": "RES_ALREADY_LOADED"
            }
        )

    plan_no = reservation_config_manager.generate_loading_plan_no()
    vehicle_no = plan_data.vehicle_no or reservation.vehicle_no

    loading_plan = LoadingPlan(
        plan_no=plan_no,
        reservation_id=reservation.id,
        vehicle_no=vehicle_no,
        driver=plan_data.driver,
        departure_time=plan_data.departure_time,
        status="DRAFT",
        remark=plan_data.remark,
        rule_version=rule_version
    )
    db.add(loading_plan)
    db.flush()

    for i, res_box in enumerate(reservation.reservation_boxes):
        lp_box = LoadingPlanBox(
            loading_plan_id=loading_plan.id,
            reservation_box_id=res_box.id,
            box_id=res_box.box_id,
            box_code=res_box.box_code,
            loading_sequence=i + 1,
            loaded=False
        )
        db.add(lp_box)

    db.flush()

    audit_logger.log_loading_plan_create(db, loading_plan, plan_data.operator)

    db.commit()
    db.refresh(loading_plan)

    return loading_plan


@router.get(
    "/loading-plans",
    response_model=List[LoadingPlanResponse],
    summary="查询装车计划列表"
)
def get_loading_plans(
    status: Optional[str] = Query(None, description="状态筛选"),
    vehicle_no: Optional[str] = Query(None, description="车牌号筛选"),
    reservation_no: Optional[str] = Query(None, description="关联预约单号筛选"),
    operator: Optional[str] = Query(None, description="操作人（用于权限过滤）"),
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db)
):
    _check_res_config_loaded()

    query = db.query(LoadingPlan).join(Reservation)

    if operator:
        user_sites = reservation_config_manager.get_user_sites(operator)
        if user_sites:
            query = query.filter(Reservation.site_code.in_(user_sites))

    if status:
        query = query.filter(LoadingPlan.status == status)
    if vehicle_no:
        query = query.filter(LoadingPlan.vehicle_no.ilike(f"%{vehicle_no}%"))
    if reservation_no:
        query = query.filter(Reservation.reservation_no == reservation_no)

    return query.order_by(LoadingPlan.created_at.desc()).offset(skip).limit(limit).all()


@router.get(
    "/loading-plans/{plan_no}",
    response_model=LoadingPlanResponse,
    responses={
        404: {"model": ErrorResponse, "description": "装车计划不存在"}
    },
    summary="查询装车计划详情"
)
def get_loading_plan_detail(plan_no: str, operator: Optional[str] = None, db: Session = Depends(get_db)):
    _check_res_config_loaded()

    loading_plan = db.query(LoadingPlan).filter(
        LoadingPlan.plan_no == plan_no
    ).first()
    if not loading_plan:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": f"装车计划 {plan_no} 不存在",
                "code": "LP_NOT_FOUND"
            }
        )

    if operator:
        reservation = db.query(Reservation).filter(
            Reservation.id == loading_plan.reservation_id
        ).first()
        if reservation:
            _check_reservation_permission(operator, reservation)

    return loading_plan


@router.put(
    "/loading-plans/{plan_no}",
    response_model=LoadingPlanResponse,
    responses={
        400: {"model": ErrorResponse, "description": "请求错误"},
        403: {"model": ErrorResponse, "description": "权限不足"},
        404: {"model": ErrorResponse, "description": "装车计划不存在"},
        409: {"model": ErrorResponse, "description": "已确认装车无法修改"}
    },
    summary="调整装车计划"
)
def update_loading_plan(plan_no: str, update_data: LoadingPlanUpdate, db: Session = Depends(get_db)):
    _check_res_config_loaded()

    loading_plan = db.query(LoadingPlan).filter(
        LoadingPlan.plan_no == plan_no
    ).with_for_update().first()
    if not loading_plan:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": f"装车计划 {plan_no} 不存在",
                "code": "LP_NOT_FOUND"
            }
        )

    reservation = db.query(Reservation).filter(
        Reservation.id == loading_plan.reservation_id
    ).first()
    if reservation:
        _check_reservation_permission(update_data.operator, reservation)

    if loading_plan.status == "CONFIRMED":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "装车计划已确认，无法修改",
                "code": "LP_ALREADY_CONFIRMED"
            }
        )

    if loading_plan.status == "CANCELLED":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "装车计划已取消，无法修改",
                "code": "LP_ALREADY_CANCELLED"
            }
        )

    if update_data.driver is not None:
        loading_plan.driver = update_data.driver
    if update_data.departure_time is not None:
        loading_plan.departure_time = update_data.departure_time
    if update_data.remark is not None:
        loading_plan.remark = update_data.remark

    if update_data.box_sequences is not None:
        for lp_box in loading_plan.loading_plan_boxes:
            if lp_box.box_code in update_data.box_sequences:
                lp_box.loading_sequence = update_data.box_sequences[lp_box.box_code]

    db.commit()
    db.refresh(loading_plan)

    return loading_plan


@router.post(
    "/loading-plans/confirm",
    response_model=LoadingPlanResponse,
    responses={
        400: {"model": ErrorResponse, "description": "状态流转错误"},
        403: {"model": ErrorResponse, "description": "权限不足"},
        404: {"model": ErrorResponse, "description": "装车计划不存在"},
        409: {"model": ErrorResponse, "description": "状态冲突"}
    },
    summary="确认装车"
)
def confirm_loading_plan(request: LoadingPlanConfirmRequest, db: Session = Depends(get_db)):
    _check_res_config_loaded()

    loading_plan = db.query(LoadingPlan).filter(
        LoadingPlan.plan_no == request.plan_no
    ).with_for_update().first()
    if not loading_plan:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": f"装车计划 {request.plan_no} 不存在",
                "code": "LP_NOT_FOUND"
            }
        )

    reservation = db.query(Reservation).filter(
        Reservation.id == loading_plan.reservation_id
    ).first()
    if reservation:
        _check_reservation_permission(request.operator, reservation)

    old_status = loading_plan.status

    if not reservation_config_manager.can_transition_loading_plan_status(old_status, "CONFIRMED"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": f"装车计划状态 {old_status} 无法转为 CONFIRMED",
                "code": "LP_INVALID_STATUS_TRANSITION",
                "details": {"current_status": old_status}
            }
        )

    all_loaded = all(lp_box.loaded for lp_box in loading_plan.loading_plan_boxes)
    if not all_loaded:
        unloaded_boxes = [lp_box.box_code for lp_box in loading_plan.loading_plan_boxes if not lp_box.loaded]
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "还有未装车的箱子，无法确认装车完成",
                "code": "LP_NOT_ALL_BOXES_LOADED",
                "details": {"unloaded_boxes": unloaded_boxes}
            }
        )

    loading_plan.status = "CONFIRMED"
    loading_plan.confirmed_by = request.operator
    loading_plan.confirmed_at = datetime.now(timezone.utc)

    if reservation:
        old_res_status = reservation.status
        reservation.status = "LOADED"
        audit_logger.log_reservation_status_change(
            db, reservation, old_res_status, "LOADED", request.operator, "LOAD_COMPLETE"
        )

        for rb in reservation.reservation_boxes:
            rb.loading_status = "LOADED"
            rb.loaded_at = datetime.now(timezone.utc)
            rb.loaded_by = request.operator

    audit_logger.log_loading_plan_confirm(db, loading_plan, request.operator)

    db.commit()
    db.refresh(loading_plan)

    return loading_plan


@router.post(
    "/loading-plans/cancel",
    response_model=LoadingPlanResponse,
    responses={
        400: {"model": ErrorResponse, "description": "状态错误"},
        403: {"model": ErrorResponse, "description": "权限不足"},
        404: {"model": ErrorResponse, "description": "装车计划不存在"},
        409: {"model": ErrorResponse, "description": "已确认装车无法取消"}
    },
    summary="取消装车计划"
)
def cancel_loading_plan(request: LoadingPlanCancelRequest, db: Session = Depends(get_db)):
    _check_res_config_loaded()

    loading_plan = db.query(LoadingPlan).filter(
        LoadingPlan.plan_no == request.plan_no
    ).with_for_update().first()
    if not loading_plan:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": f"装车计划 {request.plan_no} 不存在",
                "code": "LP_NOT_FOUND"
            }
        )

    reservation = db.query(Reservation).filter(
        Reservation.id == loading_plan.reservation_id
    ).first()
    if reservation:
        _check_reservation_permission(request.operator, reservation)

    if loading_plan.status == "CONFIRMED":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "装车计划已确认装车，无法取消",
                "code": "LP_ALREADY_CONFIRMED"
            }
        )

    if loading_plan.status == "CANCELLED":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "装车计划已取消",
                "code": "LP_ALREADY_CANCELLED"
            }
        )

    old_status = loading_plan.status
    loading_plan.status = "CANCELLED"
    loading_plan.cancelled_at = datetime.now(timezone.utc)
    loading_plan.cancelled_by = request.operator
    loading_plan.cancel_reason = request.cancel_reason

    for lp_box in loading_plan.loading_plan_boxes:
        res_box = lp_box.reservation_box
        if res_box:
            res_box.loading_status = "PENDING"

    audit_logger.log_loading_plan_cancel(db, loading_plan, request.operator, request.cancel_reason)

    db.commit()
    db.refresh(loading_plan)

    return loading_plan


@router.post(
    "/loading-plans/load-box",
    response_model=LoadingPlanResponse,
    responses={
        400: {"model": ErrorResponse, "description": "请求错误"},
        403: {"model": ErrorResponse, "description": "权限不足"},
        404: {"model": ErrorResponse, "description": "装车计划或箱号不存在"},
        409: {"model": ErrorResponse, "description": "状态冲突"}
    },
    summary="标记单箱装车"
)
def load_box(request: LoadingPlanBoxLoadRequest, db: Session = Depends(get_db)):
    _check_res_config_loaded()

    loading_plan = db.query(LoadingPlan).filter(
        LoadingPlan.plan_no == request.plan_no
    ).with_for_update().first()
    if not loading_plan:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": f"装车计划 {request.plan_no} 不存在",
                "code": "LP_NOT_FOUND"
            }
        )

    reservation = db.query(Reservation).filter(
        Reservation.id == loading_plan.reservation_id
    ).first()
    if reservation:
        _check_reservation_permission(request.operator, reservation)

    if loading_plan.status not in ["DRAFT"]:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": f"装车计划状态为 {loading_plan.status}，只有 DRAFT 状态可以标记装车",
                "code": "LP_INVALID_STATUS_FOR_LOADING",
                "details": {"plan_status": loading_plan.status}
            }
        )

    lp_box = None
    for box in loading_plan.loading_plan_boxes:
        if box.box_code == request.box_code:
            lp_box = box
            break

    if not lp_box:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": f"装车计划中不存在箱号 {request.box_code}",
                "code": "LP_BOX_NOT_FOUND",
                "details": {"box_code": request.box_code}
            }
        )

    if lp_box.loaded:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": f"箱号 {request.box_code} 已装车",
                "code": "LP_BOX_ALREADY_LOADED"
            }
        )

    lp_box.loaded = True
    lp_box.loaded_at = datetime.now(timezone.utc)
    lp_box.loaded_by = request.operator

    res_box = lp_box.reservation_box
    if res_box:
        res_box.loading_status = "LOADED"
        res_box.loaded_at = datetime.now(timezone.utc)
        res_box.loaded_by = request.operator

    audit_logger.log_box_loaded(db, loading_plan, request.box_code, request.operator)

    db.commit()
    db.refresh(loading_plan)

    return loading_plan


@router.post(
    "/batch-import",
    response_model=ReservationBatchImportResponse,
    responses={
        400: {"model": ErrorResponse, "description": "配置未加载"},
        500: {"model": ErrorResponse, "description": "服务器错误"}
    },
    summary="JSON批量导入预约"
)
def batch_import_reservations(import_request: ReservationBatchImportRequest, db: Session = Depends(get_db)):
    rule_version = _check_res_config_loaded()

    items = import_request.reservations
    total_count = len(items)
    success_count = 0
    failed_count = 0
    imported_reservations = []
    errors = []
    processed_boxes = set()

    for index, item in enumerate(items):
        try:
            if not reservation_config_manager.is_site_valid(item.site_code):
                errors.append(ReservationBatchImportError(
                    index=index,
                    box_codes=item.box_codes,
                    error=f"无效的站点编码: {item.site_code}",
                    code="RES_INVALID_SITE"
                ))
                failed_count += 1
                continue

            if not reservation_config_manager.is_customer_valid(item.customer_code):
                errors.append(ReservationBatchImportError(
                    index=index,
                    box_codes=item.box_codes,
                    error=f"无效的客户编码: {item.customer_code}",
                    code="RES_INVALID_CUSTOMER"
                ))
                failed_count += 1
                continue

            if not reservation_config_manager.is_temperature_zone_valid(item.temperature_zone):
                errors.append(ReservationBatchImportError(
                    index=index,
                    box_codes=item.box_codes,
                    error=f"无效的温控要求: {item.temperature_zone}",
                    code="RES_INVALID_TEMPERATURE_ZONE"
                ))
                failed_count += 1
                continue

            _check_user_site_permission(item.created_by, item.site_code)

            is_valid_time, msg = reservation_config_manager.validate_reservation_time(item.scheduled_date)
            if not is_valid_time:
                errors.append(ReservationBatchImportError(
                    index=index,
                    box_codes=item.box_codes,
                    error=msg,
                    code="RES_INVALID_SCHEDULED_TIME"
                ))
                failed_count += 1
                continue

            if not item.box_codes:
                errors.append(ReservationBatchImportError(
                    index=index,
                    box_codes=item.box_codes,
                    error="预约至少需要一个箱号",
                    code="RES_EMPTY_BOX_LIST"
                ))
                failed_count += 1
                continue

            boxes, validation_errors = _validate_boxes_for_reservation(db, item.box_codes)
            if validation_errors:
                errors.append(ReservationBatchImportError(
                    index=index,
                    box_codes=item.box_codes,
                    error="箱号验证失败",
                    code="RES_BOX_VALIDATION_FAILED",
                    details={"errors": validation_errors}
                ))
                failed_count += 1
                continue

            box_ids = [box.id for box in boxes]
            box_codes_set = set(item.box_codes)

            duplicate_in_batch = box_codes_set & processed_boxes
            if duplicate_in_batch:
                errors.append(ReservationBatchImportError(
                    index=index,
                    box_codes=item.box_codes,
                    error=f"箱号 {', '.join(duplicate_in_batch)} 已在本次导入的其他预约中",
                    code="RES_DUPLICATE_IN_BATCH",
                    details={"duplicate_boxes": list(duplicate_in_batch)}
                ))
                failed_count += 1
                continue

            is_available, conflict_msg = _check_duplicate_box_reservation(db, box_ids)
            if not is_available:
                errors.append(ReservationBatchImportError(
                    index=index,
                    box_codes=item.box_codes,
                    error=conflict_msg,
                    code="RES_DUPLICATE_BOX_RESERVATION"
                ))
                failed_count += 1
                continue

            is_capacity_ok, capacity_msg, used, capacity = _check_vehicle_capacity(
                db, item.vehicle_no, item.scheduled_date, len(boxes), item.vehicle_type
            )
            if not is_capacity_ok:
                errors.append(ReservationBatchImportError(
                    index=index,
                    box_codes=item.box_codes,
                    error=capacity_msg,
                    code="RES_VEHICLE_CAPACITY_EXCEEDED"
                ))
                failed_count += 1
                continue

            is_temp_ok, temp_msg = _check_temperature_zone_consistency(db, box_ids, item.temperature_zone)
            if not is_temp_ok:
                errors.append(ReservationBatchImportError(
                    index=index,
                    box_codes=item.box_codes,
                    error=temp_msg,
                    code="RES_TEMPERATURE_ZONE_CONFLICT"
                ))
                failed_count += 1
                continue

            reservation_no = reservation_config_manager.generate_reservation_no()
            rule_snapshot = reservation_config_manager.get_rule_snapshot()

            reservation = Reservation(
                reservation_no=reservation_no,
                site_code=item.site_code,
                customer_code=item.customer_code,
                temperature_zone=item.temperature_zone,
                vehicle_no=item.vehicle_no,
                vehicle_type=item.vehicle_type,
                scheduled_date=item.scheduled_date,
                status="DRAFT",
                created_by=item.created_by,
                remark=item.remark,
                rule_version=rule_version,
                rule_snapshot=rule_snapshot
            )
            db.add(reservation)
            db.flush()

            for box in boxes:
                res_box = ReservationBox(
                    reservation_id=reservation.id,
                    box_id=box.id,
                    box_code=box.box_code,
                    loading_status="PENDING"
                )
                db.add(res_box)

            db.flush()

            audit_logger.log_reservation_create(db, reservation, item.created_by)

            imported_reservations.append(reservation)
            success_count += 1
            processed_boxes.update(box_codes_set)

        except HTTPException as e:
            errors.append(ReservationBatchImportError(
                index=index,
                box_codes=item.box_codes,
                error=e.detail.get("error", str(e)),
                code=e.detail.get("code", "UNKNOWN_ERROR"),
                details=e.detail.get("details")
            ))
            failed_count += 1
            continue
        except Exception as e:
            errors.append(ReservationBatchImportError(
                index=index,
                box_codes=item.box_codes,
                error=f"系统错误: {str(e)}",
                code="SYSTEM_ERROR"
            ))
            failed_count += 1
            continue

    db.commit()

    for res in imported_reservations:
        db.refresh(res)

    import_summary = {
        "total_count": total_count,
        "success_count": success_count,
        "failed_count": failed_count,
        "import_note": import_request.import_note
    }
    if imported_reservations:
        audit_logger.log_reservation_batch_import(db, import_summary, imported_reservations[0].created_by)

    return ReservationBatchImportResponse(
        success=failed_count == 0,
        total_count=total_count,
        success_count=success_count,
        failed_count=failed_count,
        imported_reservations=imported_reservations,
        errors=errors,
        import_time=datetime.now(timezone.utc),
        rule_version=rule_version
    )


@router.get(
    "/loading-plans/export/csv",
    response_model=LoadingPlanExportResponse,
    responses={
        400: {"model": ErrorResponse, "description": "配置未加载"},
        403: {"model": ErrorResponse, "description": "权限不足"},
        500: {"model": ErrorResponse, "description": "服务器错误"}
    },
    summary="CSV导出装车清单"
)
def export_loading_plan_csv(
    status: Optional[str] = Query(None, description="状态筛选"),
    vehicle_no: Optional[str] = Query(None, description="车牌号筛选"),
    reservation_no: Optional[str] = Query(None, description="关联预约单号筛选"),
    scheduled_date: Optional[date] = Query(None, description="预约日期筛选"),
    operator: Optional[str] = Query(None, description="操作人（用于权限过滤）"),
    db: Session = Depends(get_db)
):
    _check_res_config_loaded()

    query = db.query(LoadingPlan).join(Reservation)

    if operator:
        user_sites = reservation_config_manager.get_user_sites(operator)
        if user_sites:
            query = query.filter(Reservation.site_code.in_(user_sites))

    if status:
        query = query.filter(LoadingPlan.status == status)
    if vehicle_no:
        query = query.filter(LoadingPlan.vehicle_no.ilike(f"%{vehicle_no}%"))
    if reservation_no:
        query = query.filter(Reservation.reservation_no == reservation_no)
    if scheduled_date:
        day_start = datetime.combine(scheduled_date, datetime.min.time())
        day_end = datetime.combine(scheduled_date, datetime.max.time())
        query = query.filter(
            Reservation.scheduled_date >= day_start,
            Reservation.scheduled_date <= day_end
        )

    loading_plans = query.order_by(Reservation.scheduled_date.desc(), LoadingPlan.created_at.desc()).all()

    os.makedirs(EXPORTS_DIR, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    file_name = f"loading_plan_{timestamp}.csv"
    file_path = os.path.join(EXPORTS_DIR, file_name)

    with open(file_path, 'w', encoding='utf-8-sig', newline='') as f:
        writer = csv.writer(f)
        writer.writerow([
            "装车计划号", "关联预约号", "车牌号", "司机", "预计发车时间",
            "状态", "确认人", "确认时间", "站点", "客户", "温控要求",
            "箱号", "装车顺序", "是否已装车", "装车时间", "装车人",
            "规则版本", "创建时间", "更新时间"
        ])

        for lp in loading_plans:
            res = lp.reservation
            for lp_box in sorted(lp.loading_plan_boxes, key=lambda x: x.loading_sequence):
                writer.writerow([
                    lp.plan_no,
                    res.reservation_no if res else "",
                    lp.vehicle_no,
                    lp.driver or "",
                    lp.departure_time.isoformat() if lp.departure_time else "",
                    lp.status,
                    lp.confirmed_by or "",
                    lp.confirmed_at.isoformat() if lp.confirmed_at else "",
                    res.site_code if res else "",
                    res.customer_code if res else "",
                    res.temperature_zone if res else "",
                    lp_box.box_code,
                    lp_box.loading_sequence,
                    lp_box.loaded,
                    lp_box.loaded_at.isoformat() if lp_box.loaded_at else "",
                    lp_box.loaded_by or "",
                    lp.rule_version,
                    lp.created_at.isoformat() if lp.created_at else "",
                    lp.updated_at.isoformat() if lp.updated_at else ""
                ])

    return LoadingPlanExportResponse(
        file_path=file_path,
        file_name=file_name,
        total_count=len(loading_plans),
        exported_at=datetime.now(timezone.utc)
    )


@router.get(
    "/export/csv",
    response_model=LoadingPlanExportResponse,
    responses={
        400: {"model": ErrorResponse, "description": "配置未加载"},
        403: {"model": ErrorResponse, "description": "权限不足"},
        500: {"model": ErrorResponse, "description": "服务器错误"}
    },
    summary="CSV导出预约清单"
)
def export_reservations_csv(
    scheduled_date: Optional[date] = Query(None, description="预约日期筛选"),
    site_code: Optional[str] = Query(None, description="站点编码筛选"),
    status: Optional[str] = Query(None, description="状态筛选"),
    customer_code: Optional[str] = Query(None, description="客户编码筛选"),
    vehicle_no: Optional[str] = Query(None, description="车牌号筛选"),
    operator: Optional[str] = Query(None, description="操作人（用于权限过滤）"),
    db: Session = Depends(get_db)
):
    _check_res_config_loaded()

    query = db.query(Reservation)

    if operator:
        user_sites = reservation_config_manager.get_user_sites(operator)
        if user_sites:
            query = query.filter(Reservation.site_code.in_(user_sites))

    if scheduled_date:
        day_start = datetime.combine(scheduled_date, datetime.min.time())
        day_end = datetime.combine(scheduled_date, datetime.max.time())
        query = query.filter(
            Reservation.scheduled_date >= day_start,
            Reservation.scheduled_date <= day_end
        )
    if site_code:
        query = query.filter(Reservation.site_code == site_code)
    if status:
        query = query.filter(Reservation.status == status)
    if customer_code:
        query = query.filter(Reservation.customer_code == customer_code)
    if vehicle_no:
        query = query.filter(Reservation.vehicle_no.ilike(f"%{vehicle_no}%"))

    reservations = query.order_by(Reservation.scheduled_date.desc(), Reservation.created_at.desc()).all()

    os.makedirs(EXPORTS_DIR, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    file_name = f"reservations_{timestamp}.csv"
    file_path = os.path.join(EXPORTS_DIR, file_name)

    with open(file_path, 'w', encoding='utf-8-sig', newline='') as f:
        writer = csv.writer(f)
        writer.writerow([
            "预约单号", "站点", "客户", "温控要求", "车牌号", "车辆类型",
            "预约时间", "状态", "创建人", "备注", "箱号", "装车状态",
            "取消时间", "取消人", "取消原因", "规则版本",
            "创建时间", "更新时间"
        ])

        for res in reservations:
            for rb in res.reservation_boxes:
                writer.writerow([
                    res.reservation_no,
                    res.site_code,
                    res.customer_code,
                    res.temperature_zone,
                    res.vehicle_no,
                    res.vehicle_type or "",
                    res.scheduled_date.isoformat(),
                    res.status,
                    res.created_by,
                    res.remark or "",
                    rb.box_code,
                    rb.loading_status,
                    res.cancelled_at.isoformat() if res.cancelled_at else "",
                    res.cancelled_by or "",
                    res.cancel_reason or "",
                    res.rule_version,
                    res.created_at.isoformat(),
                    res.updated_at.isoformat()
                ])

    return LoadingPlanExportResponse(
        file_path=file_path,
        file_name=file_name,
        total_count=len(reservations),
        exported_at=datetime.now(timezone.utc)
    )
