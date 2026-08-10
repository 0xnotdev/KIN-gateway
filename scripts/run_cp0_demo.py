"""Run the canonical direct-versus-KIN inventory.lookup CP0 demo."""

from __future__ import annotations

import argparse
import asyncio
import json

from pathlib import Path
from uuid import uuid4

import httpx

from a2a.client import ClientConfig, create_client
from a2a.helpers import get_artifact_text
from a2a.types import Message, Part, Role, SendMessageRequest, TaskState


async def inventory_lookup(
    base_url: str,
    *,
    binding: str,
    item: str,
) -> dict[str, object]:
    """Call one unmodified A2A endpoint with the official SDK client."""

    client = await create_client(
        base_url,
        client_config=ClientConfig(
            streaming=False,
            supported_protocol_bindings=[binding],
        ),
    )
    try:
        request = SendMessageRequest(
            message=Message(
                role=Role.ROLE_USER,
                message_id=str(uuid4()),
                parts=[Part(text=item)],
            )
        )
        responses = [event async for event in client.send_message(request)]
    finally:
        await client.close()

    if len(responses) != 1 or not responses[0].HasField("task"):
        raise RuntimeError("inventory.lookup did not return exactly one Task")
    task = responses[0].task
    return {
        "task_id": task.id,
        "state": TaskState.Name(task.status.state),
        "artifacts": [get_artifact_text(artifact) for artifact in task.artifacts],
    }


async def fetch_card(base_url: str) -> dict[str, object]:
    """Capture discovery document and safe provenance headers."""

    async with httpx.AsyncClient(base_url=base_url) as client:
        response = await client.get("/.well-known/agent-card.json")
        response.raise_for_status()
    return {
        "document": response.json(),
        "etag": response.headers.get("etag"),
        "upstream_sha256": response.headers.get(
            "x-kin-upstream-agent-card-sha256"
        ),
    }


async def run_demo(
    *,
    upstream_url: str,
    gateway_url: str,
    item: str,
) -> dict[str, object]:
    """Run both bindings directly and through KIN, then compare semantics."""

    direct_card, gateway_card = await asyncio.gather(
        fetch_card(upstream_url),
        fetch_card(gateway_url),
    )
    binding_results: list[dict[str, object]] = []
    for binding in ("JSONRPC", "HTTP+JSON"):
        direct = await inventory_lookup(
            upstream_url,
            binding=binding,
            item=item,
        )
        through_kin = await inventory_lookup(
            gateway_url,
            binding=binding,
            item=item,
        )
        equivalent = (
            direct["state"] == through_kin["state"]
            and direct["artifacts"] == through_kin["artifacts"]
        )
        binding_results.append(
            {
                "binding": binding,
                "direct": direct,
                "through_kin": through_kin,
                "equivalent": equivalent,
            }
        )

    result = {
        "fixture": "inventory.lookup",
        "item": item,
        "upstream_url": upstream_url,
        "gateway_url": gateway_url,
        "direct_agent_card": direct_card,
        "gateway_agent_card": gateway_card,
        "bindings": binding_results,
        "all_equivalent": all(
            binding["equivalent"] for binding in binding_results
        ),
    }
    if not result["all_equivalent"]:
        raise RuntimeError("Direct and through-KIN results differ")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--upstream-url",
        default="http://127.0.0.1:18081",
    )
    parser.add_argument(
        "--gateway-url",
        default="http://127.0.0.1:18080",
    )
    parser.add_argument("--item", default="widget-cp0")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    result = asyncio.run(
        run_demo(
            upstream_url=args.upstream_url.rstrip("/"),
            gateway_url=args.gateway_url.rstrip("/"),
            item=args.item,
        )
    )
    rendered = json.dumps(result, indent=2) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
