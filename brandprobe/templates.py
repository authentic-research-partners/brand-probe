"""The exact generation messages, shared by pricing and execution."""

from brandprobe.schemas import AuditConfig, Prompt

SYSTEM = "Answer the question using your existing knowledge. Do not browse or use tools. If uncertain, say so. Do not invent facts."


def messages(config: AuditConfig, prompt: Prompt) -> list[dict[str, str]]:
    # Brand metadata is deliberately excluded: it would contaminate discovery.
    return [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": prompt.text},
    ]
