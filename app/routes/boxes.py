from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
from datetime import datetime, timezone
from ..database import get_db
from ..models import Sample, Box, TransferRecord
from ..schemas import (
    BoxCreate,
    BoxResponse,
    BoxPackRequest,
    TransferRequest,
    TransferResponse,
    TransferRecordResponse,
    TransferRevokeRequest,
    TransferRevokeResponse,
    AcceptanceRequest,
    HandoverFormResponse,
    ExceptionListResponse,
    ErrorResponse
)
from ..config_manager import config_manager
from ..audit import audit_logger
import json
import os

router = APIRouter(prefix="/api/boxes", tags=["boxes"])

EXPORTS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "exports")


@router.post(
    "",
    response_model=BoxResponse,
    responses={
        400: {"model": ErrorResponse, "description": "请求参数错误"},
        409: {"model": ErrorResponse, "description": "箱号重复"},
        500: {"model": ErrorResponse, "description": "服务器错误"}
    },
    summary="创建转运箱"
)
def create_box(box_data: BoxCreate, db: Session = Depends(get_db)):
    """
    创建新的转运箱。

    - **box_code**: 箱号，唯一标识
    - **destination**: 目的地检测点
    - **current_custodian**: 当前保管人
    """
    rule_version = config_manager.get_current_version()
    if not rule_version:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": "系统配置未加载，请先加载规则配置",
                "code": "CONFIG_NOT_LOADED"
            }
        )

    existing = db.query(Box).filter(Box.box_code == box_data.box_code).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": f"箱号 {box_data.box_code} 已存在",
                "code": "DUPLICATE_BOX_CODE"
            }
        )

    box = Box(
        box_code=box_data.box_code,
        destination=box_data.destination,
        current_custodian=box_data.current_custodian,
        rule_version=rule_version
    )
    db.add(box)
    db.flush()

    audit_logger.log_box_create(db, box, box_data.current_custodian)
    db.commit()
    db.refresh(box)

    return box


@router.get(
    "",
    response_model=List[BoxResponse],
    summary="查询转运箱列表"
)
def get_boxes(
    status: str = None,
    box_code: str = None,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db)
):
    query = db.query(Box)
    if status:
        query = query.filter(Box.status == status)
    if box_code:
        query = query.filter(Box.box_code.ilike(f"%{box_code}%"))
    return query.order_by(Box.created_at.desc()).offset(skip).limit(limit).all()


@router.get(
    "/{box_code}",
    response_model=BoxResponse,
    responses={404: {"model": ErrorResponse, "description": "转运箱不存在"}},
    summary="查询单个转运箱"
)
def get_box(box_code: str, db: Session = Depends(get_db)):
    box = db.query(Box).filter(Box.box_code == box_code).first()
    if not box:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": f"转运箱 {box_code} 不存在",
                "code": "BOX_NOT_FOUND"
            }
        )
    return box


@router.post(
    "/pack",
    response_model=BoxResponse,
    responses={
        400: {"model": ErrorResponse, "description": "请求错误"},
        404: {"model": ErrorResponse, "description": "箱或样本不存在"},
        409: {"model": ErrorResponse, "description": "状态冲突"}
    },
    summary="样本装箱"
)
def pack_box(request: BoxPackRequest, db: Session = Depends(get_db)):
    """
    将样本装入转运箱，批量装箱。

    - **box_code**: 箱号
    - **barcodes**: 要装箱的样本条码列表
    - **custodian**: 操作人

    错误码：
    - `BOX_NOT_FOUND`: 转运箱不存在
    - `BOX_NOT_OPEN`: 转运箱不是OPEN状态，不能装箱
    - `INVALID_CUSTODIAN`: 非当前保管人操作
    - `SAMPLE_NOT_FOUND`: 样本不存在
    - `SAMPLE_ALREADY_BOXED`: 样本已装箱
    - `SAMPLE_ISOLATED`: 已隔离样本不能装箱
    - `SAMPLE_INVALID_STATUS`: 样本状态不允许装箱
    """
    box = db.query(Box).filter(Box.box_code == request.box_code).first()
    if not box:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": f"转运箱 {request.box_code} 不存在",
                "code": "BOX_NOT_FOUND"
            }
        )

    if box.status != "OPEN":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": f"转运箱状态为 {box.status}，只有OPEN状态才能装箱",
                "code": "BOX_NOT_OPEN",
                "details": {"box_status": box.status}
            }
        )

    if box.current_custodian != request.custodian:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": f"当前保管人是 {box.current_custodian}，{request.custodian} 无权操作此箱",
                "code": "INVALID_CUSTODIAN",
                "details": {
                    "current_custodian": box.current_custodian,
                    "operation_custodian": request.custodian
                }
            }
        )

    samples_to_pack = []
    for barcode in request.barcodes:
        sample = db.query(Sample).filter(Sample.barcode == barcode).first()
        if not sample:
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "error": f"样本 {barcode} 不存在",
                    "code": "SAMPLE_NOT_FOUND",
                    "details": {"barcode": barcode}
                }
            )

        if sample.box_id is not None:
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "error": f"样本 {barcode} 已装箱，不能重复装箱",
                    "code": "SAMPLE_ALREADY_BOXED",
                    "details": {"barcode": barcode, "box_id": sample.box_id}
                }
            )

        if sample.is_isolated or sample.status == "ISOLATED":
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "error": f"样本 {barcode} 已隔离，不能装箱流转",
                    "code": "SAMPLE_ISOLATED",
                    "details": {"barcode": barcode, "isolation_reason": sample.isolation_reason}
                }
            )

        if sample.status != "CREATED":
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "error": f"样本 {barcode} 状态为 {sample.status}，只有CREATED状态才能装箱",
                    "code": "SAMPLE_INVALID_STATUS",
                    "details": {"barcode": barcode, "current_status": sample.status}
                }
            )

        if not config_manager.can_transition_status(sample.status, "BOXED"):
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "error": f"样本 {barcode} 状态 {sample.status} 不能转为BOXED",
                    "code": "INVALID_STATUS_TRANSITION"
                }
            )

        samples_to_pack.append(sample)

    for sample in samples_to_pack:
        old_status = sample.status
        sample.box_id = box.id
        sample.status = "BOXED"
        sample.current_custodian = request.custodian
        audit_logger.log_sample_status_change(
            db, sample, old_status, "BOXED", request.custodian, "PACK"
        )

    old_box_status = box.status
    box.status = "OPEN"
    db.commit()
    db.refresh(box)

    return box


@router.post(
    "/seal",
    response_model=BoxResponse,
    summary="封箱"
)
def seal_box(box_code: str, custodian: str, db: Session = Depends(get_db)):
    """
    封箱，装箱完成后封存转运箱。
    """
    box = db.query(Box).filter(Box.box_code == box_code).first()
    if not box:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": f"转运箱 {box_code} 不存在", "code": "BOX_NOT_FOUND"}
        )

    if box.current_custodian != custodian:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": f"当前保管人是 {box.current_custodian}，{custodian} 无权操作",
                "code": "INVALID_CUSTODIAN"
            }
        )

    if box.status != "OPEN":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": f"转运箱状态为 {box.status}，只有OPEN状态才能封箱",
                "code": "BOX_NOT_OPEN"
            }
        )

    old_status = box.status
    box.status = "SEALED"
    box.sealed_at = datetime.now(timezone.utc)

    for sample in box.samples:
        sample.status = "SEALED"
        sample.current_custodian = custodian
        audit_logger.log_sample_status_change(
            db, sample, "BOXED", "SEALED", custodian, "SEAL"
        )

    audit_logger.log_box_status_change(db, box, old_status, "SEALED", custodian, "SEAL")
    db.commit()
    db.refresh(box)

    return box


@router.post(
    "/transfer",
    response_model=TransferResponse,
    responses={
        400: {"model": ErrorResponse, "description": "请求错误"},
        404: {"model": ErrorResponse, "description": "箱不存在"},
        409: {"model": ErrorResponse, "description": "状态冲突或权限错误"}
    },
    summary="交接转运"
)
def transfer_box(request: TransferRequest, db: Session = Depends(get_db)):
    """
    转运箱交接，从当前保管人转交给下一个保管人。

    - **box_code**: 箱号
    - **to_point**: 接收点
    - **to_custodian**: 接收人
    - **from_custodian**: 交出人
    - **temperature**: 交接时温度
    - **temperature_records**: 温度记录（JSON格式数组）

    错误码：
    - `BOX_NOT_FOUND`: 转运箱不存在
    - `BOX_NOT_SEALED`: 转运箱未封箱，不能交接
    - `INVALID_CUSTODIAN`: 交出人不是当前保管人
    - `SAMPLE_ISOLATED`: 箱内有已隔离样本
    - `INVALID_TEMPERATURE_FORMAT`: 温度记录格式错误
    - `TEMPERATURE_VIOLATION`: 温度超出范围
    """
    box = db.query(Box).filter(Box.box_code == request.box_code).first()
    if not box:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": f"转运箱 {request.box_code} 不存在",
                "code": "BOX_NOT_FOUND"
            }
        )

    if box.status not in ["SEALED", "IN_TRANSIT"]:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": f"转运箱状态为 {box.status}，必须先封箱(SEALED)才能交接",
                "code": "BOX_NOT_SEALED",
                "details": {"box_status": box.status}
            }
        )

    if box.current_custodian != request.from_custodian:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": f"当前保管人是 {box.current_custodian}，{request.from_custodian} 不是当前保管人，无权提交交接",
                "code": "INVALID_CUSTODIAN",
                "details": {
                    "current_custodian": box.current_custodian,
                    "from_custodian": request.from_custodian
                }
            }
        )

    for sample in box.samples:
        if sample.is_isolated or sample.status == "ISOLATED":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "error": f"箱内样本 {sample.barcode} 已隔离，不能继续流转",
                    "code": "SAMPLE_ISOLATED",
                    "details": {"barcode": sample.barcode, "isolation_reason": sample.isolation_reason}
                }
            )

    if request.temperature_records:
        sample_type = box.samples[0].sample_type if box.samples else "blood"
        is_valid, errors = config_manager.validate_temperature_records(
            request.temperature_records, sample_type
        )
        if not is_valid:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "error": "温度记录格式错误",
                    "code": "INVALID_TEMPERATURE_FORMAT",
                    "details": {"errors": errors}
                }
            )

    if request.temperature is not None and box.samples:
        temp_validations = []
        for sample in box.samples:
            is_ok, msg = config_manager.check_temperature(sample.sample_type, request.temperature)
            if not is_ok:
                temp_validations.append({"barcode": sample.barcode, "message": msg})

        if temp_validations:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "error": "温度超出允许范围",
                    "code": "TEMPERATURE_VIOLATION",
                    "details": {"violations": temp_validations}
                }
            )

    from_point = box.samples[0].collection_point if box.samples else "UNKNOWN"

    transfer = TransferRecord(
        box_id=box.id,
        from_point=from_point,
        to_point=request.to_point,
        from_custodian=request.from_custodian,
        to_custodian=request.to_custodian,
        status="IN_TRANSIT",
        temperature=request.temperature,
        rule_version=config_manager.get_current_version() or "UNKNOWN"
    )
    db.add(transfer)
    db.flush()

    old_box_status = box.status
    box.status = "IN_TRANSIT"
    box.current_custodian = request.to_custodian
    box.temperature_records = request.temperature_records or box.temperature_records

    for sample in box.samples:
        old_sample_status = sample.status
        sample.status = "IN_TRANSIT"
        sample.current_custodian = request.to_custodian
        audit_logger.log_sample_status_change(
            db, sample, old_sample_status, "IN_TRANSIT", request.to_custodian, "TRANSFER"
        )

    audit_logger.log_box_status_change(
        db, box, old_box_status, "IN_TRANSIT", request.to_custodian, "TRANSFER"
    )
    audit_logger.log_transfer(db, transfer, request.from_custodian)

    db.commit()
    db.refresh(transfer)

    return TransferResponse(
        transfer_id=transfer.id,
        box_code=box.box_code,
        from_point=transfer.from_point,
        to_point=transfer.to_point,
        from_custodian=transfer.from_custodian,
        to_custodian=transfer.to_custodian,
        transfer_time=transfer.transfer_time,
        status=transfer.status,
        temperature=transfer.temperature,
        rule_version=transfer.rule_version
    )


@router.post(
    "/accept",
    response_model=BoxResponse,
    responses={
        400: {"model": ErrorResponse, "description": "请求错误"},
        404: {"model": ErrorResponse, "description": "箱不存在"},
        409: {"model": ErrorResponse, "description": "状态冲突"}
    },
    summary="到站验收"
)
def accept_box(request: AcceptanceRequest, db: Session = Depends(get_db)):
    """
    到站验收，确认转运箱送达目的地。

    - **box_code**: 箱号
    - **custodian**: 验收人
    - **temperature_records**: 温度记录
    - **check_duration**: 是否检查时限

    错误码：
    - `BOX_NOT_FOUND`: 转运箱不存在
    - `BOX_NOT_IN_TRANSIT`: 转运箱不在运输中
    - `INVALID_CUSTODIAN`: 验收人不是当前保管人
    - `SAMPLE_ISOLATED`: 箱内有已隔离样本，不能继续流转
    - `TIME_LIMIT_VIOLATION`: 超出时限
    - `INVALID_TEMPERATURE_FORMAT`: 温度记录格式错误
    """
    box = db.query(Box).filter(Box.box_code == request.box_code).first()
    if not box:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": f"转运箱 {request.box_code} 不存在",
                "code": "BOX_NOT_FOUND"
            }
        )

    if box.status != "IN_TRANSIT":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": f"转运箱状态为 {box.status}，只有运输中(IN_TRANSIT)才能验收",
                "code": "BOX_NOT_IN_TRANSIT",
                "details": {"box_status": box.status}
            }
        )

    if box.current_custodian != request.custodian:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": f"当前保管人是 {box.current_custodian}，{request.custodian} 无权验收",
                "code": "INVALID_CUSTODIAN"
            }
        )

    for sample in box.samples:
        if sample.is_isolated or sample.status == "ISOLATED":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "error": f"箱内样本 {sample.barcode} 已隔离，不能继续流转验收",
                    "code": "SAMPLE_ISOLATED",
                    "details": {"barcode": sample.barcode, "isolation_reason": sample.isolation_reason}
                }
            )

    if request.temperature_records:
        sample_type = box.samples[0].sample_type if box.samples else "blood"
        is_valid, errors = config_manager.validate_temperature_records(
            request.temperature_records, sample_type
        )
        if not is_valid:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "error": "温度记录格式错误",
                    "code": "INVALID_TEMPERATURE_FORMAT",
                    "details": {"errors": errors}
                }
            )
        box.temperature_records = request.temperature_records

    if request.check_duration:
        last_transfer = db.query(TransferRecord).filter(
            TransferRecord.box_id == box.id
        ).order_by(TransferRecord.transfer_time.desc()).first()

        if last_transfer:
            duration_minutes = int((datetime.utcnow() - last_transfer.transfer_time).total_seconds() / 60)
            time_violations = []
            for sample in box.samples:
                is_ok, msg = config_manager.check_transfer_duration(
                    sample.sample_type, duration_minutes
                )
                if not is_ok:
                    time_violations.append({"barcode": sample.barcode, "message": msg})

                is_ok, msg = config_manager.check_collection_time_limit(
                    sample.sample_type, sample.collection_time
                )
                if not is_ok:
                    time_violations.append({"barcode": sample.barcode, "message": msg})

            if time_violations:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail={
                        "error": "转运时限检查不通过",
                        "code": "TIME_LIMIT_VIOLATION",
                        "details": {"violations": time_violations, "duration_minutes": duration_minutes}
                    }
                )

    old_box_status = box.status
    box.status = "DELIVERED"

    for sample in box.samples:
        old_sample_status = sample.status
        sample.status = "DELIVERED"
        sample.current_custodian = request.custodian
        audit_logger.log_sample_status_change(
            db, sample, old_sample_status, "DELIVERED", request.custodian, "ACCEPT"
        )

    audit_logger.log_box_status_change(
        db, box, old_box_status, "DELIVERED", request.custodian, "ACCEPT"
    )
    db.commit()
    db.refresh(box)

    return box


@router.post(
    "/revoke-transfer",
    response_model=TransferRevokeResponse,
    responses={
        400: {"model": ErrorResponse, "description": "请求错误或权限不足"},
        404: {"model": ErrorResponse, "description": "箱不存在或无交接记录"},
        409: {"model": ErrorResponse, "description": "状态冲突，无法撤回"}
    },
    summary="撤回交接记录"
)
def revoke_transfer(request: TransferRevokeRequest, db: Session = Depends(get_db)):
    """
    撤回最近一条交接记录，将箱子和箱内样本恢复到可重新交接的状态。

    - **box_code**: 箱号
    - **custodian**: 操作人（必须是当前保管人）
    - **reason**: 撤回原因

    限制条件：
    - 只有 SEALED 或 IN_TRANSIT 状态的箱子可以撤回
    - 已经到站验收(DELIVERED)、隔离(ISOLATED)、检测(TESTING/COMPLETED)或归档(ARCHIVED)的记录不能撤回
    - 箱内所有样本状态必须允许撤回
    - 不能重复撤回同一条交接记录

    错误码：
    - `BOX_NOT_FOUND`: 转运箱不存在
    - `INVALID_CUSTODIAN`: 非当前保管人操作
    - `BOX_INVALID_STATUS`: 箱子状态不允许撤回
    - `NO_TRANSFER_RECORD`: 没有可撤回的交接记录
    - `TRANSFER_ALREADY_REVOKED`: 最近一条交接记录已被撤回
    - `SAMPLE_INVALID_STATUS`: 箱内样本状态不允许撤回
    - `SAMPLE_ISOLATED`: 箱内有已隔离样本
    """
    box = db.query(Box).filter(Box.box_code == request.box_code).first()
    if not box:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": f"转运箱 {request.box_code} 不存在",
                "code": "BOX_NOT_FOUND"
            }
        )

    if box.current_custodian != request.custodian:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": f"当前保管人是 {box.current_custodian}，{request.custodian} 无权操作",
                "code": "INVALID_CUSTODIAN",
                "details": {
                    "current_custodian": box.current_custodian,
                    "operation_custodian": request.custodian
                }
            }
        )

    if box.status not in ["SEALED", "IN_TRANSIT"]:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": f"转运箱状态为 {box.status}，只有 SEALED 或 IN_TRANSIT 状态才能撤回",
                "code": "BOX_INVALID_STATUS",
                "details": {"box_status": box.status}
            }
        )

    all_transfers = db.query(TransferRecord).filter(
        TransferRecord.box_id == box.id
    ).order_by(TransferRecord.transfer_time.desc()).all()

    if not all_transfers:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "没有可撤回的交接记录",
                "code": "NO_TRANSFER_RECORD"
            }
        )

    last_transfer = all_transfers[0]

    if last_transfer.is_revoked:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "最近一条交接记录已被撤回，无需重复操作",
                "code": "TRANSFER_ALREADY_REVOKED",
                "details": {"transfer_id": last_transfer.id}
            }
        )

    for sample in box.samples:
        if sample.is_isolated or sample.status == "ISOLATED":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "error": f"箱内样本 {sample.barcode} 已隔离，不能撤回交接",
                    "code": "SAMPLE_ISOLATED",
                    "details": {"barcode": sample.barcode, "isolation_reason": sample.isolation_reason}
                }
            )
        if sample.status not in ["SEALED", "IN_TRANSIT"]:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "error": f"箱内样本 {sample.barcode} 状态为 {sample.status}，不允许撤回",
                    "code": "SAMPLE_INVALID_STATUS",
                    "details": {"barcode": sample.barcode, "sample_status": sample.status}
                }
            )

    old_box_status = box.status
    old_box_custodian = box.current_custodian
    new_box_custodian = last_transfer.from_custodian

    last_transfer.is_revoked = True
    last_transfer.revoked_at = datetime.now(timezone.utc)
    last_transfer.revoked_by = request.custodian
    last_transfer.revoke_reason = request.reason

    old_box_status_val = box.status
    box.status = "SEALED"
    box.current_custodian = last_transfer.from_custodian

    for sample in box.samples:
        old_sample_status = sample.status
        old_sample_custodian = sample.current_custodian
        sample.status = "SEALED"
        sample.current_custodian = last_transfer.from_custodian
        audit_logger.log_sample_revoke_transfer(
            db, sample,
            old_sample_status, "SEALED",
            old_sample_custodian, last_transfer.from_custodian,
            request.custodian, last_transfer.id, request.reason
        )

    audit_logger.log_box_revoke_transfer(
        db, box,
        old_box_status_val, "SEALED",
        old_box_custodian, last_transfer.from_custodian,
        request.custodian, last_transfer.id, request.reason
    )
    audit_logger.log_transfer_revoke(db, last_transfer, request.custodian, request.reason)

    db.commit()
    db.refresh(last_transfer)
    db.refresh(box)

    return TransferRevokeResponse(
        success=True,
        message=f"交接记录已撤回，箱子和样本已恢复到 SEALED 状态",
        revoked_transfer_id=last_transfer.id,
        box_code=box.box_code,
        old_box_status=old_box_status,
        new_box_status="SEALED",
        old_custodian=old_box_custodian,
        new_custodian=new_box_custodian,
        rule_version=config_manager.get_current_version() or "UNKNOWN"
    )


@router.get(
    "/{box_code}/transfer-history",
    response_model=List[TransferRecordResponse],
    responses={404: {"model": ErrorResponse, "description": "转运箱不存在"}},
    summary="查询转运箱交接记录历史"
)
def get_transfer_history(box_code: str, db: Session = Depends(get_db)):
    """
    查询转运箱的所有交接记录历史，包括已撤回的记录。
    """
    box = db.query(Box).filter(Box.box_code == box_code).first()
    if not box:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": f"转运箱 {box_code} 不存在", "code": "BOX_NOT_FOUND"}
        )

    transfers = db.query(TransferRecord).filter(
        TransferRecord.box_id == box.id
    ).order_by(TransferRecord.transfer_time.desc()).all()

    return transfers


@router.post(
    "/{box_code}/complete-testing",
    response_model=BoxResponse,
    summary="完成检测"
)
def complete_testing(box_code: str, custodian: str, db: Session = Depends(get_db)):
    """
    标记箱内所有样本检测完成。
    """
    box = db.query(Box).filter(Box.box_code == box_code).first()
    if not box:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": f"转运箱 {box_code} 不存在", "code": "BOX_NOT_FOUND"}
        )

    if box.status != "DELIVERED":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": f"转运箱状态为 {box.status}，必须先验收(DELIVERED)",
                "code": "BOX_NOT_DELIVERED"
            }
        )

    for sample in box.samples:
        if sample.is_isolated or sample.status == "ISOLATED":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "error": f"样本 {sample.barcode} 已隔离，不能标记检测完成",
                    "code": "SAMPLE_ISOLATED"
                }
            )
        old_status = sample.status
        sample.status = "TESTING"
        audit_logger.log_sample_status_change(
            db, sample, old_status, "TESTING", custodian, "START_TESTING"
        )

    for sample in box.samples:
        old_status = sample.status
        sample.status = "COMPLETED"
        sample.current_custodian = custodian
        audit_logger.log_sample_status_change(
            db, sample, old_status, "COMPLETED", custodian, "COMPLETE_TESTING"
        )

    old_box_status = box.status
    box.status = "TESTING_COMPLETED"
    box.current_custodian = custodian
    audit_logger.log_box_status_change(
        db, box, old_box_status, "TESTING_COMPLETED", custodian, "COMPLETE_TESTING"
    )

    db.commit()
    db.refresh(box)
    return box


@router.get(
    "/{box_code}/handover-form",
    response_model=HandoverFormResponse,
    summary="生成交接单"
)
def get_handover_form(box_code: str, db: Session = Depends(get_db)):
    """
    生成转运箱交接单，包含撤回历史记录。
    """
    box = db.query(Box).filter(Box.box_code == box_code).first()
    if not box:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": f"转运箱 {box_code} 不存在", "code": "BOX_NOT_FOUND"}
        )

    all_transfers = db.query(TransferRecord).filter(
        TransferRecord.box_id == box.id
    ).order_by(TransferRecord.transfer_time.desc()).all()

    active_transfer = None
    for t in all_transfers:
        if not t.is_revoked:
            active_transfer = t
            break

    revoked_history = []
    for t in all_transfers:
        if t.is_revoked:
            revoked_history.append({
                "transfer_id": t.id,
                "from_point": t.from_point,
                "to_point": t.to_point,
                "from_custodian": t.from_custodian,
                "to_custodian": t.to_custodian,
                "transfer_time": t.transfer_time.isoformat() if t.transfer_time else None,
                "temperature": t.temperature,
                "rule_version": t.rule_version,
                "revoked_at": t.revoked_at.isoformat() if t.revoked_at else None,
                "revoked_by": t.revoked_by,
                "revoke_reason": t.revoke_reason
            })

    transfer = active_transfer

    samples = []
    for sample in box.samples:
        samples.append({
            "barcode": sample.barcode,
            "sample_type": sample.sample_type,
            "collection_point": sample.collection_point,
            "collection_time": sample.collection_time.isoformat(),
            "status": sample.status
        })

    form = HandoverFormResponse(
        box_code=box.box_code,
        transfer_id=transfer.id if transfer else 0,
        from_point=transfer.from_point if transfer else box.samples[0].collection_point if box.samples else "UNKNOWN",
        to_point=transfer.to_point if transfer else box.destination,
        from_custodian=transfer.from_custodian if transfer else box.current_custodian,
        to_custodian=transfer.to_custodian if transfer else box.current_custodian,
        transfer_time=transfer.transfer_time if transfer else datetime.now(timezone.utc),
        samples=samples,
        temperature=transfer.temperature if transfer else None,
        rule_version=box.rule_version,
        is_revoked=transfer.is_revoked if transfer else None,
        revoked_at=transfer.revoked_at if transfer else None,
        revoked_by=transfer.revoked_by if transfer else None,
        revoke_reason=transfer.revoke_reason if transfer else None,
        revoked_transfer_history=revoked_history if revoked_history else None
    )

    os.makedirs(EXPORTS_DIR, exist_ok=True)
    export_path = os.path.join(EXPORTS_DIR, f"handover_form_{box_code}.json")
    with open(export_path, 'w', encoding='utf-8') as f:
        json.dump(form.model_dump(), f, ensure_ascii=False, indent=2, default=str)

    return form


@router.get(
    "/{box_code}/exception-list",
    response_model=ExceptionListResponse,
    summary="生成异常清单"
)
def get_exception_list(box_code: str, db: Session = Depends(get_db)):
    """
    生成转运箱异常清单，包含撤回历史记录。
    """
    box = db.query(Box).filter(Box.box_code == box_code).first()
    if not box:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": f"转运箱 {box_code} 不存在", "code": "BOX_NOT_FOUND"}
        )

    exceptions = []

    if box.temperature_records:
        try:
            records = json.loads(box.temperature_records)
            for i, record in enumerate(records):
                if isinstance(record, dict) and "temperature" in record:
                    for sample in box.samples:
                        is_ok, msg = config_manager.check_temperature(
                            sample.sample_type, record["temperature"]
                        )
                        if not is_ok:
                            exceptions.append({
                                "type": "TEMPERATURE_VIOLATION",
                                "barcode": sample.barcode,
                                "record_index": i + 1,
                                "temperature": record["temperature"],
                                "message": msg
                            })
        except json.JSONDecodeError:
            exceptions.append({
                "type": "INVALID_TEMPERATURE_RECORDS",
                "message": "温度记录格式错误，无法解析"
            })

    for sample in box.samples:
        if sample.is_isolated:
            exceptions.append({
                "type": "SAMPLE_ISOLATED",
                "barcode": sample.barcode,
                "reason": sample.isolation_reason
            })

        is_ok, msg = config_manager.check_collection_time_limit(
            sample.sample_type, sample.collection_time
        )
        if not is_ok:
            exceptions.append({
                "type": "TIME_LIMIT_VIOLATION",
                "barcode": sample.barcode,
                "message": msg
            })

    all_transfers = db.query(TransferRecord).filter(
        TransferRecord.box_id == box.id
    ).order_by(TransferRecord.transfer_time.desc()).all()

    revoked_history = []
    for t in all_transfers:
        if t.is_revoked:
            revoked_history.append({
                "transfer_id": t.id,
                "from_point": t.from_point,
                "to_point": t.to_point,
                "from_custodian": t.from_custodian,
                "to_custodian": t.to_custodian,
                "transfer_time": t.transfer_time.isoformat() if t.transfer_time else None,
                "temperature": t.temperature,
                "rule_version": t.rule_version,
                "revoked_at": t.revoked_at.isoformat() if t.revoked_at else None,
                "revoked_by": t.revoked_by,
                "revoke_reason": t.revoke_reason
            })

    for t in all_transfers:
        if t.is_revoked:
            exceptions.append({
                "type": "TRANSFER_REVOKED",
                "transfer_id": t.id,
                "revoked_at": t.revoked_at.isoformat() if t.revoked_at else None,
                "revoked_by": t.revoked_by,
                "revoke_reason": t.revoke_reason,
                "message": f"交接记录已被撤回: {t.revoke_reason}"
            })

    result = ExceptionListResponse(
        box_code=box_code,
        exceptions=exceptions,
        generated_at=datetime.now(timezone.utc),
        total_exceptions=len(exceptions),
        revoked_transfer_history=revoked_history if revoked_history else None
    )

    os.makedirs(EXPORTS_DIR, exist_ok=True)
    export_path = os.path.join(EXPORTS_DIR, f"exception_list_{box_code}.json")
    with open(export_path, 'w', encoding='utf-8') as f:
        json.dump(result.model_dump(), f, ensure_ascii=False, indent=2, default=str)

    return result
