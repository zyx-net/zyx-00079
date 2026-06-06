from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import os
import json

from app.database import engine, Base, SessionLocal
from app.models import ConfigVersion, WorkOrderRuleVersion
from app.config_manager import config_manager, ConfigValidationError
from app.work_order_config import work_order_config_manager, WorkOrderConfigValidationError
from app.routes import samples, boxes, config, audit, work_orders


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        active_config = db.query(ConfigVersion).filter(ConfigVersion.is_active == True).first()
        if active_config and os.path.exists(active_config.rule_file_path):
            try:
                with open(active_config.rule_file_path, 'r', encoding='utf-8') as f:
                    config_content = f.read()
                config_data = json.loads(config_content)
                config_manager._current_config = config_data
                config_manager._current_version = active_config.version
                config_manager._config_file_path = active_config.rule_file_path
                print(f"[STARTUP] 已恢复转运规则配置版本: {active_config.version}")
            except Exception as e:
                print(f"[STARTUP] 恢复转运规则配置失败: {e}")
        else:
            print("[STARTUP] 无活动转运规则配置，请通过API加载规则配置")

        active_wo_config = db.query(WorkOrderRuleVersion).filter(WorkOrderRuleVersion.is_active == True).first()
        if active_wo_config and os.path.exists(active_wo_config.rule_file_path):
            try:
                with open(active_wo_config.rule_file_path, 'r', encoding='utf-8') as f:
                    wo_config_content = f.read()
                wo_config_data = json.loads(wo_config_content)
                work_order_config_manager._current_config = wo_config_data
                work_order_config_manager._current_version = active_wo_config.version
                work_order_config_manager._config_file_path = active_wo_config.rule_file_path
                print(f"[STARTUP] 已恢复工单规则配置版本: {active_wo_config.version}")
            except Exception as e:
                print(f"[STARTUP] 恢复工单规则配置失败: {e}")
        else:
            print("[STARTUP] 无活动工单规则配置，请通过API加载工单规则配置")
    finally:
        db.close()

    yield
    print("[SHUTDOWN] 服务关闭，数据已持久化到SQLite数据库")


app = FastAPI(
    title="实验室样本转运管理系统",
    description="""
    管理实验室样本从采集点到检测点的转运交接全流程。

    ## 功能特性
    - 样本建档与条码管理
    - 转运箱装箱与封箱
    - 转运交接与到站验收
    - 异常样本隔离
    - 检测结果归档
    - 温控与时序规则校验
    - 完整审计日志追踪
    """,
    version="1.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    errors = []
    for error in exc.errors():
        errors.append({
            "field": "->".join([str(loc) for loc in error["loc"]]),
            "message": error["msg"],
            "type": error["type"]
        })
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "error": "请求参数验证失败",
            "code": "VALIDATION_ERROR",
            "details": {"errors": errors}
        }
    )


@app.exception_handler(ConfigValidationError)
async def config_validation_exception_handler(request: Request, exc: ConfigValidationError):
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={
            "error": exc.message,
            "code": exc.error_code,
            "details": exc.details
        }
    )


@app.exception_handler(WorkOrderConfigValidationError)
async def work_order_config_validation_exception_handler(request: Request, exc: WorkOrderConfigValidationError):
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={
            "error": exc.message,
            "code": exc.error_code,
            "details": exc.details
        }
    )


app.include_router(config.router)
app.include_router(samples.router)
app.include_router(boxes.router)
app.include_router(audit.router)
app.include_router(work_orders.router)


@app.get("/", tags=["system"])
async def root():
    return {
        "name": "实验室样本转运管理系统",
        "version": "1.0.0",
        "status": "running",
        "docs": "/docs",
        "config_version": config_manager.get_current_version() or "未加载"
    }


@app.get("/health", tags=["system"])
async def health_check():
    return {
        "status": "healthy",
        "database": "connected",
        "config_loaded": config_manager.get_current_version() is not None,
        "config_version": config_manager.get_current_version()
    }


@app.get("/api/transfers", tags=["transfers"])
def get_transfer_records(
    box_code: str = None,
    status: str = None,
    skip: int = 0,
    limit: int = 100
):
    from app.models import TransferRecord, Box
    from app.database import SessionLocal
    from app.schemas import TransferRecordResponse

    db = SessionLocal()
    try:
        query = db.query(TransferRecord)
        if box_code:
            box = db.query(Box).filter(Box.box_code == box_code).first()
            if box:
                query = query.filter(TransferRecord.box_id == box.id)
        if status:
            query = query.filter(TransferRecord.status == status)
        records = query.order_by(TransferRecord.transfer_time.desc()).offset(skip).limit(limit).all()
        return [TransferRecordResponse.model_validate(r) for r in records]
    finally:
        db.close()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True
    )
