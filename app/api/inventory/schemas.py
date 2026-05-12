from pydantic import BaseModel
from typing import List, Optional


class RequestItemSchema(BaseModel):
    product_id: int
    quantity: float
    unit: str


class RequestTicketSchema(BaseModel):
    source_warehouse_id: Optional[int] = None
    dest_warehouse_id: int
    items: List[RequestItemSchema]
    notes: Optional[str] = None


class UpdateRequestTicketSchema(BaseModel):
    items: List[RequestItemSchema]
    notes: Optional[str] = None
    source_warehouse_id: Optional[int] = None


class ApproveItemSchema(BaseModel):
    id: Optional[int] = None
    product_id: int
    approved_quantity: float


class ApproveTicketSchema(BaseModel):
    items: List[ApproveItemSchema]
    approver_notes: Optional[str] = None


class DirectTransferItemSchema(BaseModel):
    product_id: int
    quantity: float
    unit: str


class DirectTransferSchema(BaseModel):
    source_warehouse_id: Optional[int] = None
    dest_warehouse_id: int
    items: List[DirectTransferItemSchema]
    notes: Optional[str] = None


class UpdateDirectExportItemSchema(BaseModel):
    product_id: int
    quantity: float
    unit: str


class UpdateDirectExportSchema(BaseModel):
    items: List[UpdateDirectExportItemSchema]
    notes: Optional[str] = None


class ReceiveItemSchema(BaseModel):
    id: int
    product_id: int
    received_quantity: float
    loss_quantity: float = 0.0
    loss_reason: Optional[str] = None


class ReceiveTicketSchema(BaseModel):
    items: List[ReceiveItemSchema]
    notes: Optional[str] = None
    compensation_mode: str = "none"
