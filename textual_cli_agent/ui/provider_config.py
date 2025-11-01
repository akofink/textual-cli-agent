from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Optional, cast

from ..providers.base import ProviderConfig, ProviderFactory

logger = logging.getLogger(__name__)


if TYPE_CHECKING:
    from .app import ChatApp


class ProviderConfigMixin:
    def _apply_provider_config(
        self,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        system: Optional[str] = None,
    ) -> None:
        app = cast("ChatApp", self)
        try:
            cfg = ProviderConfig(
                model=model or app.provider.cfg.model,
                api_key=app.provider.cfg.api_key,
                base_url=app.provider.cfg.base_url,
                temperature=temperature
                if temperature is not None
                else app.provider.cfg.temperature,
                system_prompt=system
                if system is not None
                else app.provider.cfg.system_prompt,
            )
            prov_name = type(app.provider).__name__.replace("Provider", "").lower()
            if prov_name in ("openai", "anthropic", "ollama"):
                new_provider = ProviderFactory.create(prov_name, cfg)
            else:
                new_provider = type(app.provider)(cfg)
            app.provider = new_provider
            app.engine.provider = new_provider
        except Exception as e:
            logger.error(f"Error applying provider config: {e}")

    def _apply_saved_provider_config(self) -> None:
        app = cast("ChatApp", self)
        try:
            saved_provider = app.config.get("provider")
            saved_model = app.config.get("model")
            saved_temp = app.config.get("temperature")

            changes_needed = False
            current_provider_type = (
                type(app.provider).__name__.replace("Provider", "").lower()
            )
            if saved_provider and saved_provider != current_provider_type:
                changes_needed = True
            if saved_model and saved_model != app.provider.cfg.model:
                changes_needed = True
            if saved_temp is not None and saved_temp != app.provider.cfg.temperature:
                changes_needed = True

            if changes_needed:
                cfg = ProviderConfig(
                    model=saved_model or app.provider.cfg.model,
                    api_key=app.provider.cfg.api_key,
                    base_url=app.provider.cfg.base_url,
                    temperature=saved_temp
                    if saved_temp is not None
                    else app.provider.cfg.temperature,
                    system_prompt=app.provider.cfg.system_prompt,
                )

                if saved_provider and saved_provider in (
                    "openai",
                    "anthropic",
                    "ollama",
                ):
                    new_provider = ProviderFactory.create(saved_provider, cfg)
                else:
                    new_provider = type(app.provider)(cfg)

                app.provider = new_provider
                app.engine.provider = new_provider
                logger.debug(
                    f"Applied saved provider config: {saved_provider}, {saved_model}, {saved_temp}"
                )
        except Exception as e:
            logger.warning(f"Failed to apply saved provider config: {e}")

    def _status_title(self) -> str:
        app = cast("ChatApp", self)
        return (
            f"ChatApp - provider={type(app.provider).__name__.replace('Provider', '').lower()} "
            f"model={app.provider.cfg.model} temp={app.provider.cfg.temperature} "
            f"auto={app.auto_continue} rounds={app.max_rounds} pending={app._pending_count}"
        )

    def _refresh_header(self) -> None:
        try:
            cast("ChatApp", self).sub_title = self._status_title()
        except Exception:
            pass
