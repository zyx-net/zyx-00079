from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text, Float, Boolean
from sqlalchemy.orm import relationship
from datetime import datetime
from .database import Base


class ConfigVersion(Base):
    __tablename__ = "config_versions"

    id = Column(Integer, primary_key=True, index=True)
    version = Column(String(50), unique=True, nullable=False)
    rule_file_path = Column(String(255), nullable=False)
    loaded_at = Column(DateTime, default=datetime.utcnow)
    is_active = Column(Boolean, default=True)
    config_content = Column(Text, nullable=False)


class Sample(Base):
    __tablename__ = "samples"

    id = Column(Integer, primary_key=True, index=True)
    barcode = Column(String(100), unique=True, nullable=False, index=True)
    sample_type = Column(String(50), nullable=False)
    collection_point = Column(String(100), nullable=False)
    collection_time = Column(DateTime, nullable=False)
    patient_info = Column(Text)
    status = Column(String(50), nullable=False, default="CREATED")
    current_custodian = Column(String(100), nullable=False)
    box_id = Column(Integer, ForeignKey("boxes.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    rule_version = Column(String(50), nullable=False)
    is_isolated = Column(Boolean, default=False)
    isolation_reason = Column(String(255), nullable=True)
    test_result = Column(String(50), nullable=True)
    result_time = Column(DateTime, nullable=True)
    archived_at = Column(DateTime, nullable=True)

    box = relationship("Box", back_populates="samples")
    transfer_records = relationship("TransferRecord", back_populates="sample")


class Box(Base):
    __tablename__ = "boxes"

    id = Column(Integer, primary_key=True, index=True)
    box_code = Column(String(100), unique=True, nullable=False, index=True)
    destination = Column(String(100), nullable=False)
    status = Column(String(50), nullable=False, default="OPEN")
    current_custodian = Column(String(100), nullable=False)
    temperature_records = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    sealed_at = Column(DateTime, nullable=True)
    rule_version = Column(String(50), nullable=False)

    samples = relationship("Sample", back_populates="box")
    transfer_records = relationship("TransferRecord", back_populates="box")
    work_orders = relationship("ExceptionWorkOrder", back_populates="box")


class TransferRecord(Base):
    __tablename__ = "transfer_records"

    id = Column(Integer, primary_key=True, index=True)
    sample_id = Column(Integer, ForeignKey("samples.id"), nullable=True)
    box_id = Column(Integer, ForeignKey("boxes.id"), nullable=True)
    from_point = Column(String(100), nullable=False)
    to_point = Column(String(100), nullable=False)
    from_custodian = Column(String(100), nullable=False)
    to_custodian = Column(String(100), nullable=False)
    transfer_time = Column(DateTime, default=datetime.utcnow)
    status = Column(String(50), nullable=False)
    temperature = Column(Float, nullable=True)
    duration_minutes = Column(Integer, nullable=True)
    rule_version = Column(String(50), nullable=False)
    is_revoked = Column(Boolean, default=False)
    revoked_at = Column(DateTime, nullable=True)
    revoked_by = Column(String(100), nullable=True)
    revoke_reason = Column(String(255), nullable=True)

    sample = relationship("Sample", back_populates="transfer_records")
    box = relationship("Box", back_populates="transfer_records")
    work_orders = relationship("ExceptionWorkOrder", back_populates="transfer_record")


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, index=True)
    entity_type = Column(String(50), nullable=False)
    entity_id = Column(Integer, nullable=False)
    action = Column(String(100), nullable=False)
    old_status = Column(String(50), nullable=True)
    new_status = Column(String(50), nullable=True)
    custodian = Column(String(100), nullable=False)
    rule_version = Column(String(50), nullable=False)
    details = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class WorkOrderRuleVersion(Base):
    __tablename__ = "work_order_rule_versions"

    id = Column(Integer, primary_key=True, index=True)
    version = Column(String(50), unique=True, nullable=False)
    rule_file_path = Column(String(255), nullable=False)
    loaded_at = Column(DateTime, default=datetime.utcnow)
    is_active = Column(Boolean, default=True)
    config_content = Column(Text, nullable=False)


class ExceptionWorkOrder(Base):
    __tablename__ = "exception_work_orders"

    id = Column(Integer, primary_key=True, index=True)
    work_order_no = Column(String(50), unique=True, nullable=False, index=True)
    exception_type = Column(String(50), nullable=False)
    severity = Column(String(20), nullable=False)
    box_code = Column(String(100), nullable=False, index=True)
    box_id = Column(Integer, ForeignKey("boxes.id"), nullable=True)
    transfer_record_id = Column(Integer, ForeignKey("transfer_records.id"), nullable=True)
    site_code = Column(String(50), nullable=False, index=True)
    reported_by = Column(String(100), nullable=False)
    reported_at = Column(DateTime, default=datetime.utcnow)
    description = Column(Text, nullable=False)
    status = Column(String(50), nullable=False, default="OPEN")
    assignee = Column(String(100), nullable=True)
    assigned_at = Column(DateTime, nullable=True)
    closed_at = Column(DateTime, nullable=True)
    closed_by = Column(String(100), nullable=True)
    close_reason = Column(String(255), nullable=True)
    is_revoked = Column(Boolean, default=False)
    revoked_at = Column(DateTime, nullable=True)
    revoked_by = Column(String(100), nullable=True)
    revoke_reason = Column(String(255), nullable=True)
    rule_version = Column(String(50), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    box = relationship("Box", back_populates="work_orders")
    transfer_record = relationship("TransferRecord", back_populates="work_orders")
    process_records = relationship("WorkOrderProcessRecord", back_populates="work_order", cascade="all, delete-orphan")


class WorkOrderProcessRecord(Base):
    __tablename__ = "work_order_process_records"

    id = Column(Integer, primary_key=True, index=True)
    work_order_id = Column(Integer, ForeignKey("exception_work_orders.id"), nullable=False)
    operator = Column(String(100), nullable=False)
    operation = Column(String(50), nullable=False)
    remark = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    work_order = relationship("ExceptionWorkOrder", back_populates="process_records")


class ReservationRuleVersion(Base):
    __tablename__ = "reservation_rule_versions"

    id = Column(Integer, primary_key=True, index=True)
    version = Column(String(50), unique=True, nullable=False)
    rule_file_path = Column(String(255), nullable=False)
    loaded_at = Column(DateTime, default=datetime.utcnow)
    is_active = Column(Boolean, default=True)
    config_content = Column(Text, nullable=False)


class Reservation(Base):
    __tablename__ = "reservations"

    id = Column(Integer, primary_key=True, index=True)
    reservation_no = Column(String(50), unique=True, nullable=False, index=True)
    site_code = Column(String(50), nullable=False, index=True)
    customer_code = Column(String(50), nullable=False, index=True)
    temperature_zone = Column(String(50), nullable=False)
    vehicle_no = Column(String(50), nullable=False, index=True)
    vehicle_type = Column(String(50), nullable=True)
    scheduled_date = Column(DateTime, nullable=False, index=True)
    status = Column(String(50), nullable=False, default="DRAFT")
    created_by = Column(String(100), nullable=False)
    remark = Column(Text, nullable=True)
    rule_version = Column(String(50), nullable=False)
    rule_snapshot = Column(Text, nullable=False)
    cancelled_at = Column(DateTime, nullable=True)
    cancelled_by = Column(String(100), nullable=True)
    cancel_reason = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    reservation_boxes = relationship("ReservationBox", back_populates="reservation", cascade="all, delete-orphan")
    loading_plans = relationship("LoadingPlan", back_populates="reservation")


class ReservationBox(Base):
    __tablename__ = "reservation_boxes"

    id = Column(Integer, primary_key=True, index=True)
    reservation_id = Column(Integer, ForeignKey("reservations.id"), nullable=False)
    box_id = Column(Integer, ForeignKey("boxes.id"), nullable=False)
    box_code = Column(String(100), nullable=False, index=True)
    loading_status = Column(String(50), nullable=False, default="PENDING")
    loaded_at = Column(DateTime, nullable=True)
    loaded_by = Column(String(100), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    reservation = relationship("Reservation", back_populates="reservation_boxes")
    box = relationship("Box")


class LoadingPlan(Base):
    __tablename__ = "loading_plans"

    id = Column(Integer, primary_key=True, index=True)
    plan_no = Column(String(50), unique=True, nullable=False, index=True)
    reservation_id = Column(Integer, ForeignKey("reservations.id"), nullable=False)
    vehicle_no = Column(String(50), nullable=False, index=True)
    driver = Column(String(100), nullable=True)
    departure_time = Column(DateTime, nullable=True)
    status = Column(String(50), nullable=False, default="DRAFT")
    confirmed_by = Column(String(100), nullable=True)
    confirmed_at = Column(DateTime, nullable=True)
    cancelled_at = Column(DateTime, nullable=True)
    cancelled_by = Column(String(100), nullable=True)
    cancel_reason = Column(String(255), nullable=True)
    remark = Column(Text, nullable=True)
    rule_version = Column(String(50), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    reservation = relationship("Reservation", back_populates="loading_plans")
    loading_plan_boxes = relationship("LoadingPlanBox", back_populates="loading_plan", cascade="all, delete-orphan")


class LoadingPlanBox(Base):
    __tablename__ = "loading_plan_boxes"

    id = Column(Integer, primary_key=True, index=True)
    loading_plan_id = Column(Integer, ForeignKey("loading_plans.id"), nullable=False)
    reservation_box_id = Column(Integer, ForeignKey("reservation_boxes.id"), nullable=False)
    box_id = Column(Integer, ForeignKey("boxes.id"), nullable=False)
    box_code = Column(String(100), nullable=False, index=True)
    loading_sequence = Column(Integer, nullable=False, default=0)
    loaded = Column(Boolean, default=False)
    loaded_at = Column(DateTime, nullable=True)
    loaded_by = Column(String(100), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    loading_plan = relationship("LoadingPlan", back_populates="loading_plan_boxes")
    reservation_box = relationship("ReservationBox")
    box = relationship("Box")
