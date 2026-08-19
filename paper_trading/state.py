"""状态管理：两个分仓的持仓/现金/净值持久化（JSON）。"""
from __future__ import annotations
import json
from dataclasses import dataclass, field, asdict
from pathlib import Path

from config import STATE_FILE, DIV_CAPITAL, VOL_CAPITAL


@dataclass
class Book:
    name: str
    cash: float
    holdings: dict = field(default_factory=dict)   # ts_code -> shares
    cost: dict = field(default_factory=dict)        # ts_code -> 持仓成本(元)
    position: float = 1.0                          # 波动率分仓的仓位 0..1
    nav_history: list = field(default_factory=list) # [{date, nav, ret}]


@dataclass
class State:
    start_date: str = ""
    dividend_book: Book = field(default_factory=lambda: Book("股息分仓", DIV_CAPITAL))
    voltrend_book: Book = field(default_factory=lambda: Book("波动率分仓", VOL_CAPITAL, position=1.0))

    def save(self, path: Path = STATE_FILE):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: Path = STATE_FILE):
        if not path.exists():
            return cls()
        d = json.loads(path.read_text(encoding="utf-8"))
        db = Book(**d["dividend_book"])
        vb = Book(**d["voltrend_book"])
        db.nav_history = _dedupe_nav(db.nav_history)
        vb.nav_history = _dedupe_nav(vb.nav_history)
        return cls(start_date=d.get("start_date", ""), dividend_book=db, voltrend_book=vb)

    @classmethod
    def reset(cls, path: Path = STATE_FILE):
        """重置为全新初始状态（现金满额、空持仓、空净值历史）。"""
        s = cls()
        s.save(path)
        return s


def _dedupe_nav(history):
    seen, out = set(), []
    for h in history or []:
        k = (h.get("date"), h.get("nav"))
        if k in seen:
            continue
        seen.add(k)
        out.append(h)
    return out


def book_nav(book: Book, price_map: dict) -> float:
    mv = sum(book.holdings.get(c, 0) * price_map.get(c, 0.0) for c in book.holdings)
    return book.cash + mv
