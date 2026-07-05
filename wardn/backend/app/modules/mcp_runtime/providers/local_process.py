from collections.abc import Callable
from dataclasses import dataclass
from threading import Event, Lock
from typing import Any

from app.modules.mcp_gateway import client
from app.modules.mcp_registry.models import MCPServerInstallation
from app.modules.mcp_runtime.models import MCPRuntimeSession
from app.modules.mcp_runtime.provider import (
    RUNTIME_HEALTH_NOT_READY,
    RUNTIME_HEALTH_READY,
    RUNTIME_HEALTH_STOPPED,
    RUNTIME_KIND_PACKAGE,
    RUNTIME_PROVIDER_LOCAL,
    RUNTIME_TRANSPORT_STDIO,
    PackageRuntimeSpec,
    RuntimeHealth,
    RuntimeSpec,
    base_runtime_spec,
    package_runtime,
    runtime_kind,
)

TERMINAL_RUNTIME_STATUSES = {"stopped", "failed", "expired"}
LOCAL_TRANSPORT_STDIO = "stdio"


@dataclass
class ManagedStdioSession:
    session: client.MCPStdioSession
    next_request_id: int = 2


class LocalProcessRuntimeProvider:
    name = RUNTIME_PROVIDER_LOCAL

    def __init__(self) -> None:
        self._stdio_sessions: dict[str, ManagedStdioSession] = {}
        self._stdio_lock = Lock()

    def supports(self, installation: MCPServerInstallation) -> bool:
        return runtime_kind(installation) == RUNTIME_KIND_PACKAGE

    def runtime_spec(self, installation: MCPServerInstallation) -> RuntimeSpec:
        runtime = package_runtime(installation)
        return base_runtime_spec(
            installation,
            provider_name=self.name,
            transport=RUNTIME_TRANSPORT_STDIO,
            command=runtime.command,
            args=runtime.args,
            cwd=runtime.cwd,
        )

    def list_tools(
        self,
        installation: MCPServerInstallation,
        *,
        runtime_session: MCPRuntimeSession | None = None,
    ) -> list[dict[str, Any]]:
        runtime = package_runtime(installation)
        return client.list_stdio_tools(
            runtime.command,
            runtime.args,
            cwd=runtime.cwd,
            environment=runtime.environment,
        )

    def call_tool(
        self,
        installation: MCPServerInstallation,
        *,
        tool_name: str,
        arguments: dict[str, Any],
        cancel_event: Event | None = None,
        cancel_reason: str = "Tool call cancelled.",
        request_meta: dict[str, Any] | None = None,
        progress_callback: client.MCPProgressCallback | None = None,
        runtime_session: MCPRuntimeSession | None = None,
    ) -> dict[str, Any]:
        runtime = package_runtime(installation)
        return self._with_stdio_session(
            installation,
            runtime=runtime,
            action=lambda managed: self._call_stdio_tool(
                managed,
                tool_name=tool_name,
                arguments=arguments,
                cancel_event=cancel_event,
                cancel_reason=cancel_reason,
                request_meta=request_meta,
                progress_callback=progress_callback,
            ),
        )

    def ensure_runtime(
        self,
        installation: MCPServerInstallation,
        *,
        runtime_session: MCPRuntimeSession | None = None,
        wait_ready: bool = True,
    ) -> RuntimeHealth:
        return RuntimeHealth(
            status=RUNTIME_HEALTH_NOT_READY,
            healthy=False,
            ready=False,
            message="Local stdio runtime warmup is not supported without a tool call.",
        )

    def stop_runtime(
        self,
        runtime_session: MCPRuntimeSession,
        *,
        delete_resources: bool = False,
    ) -> None:
        self._drop_stdio_session(runtime_session.config_fingerprint)

    def health(self, runtime_session: MCPRuntimeSession) -> RuntimeHealth:
        if runtime_session.status in TERMINAL_RUNTIME_STATUSES:
            return RuntimeHealth(
                status=RUNTIME_HEALTH_STOPPED,
                healthy=False,
                ready=False,
                message=f"Runtime session is {runtime_session.status}.",
            )

        stdio_health = self._stdio_session_health(runtime_session)
        if stdio_health is not None:
            return stdio_health

        return RuntimeHealth(
            status=RUNTIME_HEALTH_NOT_READY,
            healthy=False,
            ready=False,
            message="Local runtime process is not present in this backend process.",
        )

    def stop_all(self) -> None:
        with self._stdio_lock:
            stdio_keys = list(self._stdio_sessions)
        for key in stdio_keys:
            self._drop_stdio_session(key)

    def _stdio_session_key(
        self,
        installation: MCPServerInstallation,
        *,
        runtime: PackageRuntimeSpec,
    ) -> str:
        return base_runtime_spec(
            installation,
            provider_name=self.name,
            transport=RUNTIME_TRANSPORT_STDIO,
            command=runtime.command,
            args=runtime.args,
            cwd=runtime.cwd,
        ).fingerprint()

    def _with_stdio_session(
        self,
        installation: MCPServerInstallation,
        *,
        runtime: PackageRuntimeSpec,
        action: Callable[[ManagedStdioSession], Any],
    ) -> Any:
        key = self._stdio_session_key(installation, runtime=runtime)
        with self._stdio_lock:
            managed = self._stdio_sessions.get(key)
            if managed is None or managed.session.process.poll() is not None:
                managed = ManagedStdioSession(
                    client.open_stdio_session(
                        runtime.command,
                        runtime.args,
                        cwd=runtime.cwd,
                        environment=runtime.environment,
                    )
                )
                self._stdio_sessions[key] = managed
            try:
                return action(managed)
            except Exception:
                self._drop_stdio_session(key)
                raise

    def _drop_stdio_session(self, key: str) -> None:
        managed = self._stdio_sessions.pop(key, None)
        if managed is not None:
            client.close_stdio_session(managed.session)

    def _stdio_session_health(
        self,
        runtime_session: MCPRuntimeSession,
    ) -> RuntimeHealth | None:
        with self._stdio_lock:
            managed = self._stdio_sessions.get(runtime_session.config_fingerprint)
        if managed is None:
            return None

        return_code = managed.session.process.poll()
        details = {
            "transport": RUNTIME_TRANSPORT_STDIO,
            "processId": managed.session.process.pid,
            "returnCode": return_code,
        }
        if return_code is not None:
            return RuntimeHealth(
                status=RUNTIME_HEALTH_NOT_READY,
                healthy=False,
                ready=False,
                message="Local stdio runtime process has exited.",
                details=details,
            )
        return RuntimeHealth(
            status=RUNTIME_HEALTH_READY,
            healthy=True,
            ready=True,
            message="Local stdio runtime process is running.",
            details=details,
        )

    def _list_stdio_tools(self, managed: ManagedStdioSession) -> list[dict[str, Any]]:
        tools, next_request_id = client.list_stdio_session_tools(
            managed.session,
            request_id_start=managed.next_request_id,
        )
        managed.next_request_id = next_request_id
        return tools

    def _call_stdio_tool(
        self,
        managed: ManagedStdioSession,
        *,
        tool_name: str,
        arguments: dict[str, Any],
        cancel_event: Event | None = None,
        cancel_reason: str = "Tool call cancelled.",
        request_meta: dict[str, Any] | None = None,
        progress_callback: client.MCPProgressCallback | None = None,
    ) -> dict[str, Any]:
        request_id = managed.next_request_id
        managed.next_request_id += 1
        return client.call_stdio_session_tool(
            managed.session,
            request_id=request_id,
            tool_name=tool_name,
            arguments=arguments,
            cancel_event=cancel_event,
            cancel_reason=cancel_reason,
            request_meta=request_meta,
            progress_callback=progress_callback,
        )
