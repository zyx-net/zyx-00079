from pydantic import BaseModel, Field, field_validator
from datetime import datetime
from typing import Optional, List, Dict, Any


class SampleCreate(BaseModel):
    barcode: str = Field(..., min_length=1, max_length=100, description="样本条码，唯一标识")
    sample_type: str = Field(..., description="样本类型，如血液、唾液、核酸")
    collection_point: str = Field(..., description="采集点名称")
    collection_time: datetime = Field(..., description="采集时间")
    patient_info: Optional[str] = Field(None, description="患者信息（JSON格式）")
    current_custodian: str = Field(..., description="当前保管人")

    @field_validator('barcode')
    def barcode_not_empty(cls, v):
        if not v.strip():
            raise ValueError("条码不能为空")
        return v


class SampleResponse(BaseModel):
    id: int
    barcode: str
    sample_type: str
    collection_point: str
    collection_time: datetime
    patient_info: Optional[str]
    status: str
    current_custodian: str
    box_id: Optional[int]
    created_at: datetime
    updated_at: datetime
    rule_version: str
    is_isolated: bool
    isolation_reason: Optional[str]
    test_result: Optional[str]
    result_time: Optional[datetime]
    archived_at: Optional[datetime]

    class Config:
        from_attributes = True


class BoxCreate(BaseModel):
    box_code: str = Field(..., description="箱号，唯一标识")
    destination: str = Field(..., description="目的地检测点")
    current_custodian: str = Field(..., description="当前保管人")


class BoxResponse(BaseModel):
    id: int
    box_code: str
    destination: str
    status: str
    current_custodian: str
    temperature_records: Optional[str]
    created_at: datetime
    updated_at: datetime
    sealed_at: Optional[datetime]
    rule_version: str
    samples: List[SampleResponse] = []

    class Config:
        from_attributes = True


class BoxPackRequest(BaseModel):
    box_code: str = Field(..., description="箱号")
    barcodes: List[str] = Field(..., description="要装箱的样本条码列表")
    custodian: str = Field(..., description="操作人")


class TransferRequest(BaseModel):
    box_code: str = Field(..., description="箱号")
    to_point: str = Field(..., description="接收点")
    to_custodian: str = Field(..., description="接收人")
    from_custodian: str = Field(..., description="交出人")
    temperature: Optional[float] = Field(None, description="交接时温度")
    temperature_records: Optional[str] = Field(None, description="温度记录（JSON格式）")


class TransferResponse(BaseModel):
    transfer_id: int
    box_code: str
    from_point: str
    to_point: str
    from_custodian: str
    to_custodian: str
    transfer_time: datetime
    status: str
    temperature: Optional[float]
    rule_version: str

    class Config:
        from_attributes = True


class AcceptanceRequest(BaseModel):
    box_code: str = Field(..., description="箱号")
    custodian: str = Field(..., description="验收人")
    temperature_records: Optional[str] = Field(None, description="温度记录")
    check_duration: bool = Field(True, description="是否检查时限")


class IsolationRequest(BaseModel):
    barcode: str = Field(..., description="样本条码")
    custodian: str = Field(..., description="操作人")
    reason: str = Field(..., description="隔离原因")


class ResultArchiveRequest(BaseModel):
    barcode: str = Field(..., description="样本条码")
    custodian: str = Field(..., description="归档人")
    test_result: str = Field(..., description="检测结果")
    result_time: Optional[datetime] = Field(None, description="检测时间")


class TransferRecordResponse(BaseModel):
    id: int
    sample_id: Optional[int]
    box_id: Optional[int]
    from_point: str
    to_point: str
    from_custodian: str
    to_custodian: str
    transfer_time: datetime
    status: str
    temperature: Optional[float]
    duration_minutes: Optional[int]
    rule_version: str
    is_revoked: bool
    revoked_at: Optional[datetime]
    revoked_by: Optional[str]
    revoke_reason: Optional[str]

    class Config:
        from_attributes = True


class TransferRevokeRequest(BaseModel):
    box_code: str = Field(..., description="箱号")
    custodian: str = Field(..., description="操作人（当前保管人）")
    reason: str = Field(..., min_length=1, max_length=255, description="撤回原因")


class TransferRevokeResponse(BaseModel):
    success: bool
    message: str
    revoked_transfer_id: int
    box_code: str
    old_box_status: str
    new_box_status: str
    old_custodian: str
    new_custodian: str
    rule_version: str


class AuditLogResponse(BaseModel):
    id: int
    entity_type: str
    entity_id: int
    action: str
    old_status: Optional[str]
    new_status: Optional[str]
    custodian: str
    rule_version: str
    details: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True


class ErrorResponse(BaseModel):
    error: str
    code: str
    details: Optional[Dict[str, Any]] = None


class ConfigVersionResponse(BaseModel):
    id: int
    version: str
    rule_file_path: str
    loaded_at: datetime
    is_active: bool

    class Config:
        from_attributes = True


class HandoverFormResponse(BaseModel):
    box_code: str
    transfer_id: int
    from_point: str
    to_point: str
    from_custodian: str
    to_custodian: str
    transfer_time: datetime
    samples: List[Dict[str, Any]]
    temperature: Optional[float]
    rule_version: str
    is_revoked: Optional[bool] = None
    revoked_at: Optional[datetime] = None
    revoked_by: Optional[str] = None
    revoke_reason: Optional[str] = None
    revoked_transfer_history: Optional[List[Dict[str, Any]]] = None


class ExceptionListResponse(BaseModel):
    box_code: str
    exceptions: List[Dict[str, Any]]
    generated_at: datetime
    total_exceptions: int
    revoked_transfer_history: Optional[List[Dict[str, Any]]] = None


class BatchTransferItem(BaseModel):
    box_code: str = Field(..., description="箱号")
    to_point: str = Field(..., description="接收点")
    to_custodian: str = Field(..., description="接收人")
    from_custodian: str = Field(..., description="交出人")
    temperature: Optional[float] = Field(None, description="交接时温度")
    transfer_time: datetime = Field(..., description="交接时间")
    temperature_records: Optional[str] = Field(None, description="温度记录（JSON格式数组）")


class BatchImportRequest(BaseModel):
    transfers: List[BatchTransferItem] = Field(..., description="批量交接记录列表")
    import_note: Optional[str] = Field(None, description="导入备注")


class BatchImportError(BaseModel):
    index: int
    box_code: str
    error: str
    code: str
    details: Optional[Dict[str, Any]] = None


class BatchImportResponse(BaseModel):
    success: bool
    total_count: int
    success_count: int
    failed_count: int
    imported_transfers: List[TransferResponse]
    errors: List[BatchImportError]
    import_time: datetime
    rule_version: str


class WorkOrderCreate(BaseModel):
    exception_type: str = Field(..., description="异常类型：DAMAGED（破损）、TEMPERATURE（温控超限）、SIGNATURE_DISPUTE（签收争议）")
    box_code: str = Field(..., description="关联箱号")
    transfer_record_id: Optional[int] = Field(None, description="关联交接记录ID")
    site_code: str = Field(..., description="站点编码")
    reported_by: str = Field(..., description="上报人")
    description: str = Field(..., min_length=1, description="异常描述")
    reported_at: Optional[datetime] = Field(None, description="上报时间，默认当前时间")


class WorkOrderProcessRecordResponse(BaseModel):
    id: int
    work_order_id: int
    operator: str
    operation: str
    remark: str
    created_at: datetime

    class Config:
        from_attributes = True


class WorkOrderResponse(BaseModel):
    id: int
    work_order_no: str
    exception_type: str
    severity: str
    box_code: str
    box_id: Optional[int]
    transfer_record_id: Optional[int]
    site_code: str
    reported_by: str
    reported_at: datetime
    description: str
    status: str
    assignee: Optional[str]
    assigned_at: Optional[datetime]
    closed_at: Optional[datetime]
    closed_by: Optional[str]
    close_reason: Optional[str]
    is_revoked: bool
    revoked_at: Optional[datetime]
    revoked_by: Optional[str]
    revoke_reason: Optional[str]
    rule_version: str
    created_at: datetime
    updated_at: datetime
    process_records: List[WorkOrderProcessRecordResponse] = []

    class Config:
        from_attributes = True


class WorkOrderAssignRequest(BaseModel):
    work_order_no: str = Field(..., description="工单号")
    assignee: str = Field(..., description="处理人")
    operator: str = Field(..., description="操作人")


class WorkOrderProcessRequest(BaseModel):
    work_order_no: str = Field(..., description="工单号")
    operation: str = Field(..., description="操作类型")
    remark: str = Field(..., min_length=1, description="处理备注")
    operator: str = Field(..., description="操作人")


class WorkOrderCloseRequest(BaseModel):
    work_order_no: str = Field(..., description="工单号")
    close_reason: str = Field(..., min_length=1, description="关闭原因")
    operator: str = Field(..., description="操作人")


class WorkOrderRevokeCloseRequest(BaseModel):
    work_order_no: str = Field(..., description="工单号")
    revoke_reason: str = Field(..., min_length=1, description="撤销原因")
    operator: str = Field(..., description="操作人")


class WorkOrderBatchImportItem(BaseModel):
    exception_type: str = Field(..., description="异常类型")
    box_code: str = Field(..., description="关联箱号")
    transfer_record_id: Optional[int] = Field(None, description="关联交接记录ID")
    site_code: str = Field(..., description="站点编码")
    reported_by: str = Field(..., description="上报人")
    description: str = Field(..., description="异常描述")
    reported_at: Optional[datetime] = Field(None, description="上报时间")


class WorkOrderBatchImportRequest(BaseModel):
    work_orders: List[WorkOrderBatchImportItem] = Field(..., description="批量工单列表")
    import_note: Optional[str] = Field(None, description="导入备注")


class WorkOrderBatchImportError(BaseModel):
    index: int
    box_code: str
    error: str
    code: str
    details: Optional[Dict[str, Any]] = None


class WorkOrderBatchImportResponse(BaseModel):
    success: bool
    total_count: int
    success_count: int
    failed_count: int
    imported_work_orders: List[WorkOrderResponse]
    errors: List[WorkOrderBatchImportError]
    import_time: datetime
    rule_version: str


class WorkOrderExportResponse(BaseModel):
    file_path: str
    file_name: str
    total_count: int
    exported_at: datetime


class ReservationBoxCreate(BaseModel):
    box_code: str = Field(..., description="箱号")


class ReservationBoxResponse(BaseModel):
    id: int
    reservation_id: int
    box_id: int
    box_code: str
    loading_status: str
    loaded_at: Optional[datetime]
    loaded_by: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True


class ReservationCreate(BaseModel):
    site_code: str = Field(..., description="站点编码")
    customer_code: str = Field(..., description="客户编码")
    temperature_zone: str = Field(..., description="温控要求：FROZEN、REFRIGERATED、AMBIENT、CRYOGENIC")
    vehicle_no: str = Field(..., description="车牌号")
    vehicle_type: Optional[str] = Field(None, description="车辆类型：small、large、default")
    scheduled_date: datetime = Field(..., description="预约出库时间")
    box_codes: List[str] = Field(..., description="待出库箱号列表")
    created_by: str = Field(..., description="创建人")
    remark: Optional[str] = Field(None, description="备注")


class ReservationUpdate(BaseModel):
    site_code: Optional[str] = Field(None, description="站点编码")
    customer_code: Optional[str] = Field(None, description="客户编码")
    temperature_zone: Optional[str] = Field(None, description="温控要求")
    vehicle_no: Optional[str] = Field(None, description="车牌号")
    vehicle_type: Optional[str] = Field(None, description="车辆类型")
    scheduled_date: Optional[datetime] = Field(None, description="预约出库时间")
    box_codes: Optional[List[str]] = Field(None, description="待出库箱号列表")
    remark: Optional[str] = Field(None, description="备注")
    operator: str = Field(..., description="操作人")


class ReservationResponse(BaseModel):
    id: int
    reservation_no: str
    site_code: str
    customer_code: str
    temperature_zone: str
    vehicle_no: str
    vehicle_type: Optional[str]
    scheduled_date: datetime
    status: str
    created_by: str
    remark: Optional[str]
    rule_version: str
    cancelled_at: Optional[datetime]
    cancelled_by: Optional[str]
    cancel_reason: Optional[str]
    created_at: datetime
    updated_at: datetime
    reservation_boxes: List[ReservationBoxResponse] = []

    class Config:
        from_attributes = True


class ReservationCancelRequest(BaseModel):
    reservation_no: str = Field(..., description="预约单号")
    cancel_reason: str = Field(..., min_length=1, max_length=255, description="取消原因")
    operator: str = Field(..., description="操作人")


class ReservationConfirmRequest(BaseModel):
    reservation_no: str = Field(..., description="预约单号")
    operator: str = Field(..., description="操作人")


class LoadingPlanBoxResponse(BaseModel):
    id: int
    loading_plan_id: int
    reservation_box_id: int
    box_id: int
    box_code: str
    loading_sequence: int
    loaded: bool
    loaded_at: Optional[datetime]
    loaded_by: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True


class LoadingPlanCreate(BaseModel):
    reservation_no: str = Field(..., description="关联预约单号")
    vehicle_no: Optional[str] = Field(None, description="车牌号，默认使用预约中的车牌号")
    driver: Optional[str] = Field(None, description="司机")
    departure_time: Optional[datetime] = Field(None, description="预计发车时间")
    operator: str = Field(..., description="操作人")
    remark: Optional[str] = Field(None, description="备注")


class LoadingPlanUpdate(BaseModel):
    driver: Optional[str] = Field(None, description="司机")
    departure_time: Optional[datetime] = Field(None, description="预计发车时间")
    remark: Optional[str] = Field(None, description="备注")
    box_sequences: Optional[Dict[str, int]] = Field(None, description="箱号到装车顺序的映射")
    operator: str = Field(..., description="操作人")


class LoadingPlanResponse(BaseModel):
    id: int
    plan_no: str
    reservation_id: int
    vehicle_no: str
    driver: Optional[str]
    departure_time: Optional[datetime]
    status: str
    confirmed_by: Optional[str]
    confirmed_at: Optional[datetime]
    cancelled_at: Optional[datetime]
    cancelled_by: Optional[str]
    cancel_reason: Optional[str]
    remark: Optional[str]
    rule_version: str
    created_at: datetime
    updated_at: datetime
    loading_plan_boxes: List[LoadingPlanBoxResponse] = []

    class Config:
        from_attributes = True


class LoadingPlanConfirmRequest(BaseModel):
    plan_no: str = Field(..., description="装车计划单号")
    operator: str = Field(..., description="操作人")


class LoadingPlanCancelRequest(BaseModel):
    plan_no: str = Field(..., description="装车计划单号")
    cancel_reason: str = Field(..., min_length=1, max_length=255, description="取消原因")
    operator: str = Field(..., description="操作人")


class LoadingPlanBoxLoadRequest(BaseModel):
    plan_no: str = Field(..., description="装车计划单号")
    box_code: str = Field(..., description="箱号")
    operator: str = Field(..., description="操作人")


class ReservationBatchImportItem(BaseModel):
    site_code: str = Field(..., description="站点编码")
    customer_code: str = Field(..., description="客户编码")
    temperature_zone: str = Field(..., description="温控要求")
    vehicle_no: str = Field(..., description="车牌号")
    vehicle_type: Optional[str] = Field(None, description="车辆类型")
    scheduled_date: datetime = Field(..., description="预约出库时间")
    box_codes: List[str] = Field(..., description="待出库箱号列表")
    created_by: str = Field(..., description="创建人")
    remark: Optional[str] = Field(None, description="备注")


class ReservationBatchImportRequest(BaseModel):
    reservations: List[ReservationBatchImportItem] = Field(..., description="批量预约列表")
    import_note: Optional[str] = Field(None, description="导入备注")


class ReservationBatchImportError(BaseModel):
    index: int
    box_codes: List[str]
    error: str
    code: str
    details: Optional[Dict[str, Any]] = None


class ReservationBatchImportResponse(BaseModel):
    success: bool
    total_count: int
    success_count: int
    failed_count: int
    imported_reservations: List[ReservationResponse]
    errors: List[ReservationBatchImportError]
    import_time: datetime
    rule_version: str


class LoadingPlanExportResponse(BaseModel):
    file_path: str
    file_name: str
    total_count: int
    exported_at: datetime


class ReservationDetailResponse(ReservationResponse):
    loading_plans: List[LoadingPlanResponse] = []
    rule_snapshot: Optional[str] = None
    transfer_records: List[TransferRecordResponse] = []
    work_orders: List[WorkOrderResponse] = []
