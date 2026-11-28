"""Adapter for the college's existing student database.

The app only ever talks to the college data through `CollegeDirectory`. Today it is backed
by a mock SQLite file; to go live, write another class with the same two methods that
queries the real database (MySQL/Postgres/REST API...) and return it from `get_directory()`.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Protocol

from . import config


@dataclass
class CollegeStudent:
    student_id: str
    name: str
    stop_id: str
    fee_paid: bool


class CollegeDirectory(Protocol):
    def lookup(self, student_id: str) -> CollegeStudent | None: ...
    def all_students(self) -> list[CollegeStudent]: ...
    def mark_fee_paid(self, student_id: str) -> None: ...


class MockSqliteDirectory:
    def __init__(self, path=config.COLLEGE_DB_PATH):
        self.path = path

    def _conn(self):
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def init_schema(self):
        with self._conn() as c:
            c.execute(
                """CREATE TABLE IF NOT EXISTS students (
                    student_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    stop_id TEXT NOT NULL,
                    fee_paid INTEGER NOT NULL
                )"""
            )

    @staticmethod
    def _row(r) -> CollegeStudent:
        return CollegeStudent(r["student_id"], r["name"], r["stop_id"], bool(r["fee_paid"]))

    def lookup(self, student_id: str) -> CollegeStudent | None:
        with self._conn() as c:
            r = c.execute(
                "SELECT * FROM students WHERE student_id = ?", (student_id.strip().upper(),)
            ).fetchone()
        return self._row(r) if r else None

    def all_students(self) -> list[CollegeStudent]:
        with self._conn() as c:
            return [self._row(r) for r in c.execute("SELECT * FROM students")]

    def mark_fee_paid(self, student_id: str) -> None:
        # Real integration: write back to the college ERP (or let the accounts office reconcile).
        with self._conn() as c:
            c.execute("UPDATE students SET fee_paid = 1 WHERE student_id = ?", (student_id.strip().upper(),))


_directory: CollegeDirectory | None = None


def get_directory() -> CollegeDirectory:
    global _directory
    if _directory is None:
        _directory = MockSqliteDirectory()
    return _directory
