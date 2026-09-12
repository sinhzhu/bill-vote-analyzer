from __future__ import annotations

import argparse
import csv
import re
from dataclasses import dataclass, field
from enum import Enum

class votechoice(Enum):
    YEA = "Yea"
    NAY = "Nay"
    ABSTAIN = "Abstain"   
    ABSENT = "Absent"     

    @staticmethod
    def from_string(raw: str) -> "votechoice":
        s = (raw or "").strip().lower()
        if s in ("yea", "yes", "aye", "y"):
            return votechoice.YEA
        if s in ("nay", "no", "n"):
            return votechoice.NAY
        if s in ("present", "abstain", "abstention", "pres"):
            return votechoice.ABSTAIN
        return votechoice.ABSENT

@dataclass
class legislator:
    legislator_id: str
    name: str
    party: str   
    state: str
    chamber: str 

    @staticmethod
    def normalize_party(raw: str) -> str:
        s = (raw or "").strip().lower()
        if s.startswith("democrat") or s == "d":
            return "D"
        if s.startswith("republican") or s == "r":
            return "R"
        return "I"

class chamber:
    def __init__(self, name: str, total_seats: int):
        self.name = name
        self.total_seats = total_seats

    def quorum(self) -> int:
        """Minimum members needed to do business: majority of seats."""
        return self.total_seats // 2 + 1

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(name={self.name!r}, seats={self.total_seats})"


class housecham(chamber):
    def __init__(self) -> None:
        super().__init__("house", 435)


class SenateChamber(chamber):
    def __init__(self) -> None:
        super().__init__("senate", 100)


def make_chamber(name: str) -> chamber:
    name = (name or "house").strip().lower()
    return SenateChamber() if name == "senate" else housecham()

@dataclass
class bill:
    bill_id: str
    title: str = ""
    chamber_name: str = "house"
    votes: dict = field(default_factory=dict) 

    def record(self, legislator_id: str, vote: votechoice) -> None:
        self.votes[legislator_id] = vote

    def tally(self) -> dict:
        counts = {votechoice.YEA: 0, votechoice.NAY: 0,
                  votechoice.ABSTAIN: 0, votechoice.ABSENT: 0}
        for v in self.votes.values():
            counts[v] += 1
        return counts

    def passed(self) -> bool:
        t = self.tally()
        return t[votechoice.YEA] > t[votechoice.NAY]

    def party_line_score(self, legislators: dict) -> float:
        def yea_share(party: str) -> float | None:
            yeas = nays = 0
            for lid, v in self.votes.items():
                leg = legislators.get(lid)
                if leg is None or leg.party != party:
                    continue
                if v == votechoice.YEA:
                    yeas += 1
                elif v == votechoice.NAY:
                    nays += 1
            total = yeas + nays
            return (yeas / total) if total else None

        d = yea_share("D")
        r = yea_share("R")
        if d is None or r is None:
            return 0.0
        return abs(d - r)

class congress:
    def __init__(self) -> None:
        self.legislators: dict[str, legislator] = {}
        self.bills: dict[str, bill] = {}

    def add_leg(self, leg: legislator) -> None:
        self.legislators[leg.legislator_id] = leg

    def add_bill(self, bill: bill) -> None:
        self.bills[bill.bill_id] = bill

    @staticmethod
    def slug_id(name: str) -> str:
        base = re.sub(r"\s*\[[^\]]*\]\s*", "", name or "").strip()
        base = base.lower()
        base = re.sub(r"[^a-z0-9]+", "_", base).strip("_")
        return base or "unknown"

    def csv_load(self, path: str, bill_id: str,
                               title: str = "", chamber_name: str = "house") -> bill:
        """Read a congress.gov roll-call CSV (with metadata rows on top)."""
        bill = self.bills.get(bill_id)
        if bill is None:
            bill = bill(bill_id=bill_id, title=title or bill_id,
                        chamber_name=chamber_name)
            self.add_bill(bill)
        else:
            if title:
                bill.title = title

        with open(path, newline="", encoding="utf-8-sig") as f:
            reader = csv.reader(f)
            header_idx = None
            header = []
            rows = list(reader)
            for i, row in enumerate(rows):
                norm = [c.strip().lower() for c in row]
                if norm[:4] == ["representative", "party", "state", "vote"]:
                    header_idx = i
                    header = norm
                    break
                if norm[:4] == ["senator", "party", "state", "vote"]:
                    header_idx = i
                    header = ["representative", "party", "state", "vote"]
                    break
            if header_idx is None:
                raise ValueError(
                    "Could not find header row 'Representative,Party,State,Vote'. "
                    "Make sure this is a congress.gov roll-call download.")
            col = {name: idx for idx, name in enumerate(header)}
            for row in rows[header_idx + 1:]:
                if not row or all(not c.strip() for c in row):
                    continue
                if len(row) <= max(col.values()):
                    continue
                raw_name = row[col["representative"]].strip()
                raw_party = row[col["party"]].strip()
                raw_state = row[col["state"]].strip()
                raw_vote = row[col["vote"]].strip()
                if not raw_name:
                    continue
                lid = self.slug_id(raw_name)
                clean_name = re.sub(r"\s*\[[^\]]*\]\s*", "", raw_name).strip()
                party = legislator.normalize_party(raw_party)
                if lid not in self.legislators:
                    self.add_leg(legislator(
                        legislator_id=lid, name=clean_name,
                        party=party, state=raw_state,
                        chamber=chamber_name))
                bill.record(lid, votechoice.from_string(raw_vote))
        return bill

    def majority(self, bill: bill, party: str) -> votechoice | None:
        yeas = nays = 0
        for lid, v in bill.votes.items():
            leg = self.legislators.get(lid)
            if leg is None or leg.party != party:
                continue
            if v == votechoice.YEA:
                yeas += 1
            elif v == votechoice.NAY:
                nays += 1
        if yeas == 0 and nays == 0:
            return None
        return votechoice.YEA if yeas >= nays else votechoice.NAY

    def bipart_score(self, legislator_id: str) -> float:
        leg = self.legislators.get(legislator_id)
        if leg is None:
            return 0.0
        crossed = total = 0
        for bill in self.bills.values():
            v = bill.votes.get(legislator_id)
            if v not in (votechoice.YEA, votechoice.NAY):
                continue
            majority = self.majority(bill, leg.party)
            if majority is None:
                continue
            total += 1
            if v != majority:
                crossed += 1
        return (crossed / total) if total else 0.0

    def agreerate(self, id1: str, id2: str) -> float:
        same = both = 0
        for bill in self.bills.values():
            v1 = bill.votes.get(id1)
            v2 = bill.votes.get(id2)
            if v1 not in (votechoice.YEA, votechoice.NAY):
                continue
            if v2 not in (votechoice.YEA, votechoice.NAY):
                continue
            both += 1
            if v1 == v2:
                same += 1
        return (same / both) if both else 0.0

    def bipartisan(self, n: int = 5) -> list:
        scored = [(lid, self.bipart_score(lid))
                  for lid in self.legislators]
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:n]


def demo_report(cong: congress) -> str:
    lines = []
    lines.append(f"legislators: {len(cong.legislators)}  Bills: {len(cong.bills)}")
    for bid, bill in cong.bills.items():
        t = bill.tally()
        lines.append(
            f"\nBill {bid} ({bill.title}): "
            f"Yea={t[votechoice.YEA]} Nay={t[votechoice.NAY]} "
            f"Abstain={t[votechoice.ABSTAIN]} Absent={t[votechoice.ABSENT]} "
            f"-> {'PASSED' if bill.passed() else 'FAILED'} "
            f"| party-line={bill.party_line_score(cong.legislators):.2f}")
    lines.append("\nMost bipartisan (cross party lines most):")
    for lid, score in cong.bipartisan(5):
        leg = cong.legislators[lid]
        lines.append(f"  {leg.name} [{leg.party}-{leg.state}] score={score:.2f}")
    return "\n".join(lines)


def main() -> None:
    p = argparse.ArgumentParser(description="Legislative bill & Vote Analyzer")
    p.add_argument("csv", help="congress.gov roll-call CSV path")
    p.add_argument("--bill", default="h119-362", help="bill id label")
    p.add_argument("--title", default="", help="bill title")
    p.add_argument("--chamber", default="house", help="house or senate")
    p.add_argument("--agree", nargs=2, metavar=("ID1", "ID2"),
                   help="show agreement rate between two legislator ids")
    args = p.parse_args()

    cong = congress()
    bill = cong.csv_load(args.csv, args.bill, args.title, args.chamber)
    print(demo_report(cong))
    print(f"\nChambers: House quorum={housecham().quorum()} "
          f"Senate quorum={SenateChamber().quorum()}")
    if args.agree:
        a, b = args.agree
        print(f"\nAgreement {a} vs {b}: {cong.agreerate(a, b):.2%}")


if __name__ == "__main__":
    main()
