"""Qt-free, security-first automation core for Aashi.

The package exposes service classes and data models without starting Qt,
opening a microphone, launching a process, or capturing a screen at import
time.  Platform integrations are injected at construction or invoked only by
an explicit method call.
"""

from __future__ import annotations

from .files import FileService, FileSummary
from .launcher import (
    DEFAULT_APPLICATIONS,
    SUPPORTED_APPLICATIONS,
    ApplicationLauncher,
    ApplicationSpec,
)
from .memory import MemoryFact, MemoryStore, MemoryValidationError, SensitiveFactError
from .models import Action, ActionKind, ActionResult, ActionRisk, ActionStatus
from .permissions import (
    AuthorizationError,
    PathTraversalError,
    PermissionDecision,
    PermissionService,
)
from .proactive import (
    CandidateKind,
    ContextEvidence,
    ProactiveCandidate,
    ProactiveContext,
    ProactiveDecision,
    ProactiveDecisionEngine,
    ProactivePolicy,
    RecommendationCandidate,
    WarningCandidate,
)
from .screen import QScreenBackend, ScreenCapture, ScreenCaptureBackend, ScreenCaptureService, ScreenInfo
from .runtime import AssistantRuntime, RequestOutcome, TaskState, default_authorized_roots, platform_open_folder
from .foreground import ForegroundContext, ForegroundProvider, NullForegroundProvider, WindowsForegroundProvider
from .monitoring import AnalysisKind, MonitoringObservation, MonitoringPolicy, ScreenAnalysis, ScreenMonitor
from .tasks import (
    ProjectTestRunner,
    TaskExecutionResult,
    TaskExecutor,
    TaskExecutionState,
    TaskPlan,
    TaskStep,
    TestRunReport,
)
from .speech import (
    LocalSpeechAdapter,
    NullSpeechAdapter,
    SpeechAdapter,
    SpeechEvent,
    SpeechInput,
    SpeechOperation,
    SpeechOutput,
    SpeechService,
    SpeechState,
    SpeechStatus,
)

__all__ = [
    "Action",
    "ActionKind",
    "ActionResult",
    "ActionRisk",
    "ActionStatus",
    "AssistantRuntime",
    "AnalysisKind",
    "ApplicationLauncher",
    "ApplicationSpec",
    "AuthorizationError",
    "CandidateKind",
    "ContextEvidence",
    "DEFAULT_APPLICATIONS",
    "FileService",
    "FileSummary",
    "ForegroundContext",
    "ForegroundProvider",
    "LocalSpeechAdapter",
    "MemoryFact",
    "MemoryStore",
    "MemoryValidationError",
    "NullSpeechAdapter",
    "NullForegroundProvider",
    "PathTraversalError",
    "PermissionDecision",
    "PermissionService",
    "ProactiveCandidate",
    "ProactiveContext",
    "ProactiveDecision",
    "ProactiveDecisionEngine",
    "ProactivePolicy",
    "QScreenBackend",
    "RecommendationCandidate",
    "ScreenCapture",
    "ScreenCaptureBackend",
    "ScreenCaptureService",
    "ScreenInfo",
    "ScreenAnalysis",
    "ScreenMonitor",
    "MonitoringObservation",
    "MonitoringPolicy",
    "RequestOutcome",
    "SensitiveFactError",
    "SpeechEvent",
    "SpeechAdapter",
    "SpeechInput",
    "SpeechOperation",
    "SpeechOutput",
    "SpeechService",
    "SpeechState",
    "SpeechStatus",
    "SUPPORTED_APPLICATIONS",
    "TaskState",
    "TaskExecutionState",
    "TaskExecutionResult",
    "TaskExecutor",
    "TaskPlan",
    "TaskStep",
    "ProjectTestRunner",
    "TestRunReport",
    "WarningCandidate",
    "WindowsForegroundProvider",
    "default_authorized_roots",
    "platform_open_folder",
]
