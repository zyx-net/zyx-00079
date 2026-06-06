from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
from ..database import get_db
from ..models import ConfigVersion
from ..schemas import ConfigVersionResponse, ErrorResponse
from ..config_manager import config_manager, ConfigValidationError

router = APIRouter(prefix="/api/config", tags=["config"])


@router.post(
    "/load",
    response_model=ConfigVersionResponse,
    responses={
        400: {"model": ErrorResponse, "description": "配置校验失败"},
        404: {"model": ErrorResponse, "description": "配置文件不存在"},
        500: {"model": ErrorResponse, "description": "服务器错误"}
    },
    summary="加载规则配置"
)
def load_config(config_path: str, db: Session = Depends(get_db)):
    """
    加载并验证规则配置文件。

    - **config_path**: 配置文件路径

    坏配置样例触发的校验错误：
    - `INVALID_JSON_FORMAT`: 无效JSON格式
    - `MISSING_REQUIRED_FIELD`: 缺少必填字段（如status_flow）
    - `MISSING_TEMPERATURE_RULE`: 样本类型缺少温度规则
    - `INVALID_TEMPERATURE_RANGE`: 温度范围min > max
    - `MISSING_TIME_LIMIT_RULE`: 样本类型缺少时限规则
    - `INVALID_TIME_LIMIT_VALUE`: 时限值无效（非正数）
    - `MISSING_CREATED_STATUS`: 状态流转缺少CREATED初始状态
    """
    try:
        config, version = config_manager.load_config(config_path, db)
        active_config = db.query(ConfigVersion).filter(ConfigVersion.is_active == True).first()
        return active_config
    except ConfigValidationError as e:
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
                "error": f"加载配置失败: {str(e)}",
                "code": "LOAD_CONFIG_ERROR"
            }
        )


@router.get(
    "/versions",
    response_model=List[ConfigVersionResponse],
    summary="查询配置版本列表"
)
def get_config_versions(db: Session = Depends(get_db)):
    return db.query(ConfigVersion).order_by(ConfigVersion.loaded_at.desc()).all()


@router.get(
    "/current",
    response_model=ConfigVersionResponse,
    responses={404: {"model": ErrorResponse, "description": "无活动配置"}},
    summary="获取当前活动配置"
)
def get_current_config(db: Session = Depends(get_db)):
    active_config = db.query(ConfigVersion).filter(ConfigVersion.is_active == True).first()
    if not active_config:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "没有活动的配置",
                "code": "NO_ACTIVE_CONFIG"
            }
        )
    return active_config


@router.get(
    "/rules",
    summary="查看当前配置规则详情"
)
def get_current_rules():
    config = config_manager.get_current_config()
    if not config:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "配置未加载",
                "code": "CONFIG_NOT_LOADED"
            }
        )
    return {
        "version": config.get("version"),
        "description": config.get("description"),
        "temperature_rules": config.get("temperature_rules"),
        "time_limit_rules": config.get("time_limit_rules"),
        "sample_types": config.get("sample_types"),
        "status_flow": config.get("status_flow"),
        "collection_points": config.get("collection_points"),
        "testing_points": config.get("testing_points")
    }
