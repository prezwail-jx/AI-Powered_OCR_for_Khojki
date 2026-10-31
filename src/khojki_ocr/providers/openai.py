from .base import Adapter, response_dict, parse_usage
from ..schemas import OCRPayload, ProviderResponse


class OpenAIAdapter(Adapter):
    provider = "openai"
    key_variable = "OPENAI_API_KEY"

    def build_payload(self, request):
        content = []
        for image in request.images:
            content.extend([{"type": "input_text", "text": image.label},
                            {"type": "input_image", "image_url": image.data_url(), "detail": request.settings.image_detail}])
        payload = {"model": request.settings.model, "store": False, "stream": False,
                "max_output_tokens": request.settings.max_output_tokens,
                "input": [{"role": "system", "content": request.system_prompt}, {"role": "user", "content": content}],
                "text": {"format": {"type": "json_schema", "name": "khojki_transcription", "strict": True,
                                      "schema": OCRPayload.model_json_schema()}}}
        if request.settings.openai_service_tier is not None:
            payload["service_tier"] = request.settings.openai_service_tier
        if request.settings.openai_cache_mode is not None:
            # Explicit-only with NO breakpoints does not create cloud cache writes.
            # The local response cache is separate and remains enabled.
            payload["prompt_cache_options"] = {"mode": request.settings.openai_cache_mode, "ttl": "30m"}
        return payload

    def send(self, request):
        response = self.client.responses.create(**self.build_payload(request))
        raw = response_dict(response)
        usage, warning = parse_usage(raw.get("usage"), self.provider)
        texts, refused = [], False
        for output in raw.get("output") or []:
            if output.get("type") == "message":
                for part in output.get("content") or []:
                    if part.get("type") == "refusal":
                        refused = True
                    elif part.get("type") == "output_text" and isinstance(part.get("text"), str):
                        texts.append(part["text"])
        status = raw.get("status")
        state = "refused" if refused else "truncated" if status == "incomplete" else "completed" if status == "completed" else "transport_error"
        details = (raw.get("usage") or {}).get("input_tokens_details") or {}
        billing = {"service_tier": raw.get("service_tier"), "cache_write_tokens": details.get("cache_write_tokens"),
                   "cache_write_tokens_details": details.get("cache_write_tokens_details")}
        return ProviderResponse(state=state, raw_text="".join(texts), returned_model=raw.get("model"), billing_metadata=billing,
                                request_id=getattr(response, "_request_id", None) or raw.get("id"), usage=usage, usage_warning=warning)
