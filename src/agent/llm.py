"""OpenAI-compatible chat completions client."""

import gc

from . import httpc


class LLMError(Exception):
    pass


class Client:
    def __init__(self, cfg, cadata=None):
        self.base_url = cfg["base_url"].rstrip("/")
        self.api_key = cfg["api_key"]
        self.model = cfg["model"]
        self.temperature = cfg["temperature"]
        self.max_tokens = cfg["max_tokens"]
        self.timeout = cfg["request_timeout"]
        # Callers normally load the trust bundle once and share it; fall back
        # to loading it here so a Client is still usable standalone.
        if cadata is None and cfg.get("verify_tls"):
            cadata = httpc.load_ca(cfg["ca_cert"])
        self.cadata = cadata
        if cfg.get("verify_tls") and not self.cadata:
            print("[llm] WARNING: proceeding without certificate verification")
        # Adjusted on the fly from the API's error responses.
        self._token_key = "max_tokens"
        self._send_temperature = True

    def _payload(self, messages, tools):
        payload = {"model": self.model, "messages": messages}
        # Newer models renamed max_tokens and refuse a custom temperature.
        # Which applies is discovered from the API's own error, so no model
        # name list has to be maintained here.
        payload[self._token_key] = self.max_tokens
        if self._send_temperature:
            payload["temperature"] = self.temperature
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        return payload

    def _adapt(self, detail):
        """Adjust to an unsupported-parameter error. True if worth retrying."""
        if "max_completion_tokens" in detail and self._token_key == "max_tokens":
            self._token_key = "max_completion_tokens"
            print("[llm] switching to max_completion_tokens for %s" % self.model)
            return True
        if "'temperature'" in detail and self._send_temperature:
            self._send_temperature = False
            print("[llm] %s rejects a custom temperature; using its default"
                  % self.model)
            return True
        return False

    def chat(self, messages, tools=None):
        """One completion round. Returns the assistant message dict."""
        if not self.api_key:
            raise LLMError("no api_key configured; set it in /config.json")

        headers = {
            "Authorization": "Bearer " + self.api_key,
            "Content-Type": "application/json",
        }

        gc.collect()
        for _ in range(3):
            try:
                resp = httpc.post(
                    self.base_url + "/chat/completions",
                    headers=headers,
                    body=self._payload(messages, tools),
                    timeout=self.timeout,
                    cadata=self.cadata,
                )
            except OSError as exc:
                raise LLMError("network error talking to %s: %s"
                               % (self.base_url, exc))

            if resp.status_code == 200:
                break

            detail = resp.text[:400]
            resp.content = b""
            if resp.status_code == 400 and self._adapt(detail):
                gc.collect()
                continue
            raise LLMError("HTTP %d from API: %s" % (resp.status_code, detail))
        else:
            raise LLMError("API kept rejecting the request parameters")

        try:
            data = resp.json()
        except Exception as exc:
            raise LLMError("could not parse API response: %s" % exc)
        finally:
            resp.content = b""
            gc.collect()

        if "error" in data:
            raise LLMError(str(data["error"].get("message", data["error"])))

        choices = data.get("choices")
        if not choices:
            raise LLMError("API returned no choices")

        usage = data.get("usage") or {}
        if usage:
            print("[llm] tokens prompt=%s completion=%s" % (
                usage.get("prompt_tokens"), usage.get("completion_tokens")))

        return choices[0].get("message", {})

    def list_models(self, timeout=15):
        """Return sorted model ids from GET {base_url}/models, or raise LLMError.

        Used by the config screen to populate the model dropdown. Providers that
        are only chat-compatible may not implement this endpoint; callers should
        fall back to a free-text field.
        """
        if not self.api_key:
            raise LLMError("no api_key configured")

        headers = {
            "Authorization": "Bearer " + self.api_key,
            "Content-Type": "application/json",
        }
        gc.collect()
        try:
            resp = httpc.get(
                self.base_url + "/models",
                headers=headers,
                timeout=timeout,
                cadata=self.cadata,
            )
        except OSError as exc:
            raise LLMError("network error listing models at %s: %s"
                           % (self.base_url, exc))

        if resp.status_code != 200:
            detail = resp.text[:200]
            resp.content = b""
            raise LLMError("HTTP %d listing models: %s"
                           % (resp.status_code, detail))

        try:
            data = resp.json()
        except Exception as exc:
            raise LLMError("could not parse models response: %s" % exc)
        finally:
            resp.content = b""
            gc.collect()

        ids = []
        for item in data.get("data") or []:
            mid = item.get("id") if isinstance(item, dict) else None
            if mid:
                ids.append(str(mid))
        # Unique + sort so the dropdown is stable and scannable.
        ids = sorted(set(ids))
        if not ids:
            raise LLMError("models endpoint returned no model ids")
        return ids
