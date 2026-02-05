"""Tests for ModelPickerController (swecli/ui_textual/controllers/model_picker_controller.py)."""

import asyncio
from unittest.mock import MagicMock, AsyncMock, patch
from types import SimpleNamespace

import pytest

from swecli.config.models import ModelInfo, ProviderInfo
from swecli.ui_textual.controllers.model_picker_controller import ModelPickerController


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_model(
    model_id="m1", name="Model 1", context_length=128000,
    capabilities=None, recommended=False, supports_temperature=True,
):
    return ModelInfo(
        id=model_id,
        name=name,
        provider="TestProvider",
        context_length=context_length,
        capabilities=capabilities or ["text"],
        recommended=recommended,
        supports_temperature=supports_temperature,
    )


def _make_provider(
    provider_id="test", name="Test", models=None,
):
    if models is None:
        models = {
            "m1": _make_model("m1", "Model 1", 128000, ["text", "vision"]),
            "m2": _make_model("m2", "Model 2", 64000, ["text"]),
        }
    return ProviderInfo(
        id=provider_id,
        name=name,
        description="Test provider",
        api_key_env=f"{provider_id.upper()}_KEY",
        api_base_url=f"https://api.{provider_id}.com",
        models=models,
    )


class MockConversation:
    def __init__(self):
        self.messages = []
        self.lines = []

    def add_system_message(self, msg):
        self.messages.append(("system", msg))

    def add_assistant_message(self, msg):
        self.messages.append(("assistant", msg))

    def add_error(self, msg):
        self.messages.append(("error", msg))

    def write(self, content):
        self.lines.append(content)

    def scroll_end(self, animate=False):
        pass

    def _truncate_from(self, start):
        self.lines = self.lines[:start]


class MockApp:
    def __init__(self):
        self.conversation = MockConversation()
        self.model_slots = {}
        self.get_model_config = None
        self.on_model_selected = None
        self.input_field = MagicMock()
        self.input_field.load_text = MagicMock()
        self.input_field.cursor_position = 0
        self.input_field.focus = MagicMock()
        self._refreshed = False

    def refresh(self):
        self._refreshed = True


@pytest.fixture
def mock_app():
    return MockApp()


@pytest.fixture
def controller(mock_app):
    return ModelPickerController(mock_app)


# ---------------------------------------------------------------------------
# Tests: Lifecycle
# ---------------------------------------------------------------------------

class TestPickerLifecycle:
    """Test controller lifecycle management."""

    def test_initial_state_is_inactive(self, controller):
        assert controller.active is False
        assert controller.state is None

    @pytest.mark.asyncio
    @patch("swecli.config.get_model_registry")
    async def test_start_sets_active(self, mock_get_registry, controller):
        mock_registry = MagicMock()
        mock_registry.list_providers.return_value = []
        mock_get_registry.return_value = mock_registry

        await controller.start()

        assert controller.active is True
        assert controller.state is not None
        assert controller.state["stage"] == "slot"

    def test_end_clears_state(self, controller):
        controller.state = {"stage": "slot", "panel_start": None}
        controller.end("Done")
        assert controller.active is False
        assert controller.state is None

    def test_end_with_message(self, controller, mock_app):
        controller.state = {"stage": "slot", "panel_start": None}
        controller.end("Finished!")
        assert any("Finished!" in str(m) for m in mock_app.conversation.messages)

    def test_cancel_clears_state(self, controller):
        controller.state = {"stage": "slot", "panel_start": None}
        controller.cancel()
        assert controller.active is False

    def test_cancel_noop_when_inactive(self, controller):
        controller.cancel()
        assert controller.active is False


class TestAdjustIndices:
    """Test panel_start adjustment on resize."""

    def test_adjust_increases_start(self, controller):
        controller.state = {"panel_start": 10}
        controller.adjust_indices(delta=5, first_affected=5)
        assert controller.state["panel_start"] == 15

    def test_adjust_no_change_before_affected(self, controller):
        controller.state = {"panel_start": 3}
        controller.adjust_indices(delta=5, first_affected=10)
        assert controller.state["panel_start"] == 3

    def test_adjust_noop_when_inactive(self, controller):
        controller.adjust_indices(delta=5, first_affected=0)
        # Should not raise


# ---------------------------------------------------------------------------
# Tests: Navigation (move)
# ---------------------------------------------------------------------------

class TestPickerMove:
    """Test cursor movement in different stages."""

    def test_move_slot_wraps_forward(self, controller):
        controller.state = {
            "stage": "slot",
            "slot_items": [
                {"value": "normal", "label": "Normal", "summary": "x", "option": "1"},
                {"value": "thinking", "label": "Thinking", "summary": "x", "option": "2"},
                {"value": "vision", "label": "Vision", "summary": "x", "option": "3"},
            ],
            "slot_index": 2,
            "panel_start": None,
        }
        # Mock the render methods since they depend on app internals
        controller._render_model_slot_panel = MagicMock()

        controller.move(1)
        assert controller.state["slot_index"] == 0  # Wraps around

    def test_move_slot_wraps_backward(self, controller):
        controller.state = {
            "stage": "slot",
            "slot_items": [
                {"value": "normal", "label": "Normal", "summary": "x", "option": "1"},
                {"value": "thinking", "label": "Thinking", "summary": "x", "option": "2"},
                {"value": "vision", "label": "Vision", "summary": "x", "option": "3"},
            ],
            "slot_index": 0,
            "panel_start": None,
        }
        controller._render_model_slot_panel = MagicMock()

        controller.move(-1)
        assert controller.state["slot_index"] == 2

    def test_move_provider_stage(self, controller):
        p1 = _make_provider("p1", "Provider 1")
        p2 = _make_provider("p2", "Provider 2")
        controller.state = {
            "stage": "provider",
            "providers": [
                {"provider": p1, "models": [], "is_universal": False},
                {"provider": p2, "models": [], "is_universal": False},
            ],
            "provider_index": 0,
            "panel_start": None,
        }
        controller._render_provider_panel = MagicMock()

        controller.move(1)
        assert controller.state["provider_index"] == 1

    def test_move_model_stage(self, controller):
        m1 = _make_model("m1", "Model 1")
        m2 = _make_model("m2", "Model 2")
        controller.state = {
            "stage": "model",
            "models": [m1, m2],
            "model_index": 0,
            "panel_start": None,
        }
        controller._render_model_list_panel = MagicMock()

        controller.move(1)
        assert controller.state["model_index"] == 1

    def test_move_noop_when_inactive(self, controller):
        controller.move(1)  # Should not raise


# ---------------------------------------------------------------------------
# Tests: back
# ---------------------------------------------------------------------------

class TestPickerBack:
    """Test back navigation between stages."""

    def test_back_from_model_to_provider(self, controller):
        controller.state = {"stage": "model", "panel_start": None}
        controller._render_provider_panel = MagicMock()

        controller.back()
        assert controller.state["stage"] == "provider"

    def test_back_from_provider_to_slot(self, controller):
        controller.state = {"stage": "provider", "panel_start": None}
        controller._render_model_slot_panel = MagicMock()

        controller.back()
        assert controller.state["stage"] == "slot"

    def test_back_from_slot_cancels(self, controller):
        controller.state = {"stage": "slot", "panel_start": None}

        controller.back()
        assert controller.active is False

    def test_back_noop_when_inactive(self, controller):
        controller.back()  # Should not raise


# ---------------------------------------------------------------------------
# Tests: _compute_providers_for_slot
# ---------------------------------------------------------------------------

class TestComputeProvidersForSlot:
    """Test provider filtering by slot type."""

    def _make_registry(self):
        """Create a mock registry with known providers."""
        openai_models = {
            "gpt-4o": _make_model("gpt-4o", "GPT-4o", 128000, ["text", "vision"]),
            "o3": _make_model("o3", "O3", 200000, ["text", "reasoning"]),
        }
        fireworks_models = {
            "ds-r1": _make_model("ds-r1", "DeepSeek R1", 128000, ["text", "reasoning"]),
            "qwen": _make_model("qwen", "Qwen", 128000, ["text"]),
        }
        anthropic_models = {
            "claude": _make_model("claude", "Claude", 200000, ["text", "vision", "reasoning"]),
        }

        registry = MagicMock()
        providers = [
            _make_provider("openai", "OpenAI", openai_models),
            _make_provider("fireworks", "Fireworks", fireworks_models),
            _make_provider("anthropic", "Anthropic", anthropic_models),
        ]
        registry.list_providers.return_value = providers
        return registry

    def test_normal_slot_returns_all_providers(self, controller):
        """Normal slot should show all providers with models."""
        registry = self._make_registry()
        # Mock _get_configured_provider_ids to return all
        controller._get_configured_provider_ids = MagicMock(
            return_value={"openai", "fireworks", "anthropic"}
        )

        result = controller._compute_providers_for_slot("normal", registry)
        provider_ids = [r["provider"].id for r in result]

        assert "openai" in provider_ids
        assert "fireworks" in provider_ids
        assert "anthropic" in provider_ids

    def test_thinking_slot_filters_by_reasoning(self, controller):
        """Thinking slot should show providers with reasoning models or universal providers."""
        registry = self._make_registry()
        controller._get_configured_provider_ids = MagicMock(
            return_value={"openai", "fireworks", "anthropic"}
        )

        result = controller._compute_providers_for_slot("thinking", registry)
        provider_ids = [r["provider"].id for r in result]

        # OpenAI and Anthropic are universal, Fireworks has reasoning model
        assert "openai" in provider_ids
        assert "anthropic" in provider_ids
        assert "fireworks" in provider_ids

    def test_thinking_slot_filters_out_text_only_providers(self, controller):
        """Providers with only text models should be excluded from thinking slot."""
        text_only_provider = _make_provider(
            "text_only", "TextOnly",
            {"m1": _make_model("m1", "M1", 64000, ["text"])},
        )

        registry = MagicMock()
        registry.list_providers.return_value = [text_only_provider]
        controller._get_configured_provider_ids = MagicMock(
            return_value={"text_only"}
        )

        result = controller._compute_providers_for_slot("thinking", registry)
        assert len(result) == 0

    def test_vision_slot_filters_by_vision(self, controller):
        """Vision slot should show providers with vision models or universal providers."""
        registry = self._make_registry()
        controller._get_configured_provider_ids = MagicMock(
            return_value={"openai", "fireworks", "anthropic"}
        )

        result = controller._compute_providers_for_slot("vision", registry)
        provider_ids = [r["provider"].id for r in result]

        # OpenAI and Anthropic are universal
        assert "openai" in provider_ids
        assert "anthropic" in provider_ids

    def test_vision_slot_excludes_providers_without_vision(self, controller):
        """Non-universal providers without vision models should be excluded."""
        no_vision = _make_provider(
            "novision", "NoVision",
            {"m1": _make_model("m1", "M1", 64000, ["text", "reasoning"])},
        )

        registry = MagicMock()
        registry.list_providers.return_value = [no_vision]
        controller._get_configured_provider_ids = MagicMock(
            return_value={"novision"}
        )

        result = controller._compute_providers_for_slot("vision", registry)
        assert len(result) == 0

    def test_returns_empty_for_none_registry(self, controller):
        result = controller._compute_providers_for_slot("normal", None)
        assert result == []

    def test_models_sorted_by_context_length(self, controller):
        """Models within each provider should be sorted by context_length descending."""
        models = {
            "small": _make_model("small", "Small", 32000, ["text"]),
            "large": _make_model("large", "Large", 200000, ["text"]),
            "medium": _make_model("medium", "Medium", 128000, ["text"]),
        }
        provider = _make_provider("test", "Test", models)

        registry = MagicMock()
        registry.list_providers.return_value = [provider]
        controller._get_configured_provider_ids = MagicMock(return_value={"test"})

        result = controller._compute_providers_for_slot("normal", registry)
        assert len(result) == 1
        result_models = result[0]["models"]
        context_lengths = [m.context_length for m in result_models]
        assert context_lengths == sorted(context_lengths, reverse=True)


# ---------------------------------------------------------------------------
# Tests: _model_slot_labels & _model_slot_description
# ---------------------------------------------------------------------------

class TestSlotLabelsAndDescriptions:
    """Test static label and description helpers."""

    def test_slot_labels(self):
        labels = ModelPickerController._model_slot_labels()
        assert "normal" in labels
        assert "thinking" in labels
        assert "vision" in labels
        assert "Normal" in labels["normal"]
        assert "Reasoning" in labels["thinking"]
        assert "Multimodal" in labels["vision"]

    def test_slot_description_normal(self):
        desc = ModelPickerController._model_slot_description("normal")
        assert "coding" in desc.lower() or "chat" in desc.lower()

    def test_slot_description_thinking(self):
        desc = ModelPickerController._model_slot_description("thinking")
        assert "reasoning" in desc.lower() or "planning" in desc.lower()

    def test_slot_description_vision(self):
        desc = ModelPickerController._model_slot_description("vision")
        assert "image" in desc.lower() or "multimodal" in desc.lower()

    def test_slot_description_unknown(self):
        desc = ModelPickerController._model_slot_description("unknown")
        assert desc == ""


# ---------------------------------------------------------------------------
# Tests: _commit_single_model
# ---------------------------------------------------------------------------

class TestCommitSingleModel:
    """Test saving a single model selection."""

    @pytest.mark.asyncio
    async def test_commit_success(self, controller, mock_app):
        """Committing a text-only model should call on_model_selected once."""
        provider = _make_provider("openai", "OpenAI")
        model = _make_model("gpt-3.5", "GPT-3.5", 16000, ["text"])

        mock_result = MagicMock()
        mock_result.success = True
        mock_result.message = "Switched"
        mock_app.on_model_selected = MagicMock(return_value=mock_result)

        success = await controller._commit_single_model("normal", provider, model)

        assert success is True
        # Text-only model won't trigger auto-populate, so exactly one call
        mock_app.on_model_selected.assert_called_once_with("normal", "openai", "gpt-3.5")

    @pytest.mark.asyncio
    async def test_commit_failure(self, controller, mock_app):
        provider = _make_provider("openai", "OpenAI")
        model = _make_model("gpt-4o", "GPT-4o")

        mock_result = MagicMock()
        mock_result.success = False
        mock_result.message = "Failed to save"
        mock_app.on_model_selected = MagicMock(return_value=mock_result)

        success = await controller._commit_single_model("normal", provider, model)

        assert success is False

    @pytest.mark.asyncio
    async def test_commit_no_handler(self, controller, mock_app):
        """Should return False when no handler is available."""
        mock_app.on_model_selected = None
        provider = _make_provider("openai", "OpenAI")
        model = _make_model("gpt-4o", "GPT-4o")

        success = await controller._commit_single_model("normal", provider, model)

        assert success is False

    @pytest.mark.asyncio
    async def test_commit_with_async_handler(self, controller, mock_app):
        """Should handle async on_model_selected properly."""
        provider = _make_provider("openai", "OpenAI")
        model = _make_model("gpt-4o", "GPT-4o")

        mock_result = MagicMock()
        mock_result.success = True
        mock_result.message = ""
        mock_app.on_model_selected = AsyncMock(return_value=mock_result)

        success = await controller._commit_single_model("normal", provider, model)

        assert success is True


# ---------------------------------------------------------------------------
# Tests: _auto_populate_slots
# ---------------------------------------------------------------------------

class TestAutoPopulateSlots:
    """Test auto-population of thinking/vision slots."""

    @pytest.mark.asyncio
    async def test_auto_populate_thinking(self, controller, mock_app):
        """Should auto-set thinking slot when model has reasoning capability."""
        provider = _make_provider("openai", "OpenAI")
        model = _make_model("gpt-5", "GPT-5", 128000, ["text", "vision", "reasoning"])

        mock_result = MagicMock()
        mock_result.success = True
        mock_app.on_model_selected = MagicMock(return_value=mock_result)

        # Mock config snapshot to show empty thinking/vision
        controller._get_model_config_snapshot = MagicMock(return_value={
            "normal": {"model": "gpt-5"},
            "thinking": {"model": ""},
            "vision": {"model": ""},
        })

        labels = ModelPickerController._model_slot_labels()
        await controller._auto_populate_slots(provider, model, labels)

        # Should have called on_model_selected for both thinking and vision
        calls = mock_app.on_model_selected.call_args_list
        slots_called = [call[0][0] for call in calls]
        assert "thinking" in slots_called
        assert "vision" in slots_called

    @pytest.mark.asyncio
    async def test_no_auto_populate_when_set(self, controller, mock_app):
        """Should not overwrite existing slot configurations."""
        provider = _make_provider("openai", "OpenAI")
        model = _make_model("gpt-5", "GPT-5", 128000, ["text", "vision", "reasoning"])

        mock_app.on_model_selected = MagicMock()

        # Both slots already have models
        controller._get_model_config_snapshot = MagicMock(return_value={
            "normal": {"model": "gpt-5"},
            "thinking": {"model": "o3"},
            "vision": {"model": "gpt-4o"},
        })

        labels = ModelPickerController._model_slot_labels()
        await controller._auto_populate_slots(provider, model, labels)

        # Should not have called on_model_selected
        mock_app.on_model_selected.assert_not_called()

    @pytest.mark.asyncio
    async def test_auto_populate_only_vision(self, controller, mock_app):
        """Should auto-populate only vision when thinking is already set."""
        provider = _make_provider("openai", "OpenAI")
        model = _make_model("gpt-5", "GPT-5", 128000, ["text", "vision", "reasoning"])

        mock_result = MagicMock()
        mock_result.success = True
        mock_app.on_model_selected = MagicMock(return_value=mock_result)

        # Thinking is set, vision is empty
        controller._get_model_config_snapshot = MagicMock(return_value={
            "normal": {"model": "gpt-5"},
            "thinking": {"model": "o3"},
            "vision": {"model": ""},
        })

        labels = ModelPickerController._model_slot_labels()
        await controller._auto_populate_slots(provider, model, labels)

        calls = mock_app.on_model_selected.call_args_list
        slots_called = [call[0][0] for call in calls]
        assert "thinking" not in slots_called
        assert "vision" in slots_called


# ---------------------------------------------------------------------------
# Tests: handle_input
# ---------------------------------------------------------------------------

class TestHandleInput:
    """Test text-based input handling in picker."""

    @pytest.mark.asyncio
    async def test_handle_input_inactive(self, controller):
        """Should return False when picker is not active."""
        result = await controller.handle_input("1")
        assert result is False

    @pytest.mark.asyncio
    async def test_handle_empty_input(self, controller):
        controller.state = {"stage": "slot"}
        result = await controller.handle_input("")
        assert result is True  # Consumed but no action

    @pytest.mark.asyncio
    async def test_quit_on_slot_stage(self, controller):
        controller.state = {"stage": "slot", "panel_start": None}
        result = await controller.handle_input("quit")
        assert result is True
        assert controller.active is False

    @pytest.mark.asyncio
    async def test_cancel_on_provider_stage(self, controller):
        controller.state = {"stage": "provider", "panel_start": None}
        result = await controller.handle_input("x")
        assert result is True
        assert controller.active is False

    @pytest.mark.asyncio
    async def test_back_on_provider_stage(self, controller):
        controller.state = {"stage": "provider", "panel_start": None}
        controller._render_model_slot_panel = MagicMock()
        result = await controller.handle_input("b")
        assert result is True
        assert controller.state["stage"] == "slot"

    @pytest.mark.asyncio
    async def test_cancel_on_model_stage(self, controller):
        controller.state = {"stage": "model", "panel_start": None}
        result = await controller.handle_input("cancel")
        assert result is True
        assert controller.active is False

    @pytest.mark.asyncio
    async def test_back_on_model_stage(self, controller):
        controller.state = {"stage": "model", "panel_start": None}
        controller._render_provider_panel = MagicMock()
        result = await controller.handle_input("back")
        assert result is True
        assert controller.state["stage"] == "provider"


# ---------------------------------------------------------------------------
# Tests: _get_model_config_snapshot
# ---------------------------------------------------------------------------

class TestGetModelConfigSnapshot:
    """Test building config snapshot from app state."""

    def test_from_get_model_config(self, controller, mock_app):
        """Should use get_model_config callback if available."""
        mock_app.get_model_config = MagicMock(return_value={
            "normal": {"provider": "openai", "model": "gpt-4o"},
            "thinking": {"provider": "openai", "model": "o3"},
        })

        snapshot = controller._get_model_config_snapshot()

        assert snapshot["normal"]["provider"] == "openai"
        assert snapshot["normal"]["model"] == "gpt-4o"
        assert snapshot["thinking"]["model"] == "o3"

    def test_fallback_to_model_slots(self, controller, mock_app):
        """Should fall back to model_slots if get_model_config is None."""
        mock_app.get_model_config = None
        mock_app.model_slots = {
            "normal": ("OpenAI", "gpt-4o"),
            "thinking": ("OpenAI", "O3"),
        }

        snapshot = controller._get_model_config_snapshot()

        assert snapshot["normal"]["provider_display"] == "OpenAI"
        assert snapshot["normal"]["model_display"] == "gpt-4o"

    def test_empty_when_no_data(self, controller, mock_app):
        """Should return empty dict when no data available."""
        mock_app.get_model_config = None
        mock_app.model_slots = {}

        snapshot = controller._get_model_config_snapshot()

        assert snapshot == {}
