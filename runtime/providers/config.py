from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path

from .aureon_provider import AureonProvider
from .base import ModelProvider
from .gemini_provider import GeminiProvider
from .openai_compatible import OpenAICompatibleProvider
from runtime_paths import runtime_state_dir


DEFAULT_MODEL = "openrouter/google/gemma-3-27b-it"
DEFAULT_PROVIDER_CHAIN = [
    {"name": "openrouter", "model": "google/gemma-3-27b-it", "enabled": True},
    {"name": "gemini", "model": "gemini-2.5-flash", "enabled": True},
    {"name": "xai", "model": "grok-4.3", "enabled": True},
    {"name": "deepseek", "model": "deepseek-chat", "enabled": True},
]

DEFAULT_MODEL_PRESETS: dict[str, str] = {
    "gemma": "openrouter/google/gemma-3-27b-it",
    "openrouter": "openrouter/free",
    "openrouter-gemma": "openrouter/google/gemma-3-27b-it",
    "gemini": "gemini/gemini-2.5-flash",
    "grok": "xai/grok-4.3",
    "xai": "xai/grok-4.3",
    "deepseek": "deepseek/deepseek-chat",
    "aureon": "aureon/aureon-queen",
}

API_FILE_CANDIDATES = [
    Path.home() / ".config" / "aoia" / "secrets" / "openrouter.env",
    Path.home() / ".config" / "aoia" / "secrets" / "gemini.env",
    Path.home() / ".config" / "aoia" / "secrets" / "xai.env",
    Path.home() / ".config" / "aoia" / "secrets" / "deepseek.env",
    Path.home() / ".config" / "openrouter" / "api.env",
    Path.home() / ".config" / "gemini" / "api.env",
    Path.home() / ".config" / "xai" / "api.env",
    Path.home() / ".config" / "grok" / "api.env",
    Path.home() / ".config" / "deepseek" / "api.env",
]

REMOVED_PROVIDERS = {"openai", "huggingface", "gemma-hf"}


@dataclass
class ProviderConfig:
    name: str
    model: str
    enabled: bool = True

    @property
    def full_name(self) -> str:
        return f"{self.name}/{self.model}"


def load_api_environment() -> None:
    """Load private local API env files without exposing secrets."""
    for env_path in API_FILE_CANDIDATES:
        if not env_path.exists():
            continue
        values: dict[str, str] = {}
        for raw in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            if line.startswith("export "):
                line = line[len("export ") :].strip()
            name, value = line.split("=", 1)
            name = name.strip()
            value = value.strip().strip('"').strip("'")
            if name and value:
                values[name] = value
        for name, value in values.items():
            if not os.getenv(name):
                os.environ[name] = value


class ProviderManager:
    """Cloud-provider manager with fallback routing and no fake offline mode."""

    def __init__(self, project_dir: Path, *, fixture_base_url: str | None = None) -> None:
        if fixture_base_url is None:
            load_api_environment()
        self.fixture_base_url = fixture_base_url
        self.project_dir = project_dir
        state_dir = runtime_state_dir(project_dir)
        self.config_path = state_dir / "state" / "model_config.json"
        self.providers_path = state_dir / "state" / "providers.json"
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        self.provider_chain = self._load_provider_chain()
        self.current_model = self.normalize_model_name(self._load_model_name())
        self.provider: ModelProvider | None = None
        self.last_used_model = ""

    def generate(self, prompt: str) -> str:
        if self.fixture_base_url is not None:
            raise RuntimeError("TEST_TRANSPORT_ONLY: ordinary cloud chat is disabled in fixture mode")
        return self.generate_with_fallback(prompt)

    def strict_status(self) -> dict:
        enabled = any(p.name == "openrouter" and p.enabled for p in self.provider_chain)
        return {"provider": "openrouter", "enabled": enabled,
                "mode": "TEST" if self.fixture_base_url is not None else "LIVE_PENDING_AUTHORIZATION",
                "configured": self.fixture_base_url is not None or self._provider_is_available("openrouter"),
                "fallback": False, "retry": False}

    def generate_exact(self, request, cancel, deadline):
        """CPL policy on the same manager; never mutates current_model."""
        from .exact import ExactCallError

        request.validate()
        if not any(p.name == request.provider_connection_id and p.enabled for p in self.provider_chain):
            raise ExactCallError("PROVIDER_DISABLED")
        fixture = self.fixture_base_url is not None
        if (request.transport_scope == "TEST") != fixture:
            raise ExactCallError("TRANSPORT_SCOPE_MISMATCH")
        if not fixture and not self._provider_is_available("openrouter"):
            raise ExactCallError("PROVIDER_UNCONFIGURED")
        adapter = OpenAICompatibleProvider(
            provider="openrouter", model=request.requested_model,
            api_key="fixture-key-not-a-real-credential" if fixture else self._load_env_key("OPENROUTER_API_KEY"),
            base_url=self.fixture_base_url if fixture else "https://openrouter.ai/api/v1",
        )
        return adapter.generate_exact(request, cancel, deadline, fixture=fixture)

    def strict_known_secrets(self) -> tuple[str, ...]:
        if self.fixture_base_url is not None:
            return ("fixture-key-not-a-real-credential",)
        value = os.getenv("OPENROUTER_API_KEY", "").strip()
        return (value,) if value else ()

    def generate_with_fallback(self, prompt: str) -> str:
        if self.fixture_base_url is not None:
            raise RuntimeError("TEST_TRANSPORT_ONLY: ordinary cloud chat is disabled in fixture mode")
        errors: list[str] = []
        tried: set[str] = set()
        for full_model in self._fallback_candidates():
            if full_model in tried:
                continue
            tried.add(full_model)
            try:
                provider = self._build_provider(full_model)
                response = provider.generate(prompt)
                self.provider = provider
                self.current_model = full_model
                self.last_used_model = provider.full_name
                return response
            except Exception as error:
                errors.append(f"{full_model}: {error}")

        if not errors:
            raise RuntimeError("No enabled cloud providers are configured.")

        raise RuntimeError(
            "No configured cloud provider succeeded. Checked:\n- " + "\n- ".join(errors)
        )

    def switch_model(self, model_name: str) -> str:
        normalized = self.normalize_model_name(model_name)
        self.current_model = normalized
        self.last_used_model = ""
        self.provider = None
        self.config_path.write_text(
            json.dumps({"model": normalized}, indent=2),
            encoding="utf-8",
        )
        return self.current_model

    def describe(self) -> str:
        return self.last_used_model or self.current_model

    def active_fallback_chain(self) -> list[str]:
        return [provider.full_name for provider in self.provider_chain if provider.enabled]

    def available_models(self) -> list[str]:
        return [
            f"{alias:<15} -> {model}"
            for alias, model in DEFAULT_MODEL_PRESETS.items()
            if model.split("/", 1)[0] not in REMOVED_PROVIDERS
            and self._provider_is_available(model.split("/", 1)[0])
        ]

    def provider_status(self) -> list[dict[str, str | bool]]:
        rows: list[dict[str, str | bool]] = []
        for provider in self.provider_chain:
            rows.append(
                {
                    "name": provider.name,
                    "model": provider.model,
                    "enabled": provider.enabled,
                    "available": self._provider_is_available(provider.name),
                    "full_name": provider.full_name,
                }
            )
        return rows

    def model_notice(self, model_name: str) -> str | None:
        normalized = self.normalize_model_name(model_name)
        provider = normalized.split("/", 1)[0]
        if provider == "gemini":
            return "Gemini uses GEMINI_API_KEY and the google-genai SDK."
        if provider == "openrouter":
            return "OpenRouter uses OPENROUTER_API_KEY. Current Gemma preset: google/gemma-3-27b-it."
        if provider == "deepseek":
            return "DeepSeek uses DEEPSEEK_API_KEY and an OpenAI-compatible endpoint."
        if provider == "xai":
            return "Grok uses XAI_API_KEY and the OpenAI-compatible xAI endpoint."
        if provider == "aureon":
            return "Aureon requires a live AUREON_API_BASE_URL. No offline fake mode is used."
        if provider in REMOVED_PROVIDERS:
            return "This provider was removed from the terminal app because it is not configured."
        return None

    def normalize_model_name(self, model_name: str) -> str:
        value = model_name.strip()
        if not value:
            raise ValueError("Model name cannot be empty.")

        lowered = value.lower()
        if lowered in DEFAULT_MODEL_PRESETS:
            return DEFAULT_MODEL_PRESETS[lowered]

        if ":" in value and "/" not in value:
            provider, model = value.split(":", 1)
            value = f"{provider.strip()}/{model.strip()}"

        if "/" not in value:
            return f"gemini/{value}"

        provider, model = value.split("/", 1)
        provider = provider.strip().lower()
        model = model.strip()
        if not provider or not model:
            raise ValueError(f"Invalid model name: {model_name}")
        return f"{provider}/{model}"

    def _fallback_candidates(self) -> list[str]:
        candidates = [self.current_model]
        candidates.extend(
            provider.full_name
            for provider in self.provider_chain
            if provider.enabled and self._provider_is_available(provider.name)
        )
        return candidates

    def _load_provider_chain(self) -> list[ProviderConfig]:
        if not self.providers_path.exists():
            providers = [ProviderConfig(**payload) for payload in DEFAULT_PROVIDER_CHAIN]
            self.providers_path.write_text(
                json.dumps({"providers": [asdict(provider) for provider in providers]}, indent=2),
                encoding="utf-8",
            )
            return providers

        try:
            payload = json.loads(self.providers_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            payload = {"providers": DEFAULT_PROVIDER_CHAIN}

        providers: list[ProviderConfig] = []
        for item in payload.get("providers", []):
            if not isinstance(item, dict):
                continue
            name = str(item.get("name", "")).strip()
            model = str(item.get("model", "")).strip()
            if name in REMOVED_PROVIDERS:
                continue
            if name and model:
                providers.append(
                    ProviderConfig(
                        name=name,
                        model=model,
                        enabled=bool(item.get("enabled", True)),
                    )
                )

        if not providers:
            return [ProviderConfig(**item) for item in DEFAULT_PROVIDER_CHAIN]

        existing = {(provider.name, provider.model) for provider in providers}
        for item in DEFAULT_PROVIDER_CHAIN:
            key = (item["name"], item["model"])
            if key not in existing:
                providers.append(ProviderConfig(**item))
        return providers

    def _load_model_name(self) -> str:
        if not self.config_path.exists():
            return DEFAULT_MODEL
        try:
            payload = json.loads(self.config_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return DEFAULT_MODEL
        model = str(payload.get("model") or DEFAULT_MODEL)
        provider = model.split("/", 1)[0]
        if provider in REMOVED_PROVIDERS:
            return DEFAULT_MODEL
        return model

    def _build_provider(self, model_name: str) -> ModelProvider:
        provider, model = model_name.split("/", 1)

        if provider == "aureon":
            return AureonProvider(model)
        if provider == "gemini":
            api_key = os.getenv("GEMINI_API_KEY")
            if not api_key:
                raise FileNotFoundError("GEMINI_API_KEY not found")
            return GeminiProvider(api_key, model)
        if provider == "openrouter":
            return OpenAICompatibleProvider(
                provider="openrouter",
                api_key=self._load_env_key("OPENROUTER_API_KEY"),
                model=model,
                base_url="https://openrouter.ai/api/v1",
            )
        if provider == "deepseek":
            return OpenAICompatibleProvider(
                provider="deepseek",
                api_key=self._load_env_key("DEEPSEEK_API_KEY"),
                model=model,
                base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1"),
            )
        if provider == "xai":
            return OpenAICompatibleProvider(
                provider="xai",
                api_key=self._load_xai_key(),
                model=model,
                base_url=os.getenv("XAI_BASE_URL", "https://api.x.ai/v1"),
            )
        if provider in REMOVED_PROVIDERS:
            raise ValueError(f"Provider removed from terminal app: {provider}")

        raise ValueError(f"Unsupported provider: {provider}")

    @staticmethod
    def _load_env_key(env_name: str) -> str:
        value = os.getenv(env_name, "").strip()
        if value:
            return value
        raise FileNotFoundError(f"{env_name} not found")

    @staticmethod
    def _load_xai_key() -> str:
        value = os.getenv("XAI_API_KEY", "").strip()
        if value:
            return value
        raise FileNotFoundError("XAI_API_KEY not found")

    @staticmethod
    def _provider_is_available(provider: str) -> bool:
        if provider == "aureon":
            return bool(os.getenv("AUREON_API_BASE_URL", "").strip())
        if provider == "gemini":
            return bool(os.getenv("GEMINI_API_KEY", "").strip())
        if provider == "openrouter":
            return bool(os.getenv("OPENROUTER_API_KEY", "").strip())
        if provider == "xai":
            return bool(os.getenv("XAI_API_KEY", "").strip())
        if provider == "deepseek":
            return bool(os.getenv("DEEPSEEK_API_KEY", "").strip())
        if provider in REMOVED_PROVIDERS:
            return False
        return False
