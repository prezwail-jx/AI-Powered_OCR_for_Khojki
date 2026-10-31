from .base import Adapter, response_dict, parse_usage
from ..schemas import OCRPayload, ProviderResponse
from ..storage import canonical_json


class DeepSeekAdapter(Adapter):
    provider = "deepseek"
    key_variable = "DEEPSEEK_API_KEY"

    def build_payload(self, request):
        content = []
        for image in request.images:
            content.extend([{"type": "text", "text": image.label},
                            {"type": "image_url", "image_url": {"url": image.data_url(), "detail": request.settings.image_detail}}])
        return {"model": request.settings.model, "stream": False, "max_tokens": request.settings.max_output_tokens,
                "messages": [{"role": "system", "content": request.system_prompt + "\nJSON schema:\n" + canonical_json(OCRPayload.model_json_schema())},
                             {"role": "user", "content": content}],
                "response_format": {"type": "json_object"}, "extra_body": {"thinking": {"type": "disabled"}}}

    def send(self, request):
        response = self.client.chat.completions.create(**self.build_payload(request))
        raw = response_dict(response)
        usage, warning = parse_usage(raw.get("usage"), self.provider)
        choices = raw.get("choices") or []
        state, text = "schema_error", ""
        if len(choices) == 1:
            choice = choices[0]
            message = choice.get("message") or {}
            content = message.get("content")
            text = content if isinstance(content, str) else ""
            finish = choice.get("finish_reason")
            state = ("refused" if finish == "content_filter" or message.get("refusal") else
                     "truncated" if finish == "length" else "completed" if finish == "stop" else "transport_error")
        return ProviderResponse(state=state, raw_text=text, returned_model=raw.get("model"),
                                request_id=getattr(response, "_request_id", None) or raw.get("id"), usage=usage, usage_warning=warning)
