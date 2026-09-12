from __future__ import annotations

import argparse
import csv
import re
from collections import Counter
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

        match s:
            case "yea" | "yes" | "aye" | "y":
                return votechoice.YEA

            case "nay" | "no" | "n":
                return votechoice.NAY

            case "present" | "abstain" | "abstention" | "pres":
                return votechoice.ABSTAIN

            case _:
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

        match s:
            case _ if s.startswith("democrat") or s == "d":
                return "D"

            case _ if s.startswith("republican") or s == "r":
                return "R"

            case _:
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


class senatecham(chamber):
    def __init__(self) -> None:
        super().__init__("senate", 100)


def make_cham(name: str) -> chamber:
    name = (name or "house").strip().lower()

    return senatecham() if name == "senate" else housecham()

@dataclass
class bill:
    bill_id: str
    title: str = ""
    chamber_name: str = "house"
    votes: dict = field(default_factory=dict) 

    def record(self, legislator_id: str, vote: votechoice) -> None:
        self.votes[legislator_id] = vote

    def tally(self) -> dict:
        votecount = Counter(self.votes.values())

        return {
            votechoice.YEA: votecount.get(votechoice.YEA, 0),
            votechoice.NAY: votecount.get(votechoice.NAY, 0),
            votechoice.ABSTAIN: votecount.get(votechoice.ABSTAIN, 0),
            votechoice.ABSENT: votecount.get(votechoice.ABSENT, 0),
        }

    def passed(self) -> bool:
        t = self.tally()

        return t[votechoice.YEA] > t[votechoice.NAY]

    def _yeasha(self, legislators: dict, party: str) -> float | None:
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

    def pl_score(self, legislators: dict) -> float:
        d = self._yeasha(legislators, "D")
        r = self._yeasha(legislators, "R")

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

    @staticmethod
    def _findheadrow(rows: list) -> tuple[int | None, list]:
        for i, row in enumerate(rows):
            norm = [c.strip().lower() for c in row]

            match norm[:4]:
                case ["representative", "party", "state", "vote"]:
                    return i, norm

                case ["senator", "party", "state", "vote"]:
                    return i, ["representative", "party", "state", "vote"]

        return None, []

    def _ensureleg(self, raw_name: str, raw_party: str,
                           raw_state: str, chamber_name: str) -> str:
        lid = self.slug_id(raw_name)
        clean_name = re.sub(r"\s*\[[^\]]*\]\s*", "", raw_name).strip()
        party = legislator.normalize_party(raw_party)

        if lid not in self.legislators:
            self.add_leg(legislator(
                legislator_id=lid, name=clean_name,
                party=party, state=raw_state,
                chamber=chamber_name))

        return lid

    def csv_load(self, path: str, bill_id: str,
                               title: str = "", chamber_name: str = "house") -> bill:
        """Read a congress.gov roll-call CSV (with metadata rows on top)."""
        existing = self.bills.get(bill_id)

        if existing is None:
            existing = bill(bill_id=bill_id, title=title or bill_id,
                            chamber_name=chamber_name)
            self.add_bill(existing)
        elif title:
            existing.title = title

        with open(path, newline="", encoding="utf-8-sig") as f:
            reader = csv.reader(f)
            rows = list(reader)

            headeridx, header = self._findheadrow(rows)

            if headeridx is None:
                raise ValueError(
                    "Could not find header row 'Representative,Party,State,Vote'. "
                    "Make sure this is a congress.gov roll-call download.")

            col = {name: idx for idx, name in enumerate(header)}

            for row in rows[headeridx + 1:]:
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

                lid = self._ensureleg(
                    raw_name, raw_party, raw_state, chamber_name)

                existing.record(lid, votechoice.from_string(raw_vote))

        return existing

    def majority(self, targ_bill: bill, party: str) -> votechoice | None:
        yeas = nays = 0

        for lid, v in targ_bill.votes.items():
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

        majorities = {
            bid: self.majority(b, leg.party)
            for bid, b in self.bills.items()
        }

        crossed = total = 0

        for bid, b in self.bills.items():
            v = b.votes.get(legislator_id)

            if v not in (votechoice.YEA, votechoice.NAY):
                continue

            maj = majorities[bid]

            if maj is None:
                continue

            total += 1

            if v != maj:
                crossed += 1

        return (crossed / total) if total else 0.0

    def agreerate(self, id1: str, id2: str) -> float:
        same = both = 0

        for b in self.bills.values():
            v1 = b.votes.get(id1)
            v2 = b.votes.get(id2)

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


def demo_rep(cong: congress) -> str:
    lines = []
    lines.append(f"legislators: {len(cong.legislators)}  Bills: {len(cong.bills)}")

    lines.extend([
        f"\nBill {bid} ({b.title}): "
        f"Yea={t[votechoice.YEA]} Nay={t[votechoice.NAY]} "
        f"Abstain={t[votechoice.ABSTAIN]} Absent={t[votechoice.ABSENT]} "
        f"-> {'PASSED' if b.passed() else 'FAILED'} "
        f"| party-line={b.pl_score(cong.legislators):.2f}"
        for bid, b in cong.bills.items()
        for t in [b.tally()]
    ])

    lines.append("\nMost bipartisan (cross party lines most):")

    lines.extend([
        f"  {cong.legislators[lid].name} "
        f"[{cong.legislators[lid].party}-{cong.legislators[lid].state}] "
        f"score={score:.2f}"
        for lid, score in cong.bipartisan(5)
    ])

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
    loaded = cong.csv_load(args.csv, args.bill, args.title, args.chamber)

    print(demo_rep(cong))

    print(f"\nChambers: House quorum={housecham().quorum()} "
          f"Senate quorum={senatecham().quorum()}")

    if args.agree:
        a, b = args.agree

        print(f"\nAgreement {a} vs {b}: {cong.agreerate(a, b):.2%}")


if __name__ == "__main__":
    main()
