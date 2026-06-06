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
