from __future__ import annotations

import re
from pathlib import Path
from typing import Optional


class ParserService:
    SITE_POKERSTARS = "PokerStars"
    SITE_GGPOKER = "GGPoker"
    SITE_COINPOKER = "CoinPoker"
    SITE_UNKNOWN = "Unknown"

    def detect_site(self, content: str) -> str:
        sample = content[:50000]
        lower = sample.lower()

        if (
            "coinpoker hand #" in lower
            or "coinpoker game #" in lower
            or ("<game" in lower and "<player" in lower)
        ):
            return self.SITE_COINPOKER

        # Bazı GG exportları PokerStars başlığı kullanıyor.
        # Table adı GG_ ile başlıyorsa GGPoker olarak işaretle.
        if re.search(
            r"Table ['\"]GG_[^'\"]+['\"]",
            sample,
            re.IGNORECASE,
        ):
            return self.SITE_GGPOKER

        if (
            "ggpoker hand #" in lower
            or "ggnetwork hand #" in lower
            or ("poker hand #" in lower and "ggpoker" in lower)
            or "rush & cash" in lower
        ):
            return self.SITE_GGPOKER

        if (
            "pokerstars hand #" in lower
            or "pokerstars game #" in lower
            or "pokerstars zoom hand #" in lower
        ):
            return self.SITE_POKERSTARS

        return self.SITE_UNKNOWN

    def parse_file(self, file_path: str | Path) -> list[dict]:
        path = Path(file_path)

        try:
            content = path.read_text(
                encoding="utf-8",
                errors="ignore",
            )
        except OSError:
            return []

        site = self.detect_site(content)

        if site == self.SITE_UNKNOWN:
            return []

        raw_hands = self.split_hands(content, site)
        parsed_hands: list[dict] = []

        for raw_hand in raw_hands:
            parsed = self.parse_hand(
                raw_hand=raw_hand,
                site=site,
                source_file=str(path),
            )

            if parsed and parsed.get("hand", {}).get("hand_id"):
                parsed_hands.append(parsed)

        return parsed_hands

    def split_hands(
        self,
        content: str,
        site: Optional[str] = None,
    ) -> list[str]:
        if not content or not content.strip():
            return []

        if site is None:
            site = self.detect_site(content)

        if site == self.SITE_COINPOKER:
            return self._split_coinpoker(content)

        if site == self.SITE_POKERSTARS:
            return self._split_pokerstars(content)

        if site == self.SITE_GGPOKER:
            return self._split_ggpoker(content)

        return []

    def parse_hand(
        self,
        raw_hand: str,
        site: str,
        source_file: str = "",
    ) -> Optional[dict]:
        raw_hand = raw_hand.strip()

        if not raw_hand:
            return None

        if site == self.SITE_COINPOKER:
            # Yeni CoinPoker exportları PokerStars-benzeri düz metindir.
            if (
                "CoinPoker Hand #" in raw_hand
                and "*** HOLE CARDS ***" in raw_hand
                and re.search(r"^Seat\s+\d+:", raw_hand, re.MULTILINE)
            ):
                return self._parse_stars_style_hand(
                    raw_hand=raw_hand,
                    detected_site=self.SITE_COINPOKER,
                    source_file=source_file,
                )

            return self._parse_coinpoker_hand(
                raw_hand,
                source_file,
            )

        if site in {
            self.SITE_POKERSTARS,
            self.SITE_GGPOKER,
        }:
            return self._parse_stars_style_hand(
                raw_hand=raw_hand,
                detected_site=site,
                source_file=source_file,
            )

        return None

    # =========================================================
    # COINPOKER
    # =========================================================

    def _split_coinpoker(self, content: str) -> list[str]:
        pattern = re.compile(
            r"(?=CoinPoker (?:Hand|Game) #[\w-]+:)",
            re.IGNORECASE,
        )
        return self._clean_split(pattern.split(content))

    def _parse_coinpoker_hand(
        self,
        raw_hand: str,
        source_file: str,
    ) -> Optional[dict]:
        header = re.search(
            r"CoinPoker (?:Hand|Game) #([\w-]+):"
            r".*?\((?:₮|\$|€|£)?([\d.,]+)"
            r"/(?:₮|\$|€|£)?([\d.,]+)"
            r"(?:\s*-\s*Ante\s*(?:₮|\$|€|£)?([\d.,]+)[^)]*)?"
            r"\)\s*-\s*"
            r"(\d{4}/\d{2}/\d{2}\s+\d{2}:\d{2}:\d{2}(?:\s+[+-]\d{2})?)",
            raw_hand,
            re.IGNORECASE,
        )

        if not header:
            return None

        hand_id = header.group(1).strip()
        small_blind = self._to_float(header.group(2))
        big_blind = self._to_float(header.group(3))
        ante = self._to_float(header.group(4))
        played_at = header.group(5).strip()

        table_match = re.search(
            r"Table ['\"]([^'\"]+)['\"]\s+"
            r"(\d+)-max\s+Seat #(\d+) is the button",
            raw_hand,
            re.IGNORECASE,
        )

        table_name = table_match.group(1).strip() if table_match else None
        max_players = (
            int(table_match.group(2))
            if table_match
            else None
        )
        button_seat = (
            int(table_match.group(3))
            if table_match
            else None
        )

        player_matches = list(
            re.finditer(
                r"^Seat\s+(\d+):\s+(.+?)\s+"
                r"\((?:₮|\$|€|£)?([\d.,]+)\s+in chips\)\s*$",
                raw_hand,
                re.IGNORECASE | re.MULTILINE,
            )
        )

        seats: list[dict] = []

        for match in player_matches:
            seats.append(
                {
                    "seat_no": int(match.group(1)),
                    "player_name": match.group(2).strip(),
                    "starting_stack": self._to_float(
                        match.group(3)
                    ),
                }
            )

        positions = self._calculate_positions(
            seats=seats,
            button_seat=button_seat,
            max_seats=max_players or 6,
        )

        players: list[dict] = []

        for player in seats:
            players.append(
                {
                    "hand_id": hand_id,
                    "seat_no": player["seat_no"],
                    "player_name": player["player_name"],
                    "starting_stack": player["starting_stack"],
                    "position": positions.get(
                        player["seat_no"],
                        "",
                    ),
                }
            )

        flop = self._first_match(
            [
                r"\*\*\* FLOP \*\*\*\s+\[([^\]]+)\]",
            ],
            raw_hand,
        )

        turn = self._first_match(
            [
                r"\*\*\* TURN \*\*\*\s+\[[^\]]+\]\s+\[([^\]]+)\]",
            ],
            raw_hand,
        )

        river = self._first_match(
            [
                r"\*\*\* RIVER \*\*\*\s+\[[^\]]+\]\s+\[([^\]]+)\]",
            ],
            raw_hand,
        )

        summary_match = re.search(
            r"Total pot\s+(?:₮|\$|€|£)?([\d.,]+)"
            r"\s*\|\s*Rake\s+(?:₮|\$|€|£)?([\d.,]+)",
            raw_hand,
            re.IGNORECASE,
        )

        pot = (
            self._to_float(summary_match.group(1))
            if summary_match
            else None
        )
        rake = (
            self._to_float(summary_match.group(2))
            if summary_match
            else None
        )

        actions = self._parse_coinpoker_actions(
            raw_hand=raw_hand,
            hand_id=hand_id,
            player_names={
                player["player_name"]
                for player in players
            },
        )

        hand = {
            "hand_id": hand_id,
            "site": self.SITE_COINPOKER,
            "table_name": table_name,
            "stakes": (
                f"{small_blind:g}/{big_blind:g}"
                if small_blind is not None
                and big_blind is not None
                else None
            ),
            "played_at": played_at,
            "max_players": max_players,
            "button_seat": button_seat,
            "flop": flop,
            "turn": turn,
            "river": river,
            "pot": pot,
            "rake": rake,
            "source_file": source_file,
            "small_blind": small_blind,
            "big_blind": big_blind,
            "ante": ante,
        }

        return {
            "hand": hand,
            "players": players,
            "actions": actions,
        }

    def _parse_coinpoker_actions(
        self,
        raw_hand: str,
        hand_id: str,
        player_names: set[str],
    ) -> list[dict]:
        actions: list[dict] = []
        street = "PREFLOP"
        sequence_no = 0

        for original_line in raw_hand.splitlines():
            line = original_line.strip()

            if not line:
                continue

            upper = line.upper()

            if upper == "*** HOLE CARDS ***":
                street = "PREFLOP"
                continue

            if upper.startswith("*** FLOP ***"):
                street = "FLOP"
                continue

            if upper.startswith("*** TURN ***"):
                street = "TURN"
                continue

            if upper.startswith("*** RIVER ***"):
                street = "RIVER"
                continue

            if "*** SHOWDOWN" in upper:
               street = "SHOWDOWN"
            continue
            
            if upper.startswith("*** SUMMARY ***"):
                break

            action = self._parse_action_line(
                line=line,
                player_names=player_names,
            )

            if action is None:
                continue

            sequence_no += 1

            action.update(
                {
                    "hand_id": hand_id,
                    "sequence_no": sequence_no,
                    "street": street,
                }
            )

            actions.append(action)

        return actions

    def _parse_action_line(
        self,
        line: str,
        player_names: set[str],
    ) -> Optional[dict]:
        if ":" not in line:
            return None

        player_name, action_text = line.split(":", 1)
        player_name = player_name.strip()
        action_text = action_text.strip()

        if player_name not in player_names:
            return None

        lower = action_text.lower()
        all_in = "all-in" in lower

        if lower == "folds":
            return self._action_row(
                player_name,
                "FOLD",
                all_in=all_in,
            )

        if lower == "checks":
            return self._action_row(
                player_name,
                "CHECK",
                all_in=all_in,
            )

        match = re.match(
            r"calls\s+(?:₮|\$|€|£)?([\d.,]+)",
            action_text,
            re.IGNORECASE,
        )
        if match:
            amount = self._to_float(match.group(1))
            return self._action_row(
                player_name,
                "CALL",
                amount=amount,
                to_amount=amount,
                all_in=all_in,
            )

        match = re.match(
            r"bets\s+(?:₮|\$|€|£)?([\d.,]+)",
            action_text,
            re.IGNORECASE,
        )
        if match:
            amount = self._to_float(match.group(1))
            return self._action_row(
                player_name,
                "BET",
                amount=amount,
                to_amount=amount,
                all_in=all_in,
            )

        match = re.match(
            r"raises\s+(?:₮|\$|€|£)?([\d.,]+)"
            r"\s+to\s+(?:₮|\$|€|£)?([\d.,]+)",
            action_text,
            re.IGNORECASE,
        )
        if match:
            amount = self._to_float(match.group(1))
            to_amount = self._to_float(match.group(2))
            return self._action_row(
                player_name,
                "RAISE",
                amount=amount,
                to_amount=to_amount,
                all_in=all_in,
            )

        match = re.match(
            r"posts the ante\s+(?:₮|\$|€|£)?([\d.,]+)",
            action_text,
            re.IGNORECASE,
        )
        if match:
            amount = self._to_float(match.group(1))
            return self._action_row(
                player_name,
                "POST_ANTE",
                amount=amount,
                to_amount=amount,
            )

        match = re.match(
            r"posts small blind\s+(?:₮|\$|€|£)?([\d.,]+)",
            action_text,
            re.IGNORECASE,
        )
        if match:
            amount = self._to_float(match.group(1))
            return self._action_row(
                player_name,
                "POST_SB",
                amount=amount,
                to_amount=amount,
            )

        match = re.match(
            r"posts big blind\s+(?:₮|\$|€|£)?([\d.,]+)",
            action_text,
            re.IGNORECASE,
        )
        if match:
            amount = self._to_float(match.group(1))
            return self._action_row(
                player_name,
                "POST_BB",
                amount=amount,
                to_amount=amount,
            )

        match = re.match(
            r"shows\s+\[([^\]]+)\]",
            action_text,
            re.IGNORECASE,
        )
        if match:
            return self._action_row(
                player_name,
                "SHOW",
                cards=match.group(1).strip(),
            )

        if lower.startswith("mucks hand"):
            return self._action_row(
                player_name,
                "MUCK",
            )

        match = re.match(
            r"collected\s+(?:₮|\$|€|£)?([\d.,]+)\s+from pot",
            action_text,
            re.IGNORECASE,
        )
        if match:
            amount = self._to_float(match.group(1))
            return self._action_row(
                player_name,
                "COLLECT",
                amount=amount,
                to_amount=amount,
            )

        return None

    def _action_row(
        self,
        player_name: str,
        action: str,
        amount: Optional[float] = None,
        to_amount: Optional[float] = None,
        all_in: bool = False,
        cards: Optional[str] = None,
    ) -> dict:
        return {
            "player_name": player_name,
            "action": action,
            "amount": amount,
            "to_amount": to_amount,
            "all_in": all_in,
            "cards": cards,
        }

    def _calculate_positions(
        self,
        seats: list[dict],
        button_seat: Optional[int],
        max_seats: int,
    ) -> dict[int, str]:
        if not seats or button_seat is None:
            return {}

        occupied = {
            int(player["seat_no"])
            for player in seats
        }

        ordered_after_button: list[int] = []

        for offset in range(1, max_seats + 1):
            seat = ((button_seat - 1 + offset) % max_seats) + 1
            if seat in occupied:
                ordered_after_button.append(seat)

        positions: dict[int, str] = {
            button_seat: "BTN",
        }

        player_count = len(occupied)

        if player_count == 2:
            if ordered_after_button:
                positions[ordered_after_button[0]] = "BB"
            return positions

        if ordered_after_button:
            positions[ordered_after_button[0]] = "SB"

        if len(ordered_after_button) >= 2:
            positions[ordered_after_button[1]] = "BB"

        remaining = ordered_after_button[2:]

        preflop_maps = {
            1: ["CO"],
            2: ["UTG", "CO"],
            3: ["UTG", "HJ", "CO"],
            4: ["UTG", "UTG+1", "HJ", "CO"],
            5: ["UTG", "UTG+1", "MP", "HJ", "CO"],
            6: ["UTG", "UTG+1", "MP", "MP+1", "HJ", "CO"],
        }

        labels = preflop_maps.get(
            len(remaining),
            [f"EP{i + 1}" for i in range(len(remaining))],
        )

        for seat, label in zip(remaining, labels):
            positions[seat] = label

        return positions

    # =========================================================
    # POKERSTARS / GG POKERSTARS-STYLE EXPORT
    # =========================================================

    def _split_pokerstars(self, content: str) -> list[str]:
        pattern = re.compile(
            r"(?=PokerStars(?: Zoom)? (?:Hand|Game) #\d+)",
            re.IGNORECASE,
        )
        return self._clean_split(pattern.split(content))

    def _split_ggpoker(self, content: str) -> list[str]:
        # GG exportu bazen PokerStars header'ı kullanır.
        patterns = [
            re.compile(
                r"(?=PokerStars(?: Zoom)? (?:Hand|Game) #\d+)",
                re.IGNORECASE,
            ),
            re.compile(
                r"(?=GGPoker Hand #[\w-]+)",
                re.IGNORECASE,
            ),
            re.compile(
                r"(?=GGNetwork Hand #[\w-]+)",
                re.IGNORECASE,
            ),
            re.compile(
                r"(?=Poker Hand #[\w-]+:)",
                re.IGNORECASE,
            ),
        ]

        for pattern in patterns:
            parts = self._clean_split(pattern.split(content))
            if parts:
                return parts

        return []

    def _parse_stars_style_hand(
        self,
        raw_hand: str,
        detected_site: str,
        source_file: str,
    ) -> Optional[dict]:
        hand_id = self._first_match(
            [
                r"CoinPoker Hand #(\d+)",
                r"PokerStars(?: Zoom)? (?:Hand|Game) #(\d+)",
                r"GGPoker Hand #([\w-]+)",
                r"GGNetwork Hand #([\w-]+)",
                r"Poker Hand #([\w-]+)",
            ],
            raw_hand,
        )

        if not hand_id:
            return None

        table_match = re.search(
            r"Table ['\"]([^'\"]+)['\"]\s+"
            r"(\d+)-max\s+Seat #(\d+) is the button",
            raw_hand,
            re.IGNORECASE,
        )

        table_name = table_match.group(1).strip() if table_match else None
        max_players = int(table_match.group(2)) if table_match else None
        button_seat = int(table_match.group(3)) if table_match else None

        # GG exportu PokerStars başlığı kullanıyorsa table isminden siteyi düzelt.
        site = detected_site
        if table_name and table_name.upper().startswith("GG_"):
            site = self.SITE_GGPOKER

        header_match = re.search(
            r"(?:CoinPoker Hand|PokerStars(?: Zoom)? (?:Hand|Game)|"
            r"GGPoker Hand|GGNetwork Hand|Poker Hand)\s+#?[\w-]+:"
            r".*?\((?:₮|\$|€|£)?([\d.,]+)"
            r"/(?:₮|\$|€|£)?([\d.,]+)\)"
            r"\s*-\s*"
            r"(\d{4}[/-]\d{2}[/-]\d{2}\s+\d{2}:\d{2}:\d{2})",
            raw_hand,
            re.IGNORECASE,
        )

        small_blind = (
            self._to_float(header_match.group(1))
            if header_match
            else None
        )
        big_blind = (
            self._to_float(header_match.group(2))
            if header_match
            else None
        )
        played_at = (
            header_match.group(3).replace("-", "/")
            if header_match
            else None
        )

        player_matches = list(
            re.finditer(
                r"^Seat\s+(\d+):\s+(.+?)\s+"
                r"\((?:₮|\$|€|£)?([\d.,]+)\s+in chips\)\s*$",
                raw_hand,
                re.IGNORECASE | re.MULTILINE,
            )
        )

        seats: list[dict] = []

        for match in player_matches:
            seats.append(
                {
                    "seat_no": int(match.group(1)),
                    "player_name": match.group(2).strip(),
                    "starting_stack": self._to_float(
                        match.group(3)
                    ),
                }
            )


        flop = self._first_match(
            [r"\*\*\* FLOP \*\*\*\s+\[([^\]]+)\]"],
            raw_hand,
        )
        turn = self._first_match(
            [
                r"\*\*\* TURN \*\*\*\s+\[[^\]]+\]\s+\[([^\]]+)\]",
            ],
            raw_hand,
        )
        river = self._first_match(
            [
                r"\*\*\* RIVER \*\*\*\s+\[[^\]]+\]\s+\[([^\]]+)\]",
            ],
            raw_hand,
        )

        summary_match = re.search(
            r"Total pot\s+(?:₮|\$|€|£)?([\d.,]+)"
            r"\s*\|\s*Rake\s+(?:₮|\$|€|£)?([\d.,]+)",
            raw_hand,
            re.IGNORECASE,
        )

        pot = (
            self._to_float(summary_match.group(1))
            if summary_match
            else None
        )
        rake = (
            self._to_float(summary_match.group(2))
            if summary_match
            else None
        )

        # Önce Seat satırındaki bütün isimleri kullanarak aksiyonları parse et.
all_player_names = {
    seat["player_name"]
    for seat in seats
}

actions = self._parse_stars_style_actions(
    raw_hand=raw_hand,
    hand_id=hand_id,
    player_names=all_player_names,
)

# Aksiyonlarda gerçekten görünen oyuncular bu ele dealt-in kabul edilir.
# Sitting-out oyuncular Seat listesinde olsa bile aksiyonlarda görünmez.
active_player_names = {
    str(action.get("player_name") or "").strip()
    for action in actions
    if str(action.get("player_name") or "").strip()
}

active_seats = [
    seat
    for seat in seats
    if seat["player_name"] in active_player_names
]

# Aksiyon parserı tamamen başarısız olursa bütün oyuncuları yanlışlıkla
# silmemek için güvenli fallback.
if not active_seats:
    active_seats = seats

# ÖNEMLİ: max_seats olarak len(active_seats) kullanma.
# Seat numaraları 1–6 fiziksel masa numaralarıdır ve aralarda boşluk olabilir.
positions = self._calculate_positions(
    seats=active_seats,
    button_seat=button_seat,
    max_seats=max_players or 6,
)

players = [
    {
        "hand_id": hand_id,
        "seat_no": player["seat_no"],
        "player_name": player["player_name"],
        "starting_stack": player["starting_stack"],
        "position": positions.get(
            player["seat_no"],
            "",
        ),
    }
    for player in active_seats
]
    return {
        "hand": {
        ...
         },
        "players": players,
        "actions": actions,
    }

        return {
            "hand": {
                "hand_id": hand_id,
                "site": site,
                "table_name": table_name,
                "stakes": (
                    f"{small_blind:g}/{big_blind:g}"
                    if small_blind is not None
                    and big_blind is not None
                    else None
                ),
                "played_at": played_at,
                "max_players": max_players,
                "button_seat": button_seat,
                "flop": flop,
                "turn": turn,
                "river": river,
                "pot": pot,
                "rake": rake,
                "source_file": source_file,
                "small_blind": small_blind,
                "big_blind": big_blind,
                "ante": None,
            },
            "players": players,
            "actions": actions,
        }

    def _parse_stars_style_actions(
        self,
        raw_hand: str,
        hand_id: str,
        player_names: set[str],
    ) -> list[dict]:
        actions: list[dict] = []
        street = "PREFLOP"
        sequence_no = 0

        for original_line in raw_hand.splitlines():
            line = original_line.strip()

            if not line:
                continue

            upper = line.upper()
            lower = line.lower()

            if upper == "*** HOLE CARDS ***":
                street = "PREFLOP"
                continue

            if upper.startswith("*** FLOP ***"):
                street = "FLOP"
                continue

            if upper.startswith("*** TURN ***"):
                street = "TURN"
                continue

            if upper.startswith("*** RIVER ***"):
                street = "RIVER"
                continue

            if upper.startswith("*** SHOWDOWN ***"):
                street = "SHOWDOWN"
                continue

            if upper.startswith("*** SHOW DOWN ***"):
                street = "SHOWDOWN"
                continue

            if upper.startswith("*** SUMMARY ***"):
                break

            # GG insurance / premium satırları poker aksiyonu değildir.
            if (
                "all-in insurance" in lower
                or "pay premium" in lower
                or "mandatory/main/sub" in lower
            ):
                continue

            # Oyuncu prefix'i olmayan iade satırı.
            returned_match = re.match(
                r"Uncalled bet\s+\((?:₮|\$|€|£)?([\d.,]+)\)"
                r"\s+returned to\s+(.+)$",
                line,
                re.IGNORECASE,
            )
            if returned_match:
                player_name = returned_match.group(2).strip()

                if player_name in player_names:
                    sequence_no += 1
                    actions.append(
                        {
                            "hand_id": hand_id,
                            "sequence_no": sequence_no,
                            "street": street,
                            "player_name": player_name,
                            "action": "RETURN",
                            "amount": self._to_float(
                                returned_match.group(1)
                            ),
                            "to_amount": None,
                            "all_in": False,
                            "cards": None,
                        }
                    )
                continue

            # "Player collected X from pot" satırı iki nokta içermez.
            collect_match = re.match(
                r"(.+?)\s+collected\s+"
                r"(?:₮|\$|€|£)?([\d.,]+)\s+from pot",
                line,
                re.IGNORECASE,
            )
            if collect_match:
                player_name = collect_match.group(1).strip()

                if player_name in player_names:
                    sequence_no += 1
                    actions.append(
                        {
                            "hand_id": hand_id,
                            "sequence_no": sequence_no,
                            "street": "SHOWDOWN",
                            "player_name": player_name,
                            "action": "COLLECT",
                            "amount": self._to_float(
                                collect_match.group(2)
                            ),
                            "to_amount": None,
                            "all_in": False,
                            "cards": None,
                        }
                    )
                continue

            action = self._parse_action_line(
                line=line,
                player_names=player_names,
            )

            if action is None:
                continue

            sequence_no += 1

            action.update(
                {
                    "hand_id": hand_id,
                    "sequence_no": sequence_no,
                    "street": street,
                }
            )

            actions.append(action)

        return actions

    # =========================================================
    # HELPERS
    # =========================================================

    def _first_match(
        self,
        patterns: list[str],
        text: str,
        combine_groups: bool = False,
    ) -> Optional[str]:
        for pattern in patterns:
            match = re.search(
                pattern,
                text,
                re.IGNORECASE | re.DOTALL,
            )

            if not match:
                continue

            if combine_groups and len(match.groups()) >= 2:
                return (
                    f"{match.group(1).strip()}/"
                    f"{match.group(2).strip()}"
                )

            value = match.group(1).strip()

            if "\n" in value:
                value = value.splitlines()[0].strip()

            return value

        return None

    def _to_float(
        self,
        value: Optional[str],
    ) -> Optional[float]:
        if value is None:
            return None

        cleaned = value.strip().replace(",", ".")

        try:
            return float(cleaned)
        except ValueError:
            return None

    def _clean_split(self, parts: list[str]) -> list[str]:
        return [
            part.strip()
            for part in parts
            if part and part.strip()
        ]
