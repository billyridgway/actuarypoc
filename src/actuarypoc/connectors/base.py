from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Iterable, Mapping, Any


Record = Mapping[str, Any]


class DataConnector(ABC):
    """Abstract connector contract."""

    @abstractmethod
    def fetch(self) -> Iterable[Record]:
        """Return an iterable of normalized records."""


class CSVConnector(DataConnector):
    def __init__(self, path: str, *, delimiter: str = ",") -> None:
        self.path = path
        self.delimiter = delimiter

    def fetch(self) -> Iterable[Record]:
        import pandas as pd

        df = pd.read_csv(self.path, delimiter=self.delimiter)
        for row in df.to_dict(orient="records"):
            yield row
