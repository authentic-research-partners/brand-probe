from pathlib import Path
from brandprobe.db.connection import get_db
from brandprobe.schemas import Audit


def save(root: Path, audit: Audit) -> None:
    with get_db(root) as conn:
        conn.execute(
            "INSERT INTO audits VALUES (?, ?) ON CONFLICT(id) DO UPDATE SET body=excluded.body",
            (audit.id, audit.model_dump_json()),
        )
        conn.commit()


def get(root: Path, audit_id: str) -> Audit | None:
    with get_db(root) as conn:
        row = conn.execute("SELECT body FROM audits WHERE id=?", (audit_id,)).fetchone()
        return Audit.model_validate_json(row[0]) if row else None


def history(root: Path) -> list[Audit]:
    with get_db(root) as conn:
        return [
            Audit.model_validate_json(r[0])
            for r in conn.execute(
                "SELECT body FROM audits ORDER BY rowid DESC LIMIT 50"
            )
        ]


def running(root: Path) -> list[Audit]:
    with get_db(root) as conn:
        return [
            Audit.model_validate_json(row[0])
            for row in conn.execute(
                "SELECT body FROM audits WHERE json_extract(body, '$.status')='running'"
            )
        ]


def has_continuation(root: Path, audit_id: str) -> bool:
    with get_db(root) as conn:
        return (
            conn.execute(
                "SELECT 1 FROM audits WHERE json_extract(body, '$.plan.parent_audit_id')=?",
                (audit_id,),
            ).fetchone()
            is not None
        )
