"""The agent loop: prompt -> tool calls -> observations -> answer."""

import gc
import json

from .llm import LLMError

_BASE_PROMPT = """You are an AI agent running directly on an ESP32-S3 \
microcontroller. You are not a chatbot in a datacentre: you are embedded in \
physical hardware and can inspect and control it with your tools.

Be concise. Radio time and tokens are expensive on this device, so answer in a \
few sentences unless asked for detail.

You are extended through SKILLS. Each skill below is listed with only its name \
and description; the instructions themselves are not loaded yet.

RULE: if a request matches a skill's description, your FIRST action must be to \
call the Skill tool with that name. Do not call any other tool until you have \
read the skill. Only skip this when no skill's description covers the request.

This matters because the skills hold calibration for THIS specific board that \
you cannot infer: correct brightness scaling, signal-strength thresholds, which \
sensor readings are misleading, and how results should be reported. Several \
tools look self-explanatory but produce wrong or misleading results when driven \
without the skill's guidance. A plausible-looking direct tool call is the most \
common way to get this wrong.

CREATING SKILLS: you can grow the skill list yourself by writing \
/skills/<name>/SKILL.md (load the write-skill skill for format). Do this when:
(1) the user describes a skill they want, or asks you to teach/remember a \
procedure; or (2) you just finished a multi-step task that worked, is likely \
to be asked again, and no existing skill covers it -- save it proactively and \
mention the new skill name briefly. Do not create skills for one-off chat or \
single trivial tool calls. Prefer editing a close existing skill over \
duplicating it.

ERRORS: do not give up after the first tool or script failure. Read the error, \
reason about the cause, change something concrete, and retry. Keep iterating \
toward success within the tool-round budget (dozens of rounds are available). \
Only stop early if the board truly cannot do the task or the same approach \
has failed repeatedly with no new information. Report what actually happened; \
never describe a failed action as if it succeeded.

Available skills:
%s

Report what actually happened. If a tool fails after you have finished \
retrying, say so and include the error rather than inventing success."""


class Agent:
    def __init__(self, cfg, client, registry, skills):
        self.cfg = cfg
        self.client = client
        self.registry = registry
        self.skills = skills
        self.history = []
        self.on_event = None

    def system_prompt(self):
        extra = self.cfg.get("system_prompt") or ""
        prompt = _BASE_PROMPT % self.skills.catalog()
        return prompt + ("\n\n" + extra if extra else "")

    def reset(self):
        self.history = []

    def _emit(self, kind, text):
        print("[%s] %s" % (kind, text))
        if self.on_event:
            try:
                self.on_event(kind, text)
            except Exception:
                pass

    def _trim(self):
        """Drop the oldest turns, keeping tool_calls with their results.

        An assistant message carrying tool_calls must never be separated from
        the tool messages answering it, or the API rejects the conversation.
        """
        limit = self.cfg.get("history_limit", 24)
        if len(self.history) <= limit:
            return
        cut = len(self.history) - limit
        while cut < len(self.history) and self.history[cut].get("role") == "tool":
            cut += 1
        self.history = self.history[cut:]

    def ask(self, user_text):
        """Run one full turn, returning the assistant's final text."""
        self.history.append({"role": "user", "content": user_text})
        self._trim()

        messages = [{"role": "system", "content": self.system_prompt()}]
        messages.extend(self.history)

        max_iters = self.cfg.get("max_tool_iterations", 50)
        for round_i in range(max_iters):
            gc.collect()
            try:
                message = self.client.chat(messages, tools=self.registry.schemas())
            except LLMError as exc:
                err = "LLM error: %s" % exc
                self._emit("error", err)
                return err

            tool_calls = message.get("tool_calls") or []
            content = message.get("content") or ""

            assistant_msg = {"role": "assistant", "content": content}
            if tool_calls:
                assistant_msg["tool_calls"] = tool_calls
            messages.append(assistant_msg)
            self.history.append(assistant_msg)

            if not tool_calls:
                self._trim()
                return content or "(no reply)"

            for call in tool_calls:
                fn = call.get("function", {})
                name = fn.get("name", "")
                raw_args = fn.get("arguments") or "{}"
                try:
                    parsed = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
                except Exception:
                    parsed = {}

                self._emit("tool", "%s %s" % (name, raw_args[:120] if isinstance(raw_args, str) else raw_args))
                output = self.registry.invoke(name, parsed)
                if len(output) > 6000:
                    output = output[:6000] + "\n...[truncated]"

                result_msg = {
                    "role": "tool",
                    "tool_call_id": call.get("id", ""),
                    "content": output,
                }
                messages.append(result_msg)
                self.history.append(result_msg)

        self._trim()
        return (
            "Stopped after %d tool rounds without a final answer. "
            "Partial tool work is still in conversation history -- continue "
            "with a short follow-up (e.g. 'keep fixing until the skill works' "
            "or 'summarize blockers'). max_tool_iterations is already high; "
            "narrow the goal if retries are thrashing."
            % max_iters
        )
