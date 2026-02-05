# Manual Test Cases: Model Selection Features

**Component:** Model Selection & Configuration System
**Version:** SWE-CLI
**Last Updated:** 2026-02-05

---

## Table of Contents

1. [Setup Wizard - First-Time Model Selection](#1-setup-wizard---first-time-model-selection)
2. [/models Command - Category Selector](#2-models-command---category-selector)
3. [/models Command - Model Selector](#3-models-command---model-selector)
4. [Normal Model Configuration](#4-normal-model-configuration)
5. [Thinking Model Configuration](#5-thinking-model-configuration)
6. [Vision (VLM) Model Configuration](#6-vision-vlm-model-configuration)
7. [Auto-Population of Model Slots](#7-auto-population-of-model-slots)
8. [Cross-Provider Model Configuration](#8-cross-provider-model-configuration)
9. [Config Persistence & Hierarchy](#9-config-persistence--hierarchy)
10. [API Key Handling](#10-api-key-handling)
11. [Model-Specific API Parameters](#11-model-specific-api-parameters)
12. [Context Token Auto-Calculation](#12-context-token-auto-calculation)
13. [UI Display & Status Line](#13-ui-display--status-line)
14. [Model Registry & Provider Loading](#14-model-registry--provider-loading)
15. [Fireworks Model ID Normalization](#15-fireworks-model-id-normalization)
16. [Agent Rebuild After Model Switch](#16-agent-rebuild-after-model-switch)
17. [Edge Cases & Error Handling](#17-edge-cases--error-handling)

---

## Prerequisites

- SWE-CLI installed (`uv pip install -e ".[dev]"`)
- At least one valid API key available:
  - `FIREWORKS_API_KEY` for Fireworks AI models
  - `OPENAI_API_KEY` for OpenAI models
  - `ANTHROPIC_API_KEY` for Anthropic models
- Terminal with ANSI color support
- Backup any existing `~/.swecli/settings.json` before testing

---

## 1. Setup Wizard - First-Time Model Selection

### TC-1.1: First Launch Triggers Setup Wizard

| Field          | Value |
|----------------|-------|
| **Precondition** | No `~/.swecli/settings.json` exists (rename/remove it) |
| **Steps** | 1. Run `swecli` |
| **Expected** | Setup Wizard panel appears with "Welcome to SWE-CLI!" message |
| **Verify** | - Title says "Setup Wizard" with cyan border<br>- Text says "First-time setup detected" |

### TC-1.2: Provider Selection in Wizard

| Field          | Value |
|----------------|-------|
| **Precondition** | Setup wizard is running (TC-1.1) |
| **Steps** | 1. Observe the provider selection list<br>2. Use arrow keys to navigate<br>3. Select a provider with Enter |
| **Expected** | - Providers listed in priority order: Anthropic, OpenAI, Fireworks, Google, DeepSeek, Groq, Mistral, etc.<br>- Arrow key navigation works<br>- Selection confirmed with checkmark message |
| **Verify** | - Priority providers (anthropic, openai, fireworks) appear first<br>- Models.dev providers appear after the built-in ones<br>- Menu window shows up to 9 items at a time |

### TC-1.3: API Key Input During Wizard

| Field          | Value |
|----------------|-------|
| **Precondition** | Provider selected in wizard |
| **Steps** | 1. If env var detected, confirm "Use it?"<br>2. Or manually enter an API key<br>3. Optionally validate the key |
| **Expected** | - Detects existing env var (e.g., `$OPENAI_API_KEY`)<br>- Manual key entry is masked (password input)<br>- Validation prompt appears (default: Yes) |
| **Verify** | - Env var auto-detection works for the selected provider<br>- Correct env var name shown (e.g., `FIREWORKS_API_KEY`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`) |

### TC-1.4: Model Selection in Wizard

| Field          | Value |
|----------------|-------|
| **Precondition** | API key accepted in wizard |
| **Steps** | 1. Observe model list for chosen provider<br>2. Navigate with arrow keys<br>3. Select a model or choose "Custom Model" |
| **Expected** | - Models listed with pricing and context info<br>- Recommended model marked with "Recommended" prefix<br>- "Custom Model" option available at bottom<br>- Selected model confirmed with checkmark |
| **Verify** | - Models sorted by context length (descending)<br>- Custom model prompts for manual model ID entry |

### TC-1.5: Custom Model ID in Wizard

| Field          | Value |
|----------------|-------|
| **Precondition** | In model selection step of wizard |
| **Steps** | 1. Select "Custom Model"<br>2. Enter a custom model ID (e.g., `my-custom-model-v1`)<br>3. Complete wizard |
| **Expected** | - Prompt asks for custom model ID<br>- Custom ID is accepted and saved to config |
| **Verify** | - Check `~/.swecli/settings.json` contains the custom model ID |

### TC-1.6: Advanced Settings in Wizard

| Field          | Value |
|----------------|-------|
| **Precondition** | Model selected in wizard |
| **Steps** | 1. Answer "Yes" to "Configure advanced settings?"<br>2. Set max tokens (default: 16384)<br>3. Set temperature (default: 0.7)<br>4. Enable/disable bash execution |
| **Expected** | - Each setting has a sensible default<br>- Invalid inputs fall back to defaults (e.g., non-numeric temperature) |
| **Verify** | - Check settings saved in `~/.swecli/settings.json` |

### TC-1.7: Config Saved After Wizard Completion

| Field          | Value |
|----------------|-------|
| **Precondition** | Completed all wizard steps |
| **Steps** | 1. Let wizard finish<br>2. Inspect `~/.swecli/settings.json` |
| **Expected** | - File created at `~/.swecli/settings.json`<br>- Contains `model_provider`, `model`, `api_key`, `max_tokens`, `temperature`, `enable_bash` |
| **Verify** | - JSON is valid<br>- Values match wizard selections |

---

## 2. /models Command - Category Selector

### TC-2.1: Open Category Selector

| Field          | Value |
|----------------|-------|
| **Precondition** | SWE-CLI running with valid config |
| **Steps** | 1. Type `/models` in chat and press Enter |
| **Expected** | - Category selector box appears with title "Select Model Category"<br>- Four categories shown: Normal Model [REQUIRED], Thinking Model [Optional], Vision Model [Optional], Finish Configuration |
| **Verify** | - Box has cyan border<br>- Navigation hint "Use arrows or j/k, Enter to select" shown<br>- ESC/Ctrl+C cancel hint shown |

### TC-2.2: Category Selector - Disabled State When Normal Not Configured

| Field          | Value |
|----------------|-------|
| **Precondition** | SWE-CLI running; normal model NOT yet configured (clear `model` and `model_provider` from settings) |
| **Steps** | 1. Type `/models` |
| **Expected** | - Warning shown: "Configure Normal Model first before optional models"<br>- Thinking and Vision categories are dimmed/disabled with "[Configure Normal first]"<br>- Only "Normal Model" and "Finish Configuration" are selectable |
| **Verify** | - Arrow keys skip over disabled items<br>- Pressing Enter on disabled item does nothing |

### TC-2.3: Category Selector - All Enabled After Normal Configured

| Field          | Value |
|----------------|-------|
| **Precondition** | Normal model is configured in settings |
| **Steps** | 1. Type `/models` |
| **Expected** | - All four categories are selectable (no disabled items)<br>- No warning about configuring Normal first |
| **Verify** | - Can navigate to Thinking and Vision categories<br>- All items respond to Enter key |

### TC-2.4: Category Selector - Navigation

| Field          | Value |
|----------------|-------|
| **Precondition** | Category selector is open |
| **Steps** | 1. Press Down arrow / `j` to move down<br>2. Press Up arrow / `k` to move up<br>3. Press Enter to select |
| **Expected** | - Highlight moves between categories<br>- Selected item shown with `>` indicator and reverse-video highlight<br>- Enter confirms selection |
| **Verify** | - `j`/`k` keyboard shortcuts work same as arrows<br>- Wrap-around behavior (or stops at boundaries) |

### TC-2.5: Category Selector - Cancel

| Field          | Value |
|----------------|-------|
| **Precondition** | Category selector is open |
| **Steps** | 1. Press ESC (or Ctrl+C) |
| **Expected** | - Selector closes without changes<br>- No model changes applied<br>- Return to normal chat input |
| **Verify** | - Input is unlocked after cancel<br>- Conversation continues normally |

### TC-2.6: Category Selector - Finish Option

| Field          | Value |
|----------------|-------|
| **Precondition** | Category selector is open |
| **Steps** | 1. Navigate to "Finish Configuration"<br>2. Press Enter |
| **Expected** | - Summary message shown with all configured models:<br>  - Normal: Provider/Model<br>  - Thinking: Provider/Model (or "Not set, falls back to Normal")<br>  - Vision: Provider/Model (or "Not set, vision tasks unavailable") |
| **Verify** | - Summary uses correct provider capitalization<br>- Selector closes after summary is shown |

---

## 3. /models Command - Model Selector

### TC-3.1: Model List for Normal Category

| Field          | Value |
|----------------|-------|
| **Precondition** | Category selector open; Normal model selected |
| **Steps** | 1. Select "Normal Model" category |
| **Expected** | - Model selector appears with header "Normal Model (Standard Coding Tasks)"<br>- First item is "Back to category selection"<br>- Models grouped by provider with provider headers<br>- All text-capable models shown for all providers |
| **Verify** | - Fireworks models show capabilities (e.g., `[text]`, `[text, reasoning]`)<br>- OpenAI/Anthropic marked as "All models support all tasks"<br>- Context length shown (e.g., `256k`, `128k`) |

### TC-3.2: Model List for Thinking Category

| Field          | Value |
|----------------|-------|
| **Precondition** | Category selector open; Thinking category selected |
| **Steps** | 1. Select "Thinking Model" category |
| **Expected** | - Header: "Thinking Model (Complex Reasoning)"<br>- For Fireworks: only models with "reasoning" capability shown (e.g., Kimi K2 Thinking, Qwen3 Thinking, DeepSeek R1)<br>- For OpenAI: all models shown (universal provider)<br>- For Anthropic: all models shown (universal provider) |
| **Verify** | - Fireworks text-only models (DeepSeek V3, MiniMax M2, etc.) are NOT shown<br>- OpenAI reasoning models (O1, O3, O4) are included<br>- Provider header shows correct model count |

### TC-3.3: Model List for Vision Category

| Field          | Value |
|----------------|-------|
| **Precondition** | Category selector open; Vision category selected |
| **Steps** | 1. Select "Vision Model" category |
| **Expected** | - Header: "Vision Model (Image Processing)"<br>- For Fireworks: only models with "vision" capability (e.g., Qwen2.5-VL 32B)<br>- For OpenAI: all models shown (universal provider)<br>- For Anthropic: all models shown (universal provider) |
| **Verify** | - Fireworks text-only and reasoning-only models NOT shown<br>- Only vision-capable models from non-universal providers appear |

### TC-3.4: Model Selector - Back Navigation

| Field          | Value |
|----------------|-------|
| **Precondition** | Model selector is open for any category |
| **Steps** | 1. Navigate to "Back to category selection"<br>2. Press Enter |
| **Expected** | - Returns to category selector<br>- No model changes applied<br>- Can select a different category |
| **Verify** | - Previous category selection state is preserved<br>- Loop continues correctly |

### TC-3.5: Model Selector - Select a Model

| Field          | Value |
|----------------|-------|
| **Precondition** | Model selector open for Normal category |
| **Steps** | 1. Navigate to a specific model (e.g., GPT-5.2 under OpenAI)<br>2. Press Enter |
| **Expected** | - Model is configured for the selected slot<br>- Returns to category selector for additional configuration<br>- Config is saved to `~/.swecli/settings.json` |
| **Verify** | - Check settings file: `model_provider` and `model` updated<br>- UI footer updates to show new model name |

### TC-3.6: Model Selector - Provider Header Navigation

| Field          | Value |
|----------------|-------|
| **Precondition** | Model selector is open |
| **Steps** | 1. Navigate to a provider header (e.g., "[Fireworks AI] - 15 models")<br>2. Press Enter on the provider header |
| **Expected** | - Provider headers are shown in yellow<br>- Selecting a provider header may or may not do anything (it's a section header) |
| **Verify** | - Provider header is highlighted when selected<br>- Behavior is clear to user (not confusing) |

### TC-3.7: Model Selector - Long Model Name Truncation

| Field          | Value |
|----------------|-------|
| **Precondition** | Model selector is open |
| **Steps** | 1. Observe models with long names (e.g., "Qwen3 Coder 480B A35B Instruct (256k)") |
| **Expected** | - Long names truncated with "..." if exceeding box width (75 chars)<br>- Box border alignment maintained |
| **Verify** | - No visual glitches or broken box borders |

---

## 4. Normal Model Configuration

### TC-4.1: Switch Normal Model - Same Provider

| Field          | Value |
|----------------|-------|
| **Precondition** | Normal model is Fireworks/kimi-k2-instruct-0905 |
| **Steps** | 1. `/models` -> Normal -> Select DeepSeek V3P2 (also Fireworks)<br>2. Finish configuration |
| **Expected** | - `model` changes to `accounts/fireworks/models/deepseek-v3p2`<br>- `model_provider` stays `fireworks`<br>- `max_context_tokens` recalculated to 128000 (160000 * 0.8) |
| **Verify** | - Settings file updated<br>- Agent uses new model for next prompt<br>- Status line shows new model |

### TC-4.2: Switch Normal Model - Different Provider

| Field          | Value |
|----------------|-------|
| **Precondition** | Normal model is Fireworks/kimi-k2-instruct-0905; `OPENAI_API_KEY` is set |
| **Steps** | 1. `/models` -> Normal -> Select GPT-5.2 (OpenAI)<br>2. Finish configuration |
| **Expected** | - `model_provider` changes to `openai`<br>- `model` changes to `gpt-5.2`<br>- `max_context_tokens` recalculated to 102400 (128000 * 0.8)<br>- Agents rebuilt with new HTTP client for OpenAI |
| **Verify** | - Settings file shows `openai` and `gpt-5.2`<br>- Subsequent prompts use OpenAI API<br>- Status line shows `openai/gpt-5.2` |

### TC-4.3: Switch Normal Model to Anthropic

| Field          | Value |
|----------------|-------|
| **Precondition** | `ANTHROPIC_API_KEY` is set |
| **Steps** | 1. `/models` -> Normal -> Select any Anthropic model (e.g., Claude 3.5 Sonnet) |
| **Expected** | - `model_provider` changes to `anthropic`<br>- Uses `AnthropicAdapter` instead of `AgentHttpClient`<br>- Agent rebuild creates Anthropic-specific client |
| **Verify** | - Subsequent prompts use Anthropic API format<br>- Messages endpoint: `https://api.anthropic.com/v1/messages` |

### TC-4.4: Verify Normal Model Used in Chat

| Field          | Value |
|----------------|-------|
| **Precondition** | Normal model configured to a known model (e.g., GPT-5.2) |
| **Steps** | 1. Type a simple prompt: "What model are you?"<br>2. Observe response |
| **Expected** | - Response comes from the configured model<br>- Agent has full tool access (file write, bash, etc.) |
| **Verify** | - Response characteristics match expected model behavior<br>- Tools are available in the response |

---

## 5. Thinking Model Configuration

### TC-5.1: Configure Thinking Model Separately

| Field          | Value |
|----------------|-------|
| **Precondition** | Normal model configured; no thinking model set |
| **Steps** | 1. `/models` -> Thinking -> Select O3 (OpenAI reasoning model)<br>2. Finish configuration |
| **Expected** | - `model_thinking_provider` set to `openai`<br>- `model_thinking` set to `o3`<br>- Normal model unchanged |
| **Verify** | - Settings file shows both normal and thinking model<br>- `model_thinking_provider` and `model_thinking` present |

### TC-5.2: Thinking Model Fallback to Normal

| Field          | Value |
|----------------|-------|
| **Precondition** | `model_thinking` is `null`/not set in config |
| **Steps** | 1. Send a complex prompt that triggers thinking phase<br>2. Observe behavior |
| **Expected** | - Agent uses Normal model for thinking phase (fallback)<br>- No error about missing thinking model<br>- `get_thinking_model_info()` returns normal model info |
| **Verify** | - Debug logs (if enabled) show normal model used for thinking call |

### TC-5.3: Cross-Provider Thinking Model

| Field          | Value |
|----------------|-------|
| **Precondition** | Normal = Fireworks/Kimi K2; `OPENAI_API_KEY` set |
| **Steps** | 1. `/models` -> Thinking -> Select O1 (OpenAI)<br>2. Finish and send a prompt |
| **Expected** | - Thinking phase uses OpenAI O1 with separate HTTP client<br>- Action phase uses Fireworks Kimi K2<br>- Both API keys used correctly from env vars |
| **Verify** | - Thinking call goes to OpenAI endpoint<br>- Action call goes to Fireworks endpoint<br>- No API key cross-contamination |

### TC-5.4: Thinking Model - Temperature Handling for Reasoning Models

| Field          | Value |
|----------------|-------|
| **Precondition** | Thinking model set to O1, O3, or O4 (`supports_temperature: false`) |
| **Steps** | 1. Send a prompt |
| **Expected** | - Temperature parameter NOT included in API call to reasoning models<br>- No API error about unsupported temperature parameter |
| **Verify** | - Debug logs show no `temperature` key in request payload for reasoning model<br>- API call succeeds without temperature-related errors |

### TC-5.5: Thinking Model - Capability Filtering in Selector

| Field          | Value |
|----------------|-------|
| **Precondition** | `/models` -> Thinking category selected |
| **Steps** | 1. Observe Fireworks models listed |
| **Expected** | - Only reasoning-capable models shown for Fireworks:<br>  - Kimi K2 Thinking (reasoning)<br>  - Qwen3 235B Thinking 2507 (reasoning)<br>  - DeepSeek R1 (reasoning)<br>- Text-only models (DeepSeek V3, MiniMax M2, etc.) NOT shown |
| **Verify** | - Count matches: only 3 Fireworks reasoning models<br>- OpenAI shows all models (universal provider) |

---

## 6. Vision (VLM) Model Configuration

### TC-6.1: Configure Vision Model

| Field          | Value |
|----------------|-------|
| **Precondition** | Normal model configured; no VLM set |
| **Steps** | 1. `/models` -> Vision -> Select Qwen2.5-VL 32B (Fireworks)<br>2. Finish configuration |
| **Expected** | - `model_vlm_provider` set to `fireworks`<br>- `model_vlm` set to `accounts/fireworks/models/qwen2p5-vl-32b-instruct` |
| **Verify** | - Settings file updated with VLM fields<br>- Summary shows "Vision: Fireworks/qwen2p5-vl-32b-instruct" |

### TC-6.2: VLM Tool Availability Check

| Field          | Value |
|----------------|-------|
| **Precondition** | VLM model IS configured |
| **Steps** | 1. Ask agent to analyze an image |
| **Expected** | - VLMTool.is_available() returns True<br>- Image analysis request is sent to configured VLM provider |
| **Verify** | - No "Vision model not configured" error |

### TC-6.3: VLM Tool Unavailable - No VLM Configured

| Field          | Value |
|----------------|-------|
| **Precondition** | `model_vlm` and `model_vlm_provider` are both null/unset |
| **Steps** | 1. Ask agent to analyze an image |
| **Expected** | - Error message: "Vision model not configured. Please configure a VLM model using '/models' command and select a Vision model." |
| **Verify** | - VLMTool.is_available() returns False<br>- Helpful error message directs user to `/models` |

### TC-6.4: VLM Fallback to Normal Model with Vision Capability

| Field          | Value |
|----------------|-------|
| **Precondition** | Normal model = GPT-5.2 (has "vision" capability); VLM not explicitly set |
| **Steps** | 1. Check `get_vlm_model_info()` behavior |
| **Expected** | - Falls back to normal model since it has "vision" capability<br>- Returns normal model info for VLM tasks |
| **Verify** | - Vision tasks work using the normal model |

### TC-6.5: VLM No Fallback - Normal Model Without Vision

| Field          | Value |
|----------------|-------|
| **Precondition** | Normal model = Fireworks/DeepSeek V3 (text-only, no vision); VLM not set |
| **Steps** | 1. Check `get_vlm_model_info()` behavior |
| **Expected** | - Returns None (no vision model available)<br>- Vision tasks return error |
| **Verify** | - Image analysis returns "Vision model not configured" error |

### TC-6.6: Vision Model - Capability Filtering in Selector

| Field          | Value |
|----------------|-------|
| **Precondition** | `/models` -> Vision category selected |
| **Steps** | 1. Observe Fireworks models listed |
| **Expected** | - Only vision-capable Fireworks models shown: Qwen2.5-VL 32B<br>- All OpenAI models shown (universal provider)<br>- All Anthropic models shown (universal provider) |
| **Verify** | - Non-vision Fireworks models excluded<br>- Only 1 Fireworks model has vision capability |

---

## 7. Auto-Population of Model Slots

### TC-7.1: Auto-Populate Thinking When Normal Has Reasoning

| Field          | Value |
|----------------|-------|
| **Precondition** | Thinking slot is empty (null); VLM slot is empty |
| **Steps** | 1. `/models` -> Normal -> Select GPT-5.2 (has "reasoning" capability)<br>2. Finish configuration |
| **Expected** | - Thinking slot auto-populated with GPT-5.2 / OpenAI<br>- `model_thinking` = `gpt-5.2`, `model_thinking_provider` = `openai` |
| **Verify** | - Settings file shows auto-populated thinking fields<br>- Summary shows both Normal and Thinking pointing to GPT-5.2 |

### TC-7.2: Auto-Populate VLM When Normal Has Vision

| Field          | Value |
|----------------|-------|
| **Precondition** | VLM slot is empty (null) |
| **Steps** | 1. `/models` -> Normal -> Select GPT-5.2 (has "vision" capability)<br>2. Finish configuration |
| **Expected** | - VLM slot auto-populated with GPT-5.2 / OpenAI<br>- `model_vlm` = `gpt-5.2`, `model_vlm_provider` = `openai` |
| **Verify** | - Settings file shows auto-populated VLM fields |

### TC-7.3: No Auto-Populate When Slots Already Set

| Field          | Value |
|----------------|-------|
| **Precondition** | Thinking = O3 (OpenAI); VLM = Qwen2.5-VL (Fireworks) |
| **Steps** | 1. `/models` -> Normal -> Select GPT-5.2 (has reasoning + vision)<br>2. Finish configuration |
| **Expected** | - Thinking slot stays as O3 (NOT overwritten)<br>- VLM slot stays as Qwen2.5-VL (NOT overwritten)<br>- Only Normal model changes |
| **Verify** | - Settings file shows original thinking and VLM values unchanged |

### TC-7.4: No Auto-Populate When Normal Model Lacks Capabilities

| Field          | Value |
|----------------|-------|
| **Precondition** | Thinking and VLM slots are empty |
| **Steps** | 1. `/models` -> Normal -> Select DeepSeek V3P2 (text-only, no reasoning/vision)<br>2. Finish configuration |
| **Expected** | - Thinking slot stays null<br>- VLM slot stays null<br>- No auto-population occurs |
| **Verify** | - Settings file has no `model_thinking` or `model_vlm` |

---

## 8. Cross-Provider Model Configuration

### TC-8.1: Normal Fireworks + Thinking OpenAI + VLM Anthropic

| Field          | Value |
|----------------|-------|
| **Precondition** | All three API keys set in environment |
| **Steps** | 1. `/models` -> Normal -> Fireworks/Kimi K2 Instruct<br>2. Back to category -> Thinking -> OpenAI/O3<br>3. Back to category -> Vision -> Anthropic/Claude 3.5 Sonnet<br>4. Finish |
| **Expected** | - Three different providers configured simultaneously<br>- Each slot has correct provider and model ID<br>- Config saved correctly |
| **Verify** | - Settings: `model_provider: fireworks`, `model_thinking_provider: openai`, `model_vlm_provider: anthropic`<br>- Each uses its own API key from env var |

### TC-8.2: Multiple Configuration Rounds

| Field          | Value |
|----------------|-------|
| **Precondition** | Normal model already configured |
| **Steps** | 1. `/models` -> Normal -> Change to a different model<br>2. Back to category -> Thinking -> Set a thinking model<br>3. Back to category -> Normal -> Change again<br>4. Finish |
| **Expected** | - Each selection saves immediately<br>- Can reconfigure any slot multiple times before finishing<br>- Final config reflects last selection for each slot |
| **Verify** | - Only the last selection per slot is saved |

---

## 9. Config Persistence & Hierarchy

### TC-9.1: Config Saved to Global Settings

| Field          | Value |
|----------------|-------|
| **Precondition** | Models configured via `/models` |
| **Steps** | 1. Inspect `~/.swecli/settings.json` |
| **Expected** | - Contains: `model_provider`, `model`, `model_thinking_provider`, `model_thinking`, `model_vlm_provider`, `model_vlm`, `api_base_url`, `debug_logging`<br>- Null values excluded<br>- `api_key` NOT present (security) |
| **Verify** | - JSON is valid and parseable<br>- No sensitive data stored |

### TC-9.2: Local Project Config Overrides Global

| Field          | Value |
|----------------|-------|
| **Precondition** | Global: `model=gpt-5.2`; Project `.swecli/settings.json`: `model=gpt-5-mini` |
| **Steps** | 1. Run `swecli` from the project directory<br>2. Check active model |
| **Expected** | - Active model is `gpt-5-mini` (local overrides global)<br>- Provider from local config takes precedence |
| **Verify** | - Status line shows local project model<br>- Prompts sent to local project model |

### TC-9.3: Config Reload After Model Change

| Field          | Value |
|----------------|-------|
| **Precondition** | SWE-CLI running |
| **Steps** | 1. Change model via `/models`<br>2. Check config is reloaded |
| **Expected** | - Config saved to file immediately<br>- New config reflected in agent behavior on next prompt |
| **Verify** | - File on disk matches in-memory config |

### TC-9.4: Legacy API Key Removal

| Field          | Value |
|----------------|-------|
| **Precondition** | `~/.swecli/settings.json` contains `"api_key": "sk-..."` (legacy) |
| **Steps** | 1. Run `swecli` |
| **Expected** | - `api_key` field is stripped from loaded config<br>- API key only sourced from environment variables |
| **Verify** | - No `api_key` in the runtime config object |

---

## 10. API Key Handling

### TC-10.1: API Key from Environment Variable - Fireworks

| Field          | Value |
|----------------|-------|
| **Precondition** | `FIREWORKS_API_KEY` set in environment; `model_provider: fireworks` |
| **Steps** | 1. Run swecli and send a prompt |
| **Expected** | - API key retrieved from `FIREWORKS_API_KEY`<br>- Request sent to `https://api.fireworks.ai/inference/v1/chat/completions` |
| **Verify** | - No "No API key found" error |

### TC-10.2: API Key from Environment Variable - OpenAI

| Field          | Value |
|----------------|-------|
| **Precondition** | `OPENAI_API_KEY` set; `model_provider: openai` |
| **Steps** | 1. Send a prompt |
| **Expected** | - API key from `OPENAI_API_KEY`<br>- Request to `https://api.openai.com/v1/chat/completions` |

### TC-10.3: API Key from Environment Variable - Anthropic

| Field          | Value |
|----------------|-------|
| **Precondition** | `ANTHROPIC_API_KEY` set; `model_provider: anthropic` |
| **Steps** | 1. Send a prompt |
| **Expected** | - API key from `ANTHROPIC_API_KEY`<br>- Uses `AnthropicAdapter` client<br>- Request to `https://api.anthropic.com/v1/messages` |

### TC-10.4: Missing API Key Error

| Field          | Value |
|----------------|-------|
| **Precondition** | Unset the API key for the configured provider (e.g., `unset OPENAI_API_KEY`) |
| **Steps** | 1. Send a prompt |
| **Expected** | - Error: "No API key found. Set OPENAI_API_KEY environment variable"<br>- Error message includes the correct env var name for the provider |
| **Verify** | - Error is informative and actionable |

### TC-10.5: Cross-Provider API Keys for Thinking Model

| Field          | Value |
|----------------|-------|
| **Precondition** | Normal = Fireworks (FIREWORKS_API_KEY set); Thinking = OpenAI (OPENAI_API_KEY set) |
| **Steps** | 1. Send a prompt that triggers thinking phase |
| **Expected** | - Thinking phase uses `OPENAI_API_KEY`<br>- Action phase uses `FIREWORKS_API_KEY`<br>- Each provider uses its own env var |
| **Verify** | - Both API calls succeed with correct keys |

### TC-10.6: Missing Thinking Model API Key

| Field          | Value |
|----------------|-------|
| **Precondition** | Thinking = OpenAI; `OPENAI_API_KEY` NOT set; Normal = Fireworks |
| **Steps** | 1. Send a prompt |
| **Expected** | - Error about missing `OPENAI_API_KEY` for thinking model<br>- Or graceful fallback to normal model |
| **Verify** | - Error message specifies the correct missing env var |

---

## 11. Model-Specific API Parameters

### TC-11.1: max_completion_tokens for GPT-5 Models

| Field          | Value |
|----------------|-------|
| **Precondition** | Normal model = `gpt-5.2` or any model starting with `gpt-5` |
| **Steps** | 1. Send a prompt<br>2. Inspect API request (enable debug logging) |
| **Expected** | - Request uses `max_completion_tokens` parameter (NOT `max_tokens`)<br>- Value set to configured `max_tokens` (default: 16384) |
| **Verify** | - Check with: `uses_max_completion_tokens("gpt-5.2")` returns True |

### TC-11.2: max_completion_tokens for O-Series Models

| Field          | Value |
|----------------|-------|
| **Precondition** | Model starts with `o1`, `o3`, or `o4` |
| **Steps** | 1. Send a prompt |
| **Expected** | - Request uses `max_completion_tokens` (NOT `max_tokens`) |
| **Verify** | - `uses_max_completion_tokens("o3")` returns True<br>- `uses_max_completion_tokens("o1-pro")` returns True |

### TC-11.3: max_tokens for Non-GPT5/O-Series Models

| Field          | Value |
|----------------|-------|
| **Precondition** | Model = Fireworks/kimi-k2-instruct or any non-GPT5/O model |
| **Steps** | 1. Send a prompt |
| **Expected** | - Request uses standard `max_tokens` parameter |
| **Verify** | - `uses_max_completion_tokens("accounts/fireworks/models/kimi-k2-instruct-0905")` returns False |

### TC-11.4: Temperature Excluded for Reasoning Models

| Field          | Value |
|----------------|-------|
| **Precondition** | Model = O1, O3, or O4 (supports_temperature: false) |
| **Steps** | 1. Send a prompt |
| **Expected** | - No `temperature` field in API request<br>- API call succeeds without temperature error |
| **Verify** | - `build_temperature_param("o3", 0.6)` returns `{}` (empty dict) |

### TC-11.5: Temperature Included for Standard Models

| Field          | Value |
|----------------|-------|
| **Precondition** | Model = GPT-5.2 or Kimi K2 (supports_temperature: true) |
| **Steps** | 1. Send a prompt |
| **Expected** | - `temperature` field present in API request with configured value (default: 0.6) |
| **Verify** | - `build_temperature_param("gpt-5.2", 0.6)` returns `{"temperature": 0.6}` |

---

## 12. Context Token Auto-Calculation

### TC-12.1: Auto-Set Context Tokens on Model Change

| Field          | Value |
|----------------|-------|
| **Precondition** | Any model configured |
| **Steps** | 1. Switch Normal model to GPT-5.2 (128k context)<br>2. Check `max_context_tokens` |
| **Expected** | - `max_context_tokens` = 102400 (128000 * 0.8) |
| **Verify** | - 80% of context_length used |

### TC-12.2: Context Tokens for Large Context Model

| Field          | Value |
|----------------|-------|
| **Precondition** | Switch to Kimi K2 (256k context) |
| **Steps** | 1. Check `max_context_tokens` |
| **Expected** | - `max_context_tokens` = 204800 (256000 * 0.8) |

### TC-12.3: Old Default Values Recalculated

| Field          | Value |
|----------------|-------|
| **Precondition** | `max_context_tokens` manually set to 100000 or 256000 in settings file |
| **Steps** | 1. Start swecli |
| **Expected** | - Old defaults (100000, 256000) are recalculated based on actual model<br>- New value = model.context_length * 0.8 |
| **Verify** | - Values != 100000 or 256000 are NOT recalculated (considered custom) |

---

## 13. UI Display & Status Line

### TC-13.1: Fireworks Model Name Truncation

| Field          | Value |
|----------------|-------|
| **Precondition** | Normal model = `accounts/fireworks/models/kimi-k2-instruct-0905` |
| **Steps** | 1. Observe status line at bottom of TUI |
| **Expected** | - Model shown as `fireworks/kimi-k2-instruct-0905` (NOT full path with `accounts/`) |
| **Verify** | - `_truncate_model("accounts/fireworks/models/kimi-k2-instruct-0905")` returns `fireworks/kimi-k2-instruct-0905` |

### TC-13.2: Short Model Name Display

| Field          | Value |
|----------------|-------|
| **Precondition** | Normal model = `gpt-5.2` |
| **Steps** | 1. Observe status line |
| **Expected** | - Model shown as `gpt-5.2` (short names kept as-is) |

### TC-13.3: Very Long Model Name Truncation

| Field          | Value |
|----------------|-------|
| **Precondition** | Model name exceeds 60 characters |
| **Steps** | 1. Observe status line |
| **Expected** | - Model name truncated with "..." while preserving provider prefix |
| **Verify** | - No overflow or visual corruption |

### TC-13.4: Model Config Summary Display

| Field          | Value |
|----------------|-------|
| **Precondition** | All three model slots configured |
| **Steps** | 1. `/models` -> Finish |
| **Expected** | Summary shows:<br>- "Models configured"<br>- "Normal: Provider/model-name"<br>- "Thinking: Provider/model-name"<br>- "Vision: Provider/model-name" |
| **Verify** | - Provider names capitalized (e.g., "Fireworks", "Openai")<br>- Model names show last segment after `/` |

### TC-13.5: Summary With Missing Optional Slots

| Field          | Value |
|----------------|-------|
| **Precondition** | Only Normal model configured; Thinking and VLM null |
| **Steps** | 1. `/models` -> Finish |
| **Expected** | Summary shows:<br>- "Normal: Provider/model-name"<br>- "Thinking: Not set (falls back to Normal)"<br>- "Vision: Not set (vision tasks unavailable)" |

### TC-13.6: UI Footer Updates After Model Switch

| Field          | Value |
|----------------|-------|
| **Precondition** | SWE-CLI running |
| **Steps** | 1. `/models` -> Normal -> Switch to a different model<br>2. Observe UI footer/status bar |
| **Expected** | - Footer immediately shows new model name<br>- No need to restart application |
| **Verify** | - `chat_app.refresh()` called after model switch |

---

## 14. Model Registry & Provider Loading

### TC-14.1: Fireworks Models Loaded from JSON

| Field          | Value |
|----------------|-------|
| **Precondition** | Application starting up |
| **Steps** | 1. Check model registry contents |
| **Expected** | - 15 Fireworks models loaded from `swecli/config/providers/fireworks.json`<br>- Models include: DeepSeek V3P1/V3P2, Kimi K2 Thinking/Instruct, MiniMax M2, GPT-OSS variants, Qwen3 variants, GLM 4.6, Llama 3.3 |

### TC-14.2: OpenAI Models Loaded from JSON

| Field          | Value |
|----------------|-------|
| **Precondition** | Application starting up |
| **Steps** | 1. Check model registry contents |
| **Expected** | - 40+ OpenAI models loaded from `swecli/config/providers/openai.json`<br>- Includes: GPT-5.x, GPT-4.x, O-series, Codex, Realtime, Audio, Search, Image models |

### TC-14.3: Models.dev Catalog Augmentation

| Field          | Value |
|----------------|-------|
| **Precondition** | Models.dev catalog file exists |
| **Steps** | 1. Check providers list after loading |
| **Expected** | - Additional providers from Models.dev added (e.g., Anthropic, Google, DeepSeek)<br>- No duplicate providers (existing fireworks/openai not overwritten) |
| **Verify** | - Existing provider models preserved<br>- New providers have `_augmented` flag or similar indication |

### TC-14.4: find_model_by_id Search

| Field          | Value |
|----------------|-------|
| **Precondition** | Registry loaded |
| **Steps** | 1. Look up `gpt-5.2` by ID<br>2. Look up `accounts/fireworks/models/kimi-k2-instruct-0905`<br>3. Look up `nonexistent-model` |
| **Expected** | - `gpt-5.2`: returns (openai, "gpt-5.2", ModelInfo)<br>- Kimi K2: returns (fireworks, "kimi-k2-instruct-0905", ModelInfo)<br>- Nonexistent: returns None |

### TC-14.5: Legacy models.json Fallback

| Field          | Value |
|----------------|-------|
| **Precondition** | Rename `providers/` directory; ensure `models.json` exists |
| **Steps** | 1. Start application |
| **Expected** | - Falls back to loading from legacy `models.json`<br>- Models still available |

### TC-14.6: Capability Filtering

| Field          | Value |
|----------------|-------|
| **Precondition** | Registry loaded |
| **Steps** | 1. `list_all_models(capability="reasoning")`<br>2. `list_all_models(capability="vision")` |
| **Expected** | - Reasoning: Kimi K2 Thinking, Qwen3 Thinking, DeepSeek R1, O1/O3/O4 models, GPT-5.x (with reasoning)<br>- Vision: Qwen2.5-VL, GPT-5.2, GPT-4o, GPT-4.1, etc. |

---

## 15. Fireworks Model ID Normalization

### TC-15.1: Short Fireworks ID Normalized on Load

| Field          | Value |
|----------------|-------|
| **Precondition** | Settings file has `"model": "kimi-k2-instruct-0905"` with `"model_provider": "fireworks"` |
| **Steps** | 1. Start swecli |
| **Expected** | - Model ID normalized to `accounts/fireworks/models/kimi-k2-instruct-0905`<br>- Settings file updated on disk with full ID |
| **Verify** | - Check settings file after load: contains full `accounts/fireworks/models/...` path |

### TC-15.2: Already Normalized ID Unchanged

| Field          | Value |
|----------------|-------|
| **Precondition** | Settings has `"model": "accounts/fireworks/models/kimi-k2-instruct-0905"` |
| **Steps** | 1. Start swecli |
| **Expected** | - No normalization needed<br>- Settings file unchanged |

### TC-15.3: Non-Fireworks IDs Not Affected

| Field          | Value |
|----------------|-------|
| **Precondition** | Settings has `"model_provider": "openai"`, `"model": "gpt-5.2"` |
| **Steps** | 1. Start swecli |
| **Expected** | - OpenAI model ID `gpt-5.2` left unchanged<br>- Normalization only applies to fireworks provider |

### TC-15.4: Normalization for Thinking/VLM Slots

| Field          | Value |
|----------------|-------|
| **Precondition** | `model_thinking_provider: fireworks`, `model_thinking: deepseek-r1-05-28` |
| **Steps** | 1. Start swecli |
| **Expected** | - Thinking model normalized to `accounts/fireworks/models/deepseek-r1-05-28`<br>- Settings file updated |
| **Verify** | - All three model slots normalized independently |

---

## 16. Agent Rebuild After Model Switch

### TC-16.1: Agents Rebuilt After Provider Change

| Field          | Value |
|----------------|-------|
| **Precondition** | Running with Fireworks provider |
| **Steps** | 1. `/models` -> Normal -> Switch to OpenAI GPT-5.2<br>2. Send a prompt |
| **Expected** | - New agents created with OpenAI HTTP client<br>- Old Fireworks client discarded<br>- Both SwecliAgent and PlanningAgent rebuilt |
| **Verify** | - Response comes from OpenAI model, not Fireworks |

### TC-16.2: Agents Rebuilt After Same-Provider Model Change

| Field          | Value |
|----------------|-------|
| **Precondition** | Running with OpenAI/GPT-5.2 |
| **Steps** | 1. `/models` -> Normal -> Switch to GPT-5-mini (same OpenAI provider)<br>2. Send a prompt |
| **Expected** | - Agent factory creates new agents<br>- Same HTTP client (OpenAI) but different model in requests |
| **Verify** | - Model ID in API request is `gpt-5-mini` |

### TC-16.3: Planning Agent Uses Same Model

| Field          | Value |
|----------------|-------|
| **Precondition** | Models configured; agent rebuilt |
| **Steps** | 1. Switch to Plan mode (`/mode` or Shift+Tab)<br>2. Send a prompt |
| **Expected** | - Planning agent uses same Normal model as main agent<br>- Planning agent has read-only tools only |
| **Verify** | - Plan mode responses come from configured model |

---

## 17. Edge Cases & Error Handling

### TC-17.1: Invalid Provider in Config File

| Field          | Value |
|----------------|-------|
| **Precondition** | Manually set `"model_provider": "invalid_provider"` in settings.json |
| **Steps** | 1. Start swecli |
| **Expected** | - Validation error: "Unsupported provider 'invalid_provider'. Supported providers: fireworks, anthropic, openai" |
| **Verify** | - Pydantic validator catches the invalid provider |

### TC-17.2: Model Not Found in Registry

| Field          | Value |
|----------------|-------|
| **Precondition** | Attempt to switch to non-existent model via internal method |
| **Steps** | 1. Try selecting a model ID that doesn't exist in registry |
| **Expected** | - Error: "Model 'xyz' not found"<br>- No config changes applied |

### TC-17.3: Provider Mismatch

| Field          | Value |
|----------------|-------|
| **Precondition** | Internal edge case |
| **Steps** | 1. Try _switch_to_model with mismatched provider_id and model_id |
| **Expected** | - Error: "Model provider mismatch"<br>- No config changes |

### TC-17.4: Empty/Corrupt Settings File

| Field          | Value |
|----------------|-------|
| **Precondition** | Settings file contains `{}` (empty JSON) |
| **Steps** | 1. Start swecli |
| **Expected** | - Falls back to defaults: Fireworks/kimi-k2-instruct-0905<br>- Application starts normally |

### TC-17.5: Settings File With Invalid JSON

| Field          | Value |
|----------------|-------|
| **Precondition** | Settings file contains invalid JSON (e.g., `{invalid}`) |
| **Steps** | 1. Start swecli |
| **Expected** | - JSON parse error<br>- Application handles gracefully (falls back to defaults or shows clear error) |

### TC-17.6: Interactive Model Selector Not Available in Non-Interactive Mode

| Field          | Value |
|----------------|-------|
| **Precondition** | Running in non-interactive mode (`swecli -p "prompt"`) |
| **Steps** | 1. Try to trigger `/models` command |
| **Expected** | - Error: "Interactive model selector not available in this mode" |

### TC-17.7: Concurrent Config Saves

| Field          | Value |
|----------------|-------|
| **Precondition** | SWE-CLI running |
| **Steps** | 1. Rapidly switch models multiple times |
| **Expected** | - Last config save wins<br>- No file corruption<br>- JSON remains valid |

### TC-17.8: Anthropic VLM Limitation

| Field          | Value |
|----------------|-------|
| **Precondition** | VLM configured with Anthropic provider |
| **Steps** | 1. Ask agent to analyze an image via URL |
| **Expected** | - Error: "Anthropic vision API requires base64-encoded images. Please use Fireworks or OpenAI for URL-based image analysis." |
| **Verify** | - Anthropic VLM for URL images currently unsupported |

### TC-17.9: Universal Provider Flag

| Field          | Value |
|----------------|-------|
| **Precondition** | Check `should_use_provider_for_all()` |
| **Steps** | 1. Check for OpenAI<br>2. Check for Anthropic<br>3. Check for Fireworks |
| **Expected** | - OpenAI: True (all models shown for all categories)<br>- Anthropic: True (all models shown for all categories)<br>- Fireworks: False (models filtered by capability) |

---

## Smoke Test Checklist

Quick validation for every build:

- [ ] `/models` opens category selector
- [ ] Can select Normal model and it saves
- [ ] Switching provider changes API endpoint
- [ ] Status line shows current model name
- [ ] Sending a prompt after model switch uses new model
- [ ] Finish shows correct summary
- [ ] ESC cancels without changes
- [ ] Missing API key shows helpful error
- [ ] Fireworks model IDs normalized on load
