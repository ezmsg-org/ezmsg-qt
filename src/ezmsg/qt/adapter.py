"""TransformerAdapter - Wrap ezmsg-baseproc transformers as ez.Unit."""

from __future__ import annotations

import typing
from collections.abc import AsyncGenerator

import ezmsg.core as ez


class TransformerAdapter(ez.Unit):
    """Wraps a BaseProcessor instance as an ez.Unit.

    This adapter allows ezmsg-baseproc processors (BaseTransformer, etc.)
    to be used in ProcessorChain alongside native ez.Unit classes.

    Mirrors key features of BaseTransformerUnit:
    - zero_copy=True for performance with large messages
    - Compatible with ezmsg's pub/sub system

    Note: This adapter does not support runtime settings updates.
    The transformer should be fully configured before being passed.
    """

    INPUT = ez.InputStream(typing.Any)
    OUTPUT = ez.OutputStream(typing.Any)

    def __init__(self, transformer: typing.Any):
        """Create an adapter wrapping a transformer instance.

        Args:
            transformer: A BaseProcessor instance (or similar) with __acall__ method.
        """
        super().__init__()
        self._transformer = transformer

    @ez.subscriber(INPUT, zero_copy=True)
    @ez.publisher(OUTPUT)
    async def process(self, msg: typing.Any) -> AsyncGenerator:
        """Process incoming messages through the wrapped transformer."""
        result = await self._transformer.__acall__(msg)
        if result is not None:
            yield self.OUTPUT, result
