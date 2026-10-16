"""Schema output with inspectable final content and bounded format correction."""

import json
from urllib.parse import urlparse

from langchain_core.messages import HumanMessage

from tradingagents.llm_clients.capabilities import get_capabilities


async def structured(model, schema, messages, record):
    caps = get_capabilities(getattr(model, "model_name", ""))
    kwargs = {"include_raw": True}
    if (
        schema.__name__ == "ResearchReport"
        and urlparse(str(getattr(model, "openai_api_base", ""))).hostname == "api.deepseek.com"
        and (
            getattr(model, "model_name", "").startswith("deepseek-v4")
            or getattr(model, "model_name", "") == "deepseek-flash"
        )
    ):
        # Evidence investigation and the separate critic retain the configured
        # effort. Keep JSON report writing bounded instead of repeating a long
        # high-effort analysis that has already consumed the job's time budget.
        kwargs["reasoning_effort"] = "low"
    schema_text = json.dumps(schema.model_json_schema(), ensure_ascii=False)
    if not caps.supports_tool_choice and caps.supports_json_mode:
        # Thinking providers cannot be forced to call the schema tool.
        kwargs["method"] = "json_mode"
        messages = [
            *messages,
            HumanMessage(
                "Return one JSON object conforming to this JSON schema, with no extra text:\n"
                + schema_text
            ),
        ]
    runnable = model.with_structured_output(schema, **kwargs)
    for attempt in range(2):
        result = await runnable.ainvoke(messages)
        raw = result["raw"]
        error = result.get("parsing_error")
        cause = getattr(error, "__cause__", None)
        detail = (
            json.dumps(cause.errors(include_input=False, include_url=False))
            if hasattr(cause, "errors")
            else str(error)[-1500:]
            if error
            else None
        )
        output = {
            "schema": schema.__name__,
            "content": raw.content,
            "tool_calls": raw.tool_calls,
            "finish_reason": raw.response_metadata.get("finish_reason"),
            "usage": raw.usage_metadata,
            "parsing_error": detail,
            "request_options": {
                key: value for key, value in kwargs.items() if key != "include_raw"
            },
        }
        await record(output)
        if output["finish_reason"] == "length":
            raise ValueError(
                f"{schema.__name__} output truncated by token limit; original output retained"
            )
        if result.get("parsed") is not None:
            return schema.model_validate(result["parsed"])
        if attempt == 0:
            messages = [
                *messages,
                HumanMessage(
                    "The previous output did not conform to the JSON schema. Correct its format and return the entire JSON object. "
                    "Keep the substantive evidence, use short exact supporting quotes within the schema length limits, and do not invent content.\n"
                    + "JSON schema:\n"
                    + schema_text
                    + "\nPREVIOUS OUTPUT:\n"
                    + str(raw.content)
                    + "\nFORMAT ERRORS:\n"
                    + (detail or "No structured object returned")
                ),
            ]
    raise ValueError(
        f"{schema.__name__} returned no valid structured output after format correction; original output retained"
    )
