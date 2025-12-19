from __future__ import annotations

import abc
from typing import AsyncIterator, Dict, Optional


class ProviderResponse:
    def __init__(self, *, text: str, partial: bool, session_id: str, participant_id: Optional[str], commit_id: Optional[str]):
        self.text = text
        self.partial = partial
        self.session_id = session_id
        self.participant_id = participant_id
        self.commit_id = commit_id

    def to_dict(self) -> Dict:
        return {
            "text": self.text,
            "partial": self.partial,
            "session_id": self.session_id,
            "participant_id": self.participant_id,
            "commit_id": self.commit_id,
        }


class ProviderRequest:
    def __init__(self, *, session_id: str, participant_id: Optional[str], commit_id: Optional[str], audio_chunks: bytes, metadata: Dict):
        self.session_id = session_id
        self.participant_id = participant_id
        self.commit_id = commit_id
        self.audio_chunks = audio_chunks
        self.metadata = metadata


class TranslationProvider(abc.ABC):
    name: str

    @abc.abstractmethod
    async def connect(self) -> None:  # pragma: no cover - interface
        ...

    @abc.abstractmethod
    async def close(self) -> None:  # pragma: no cover - interface
        ...

    @abc.abstractmethod
    async def translate(self, request: ProviderRequest) -> AsyncIterator[ProviderResponse]:  # pragma: no cover
        ...

    @abc.abstractmethod
    async def health(self) -> str:  # pragma: no cover - interface
        ...

