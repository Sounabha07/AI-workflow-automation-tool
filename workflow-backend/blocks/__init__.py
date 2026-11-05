from blocks.manual_trigger import ManualTriggerBlock
from blocks.schedule_trigger import ScheduleTriggerBlock
from blocks.webhook_trigger import WebhookTriggerBlock
from blocks.input_block import InputBlock
from blocks.http_request import HttpRequestBlock
from blocks.switch import SwitchBlock
from blocks.wait_for_input import WaitForInputBlock
from blocks.llm import LLMBlock
from blocks.agent import AgentBlock

__all__ = [
    "ManualTriggerBlock", "ScheduleTriggerBlock", "WebhookTriggerBlock",
    "InputBlock", "HttpRequestBlock", "SwitchBlock", "WaitForInputBlock", "LLMBlock",
    "AgentBlock",
]

# Block types that start a run. A workflow has exactly one, with no inputs.
TRIGGER_TYPES = ("manual_trigger", "schedule_trigger", "webhook_trigger")
WAIT_TYPE = "wait_for_input"
