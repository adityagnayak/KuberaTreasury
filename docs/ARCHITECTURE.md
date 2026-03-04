# Architecture Principles (Phase 1)

## Core Principles

1. Ledger-led, not bank-statement-led: ledger event stream is system of record.
2. Multi-tenant by default: `tenant_id` on all domain tables and all access paths.
3. Event-sourced ledger: append-only `ledger_events`; projections in `ledger_positions`.
4. Operational DB separated from reporting DB via outbox/read-replica pattern.
5. Personal data physically separated from financial ledger.
6. AI usage must be pseudonymised and fully audited.

## Personal Data Separation Diagram

```mermaid
flowchart LR
    U[User / Counterparty Subject] --> PDR[(personal_data_records\nPII: name/email/phone/address)]
    PDR -->|UUID only| CP[counterparties.personal_data_id]
    CP --> LE[(ledger_events\nfinancial only + VAT code)]
    LE --> LP[(ledger_positions\nprojections)]
    LE --> IC[(intercompany_transactions\ntimestamp + TP evidence hash)]
    LE --> AE[(audit_events\nimmutable)]

    ER[GDPR Erasure Request] --> DEL[Delete/Anonymise PDR row]
    DEL --> OK[Ledger & audit remain intact\n(UUID references only)]

    HMRC[HMRC retention requirements] --> LE
    HMRC --> AE
```

## Data Boundaries

- PII boundary: only `personal_data_records` holds directly identifying fields.
- Financial boundary: ledger and payments store UUID references only.
- Compliance boundary: tax, audit, and retention records are immutable or retention-managed.
- Payments boundary (v1): `manual_pain001` export only, no direct bank API initiation.
