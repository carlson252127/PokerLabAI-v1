from __future__ import annotations

import re
from pathlib import Path
from typing import Iterator, Optional

from services.position_service import calculate_positions


class ParserService:
    SITE_POKERSTARS = "PokerStars"
    SITE_GGPOKER = "GGPoker"
    SITE_COINPOKER = "CoinPoker"
    SITE_UNKNOWN = "Unknown"

    _TEXT_HAND_HEADER = re.compile(
        r"^(?:(?:PokerStars(?: Zoom)?|GGPoker|GGNetwork|CoinPoker)\s+"
        r"(?:Hand|Game)|Poker\s+Hand)\s+#",
        re.IGNORECASE,
    )

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

    def iter_file(self, file_path: str | Path) -> Iterator[dict]:
        """Yield parsed hands without retaining a whole text export in memory.

        Legacy CoinPoker XML does not have reliable line-delimited hand
        boundaries, so it intentionally uses the established parser fallback.
        """
        path = Path(file_path)
        try:
            with path.open("r", encoding="utf-8", errors="ignore") as source:
                sample = source.read(50_000)
                site = self.detect_site(sample)
                is_xml = site == self.SITE_COINPOKER and "<game" in sample.lower()
                source.seek(0)
                if site == self.SITE_UNKNOWN or is_xml:
                    for parsed in self.parse_file(path):
                        yield parsed
                    return

                lines: list[str] = []
                for line in source:
                    if self._TEXT_HAND_HEADER.match(line.strip()) and lines:
                        parsed = self.parse_hand(
                            raw_hand="".join(lines),
                            site=site,
                            source_file=str(path),
                        )
                        if parsed and parsed.get("hand", {}).get("hand_id"):
                            yield parsed
                        lines = []
                    lines.append(line)

                if lines:
                    parsed = self.parse_hand(
                        raw_hand="".join(lines),
                        site=site,
                        source_file=str(path),
                    )
                    if parsed and parsed.get("hand", {}).get("hand_id"):
                        yield parsed
        except OSError:
            return

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
            # Modern CoinPoker exports are PokerStars-style plain text.
            if (
                "CoinPoker Hand #" in raw_hand
                and "*** HOLE CARDS ***" in raw_hand
                and re.search(
                    r"^Seat\s+\d+:",
                    raw_hand,
                    re.MULTILINE,
                )
            ):
                return self._parse_stars_style_hand(
                    raw_hand=raw_hand,
                    detected_site=self.SITE_COINPOKER,
                    source_file=source_file,
                )

            # Keep compatibility with older CoinPoker formats.
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

            if upper.startswith("*** SHOW DOWN ***"):
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
        return calculate_positions(
            seats=seats,
            button_seat=button_seat,
            max_seats=max_seats,
        )

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

        table_name = (
            table_match.group(1).strip()
            if table_match
            else None
        )
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

        site = detected_site

        # Some GG exports use a PokerStars header.
        if (
            table_name
            and table_name.upper().startswith("GG_")
        ):
            site = self.SITE_GGPOKER

        # Supports:
        # PokerStars/GG: ($1/$2) - date
        # CoinPoker: (₮0.25/₮0.50 - Ante ₮0.08 CPCC) - date +00
        header_match = re.search(
            r"(?:CoinPoker Hand|"
            r"PokerStars(?: Zoom)? (?:Hand|Game)|"
            r"GGPoker Hand|GGNetwork Hand|Poker Hand)"
            r"\s+#?[\w-]+:"
            r".*?\("
            r"(?:₮|\$|€|£)?([\d.,]+)"
            r"/(?:₮|\$|€|£)?([\d.,]+)"
            r"(?:\s*-\s*Ante\s*"
            r"(?:₮|\$|€|£)?([\d.,]+)[^)]*)?"
            r"\)"
            r"\s*-\s*"
            r"(\d{4}[/-]\d{2}[/-]\d{2}"
            r"\s+\d{2}:\d{2}:\d{2}"
            r"(?:\s+[+-]\d{2}(?::?\d{2})?)?)",
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
        ante = (
            self._to_float(header_match.group(3))
            if header_match
            and header_match.group(3)
            else None
        )
        played_at = (
            header_match.group(4).replace("-", "/")
            if header_match
            else None
        )


        # CoinPoker web-download format
        coin_download_header = re.search(
            r"^CoinPoker Hand\s+#?[\w-]+:\s*"
            r"(?:NLH|Hold(?:'|’)em(?:\s+No\s+Limit)?)\s*"
            r"\((?:₮|\$|€|£)?([\d.,]+)"
            r"/(?:₮|\$|€|£)?([\d.,]+)"
            r"/(?:₮|\$|€|£)?([\d.,]+)\)\s*"
            r"(\d{4}[/-]\d{2}[/-]\d{2}\s+\d{2}:\d{2}:\d{2})"
            r"(?:\s+[+-]\d{2}(?::?\d{2})?)?",
            raw_hand,
            re.IGNORECASE | re.MULTILINE,
        )

        ante = None

        if coin_download_header:
            small_blind = self._to_float(coin_download_header.group(1))
            big_blind = self._to_float(coin_download_header.group(2))
            ante = self._to_float(coin_download_header.group(3))
            played_at = coin_download_header.group(4).replace("-", "/")

        player_matches = list(
            re.finditer(
                r"^Seat\s+(\d+):\s+(.+?)\s+"
                r"\((?:₮|\$|€|£)?([\d.,]+)"
                r"\s+in chips\)\s*$",
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

        if not seats:
            return None

        # Parse with every seat name first, so action matching is not
        # affected by dealt-in filtering.
        all_player_names = {
            seat["player_name"]
            for seat in seats
        }

        actions = self._parse_stars_style_actions(
            raw_hand=raw_hand,
            hand_id=hand_id,
            player_names=all_player_names,
        )

        # A seat can be present while the player is sitting out/not dealt in.
        # Active players appear in at least one parsed action:
        # posting, folding, calling, raising, checking, showing or collecting.
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

        # Safe fallback: if the action parser fails completely, retain seats
        # rather than deleting every player from the hand.
        if not active_seats:
            active_seats = seats

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

        flop = self._first_match(
            [
                r"\*\*\* FLOP \*\*\*"
                r"\s+\[([^\]]+)\]",
            ],
            raw_hand,
        )
        turn = self._first_match(
            [
                r"\*\*\* TURN \*\*\*"
                r"\s+\[[^\]]+\]\s+\[([^\]]+)\]",
            ],
            raw_hand,
        )
        river = self._first_match(
            [
                r"\*\*\* RIVER \*\*\*"
                r"\s+\[[^\]]+\]\s+\[([^\]]+)\]",
            ],
            raw_hand,
        )

        summary_match = re.search(
            r"Total pot\s+"
            r"(?:₮|\$|€|£)?([\d.,]+)"
            r"\s*\|\s*Rake\s+"
            r"(?:₮|\$|€|£)?([\d.,]+)",
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
                "ante": ante,
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
