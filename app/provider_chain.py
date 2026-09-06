from __future__ import annotations

from typing import Literal


ProviderKind = Literal["local", "cloud"]


def provider_order(primary: ProviderKind, fallback_enabled: bool) -> tuple[ProviderKind, ...]:
    if not fallback_enabled:
        return (primary,)
    fallback: ProviderKind = "local" if primary == "cloud" else "cloud"
    return (primary, fallback)
