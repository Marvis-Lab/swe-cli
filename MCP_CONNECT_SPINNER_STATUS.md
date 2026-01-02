# MCP Connect Spinner Fix - Status Summary

## Original Request
Make `/mcp connect` display a spinner animation during connection, similar to how regular tool calls display.

## Issues Found & Fixed

### 1. Routing Issue (FIXED)
**Problem:** `/mcp connect` was falling through to REPL's text-based handler instead of the Textual UI controller.

**Fix:** Added routing in `runner.py`:
```python
# Line 797-800
if lowered.startswith("/mcp connect "):
    self._handle_mcp_connect_command(command)
    return
```

### 2. Event Loop Race Condition (FIXED)
**Problem:** `_loop_started.set()` was called before `run_forever()`, causing "no running event loop" error.

**Fix:** In `manager.py` line 175:
```python
self._event_loop.call_soon(self._loop_started.set)  # Signal AFTER loop starts
```

### 3. Wrong Thread Context (FIXED)
**Problem:** `handle_connect` is called from runner's processor thread (background), but UI methods like `start_tool_execution()` must run on Textual's main thread.

**Fix:** Use `call_from_thread` for all UI calls:
```python
def start_spinner():
    self.app.conversation.add_tool_call(display)
    self.app.conversation.start_tool_execution()

self.app.call_from_thread(start_spinner)
```

## Current State - BROKEN

The spinner is NOT showing. Current output:
```
⏺ MCP (github) (0s)
  ⎿  Connection failed
```

### What Should Happen
1. `⠋ MCP (github) (0s)` - spinner animating
2. `⠙ MCP (github) (1s)` - continues...
3. `⏺ MCP (github) (2s)` - final state
4. `⎿  Connected (X tools)` or `⎿  Connection failed`

### Suspected Issues

1. **Timer not firing:** `start_tool_execution()` schedules a timer via `set_timer(0.12, callback)`. The timer callback renders spinner frames. But the timer might not be firing.

2. **call_from_thread blocking:** `call_from_thread` blocks until callback completes. The sequence is:
   - `call_from_thread(start_spinner)` - blocks, returns
   - `connect_sync()` - runs connection
   - `call_from_thread(finalize)` - blocks, returns

   The timer is scheduled inside `start_spinner`, but it needs Textual's event loop to fire. If we're blocking the processor thread, does that affect timer execution?

3. **Minimum time not helping:** Added 500ms minimum display time, but spinner still doesn't show.

## Files Modified

| File | Changes |
|------|---------|
| `swecli/ui_textual/runner.py` | Added `/mcp connect` routing (lines 797-800, 1004-1013) |
| `swecli/ui_textual/controllers/mcp_command_controller.py` | Rewrote `handle_connect()` to use `call_from_thread` |
| `swecli/core/context_engineering/mcp/manager.py` | Fixed event loop signal timing (line 175) |

## Current Code State

### mcp_command_controller.py handle_connect():
```python
def handle_connect(self, command: str) -> None:
    # ... validation ...

    display = Text(f"MCP ({server_name})")

    def start_spinner():
        self.app.conversation.add_tool_call(display)
        self.app.conversation.start_tool_execution()

    self.app.call_from_thread(start_spinner)

    # Run connection
    start_time = time.monotonic()
    try:
        success = mcp_manager.connect_sync(server_name)
        error_msg = None
    except Exception as e:
        success = False
        error_msg = f"{type(e).__name__}: {e}"

    # Ensure spinner visible for at least 500ms
    elapsed = time.monotonic() - start_time
    if elapsed < 0.5:
        time.sleep(0.5 - elapsed)

    # Update UI
    def finalize():
        self.app.conversation.stop_tool_execution()
        if error_msg:
            self.app.conversation.add_tool_result(error_msg)
        elif success:
            tools = mcp_manager.get_server_tools(server_name)
            self.app.conversation.add_tool_result(f"Connected ({len(tools)} tools)")
        else:
            self.app.conversation.add_tool_result("Connection failed")

    self.app.call_from_thread(finalize)
```

## Next Steps to Investigate

1. **Check if timer is scheduled:** Add debug logging in `start_tool_execution()` to verify timer is created.

2. **Check if timer fires:** Add logging in `_animate_tool_spinner()` callback.

3. **Compare with working spinner:** Trace how regular tool calls (Read, Bash, etc.) trigger spinners via `TextualUICallback.on_tool_call()` - that flow works.

4. **Verify threading model:** The processor thread calls `handle_connect`. When we `call_from_thread(start_spinner)`:
   - Does `start_spinner` run on Textual's main thread?
   - Does the timer get scheduled on Textual's event loop?
   - Does the timer callback run while we're blocked in `connect_sync`?

## Reference: Working Spinner Flow

For regular tool calls, the working flow is:
1. `TextualUICallback.on_tool_call()` is called from message processor
2. It calls `self._app.call_from_thread(self._conversation.add_tool_call, ...)`
3. It calls `self._app.call_from_thread(self._conversation.start_tool_execution)`
4. Tool executes (takes time)
5. `on_tool_result()` calls `self._app.call_from_thread(self._conversation.stop_tool_execution)`

This is the same pattern we're using, but it's not working for MCP connect.
