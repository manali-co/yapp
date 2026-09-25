"""A cursor over the committed transcript. Everything after the cursor is what Jev sees."""

from __future__ import annotations


class Stream:
    def __init__(self, lookahead: int) -> None:
        self.lookahead = lookahead
        self.reset()

    def reset(self) -> None:
        self.committed: list[str] = []
        self.cursor = 0
        self.dictating = False
        self._typed_upto = 0
        self._fired: set[tuple[int, int]] = set()

    def set_committed(self, words: list[str]) -> bool:
        grew = len(words) > len(self.committed)
        if len(words) >= len(self.committed):
            self.committed = list(words)
        return grew

    def tail(self) -> str:
        start = max(self.cursor, self._typed_upto) if self.dictating else self.cursor
        return " ".join(self.committed[start:])

    def consume(self, n: int) -> None:
        self.cursor = min(len(self.committed), self.cursor + n)

    def already_fired(self, n: int) -> bool:
        return (self.cursor, n) in self._fired

    def mark_fired(self, n: int) -> None:
        self._fired.add((self.cursor, n))

    def enter_dictation(self) -> None:
        self.dictating = True
        self._typed_upto = self.cursor

    def exit_dictation(self) -> None:
        self.dictating = False
        self.cursor = max(self.cursor, self._typed_upto)

    def dictation_words(self, *, flush: bool = False) -> list[str]:
        """Words to type now. Holds back the last `lookahead` words unless flushing."""
        if flush:
            end = len(self.committed)
        else:
            end = max(self._typed_upto, len(self.committed) - self.lookahead)
        words = self.committed[self._typed_upto : end]
        self._typed_upto = end
        return words
