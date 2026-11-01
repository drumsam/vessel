"""Supplier and client registers (decision 0050). Quick-add stays a name
(and phone) only; the full record is filled in later, or never."""
from __future__ import annotations

from uuid import UUID

import psycopg
from fastapi import APIRouter, Depends, HTTPException

from app.api import schemas as s
from app.api.deps import current_operator, db, translate
from app.counterparty import repo as cp

router = APIRouter(tags=["counterparties"], dependencies=[Depends(current_operator)])


@router.get("/suppliers/{supplier_id}", response_model=s.SupplierDetailOut)
def get_supplier(supplier_id: UUID, conn: psycopg.Connection = Depends(db)):
    row = cp.get_supplier(conn, str(supplier_id))
    if row is None:
        raise HTTPException(404, "supplier not found")
    return row


@router.patch("/suppliers/{supplier_id}", response_model=s.SupplierDetailOut)
def patch_supplier(supplier_id: UUID, body: s.SupplierPatchIn, conn: psycopg.Connection = Depends(db)):
    try:
        with conn.transaction():
            row = cp.update_supplier(conn, str(supplier_id), body.model_dump(exclude_unset=True))
    except psycopg.Error as e:
        raise translate(e)
    if row is None:
        raise HTTPException(404, "supplier not found")
    return row


@router.post("/suppliers/{supplier_id}/aliases", response_model=s.SupplierDetailOut)
def add_supplier_alias(supplier_id: UUID, body: s.CounterpartyAliasIn, conn: psycopg.Connection = Depends(db)):
    if cp.get_supplier(conn, str(supplier_id)) is None:
        raise HTTPException(404, "supplier not found")
    with conn.transaction():
        cp.add_supplier_alias(conn, str(supplier_id), body.alias)
    return cp.get_supplier(conn, str(supplier_id))


@router.get("/clients", response_model=list[s.ClientOut])
def list_clients(conn: psycopg.Connection = Depends(db)):
    return cp.list_clients(conn)


@router.post("/clients", response_model=s.ClientDetailOut, status_code=201)
def create_client(body: s.ClientIn, conn: psycopg.Connection = Depends(db),
                  operator: dict = Depends(current_operator)):
    try:
        with conn.transaction():
            return cp.create_client(conn, name=body.name, phone=body.phone,
                                    created_by=operator["operator_id"])
    except psycopg.errors.UniqueViolation:
        raise HTTPException(409, f"a client called {body.name.strip()!r} already exists")
    except psycopg.Error as e:
        raise translate(e)


@router.get("/clients/{client_id}", response_model=s.ClientDetailOut)
def get_client(client_id: UUID, conn: psycopg.Connection = Depends(db)):
    row = cp.get_client(conn, str(client_id))
    if row is None:
        raise HTTPException(404, "client not found")
    return row


@router.patch("/clients/{client_id}", response_model=s.ClientDetailOut)
def patch_client(client_id: UUID, body: s.ClientPatchIn, conn: psycopg.Connection = Depends(db)):
    try:
        with conn.transaction():
            row = cp.update_client(conn, str(client_id), body.model_dump(exclude_unset=True))
    except psycopg.Error as e:
        raise translate(e)
    if row is None:
        raise HTTPException(404, "client not found")
    return row


@router.post("/clients/{client_id}/aliases", response_model=s.ClientDetailOut)
def add_client_alias(client_id: UUID, body: s.CounterpartyAliasIn, conn: psycopg.Connection = Depends(db)):
    if cp.get_client(conn, str(client_id)) is None:
        raise HTTPException(404, "client not found")
    with conn.transaction():
        cp.add_client_alias(conn, str(client_id), body.alias)
    return cp.get_client(conn, str(client_id))
