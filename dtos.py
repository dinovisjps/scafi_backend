"""
dtos.py — DTOs aligned 1:1 with the original source (no fields dropped)
"""
from __future__ import annotations
from typing import Optional, Any, List
from pydantic import BaseModel

class AnagrafichePayload(BaseModel):
    codice: str
    tipo: str
    tipoSoggetto: str
    anagrafica: str
    partitaIva: Optional[str] = None
    codiceFiscale: Optional[str] = None
    indirizzo: Optional[str] = None
    numeroCivico: Optional[str] = None
    cap: Optional[str] = None
    citta: Optional[str] = None
    provincia: Optional[str] = None
    nazione: Optional[str] = None
    codiceIva: Optional[str] = None
    iban: Optional[str] = None
    codiceBanca: Optional[str] = None
    payeeNumber: Optional[str] = None
    datiAudit: Optional[str] = None
    dichiarazioneIntento: Optional[str] = None
    codicePA: Optional[str] = None
    paymentTerms: Optional[str] = None
    paymentMethod: Optional[str] = None
    codiceprincipale: Optional[str] = None
    zucchettiNumber: str

class InvoiceResponse(BaseModel):
    CustomId: int
    CustomExported: Optional[bool] = None
    DocumentType: str
    DocumentNumber: str
    DocumentCompany: str
    Customer: str
    Company: str
    InvoiceDate: str
    RegistrationDate: str
    CurrencyCode: str
    ExchangeRate: int
    SubledgerCod: Optional[str] = None
    SubledgerType: Optional[str] = None
    CustomerLedger: List[Any]
    InvoiceDetails: List[Any]
    PymtTerms: str
    Attachment: Optional[str] = None

class ServiceResponse(BaseModel):
    success: str
    message: Optional[str] = None

# Kept for completeness if used elsewhere
class OrdiniPayload(BaseModel):
    id: str
    name: str
    description: Optional[str] = None

class OrdiniRequest(BaseModel):
    id: str
    name: str
    description: Optional[str] = None

class OrchestratorResponseDto(BaseModel):
    message: str
    exception: str
    timeStamp: str
    userDefinedErrorText: str
    jdeSimpleMessage: str
    jdeStatus: str
    jdeStartTimestamp: str
    jdeEndTimestamp: str
    status: str
    batchNo: str
    jdeServerExecutionSeconds: int
    objectId: int
    objectType: str
    jdeLogId: str
