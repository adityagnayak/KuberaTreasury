"""
NexusTreasury — Statement Ingestion Service (Phase 1)
Parses CAMT.053 (ISO 20022 XML) and MT940 (SWIFT legacy) bank statements.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Dict, List, Optional
from xml.etree import ElementTree as ET

from dateutil import parser as dateutil_parser
from sqlalchemy.orm import Session

from app.core.business_days import get_business_days_between
from app.core.exceptions import AccountNotFoundError, DuplicateStatementError
from app.models.entities import (
    BankAccount,
    PendingPeriodAdjustment,
    PeriodLock,
    StatementGap,
    StatementRegistry,
)
from app.models.transactions import AuditLog, CashPosition, Transaction


# ─── Result / Alert types ─────────────────────────────────────────────────────

@dataclass
class MissingStatementAlert:
    account_id: str
    missing_dates: List[date]


@dataclass
class PeriodLockAlert:
    transaction_trn: str
    value_date: date
    locked_until: date
    pending_adjustment_id: str


@dataclass
class IngestionResult:
    statement_id: str
    message_id: str
    account_id: str
    transactions_imported: int
    transactions_skipped: int
    missing_statement_alerts: List[MissingStatementAlert] = field(default_factory=list)
    period_lock_alerts: List[PeriodLockAlert] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


# ─── Character encoding helper ────────────────────────────────────────────────

def safe_decode_remittance(raw: bytes | str) -> str:
    """Decode raw bytes with UTF-8/errors=replace fallback, then NFC normalize."""
    if isinstance(raw, bytes):
        text = raw.decode("utf-8", errors="replace")
    else:
        text = raw
    return unicodedata.normalize("NFC", text)


# ─── IBAN validation ─────────────────────────────────────────────────────────

IBAN_PATTERN = re.compile(r'^[A-Z]{2}[0-9]{2}[A-Z0-9]{1,30}$')


def validate_iban(iban: str) -> bool:
    """Validate IBAN via regex and mod-97 checksum."""
    iban = iban.replace(" ", "").upper()
    if not IBAN_PATTERN.match(iban):
        return False
    rearranged = iban[4:] + iban[:4]
    numeric = "".join(
        str(ord(c) - ord('A') + 10) if c.isalpha() else c for c in rearranged
    )
    return int(numeric) % 97 == 1


# ─── Ingestion Service ────────────────────────────────────────────────────────

class StatementIngestionService:
    """
    Parses CAMT.053 and MT940 bank statements.
    Enforces: duplicate detection, gap detection, period lock enforcement,
    backdated transaction handling, and full audit logging.
    """

    CAMT053_NAMESPACES = [
        "urn:iso:std:iso:20022:tech:xsd:camt.053.001.02",
        "urn:iso:std:iso:20022:tech:xsd:camt.053.001.03",
        "urn:iso:std:iso:20022:tech:xsd:camt.053.001.04",
        "urn:iso:std:iso:20022:tech:xsd:camt.053.001.05",
        "urn:iso:std:iso:20022:tech:xsd:camt.053.001.06",
        "urn:iso:std:iso:20022:tech:xsd:camt.053.001.08",
    ]

    def __init__(self, session: Session) -> None:
        self._session = session

    # ── Public: CAMT.053 ──────────────────────────────────────────────────────

    def ingest_camt053(self, xml_bytes: bytes, user_id: str) -> IngestionResult:
        """Parse and ingest a CAMT.053 XML bank statement."""
        file_hash = hashlib.sha256(xml_bytes).hexdigest()

        try:
            root = ET.fromstring(xml_bytes)
        except ET.ParseError as exc:
            raise ValueError(f"Invalid CAMT.053 XML: {exc}") from exc

        ns_uri = self._detect_camt_namespace(root)
        ns = {"camt": ns_uri}

        msg_id_el = self._get_child_text(root, ["MsgId", "camt:MsgId"], ns)
        msg_id = safe_decode_remittance(msg_id_el or f"UNKNOWN-{file_hash[:8]}")

        stmt = self._find_element(root, ["Stmt"], ns)
        legal_seq: Optional[str] = None
        stmt_date_str: Optional[str] = None
        iban: Optional[str] = None

        if stmt is not None:
            legal_seq = self._get_child_text(stmt, ["LglSeqNb", "ElctrncSeqNb"], ns)
            stmt_date_str = self._get_child_text(stmt, ["CreDtTm", "Dt"], ns)
            acct = self._find_child(stmt, "Acct", ns)
            if acct is not None:
                id_node = self._find_child(acct, "Id", ns)
                if id_node is not None:
                    iban = self._get_child_text(id_node, ["IBAN"], ns)

        stmt_date = self._parse_date_flexible(stmt_date_str) if stmt_date_str else date.today()

        self._check_duplicate(file_hash, msg_id, legal_seq, user_id)
        account = self._resolve_account_by_iban(iban)

        stmt_record = StatementRegistry(
            account_id=account.id,
            file_hash=file_hash,
            message_id=msg_id,
            legal_sequence_number=legal_seq,
            statement_date=stmt_date,
            status="pending",
            imported_by=user_id,
            format="camt053",
        )
        self._session.add(stmt_record)
        self._session.flush()

        entries = self._find_all_elements(root, "Ntry", ns)
        txns_imported = 0
        txns_skipped = 0
        period_lock_alerts: List[PeriodLockAlert] = []

        for entry in entries:
            try:
                result_code, alert = self._process_camt_entry(
                    entry, ns, account, stmt_record, stmt_date, user_id
                )
                if result_code in ("imported", "period_lock"):
                    txns_imported += 1
                    if alert:
                        period_lock_alerts.append(alert)
                else:
                    txns_skipped += 1
            except Exception as exc:
                txns_skipped += 1
                print(f"[WARN] Skipping CAMT entry: {exc}")

        missing_alerts = self._detect_gaps(account, stmt_date)

        stmt_record.status = "processed"
        self._session.commit()

        return IngestionResult(
            statement_id=stmt_record.id,
            message_id=msg_id,
            account_id=account.id,
            transactions_imported=txns_imported,
            transactions_skipped=txns_skipped,
            missing_statement_alerts=missing_alerts,
            period_lock_alerts=period_lock_alerts,
        )

    # ── Public: MT940 ─────────────────────────────────────────────────────────

    def ingest_mt940(self, raw_text: str, user_id: str) -> IngestionResult:
        """Parse and ingest an MT940 SWIFT bank statement."""
        raw_bytes = raw_text.encode("utf-8", errors="replace")
        file_hash = hashlib.sha256(raw_bytes).hexdigest()

        parsed = self._parse_mt940(raw_text)
        msg_id = parsed.get("field_20") or f"MT940-{file_hash[:8]}"
        iban = parsed.get("field_25_iban")
        stmt_date: date = parsed.get("stmt_date", date.today())

        self._check_duplicate(file_hash, msg_id, None, user_id)
        account = self._resolve_account_by_iban(iban)

        stmt_record = StatementRegistry(
            account_id=account.id,
            file_hash=file_hash,
            message_id=msg_id,
            legal_sequence_number=parsed.get("field_28c"),
            statement_date=stmt_date,
            status="pending",
            imported_by=user_id,
            format="mt940",
        )
        self._session.add(stmt_record)
        self._session.flush()

        txns_imported = 0
        txns_skipped = 0
        period_lock_alerts: List[PeriodLockAlert] = []

        for txn_raw in parsed.get("transactions", []):
            try:
                result_code, alert = self._process_mt940_transaction(
                    txn_raw, account, stmt_record, user_id
                )
                if result_code in ("imported", "period_lock"):
                    txns_imported += 1
                    if alert:
                        period_lock_alerts.append(alert)
                else:
                    txns_skipped += 1
            except Exception as exc:
                txns_skipped += 1
                print(f"[WARN] MT940 transaction skipped: {exc}")

        missing_alerts = self._detect_gaps(account, stmt_date)
        stmt_record.status = "processed"
        self._session.commit()

        return IngestionResult(
            statement_id=stmt_record.id,
            message_id=msg_id,
            account_id=account.id,
            transactions_imported=txns_imported,
            transactions_skipped=txns_skipped,
            missing_statement_alerts=missing_alerts,
            period_lock_alerts=period_lock_alerts,
        )

    # ── Private: duplicate detection ──────────────────────────────────────────

    def _check_duplicate(
        self,
        file_hash: str,
        message_id: str,
        legal_seq: Optional[str],
        user_id: str,
    ) -> None:
        existing_hash = (
            self._session.query(StatementRegistry).filter_by(file_hash=file_hash).first()
        )
        if existing_hash:
            self._log_duplicate_attempt(message_id, user_id, existing_hash.import_timestamp)
            self._session.commit()
            raise DuplicateStatementError(
                message_id, existing_hash.import_timestamp, file_hash
            )

        query = self._session.query(StatementRegistry).filter_by(message_id=message_id)
        if legal_seq is not None:
            query = query.filter_by(legal_sequence_number=legal_seq)
        existing_msg = query.first()
        if existing_msg:
            self._log_duplicate_attempt(message_id, user_id, existing_msg.import_timestamp)
            self._session.commit()
            raise DuplicateStatementError(
                message_id, existing_msg.import_timestamp, file_hash
            )

    def _log_duplicate_attempt(
        self, message_id: str, user_id: str, original_ts: datetime
    ) -> None:
        log = AuditLog(
            table_name="statement_registry",
            record_id=None,
            action="DUPLICATE_ATTEMPT",
            new_value=json.dumps({
                "message_id": message_id,
                "original_import_timestamp": original_ts.isoformat(),
                "attempted_by": user_id,
            }),
            user_id=user_id,
        )
        self._session.add(log)

    # ── Private: gap detection ────────────────────────────────────────────────

    def _detect_gaps(
        self, account: BankAccount, new_stmt_date: date
    ) -> List[MissingStatementAlert]:
        prior = (
            self._session.query(StatementRegistry)
            .filter(
                StatementRegistry.account_id == account.id,
                StatementRegistry.status == "processed",
                StatementRegistry.statement_date < new_stmt_date,
                StatementRegistry.statement_date.isnot(None),
            )
            .order_by(StatementRegistry.statement_date.desc())
            .all()
        )
        if not prior:
            return []

        last_date = prior[0].statement_date
        missing_dates = get_business_days_between(last_date, new_stmt_date, account.currency)

        if not missing_dates:
            return []

        for d in missing_dates:
            existing = self._session.query(StatementGap).filter_by(
                account_id=account.id, expected_date=d
            ).first()
            if not existing:
                gap = StatementGap(account_id=account.id, expected_date=d)
                self._session.add(gap)
                self._session.add(AuditLog(
                    table_name="statement_gaps",
                    action="GAP_DETECTED",
                    new_value=json.dumps({
                        "account_id": account.id,
                        "missing_date": d.isoformat(),
                    }),
                ))

        return [MissingStatementAlert(account_id=account.id, missing_dates=missing_dates)]

    # ── Private: period lock ──────────────────────────────────────────────────

    def _get_current_lock(self) -> Optional[date]:
        lock = (
            self._session.query(PeriodLock)
            .order_by(PeriodLock.locked_until.desc())
            .first()
        )
        return lock.locked_until if lock else None

    def _handle_cash_position(
        self, account: BankAccount, txn: Transaction, locked_until: Optional[date]
    ) -> Optional[PeriodLockAlert]:
        signed_amount = Decimal(str(txn.amount))
        if txn.credit_debit_indicator == "DBIT":
            signed_amount = -signed_amount

        self._upsert_cash_position(
            account.id, txn.entry_date, txn.currency,
            entry_delta=signed_amount, value_delta=Decimal("0"),
        )

        alert: Optional[PeriodLockAlert] = None
        if txn.value_date != txn.entry_date:
            if locked_until and txn.value_date <= locked_until:
                adj = PendingPeriodAdjustment(
                    transaction_id=txn.id,
                    account_id=account.id,
                    value_date=txn.value_date,
                    entry_date=txn.entry_date,
                    amount=txn.amount,
                    currency=txn.currency,
                    reason=f"value_date {txn.value_date} <= locked_until {locked_until}",
                )
                self._session.add(adj)
                txn.status = "pending_period_adj"
                alert = PeriodLockAlert(
                    transaction_trn=txn.trn,
                    value_date=txn.value_date,
                    locked_until=locked_until,
                    pending_adjustment_id=adj.id,
                )
            else:
                self._upsert_cash_position(
                    account.id, txn.value_date, txn.currency,
                    entry_delta=Decimal("0"), value_delta=signed_amount,
                )
        else:
            self._upsert_cash_position(
                account.id, txn.value_date, txn.currency,
                entry_delta=Decimal("0"), value_delta=signed_amount,
            )

        return alert

    def _upsert_cash_position(
        self,
        account_id: str,
        pos_date: date,
        currency: str,
        entry_delta: Decimal,
        value_delta: Decimal,
    ) -> None:
        existing = self._session.query(CashPosition).filter_by(
            account_id=account_id, position_date=pos_date, currency=currency
        ).first()

        if existing:
            existing.entry_date_balance = (
                Decimal(str(existing.entry_date_balance)) + entry_delta
            )
            existing.value_date_balance = (
                Decimal(str(existing.value_date_balance)) + value_delta
            )
            existing.last_updated = datetime.utcnow()
        else:
            self._session.add(CashPosition(
                account_id=account_id,
                position_date=pos_date,
                currency=currency,
                entry_date_balance=entry_delta,
                value_date_balance=value_delta,
            ))

    # ── Private: CAMT.053 processing ─────────────────────────────────────────

    def _process_camt_entry(
        self,
        entry: ET.Element,
        ns: dict,
        account: BankAccount,
        stmt_record: StatementRegistry,
        stmt_date: date,
        user_id: str,
    ):
        amt_el = self._find_child(entry, "Amt", ns)
        amount_str = (amt_el.text or "0") if amt_el is not None else "0"
        amount = Decimal(amount_str.strip()).quantize(
            Decimal("0.00000001"), rounding=ROUND_HALF_UP
        )

        cdi = (self._get_child_text(entry, ["CdtDbtInd"], ns) or "CRDT").strip().upper()

        entry_date_str = self._get_child_text(entry, ["BookgDt/Dt", "BookgDt/DtTm"], ns)
        value_date_str = self._get_child_text(entry, ["ValDt/Dt", "ValDt/DtTm"], ns)

        entry_date = self._parse_date_flexible(entry_date_str) if entry_date_str else stmt_date
        value_date = self._parse_date_flexible(value_date_str) if value_date_str else entry_date

        remit_raw = self._get_child_text(entry, [
            "NtryDtls/TxDtls/RmtInf/Ustrd",
            "AddtlNtryInf",
        ], ns) or ""
        remittance_info = safe_decode_remittance(remit_raw)

        trn = self._get_child_text(entry, [
            "NtryDtls/TxDtls/Refs/EndToEndId",
            "AcctSvcrRef",
        ], ns) or f"CAMT-{stmt_record.id[:8]}-{uuid.uuid4().hex[:8]}"

        currency = (
            amt_el.get("Ccy", account.currency) if amt_el is not None else account.currency
        )

        if self._session.query(Transaction).filter_by(trn=trn).first():
            return "skipped", None

        txn = Transaction(
            trn=trn,
            account_id=account.id,
            entry_date=entry_date,
            value_date=value_date,
            amount=amount,
            currency=currency,
            remittance_info=remittance_info,
            credit_debit_indicator=cdi,
            status="booked",
            statement_id=stmt_record.id,
        )
        self._session.add(txn)
        self._session.flush()

        locked_until = self._get_current_lock()
        alert = self._handle_cash_position(account, txn, locked_until)
        return ("period_lock" if alert else "imported"), alert

    # ── Private: MT940 parsing ────────────────────────────────────────────────

    def _parse_mt940(self, raw_text: str) -> dict:
        result: dict = {
            "field_20": None,
            "field_25_iban": None,
            "field_28c": None,
            "stmt_date": date.today(),
            "transactions": [],
        }
        lines = raw_text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
        current_field: Optional[str] = None
        current_content_lines: List[str] = []

        def flush_field(tag: str, content: str) -> None:
            content = content.strip()
            if tag == "20":
                result["field_20"] = content
            elif tag == "25":
                m = re.search(r'([A-Z]{2}\d{2}[A-Z0-9]{1,30})', content)
                result["field_25_iban"] = m.group(1) if m else content
            elif tag == "28C":
                result["field_28c"] = content
            elif tag in ("60F", "60M"):
                m2 = re.match(r'[CD](\d{6})([A-Z]{3})', content)
                if m2:
                    try:
                        result["stmt_date"] = datetime.strptime(m2.group(1), "%y%m%d").date()
                    except ValueError:
                        pass
            elif tag == "61":
                result["transactions"].append({"raw_61": content, "raw_86": None})
            elif tag == "86":
                if result["transactions"]:
                    result["transactions"][-1]["raw_86"] = content

        field_pattern = re.compile(r"^:(\w+):")
        for line in lines:
            m = field_pattern.match(line)
            if m:
                if current_field:
                    flush_field(current_field, "\n".join(current_content_lines))
                current_field = m.group(1)
                current_content_lines = [line[len(m.group(0)):]]
            elif line.strip("-") == "":
                if current_field:
                    flush_field(current_field, "\n".join(current_content_lines))
                    current_field = None
                    current_content_lines = []
            elif current_field:
                current_content_lines.append(line)

        if current_field:
            flush_field(current_field, "\n".join(current_content_lines))

        parsed_txns = [
            t for raw in result["transactions"]
            if (t := self._parse_mt940_61(raw["raw_61"], raw.get("raw_86"), result["stmt_date"]))
        ]
        result["transactions"] = parsed_txns
        return result

    def _parse_mt940_61(
        self, field61: str, field86: Optional[str], stmt_date: date
    ) -> Optional[dict]:
        if not field61:
            return None
        pattern = re.compile(
            r"^(\d{6})(\d{4})?(R?[DC])([A-Z])?([\d,]+)([A-Z]{4})(.+?)$",
            re.DOTALL,
        )
        m = pattern.match(field61.strip())
        if not m:
            return None

        val_date_str = m.group(1)
        dc_indicator = m.group(3).replace("R", "")
        amount_raw = m.group(5).replace(",", ".")
        trn_ref = m.group(7).strip().split("\n")[0].strip()

        try:
            value_date = datetime.strptime(val_date_str, "%y%m%d").date()
        except ValueError:
            value_date = stmt_date

        try:
            amount = Decimal(amount_raw).quantize(
                Decimal("0.00000001"), rounding=ROUND_HALF_UP
            )
        except Exception:
            return None

        return {
            "value_date": value_date,
            "entry_date": value_date,
            "credit_debit_indicator": "CRDT" if dc_indicator == "C" else "DBIT",
            "amount": amount,
            "trn": trn_ref,
            "remittance_info": safe_decode_remittance(field86 or ""),
        }

    def _process_mt940_transaction(
        self,
        txn_raw: dict,
        account: BankAccount,
        stmt_record: StatementRegistry,
        user_id: str,
    ):
        trn = txn_raw.get("trn") or f"MT940-{uuid.uuid4().hex[:12]}"
        if self._session.query(Transaction).filter_by(trn=trn).first():
            return "skipped", None

        txn = Transaction(
            trn=trn,
            account_id=account.id,
            entry_date=txn_raw["entry_date"],
            value_date=txn_raw["value_date"],
            amount=txn_raw["amount"],
            currency=account.currency,
            remittance_info=txn_raw.get("remittance_info"),
            credit_debit_indicator=txn_raw["credit_debit_indicator"],
            status="booked",
            statement_id=stmt_record.id,
        )
        self._session.add(txn)
        self._session.flush()

        locked_until = self._get_current_lock()
        alert = self._handle_cash_position(account, txn, locked_until)
        return ("period_lock" if alert else "imported"), alert

    # ── Private: account resolution ───────────────────────────────────────────

    def _resolve_account_by_iban(self, iban: Optional[str]) -> BankAccount:
        if iban:
            clean_iban = iban.replace(" ", "").upper()
            account = self._session.query(BankAccount).filter_by(iban=clean_iban).first()
            if account:
                return account
        account = self._session.query(BankAccount).filter_by(account_status="active").first()
        if account:
            return account
        raise AccountNotFoundError(iban=iban)

    # ── Private: XML utilities ────────────────────────────────────────────────

    def _detect_camt_namespace(self, root: ET.Element) -> str:
        tag = root.tag
        if tag.startswith("{"):
            return tag[1:tag.index("}")]
        for child in root:
            if child.tag.startswith("{"):
                return child.tag[1:child.tag.index("}")]
        return "urn:iso:std:iso:20022:tech:xsd:camt.053.001.06"

    def _find_element(
        self, root: ET.Element, tags: list, ns: dict
    ) -> Optional[ET.Element]:
        for tag in tags:
            el = root.find(f".//{tag}", ns)
            if el is not None:
                return el
        return None

    def _find_all_elements(
        self, root: ET.Element, tag: str, ns: dict
    ) -> List[ET.Element]:
        results = root.findall(f".//{tag}", ns)
        if not results and ns:
            ns_uri = next(iter(ns.values()), "")
            results = root.findall(f".//{{{ns_uri}}}{tag}")
        return results

    def _find_child(
        self, parent: ET.Element, tag: str, ns: dict
    ) -> Optional[ET.Element]:
        el = parent.find(tag, ns)
        if el is None:
            for child in parent:
                local = child.tag.split("}")[-1] if "}" in child.tag else child.tag
                if local == tag:
                    return child
        return el

    def _get_child_text(
        self, parent: ET.Element, paths: list, ns: dict
    ) -> Optional[str]:
        for path in paths:
            el = parent.find(path, ns)
            if el is None:
                parts = path.split("/")
                current: Optional[ET.Element] = parent
                for part in parts:
                    if current is None:
                        break
                    found = None
                    for child in current:
                        local = child.tag.split("}")[-1] if "}" in child.tag else child.tag
                        if local == part:
                            found = child
                            break
                    current = found
                el = current
            if el is not None and el.text:
                return el.text.strip()
        return None

    def _parse_date_flexible(self, s: str) -> date:
        s = s.strip()
        try:
            return dateutil_parser.parse(s).date()
        except Exception:
            for fmt in ("%Y-%m-%d", "%Y%m%d", "%d.%m.%Y", "%m/%d/%Y"):
                try:
                    return datetime.strptime(s, fmt).date()
                except ValueError:
                    continue
        return date.today()
