from card_guess.cards import render_description
from card_guess.puzzle import (
    count_effective_chars,
    find_phrase_positions,
)
from dataclasses import dataclass

@dataclass
class GuessResult:
    status: str
    revealed_count: int = 0
    reveal_target: str | None = None

class GameState:
    def __init__(self, card):
        self.card = card
        self.wrong_count = 0
        self.ended = False
        self.revealed_positions = set()
        self.revealed_name_positions = set()

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

        return GuessResult(
            status="revealed",
            revealed_count=len(new_positions),
            reveal_target="name",
        )

    def guess(self, guess_name):
        if self.ended:
            return "ended"

        if guess_name == self.card["name"]:
            self.ended = True
            return "correct"

        self.wrong_count += 1
        return "wrong"

    def reveal_positions(self, positions):
        self.revealed_positions.update(positions)

    def handle_input(self, text):
        if self.ended:
            return GuessResult(status="ended")

        if text == self.card["name"]:
            self.ended = True
            return GuessResult(status="correct")

        return self.guess_description_phrase(text)

    def guess_description_phrase(self, phrase):
        if self.ended:
            return GuessResult(status="ended")

        if count_effective_chars(phrase) == 0:
            return GuessResult(status="invalid")

        description = render_description(self.card)

        matched_positions = find_phrase_positions(
            description,
            phrase,
        )

        if not matched_positions:
            self.wrong_count += 1
            return GuessResult(status="wrong")

        new_positions = matched_positions - self.revealed_positions

        if not new_positions:
            return GuessResult(status="already_revealed")

        self.reveal_positions(new_positions)

        return GuessResult(
            status="revealed",
            revealed_count=len(new_positions),
        )

    def should_hint(self):
        return self.wrong_count > 0 and self.wrong_count % 4 == 0

    def end(self):
        self.ended = True
        return self.card["name"]