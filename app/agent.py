"""Wedding venue decision logic."""

from pathlib import Path

from app.config import get_settings
from app.inference import DigitalOceanInferenceClient
from app.models import AgentDecision, GmailEvent


POLICY_PATH = Path(__file__).resolve().parents[1] / "prompts" / "wedding-agent.md"


async def analyze_event(event: GmailEvent) -> AgentDecision:
    """Analyze an event with Serverless Inference when configured."""
    settings = get_settings()
    if not settings.inference_configured:
        return AgentDecision(
            venue=event.venue,
            event_type="unprocessed",
            status="received",
            recommended_action="connect_serverless_inference",
            requires_human_approval=True,
        )

    policy = POLICY_PATH.read_text(encoding="utf-8")
    return await DigitalOceanInferenceClient(settings).decide(event, policy)
