import random
from dataclasses import dataclass

import jieba

from card_guess.cards import get_visible_traits, render_description
from card_guess.puzzle import (
    build_puzzle,
    count_effective_chars,
    find_phrase_positions,
)


def get_hint_type(wrong_count):
    if wrong_count == 2:
        return "rarity"

    if wrong_count == 4:
        return "description"

    if wrong_count == 6:
        return "name"

    if wrong_count >= 8 and wrong_count % 2 == 0:
        return "description" if wrong_count % 4 == 0 else "name"

    return None


@dataclass
class GuessResult:
    status: str
    revealed_count: int = 0
    reveal_target: str | None = None
    hint_type: str | None = None
    terminal_reason: str | None = None


class GameState:
    def __init__(self, card):
        self.card = card
        self.wrong_count = 0
        self.total_guess_count = 0
        self.description_reveal_count = 0
        self.successful_reveal_count = 0
        self.early_name_hint_triggered = False
        self.wrong_guesses = []
        self.ended = False
        self.rarity_revealed = False
        self.revealed_positions = set()
        self.revealed_name_positions = set()
        self.revealed_traits = set()

    def guess_name_phrase(self, phrase):
        if self.ended:
            return GuessResult(status="ended")

        if count_effective_chars(phrase) == 0:
            return GuessResult(status="invalid")

        name = self.card["name"]

        matched_positions = find_phrase_positions(
            name,
            phrase,
        )

        if not matched_positions:
            return None

        new_positions = matched_positions - self.revealed_name_positions

        if not new_positions:
            return GuessResult(
                status="already_revealed",
                reveal_target="name",
            )

        self.revealed_name_positions.update(new_positions)
        self._record_successful_reveal()

        if len(self.revealed_name_positions) >= len(name):
            self.ended = True
            return GuessResult(
                status="revealed",
                revealed_count=len(new_positions),
                reveal_target="name",
            )

        return GuessResult(
            status="revealed",
            revealed_count=len(new_positions),
            reveal_target="name",
        )

    def reveal_positions(self, positions):
        self.revealed_positions.update(positions)

    def handle_input(self, text):
        if self.ended:
            return GuessResult(status="ended")

        if text == self.card["name"]:
            self.ended = True
            result = GuessResult(status="correct")
            self._record_player_input(text, result.status)
            return result

        name_result = self.guess_name_phrase(text)
        if name_result is not None:
            self._record_player_input(text, name_result.status)
            return name_result

        description_match = self._find_description_match(text)
        if description_match is not None:
            new_positions = description_match - self.revealed_positions
            if not new_positions:
                result = GuessResult(status="already_revealed", reveal_target="description")
            else:
                self.reveal_positions(new_positions)
                hint_type = self._on_successful_description_reveal()
                result = GuessResult(
                    status="revealed",
                    revealed_count=len(new_positions),
                    reveal_target="description",
                    hint_type=hint_type,
                )
            self._record_player_input(text, result.status)
            return result

        result = self.guess_description_phrase(text)
        self._record_player_input(text, result.status)
        return result

    def _find_description_match(self, phrase):
        if count_effective_chars(phrase) == 0:
            return None

        if self.card.get("description") is None:
            return None

        description = render_description(self.card)
        matched_positions = find_phrase_positions(
            description,
            phrase,
        )
        return matched_positions or None

    def guess_description_phrase(self, phrase):
        if self.ended:
            return GuessResult(status="ended")

        if count_effective_chars(phrase) == 0:
            return GuessResult(status="invalid")

        if self.card.get("description") is None:
            self.wrong_count += 1
            hint_type = self._apply_automatic_hint_for_count(self.wrong_count)
            return GuessResult(
                status="wrong",
                hint_type=hint_type,
                terminal_reason="hint_exhausted" if self.ended else None,
            )

        description = render_description(self.card)

        matched_positions = find_phrase_positions(
            description,
            phrase,
        )

        if not matched_positions:
            self.wrong_count += 1
            hint_type = self._apply_automatic_hint_for_count(self.wrong_count)
            return GuessResult(
                status="wrong",
                hint_type=hint_type,
                terminal_reason="hint_exhausted" if self.ended else None,
            )

        new_positions = matched_positions - self.revealed_positions

        if not new_positions:
            return GuessResult(status="already_revealed")

        self.reveal_positions(new_positions)
        hint_type = self._on_successful_description_reveal()

        return GuessResult(
            status="revealed",
            revealed_count=len(new_positions),
            reveal_target="description",
            hint_type=hint_type,
        )

    def guess_trait_phrase(self, phrase):
        if self.ended:
            return GuessResult(status="ended")

        if count_effective_chars(phrase) == 0:
            return GuessResult(status="invalid")

        traits = get_visible_traits(
            self.card,
            upgraded=bool(self.card.get("upgraded", False)),
        )
        if not traits:
            return None

        matched_trait = None
        for trait in traits:
            if find_phrase_positions(trait, phrase):
                matched_trait = trait
                break

        if matched_trait is None:
            return None

        if matched_trait in self.revealed_traits:
            return GuessResult(status="already_revealed", reveal_target="trait")

        self.revealed_traits.add(matched_trait)
        return GuessResult(
            status="revealed",
            revealed_count=1,
            reveal_target="trait",
        )

    def _record_player_input(self, text, status):
        if status in {"correct", "revealed", "wrong", "already_revealed"}:
            self.total_guess_count += 1

        if status == "wrong" and text not in self.wrong_guesses:
            self.wrong_guesses.append(text)

    def _record_successful_reveal(self):
        self.successful_reveal_count += 1

        if self.early_name_hint_triggered or self.successful_reveal_count < 3:
            return None

        self.early_name_hint_triggered = True
        unknown_positions = [
            index
            for index in range(len(self.card["name"]))
            if index not in self.revealed_name_positions
        ]
        if len(unknown_positions) <= 1:
            return None

        hint = self.name_hint()
        if hint is not None:
            return "name"
        return None

    def _on_successful_description_reveal(self):
        self.description_reveal_count += 1
        return self._record_successful_reveal()

    def should_hint(self):
        return get_hint_type(self.wrong_count) is not None

    def build_puzzle(self):
        return build_puzzle(
            self.card,
            revealed_positions=self.revealed_positions,
            revealed_name_positions=self.revealed_name_positions,
            rarity_revealed=self.rarity_revealed,
        )

    def _apply_automatic_hint_for_count(self, wrong_count):
        hint_type = get_hint_type(wrong_count)

        if hint_type is None:
            return None

        if hint_type == "rarity":
            self.rarity_revealed = True
            return "rarity"

        if hint_type == "description":
            hint = self.description_hint()
            if hint is not None:
                return "description"
            fallback = self.name_hint()
            if fallback is not None:
                return "name"
            self.ended = True
            return None

        if hint_type == "name":
            hint = self.name_hint()
            if hint is not None:
                return "name"
            fallback = self.description_hint()
            if fallback is not None:
                return "description"
            self.ended = True
            return None

        return None

    def description_hint(self):
        if not self.card.get("description"):
            return None

        description = render_description(self.card)
        candidate_groups = []

        for token, _, _ in jieba.tokenize(description):
            if not token:
                continue
            if not any(char.isalpha() for char in token):
                continue

            positions = set(find_phrase_positions(description, token))
            if not positions or positions.issubset(self.revealed_positions):
                continue

            new_positions = positions - self.revealed_positions
            if not new_positions:
                continue

            text_char_count = sum(
                1 for pos in new_positions if description[pos].isalpha()
            )

            if text_char_count >= 2:
                candidate_groups.append((text_char_count, positions, new_positions))

        if not candidate_groups:
            for token, _, _ in jieba.tokenize(description):
                if not token:
                    continue
                if not any(char.isalpha() for char in token):
                    continue

                positions = set(find_phrase_positions(description, token))
                if not positions or positions.issubset(self.revealed_positions):
                    continue

                new_positions = positions - self.revealed_positions
                if not new_positions:
                    continue

                text_char_count = sum(
                    1 for pos in new_positions if description[pos].isalpha()
                )

                if text_char_count == 1:
                    candidate_groups.append((text_char_count, positions, new_positions))

        if not candidate_groups:
            return None

        _, _, chosen_positions = random.choice(candidate_groups)
        self.revealed_positions.update(chosen_positions)

        return {
            "kind": "description",
            "revealed_count": len(chosen_positions),
        }

    def name_hint(self):
        if not self.card.get("name"):
            return None

        unknown_positions = [
            index
            for index in range(len(self.card["name"]))
            if index not in self.revealed_name_positions
        ]

        if len(unknown_positions) <= 1:
            return None

        position = random.choice(unknown_positions)
        self.revealed_name_positions.add(position)

        return {
            "kind": "name",
            "revealed_count": 1,
        }

    def end(self):
        self.ended = True
        return self.card["name"]
