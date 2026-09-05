from typing import Any


class MetaAPIError(Exception):
    def __init__(
        self,
        *,
        channel: str,
        stage: str,
        meta_status: int | None = None,
        message: str = "Meta API request failed",
        response: dict[str, Any] | None = None,
    ):
        self.channel = channel
        self.stage = stage
        self.meta_status = meta_status
        self.response = response or {}
        self.message = message

        error = self.response.get("error", {})
        self.meta_code = error.get("code")
        self.meta_subcode = error.get("error_subcode")
        self.meta_message = error.get("message") or message

        super().__init__(self.meta_message)

    def to_detail(self) -> dict[str, Any]:
        # Provider response bodies are diagnostic data, not a public API
        # contract.  They can contain account identifiers or request echoes,
        # so expose only the normalized error fields to the caller.
        return {
            "channel": self.channel,
            "stage": self.stage,
            "meta_status": self.meta_status,
            "meta_code": self.meta_code,
            "meta_subcode": self.meta_subcode,
            "message": str(self.meta_message)[:300],
        }
