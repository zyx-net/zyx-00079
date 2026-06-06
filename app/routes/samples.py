from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
from datetime import datetime, timezone
from ..database import get_db
from ..models import Sample, Box
from ..schemas import (
    SampleCreate,
    SampleResponse,
    IsolationRequest,
    ResultArchiveRequest,
    ErrorResponse
)
from ..config_manager import config_manager, ConfigValidationError
from ..audit import audit_logger

router = APIRouter(prefix="/api/samples", tags=["samples"])


@router.post(
    "",
    response_model=SampleResponse,
    responses={
        400: {"model": ErrorResponse, "description": "请求参数错误"},
        409: {"model": ErrorResponse, "description": "条码重复"},
        500: {"model": ErrorResponse, "description": "服务器错误"}
    },
    summary="样本建档"
)
def create_sample(sample_data: SampleCreate, db: Session = Depends(get_db)):
    """
    创建新样本记录，实现样本建档功能。

    - **barcode**: 样本条码，唯一标识
    - **sample_type**: 样本类型（blood/saliva/nucleic_acid/urine）
    - **collection_point**: 采集点名称
    - **collection_time**: 采集时间
    - **patient_info**: 患者信息（JSON格式）
    - **current_custodian**: 当前保管人

    错误码：
    - `DUPLICATE_BARCODE`: 条码已存在
    - `INVALID_SAMPLE_TYPE`: 无效的样本类型
    - `CONFIG_NOT_LOADED`: 配置未加载
    """
    try:
        rule_version = config_manager.get_current_version()
        if not rule_version:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail={
                    "error": "系统配置未加载，请先加载规则配置",
                    "code": "CONFIG_NOT_LOADED"
                }
            )

        if not config_manager.is_sample_type_valid(sample_data.sample_type):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "error": f"无效的样本类型: {sample_data.sample_type}",
                    "code": "INVALID_SAMPLE_TYPE",
                    "details": {"valid_types": config_manager.get_current_config().get("sample_types", [])}
                }
            )

        existing = db.query(Sample).filter(Sample.barcode == sample_data.barcode).first()
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "error": f"条码 {sample_data.barcode} 已存在，不能重复建档",
                    "code": "DUPLICATE_BARCODE",
                    "details": {"existing_barcode": sample_data.barcode}
                }
            )

        sample = Sample(
            barcode=sample_data.barcode,
            sample_type=sample_data.sample_type,
            collection_point=sample_data.collection_point,
            collection_time=sample_data.collection_time,
            patient_info=sample_data.patient_info,
            status="CREATED",
            current_custodian=sample_data.current_custodian,
            rule_version=rule_version
        )
        db.add(sample)
        db.flush()

        audit_logger.log_sample_create(db, sample, sample_data.current_custodian)
        db.commit()
        db.refresh(sample)

        return sample

    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": f"创建样本失败: {str(e)}",
                "code": "CREATE_SAMPLE_ERROR"
            }
        )


@router.get(
    "",
    response_model=List[SampleResponse],
    summary="查询样本列表"
)
def get_samples(
    status: str = None,
    barcode: str = None,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db)
):
    query = db.query(Sample)
    if status:
        query = query.filter(Sample.status == status)
    if barcode:
        query = query.filter(Sample.barcode.ilike(f"%{barcode}%"))
    return query.order_by(Sample.created_at.desc()).offset(skip).limit(limit).all()


@router.get(
    "/{barcode}",
    response_model=SampleResponse,
    responses={404: {"model": ErrorResponse, "description": "样本不存在"}},
    summary="查询单个样本"
)
def get_sample(barcode: str, db: Session = Depends(get_db)):
    sample = db.query(Sample).filter(Sample.barcode == barcode).first()
    if not sample:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": f"样本 {barcode} 不存在",
                "code": "SAMPLE_NOT_FOUND"
            }
        )
    return sample


@router.post(
    "/isolate",
    response_model=SampleResponse,
    responses={
        400: {"model": ErrorResponse, "description": "请求错误"},
        404: {"model": ErrorResponse, "description": "样本不存在"},
        409: {"model": ErrorResponse, "description": "样本已隔离"}
    },
    summary="异常隔离"
)
def isolate_sample(request: IsolationRequest, db: Session = Depends(get_db)):
    """
    将异常样本隔离，隔离后的样本不能继续流转。

    - **barcode**: 样本条码
    - **custodian**: 操作人
    - **reason**: 隔离原因

    错误码：
    - `SAMPLE_NOT_FOUND`: 样本不存在
    - `ALREADY_ISOLATED`: 样本已处于隔离状态
    - `INVALID_STATUS_TRANSITION`: 状态流转不合法
    """
    sample = db.query(Sample).filter(Sample.barcode == request.barcode).first()
    if not sample:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": f"样本 {request.barcode} 不存在",
                "code": "SAMPLE_NOT_FOUND"
            }
        )

    if sample.is_isolated or sample.status == "ISOLATED":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": f"样本 {request.barcode} 已处于隔离状态，无需重复隔离",
                "code": "ALREADY_ISOLATED",
                "details": {"current_status": sample.status}
            }
        )

    old_status = sample.status
    if not config_manager.can_transition_status(old_status, "ISOLATED"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": f"状态 {old_status} 不能直接转为隔离状态",
                "code": "INVALID_STATUS_TRANSITION",
                "details": {"current_status": old_status, "target_status": "ISOLATED"}
            }
        )

    sample.status = "ISOLATED"
    sample.is_isolated = True
    sample.isolation_reason = request.reason
    sample.current_custodian = request.custodian

    audit_logger.log_isolation(db, sample, request.custodian, request.reason)
    db.commit()
    db.refresh(sample)

    return sample


@router.post(
    "/archive",
    response_model=SampleResponse,
    responses={
        400: {"model": ErrorResponse, "description": "请求错误"},
        404: {"model": ErrorResponse, "description": "样本不存在"},
        409: {"model": ErrorResponse, "description": "样本状态不允许归档"}
    },
    summary="结果归档"
)
def archive_sample_result(request: ResultArchiveRequest, db: Session = Depends(get_db)):
    """
    归档样本检测结果，完成样本生命周期。

    - **barcode**: 样本条码
    - **custodian**: 归档人
    - **test_result**: 检测结果
    - **result_time**: 检测时间（可选，默认当前时间）

    错误码：
    - `SAMPLE_NOT_FOUND`: 样本不存在
    - `SAMPLE_ISOLATED`: 已隔离样本不能归档
    - `INVALID_STATUS_TRANSITION`: 状态流转不合法，必须先完成检测
    """
    sample = db.query(Sample).filter(Sample.barcode == request.barcode).first()
    if not sample:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": f"样本 {request.barcode} 不存在",
                "code": "SAMPLE_NOT_FOUND"
            }
        )

    if sample.is_isolated or sample.status == "ISOLATED":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": f"样本 {request.barcode} 已隔离，不能归档",
                "code": "SAMPLE_ISOLATED",
                "details": {"isolation_reason": sample.isolation_reason}
            }
        )

    if sample.status != "COMPLETED":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": f"样本状态为 {sample.status}，必须先完成检测(COMPLETED)才能归档",
                "code": "INVALID_STATUS_TRANSITION",
                "details": {"current_status": sample.status, "required_status": "COMPLETED"}
            }
        )

    if not config_manager.can_transition_status(sample.status, "ARCHIVED"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": f"状态 {sample.status} 不能转为归档状态",
                "code": "INVALID_STATUS_TRANSITION"
            }
        )

    old_status = sample.status
    sample.status = "ARCHIVED"
    sample.test_result = request.test_result
    sample.result_time = request.result_time or datetime.now(timezone.utc)
    sample.archived_at = datetime.now(timezone.utc)
    sample.current_custodian = request.custodian

    audit_logger.log_archive(db, sample, request.custodian, request.test_result)
    db.commit()
    db.refresh(sample)

    return sample
