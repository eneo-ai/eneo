from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import (
    TYPE_CHECKING,
    Literal,
    NoReturn,
    Protocol,
    TypeGuard,
    TypeVar,
    get_args,
)
from uuid import UUID

from eneo.authentication.access_denial_code import AccessDenialCode
from eneo.flows.domain.flow import FlowRun, FlowRunStatusSnapshot
from eneo.flows.domain.flow_run_exceptions import FlowRunNotFoundError
from eneo.flows.domain.rag_evidence import PassageDisclosure
from eneo.flows.flow_access_policy import (
    FlowApiAction,
    user_can_perform_flow_action,
)
from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.flows.flow_api_exceptions import FlowUnauthorizedException
from eneo.flows.flow_evidence_policy import (
    CLASSIFIED_SECURITY_LEVEL,
    EvidenceCapabilityLevel,
    FlowEvidencePolicy,
    FlowHistoryAccessContext,
    resolve_flow_evidence_policy,
    resolve_service_key_evidence_capability,
)
from eneo.flows.infrastructure.flow_repo import FlowRepository
from eneo.flows.infrastructure.flow_run_repo import FlowRunRepository
from eneo.flows.principal import FlowPrincipal
from eneo.main.exceptions import NotFoundException
from eneo.roles.permissions import Permission
from eneo.users.user import UserInDB

if TYPE_CHECKING:
    from eneo.actors.actors.space_actor import SpaceAccessFacts, SpaceActor
    from eneo.spaces.space import Space


FlowRunAccessKind = Literal[
    "status",
    "cancel",
    "content",
    "artifact",
    "evidence_view",
    "evidence_export_redacted",
    "evidence_export_raw",
]
_FLOW_RUN_ACCESS_KINDS = set(get_args(FlowRunAccessKind))
# History reads never mutate; any mutation needs a live flow.
_MUTATING_ACCESS_KINDS: frozenset[FlowRunAccessKind] = frozenset({"cancel"})
FlowRunSpaceRole = Literal["admin", "owner"]
_EVIDENCE_ACCESS_KINDS: tuple[FlowRunAccessKind, ...] = (
    "evidence_view",
    "evidence_export_redacted",
    "evidence_export_raw",
)
_Loaded = TypeVar("_Loaded")


@dataclass(frozen=True, slots=True)
class FlowRunEvidenceAccess:
    """What one caller may do with one run's evidence, as the evidence routes
    would answer them: each refusal is the code those routes would refuse
    with, and None where they would let the caller through."""

    view_refusal: str | None
    redacted_export_refusal: str | None
    raw_export_refusal: str | None


class FlowRunSpaceServiceProtocol(Protocol):
    async def get_space_access_facts(self, id: UUID) -> "SpaceAccessFacts": ...

    async def get_transcription_space(self, actor: "SpaceActor") -> "Space": ...


class FlowRunActorManagerProtocol(Protocol):
    def get_space_actor(self, space: "SpaceAccessFacts") -> "SpaceActor": ...


class FlowRunAccessPolicy:
    """Who may do what with a flow's runs, asked by the flow gate and the run
    services of one request. Its memo is valid only while no route changes
    membership, publication, sensitivity or the evidence-export setting before
    asking again."""

    def __init__(
        self,
        *,
        user: UserInDB,
        flow_repo: FlowRepository,
        flow_run_repo: FlowRunRepository,
        space_service: FlowRunSpaceServiceProtocol | None = None,
        actor_manager: FlowRunActorManagerProtocol | None = None,
    ):
        self.user = user
        self.flow_repo = flow_repo
        self.flow_run_repo = flow_run_repo
        self.space_service = space_service
        self.actor_manager = actor_manager
        # One authorization pass asks the same questions about the same flow
        # several times. The policy is request-scoped, so each lookup is
        # answered once instead of once per question.
        self._space_access_by_flow_id: dict[UUID, tuple["SpaceActor | None", int]] = {}
        self._flow_context_by_mode: dict[
            tuple[UUID, bool], FlowHistoryAccessContext
        ] = {}

    def is_human_tenant_admin(self) -> bool:
        return (
            not self.principal().is_service_key
            and Permission.ADMIN in self.user.permissions
        )

    def principal(self) -> FlowPrincipal:
        return FlowPrincipal.from_user(self.user)

    async def load_run(
        self,
        *,
        run_id: UUID,
        flow_id: UUID | None = None,
        access_kind: FlowRunAccessKind = "status",
        history: bool = False,
    ) -> FlowRun:
        return await self._load_accessible_run(
            lambda: self.flow_run_repo.get(
                run_id=run_id, tenant_id=self.user.tenant_id, flow_id=flow_id
            ),
            run_of=lambda run: run,
            access_kind=access_kind,
            history=history,
        )

    async def load_run_status(
        self,
        *,
        run_id: UUID,
        flow_id: UUID | None = None,
        access_kind: FlowRunAccessKind = "status",
        history: bool = False,
    ) -> FlowRunStatusSnapshot:
        return await self._load_accessible_run(
            lambda: self.flow_run_repo.get_status(
                run_id=run_id, tenant_id=self.user.tenant_id, flow_id=flow_id
            ),
            run_of=lambda run: run,
            access_kind=access_kind,
            history=history,
        )

    async def load_run_status_with_speaker_labels(
        self,
        *,
        run_id: UUID,
        flow_id: UUID | None = None,
        access_kind: FlowRunAccessKind,
        history: bool = False,
    ) -> tuple[FlowRunStatusSnapshot, bool | None]:
        """The run's status and speaker-label setting, for a caller who may
        read the run as ``access_kind``; the rest of its content stays unread."""
        return await self._load_accessible_run(
            lambda: self.flow_run_repo.get_status_with_speaker_labels(
                run_id=run_id, tenant_id=self.user.tenant_id, flow_id=flow_id
            ),
            run_of=lambda loaded: loaded[0],
            access_kind=access_kind,
            history=history,
        )

    async def _load_accessible_run(
        self,
        load: Callable[[], Awaitable[_Loaded]],
        *,
        run_of: Callable[[_Loaded], FlowRunStatusSnapshot],
        access_kind: FlowRunAccessKind,
        history: bool,
    ) -> _Loaded:
        """What ``load`` read of one run, once the caller may access the run."""
        try:
            loaded = await load()
        except FlowRunNotFoundError as exc:
            raise NotFoundException("Flow run not found.") from exc
        await self.ensure_can_access_run(
            run_of(loaded), access_kind=access_kind, history=history
        )
        return loaded

    async def load_flow_context(
        self, *, flow_id: UUID, history: bool = False
    ) -> FlowHistoryAccessContext:
        """The flow's authorization row; a retired flow only in history mode."""
        key = (flow_id, history)
        cached = self._flow_context_by_mode.get(key)
        if cached is None:
            cached = await self.flow_repo.get_history_access_context(
                flow_id=flow_id,
                tenant_id=self.user.tenant_id,
                include_retired=history,
            )
            self._flow_context_by_mode[key] = cached
        return cached

    async def load_space_access(
        self, *, flow_id: UUID, history: bool = False
    ) -> tuple["SpaceActor | None", int]:
        if self.space_service is None or self.actor_manager is None:
            return None, 0
        # Resolved before the cache so a live read of a retired flow is refused
        # even after a history read cached its space.
        context = await self.load_flow_context(flow_id=flow_id, history=history)
        cached_access = self._space_access_by_flow_id.get(flow_id)
        if cached_access is not None:
            return cached_access
        # The caller's own facts decide the role; the flow context already
        # carries the space's classification, so no space is loaded.
        facts = await self.space_service.get_space_access_facts(context.space_id)
        actor = self.actor_manager.get_space_actor(facts)
        access = (actor, context.classification_level)
        self._space_access_by_flow_id[flow_id] = access
        return access

    async def space_role(
        self, *, flow_id: UUID, history: bool = False
    ) -> FlowRunSpaceRole | None:
        actor, _classification_level = await self.load_space_access(
            flow_id=flow_id, history=history
        )
        return self._space_role_from_actor(actor)

    @staticmethod
    def _space_role_from_actor(actor: "SpaceActor | None") -> FlowRunSpaceRole | None:
        if actor is None:
            return None
        current_role = actor.get_current_role()
        role_value = getattr(current_role, "value", current_role)
        if role_value in {"admin", "owner"}:
            return "admin" if role_value == "admin" else "owner"
        return None

    async def can_list_all_runs_in_flow(
        self, *, flow_id: UUID, history: bool = False
    ) -> bool:
        return await self.space_role(flow_id=flow_id, history=history) in {
            "admin",
            "owner",
        }

    async def ensure_can_access_run(
        self,
        run: FlowRunStatusSnapshot,
        *,
        access_kind: FlowRunAccessKind,
        history: bool = False,
    ) -> None:
        await self._ensure_caller_may_access_run(
            run, access_kind=access_kind, history=history
        )
        if access_kind in {"evidence_export_redacted", "evidence_export_raw"}:
            # Last, so a caller the rules above refuse learns nothing about the
            # flow's setting. It binds everyone they let through, tenant admins
            # and service keys included.
            await self._ensure_flow_allows_evidence_export(
                flow_id=run.flow_id, history=history
            )

    async def _ensure_caller_may_access_run(
        self,
        run: FlowRunStatusSnapshot,
        *,
        access_kind: FlowRunAccessKind,
        history: bool,
    ) -> None:
        if not self._is_known_access_kind(access_kind):
            self.deny_run_access(auth_layer="flow_run_access_kind")
        if history and access_kind in _MUTATING_ACCESS_KINDS:
            # A mutation of a retired flow's run answers like the retired flow:
            # not found, whatever the caller asked for.
            raise NotFoundException("Flow not found.")
        if run.tenant_id != self.user.tenant_id:
            self.deny_run_access(auth_layer="tenant_isolation")
        principal = self.principal()
        if principal.is_service_key:
            if not principal.matches_run(run):
                self.deny_run_access(auth_layer="flow_run_principal")
            active_api_key = self.user.active_api_key
            if active_api_key is None:
                self.deny_run_access(auth_layer="flow_run_principal")
            capability = resolve_service_key_evidence_capability(
                active_api_key.resource_permissions
            )
            policy = self._evidence_policy()
            _actor, classification_level = await self.load_space_access(
                flow_id=run.flow_id, history=history
            )
            if access_kind in {"status", "cancel", "content", "artifact"}:
                return
            if access_kind == "evidence_view":
                if capability >= EvidenceCapabilityLevel.VIEW:
                    return
                self.deny_evidence_access(
                    auth_layer="flow_run_principal",
                    message="Service principal is not authorized to view evidence for this run.",
                )
            if access_kind == "evidence_export_redacted":
                if capability >= EvidenceCapabilityLevel.REDACTED_EXPORT:
                    return
                self.deny_evidence_access(
                    auth_layer="flow_run_principal",
                    message="Service principal is not authorized to export evidence for this run.",
                )
            if access_kind == "evidence_export_raw":
                if capability < EvidenceCapabilityLevel.RAW_EXPORT:
                    self.deny_evidence_access(
                        auth_layer="flow_run_principal",
                        message="Service principal is not authorized to export raw evidence for this run.",
                    )
                if (
                    not policy.allow_service_key_raw_export_class3
                    and await self._evidence_held_to_classification_3(
                        run, space_level=classification_level
                    )
                ):
                    self.deny_raw_export_access(
                        auth_layer="flow_run_principal",
                        message="Raw evidence export is not allowed for service principals when the run's evidence is held to classification 3.",
                    )
                return
            self.deny_run_access(auth_layer="flow_run_principal")
        if self.is_human_tenant_admin():
            return

        actor, classification_level = await self.load_space_access(
            flow_id=run.flow_id, history=history
        )
        role_value = self._space_role_from_actor(actor)
        policy = self._evidence_policy()

        if role_value in {"admin", "owner"}:
            if access_kind in {
                "status",
                "cancel",
                "content",
                "artifact",
                "evidence_view",
                "evidence_export_redacted",
            }:
                return
            if access_kind == "evidence_export_raw":
                if role_value == "owner":
                    return
                if (
                    policy.allow_space_admin_raw_export_class3
                    or not await self._evidence_held_to_classification_3(
                        run, space_level=classification_level
                    )
                ):
                    return
                self.deny_raw_export_access(
                    auth_layer="space_membership",
                    message="Raw evidence export is not allowed for space admins when the run's evidence is held to classification 3.",
                )

        if principal.matches_run(run):
            if access_kind in {"status", "cancel", "content", "artifact"}:
                return
            if access_kind in {"evidence_view", "evidence_export_redacted"}:
                if user_can_perform_flow_action(self.user, FlowApiAction.TRACE_VIEW):
                    return
                raise FlowUnauthorizedException(
                    "You do not have permission to view flow trace.",
                    code=AccessDenialCode.INSUFFICIENT_TENANT_PERMISSION,
                    context={"auth_layer": "tenant_role"},
                )
            if access_kind == "evidence_export_raw":
                if not user_can_perform_flow_action(
                    self.user, FlowApiAction.TRACE_VIEW
                ):
                    raise FlowUnauthorizedException(
                        "You do not have permission to view flow trace.",
                        code=AccessDenialCode.INSUFFICIENT_TENANT_PERMISSION,
                        context={"auth_layer": "tenant_role"},
                    )
                if (
                    policy.allow_run_owner_raw_export_class3
                    or not await self._evidence_held_to_classification_3(
                        run, space_level=classification_level
                    )
                ):
                    return
                self.deny_raw_export_access(
                    auth_layer="flow_run_owner",
                    message="Raw evidence export is not allowed for this run: its evidence is held to classification 3.",
                )

        self.deny_run_access(auth_layer="flow_run_owner")

    async def evidence_access_for_run(
        self, run: FlowRunStatusSnapshot, *, history: bool = False
    ) -> FlowRunEvidenceAccess:
        """Asks this policy each evidence question the evidence routes ask,
        so a client can offer exactly what they would allow."""
        refusals: list[str | None] = []
        for access_kind in _EVIDENCE_ACCESS_KINDS:
            try:
                await self.ensure_can_access_run(
                    run, access_kind=access_kind, history=history
                )
            except FlowUnauthorizedException as exc:
                refusals.append(exc.code.value)
            else:
                refusals.append(None)
        view, redacted_export, raw_export = refusals
        return FlowRunEvidenceAccess(
            view_refusal=view,
            redacted_export_refusal=redacted_export,
            raw_export_refusal=raw_export,
        )

    async def passage_disclosure_for_run(
        self,
        run: FlowRunStatusSnapshot,
        *,
        access_kind: FlowRunAccessKind,
        history: bool = False,
    ) -> PassageDisclosure:
        """Whether this reader may see verbatim retrieved passage text.

        Reuses the sensitivity distinctions this policy already owns rather than
        introducing a second classification concept. Source identity, titles and
        counts are never gated here: withholding *which* sources a step
        retrieved would defeat the transparency the evidence exists to provide.
        """
        # Sensitivity and classification are properties of the data, not of the
        # reader, so they are read directly rather than through the space
        # service, whose membership check a tenant admin is not subject to.
        # A tenant admin bypasses authorization, never the data's classification.
        context = await self.load_flow_context(flow_id=run.flow_id, history=history)
        # A raw export has already cleared the flow's export switch and the
        # classification gates in `ensure_can_access_run`, so reaching here
        # means the reader is entitled to the underlying content.
        if access_kind == "evidence_export_raw":
            return "text_disclosed"
        if context.sensitive:
            return "text_withheld_sensitive_flow"
        if await self._evidence_held_to_classification_3(
            run, space_level=context.classification_level
        ):
            return "text_withheld_classified_space"
        return "text_disclosed"

    async def _evidence_held_to_classification_3(
        self, run: FlowRunStatusSnapshot, *, space_level: int
    ) -> bool:
        """Whether a reader of the run's evidence must clear classification 3.

        The level to clear is the higher of the space's level now and the level
        the run recorded for its evidence (`evidence_classification_level`): a
        space classified lower after the run does not lower it. A run that
        produced evidence without a recorded level could hold evidence of any
        level, so it is held to classification 3; a run that produced none
        answers to its space alone.
        """
        recorded_level = run.evidence_classification_level
        if recorded_level is not None:
            return max(space_level, recorded_level) >= CLASSIFIED_SECURITY_LEVEL
        if space_level >= CLASSIFIED_SECURITY_LEVEL:
            return True
        return await self.flow_run_repo.has_step_attempts(
            run_id=run.id, tenant_id=run.tenant_id
        )

    async def _ensure_flow_allows_evidence_export(
        self, *, flow_id: UUID, history: bool
    ) -> None:
        # The flow's current setting decides for all of its runs, old ones and a
        # retired flow's included. The access context resolves it fail-closed:
        # metadata that cannot be parsed does not allow export.
        context = await self.load_flow_context(flow_id=flow_id, history=history)
        if context.evidence_export_allowed is not True:
            self.deny_evidence_export_disabled(auth_layer="flow_evidence_policy")

    def _evidence_policy(self) -> FlowEvidencePolicy:
        tenant = getattr(self.user, "tenant", None)
        tenant_flow_settings = getattr(tenant, "flow_settings", None)
        return resolve_flow_evidence_policy(tenant_flow_settings)

    @staticmethod
    def _is_known_access_kind(access_kind: object) -> TypeGuard[FlowRunAccessKind]:
        return isinstance(access_kind, str) and access_kind in _FLOW_RUN_ACCESS_KINDS

    @staticmethod
    def deny_run_access(*, auth_layer: str) -> NoReturn:
        raise FlowUnauthorizedException(
            "You do not have access to this flow run.",
            code=FlowApiErrorCode.RUN_ACCESS_DENIED,
            context={"auth_layer": auth_layer},
        )

    @staticmethod
    def deny_evidence_access(*, auth_layer: str, message: str) -> NoReturn:
        raise FlowUnauthorizedException(
            message,
            code=FlowApiErrorCode.RUN_EVIDENCE_FORBIDDEN,
            context={"auth_layer": auth_layer},
        )

    @staticmethod
    def deny_evidence_export_disabled(*, auth_layer: str) -> NoReturn:
        raise FlowUnauthorizedException(
            "Evidence export is turned off for this flow.",
            code=FlowApiErrorCode.RUN_EVIDENCE_EXPORT_DISABLED,
            context={"auth_layer": auth_layer},
        )

    @staticmethod
    def deny_raw_export_access(*, auth_layer: str, message: str) -> NoReturn:
        raise FlowUnauthorizedException(
            message,
            code=FlowApiErrorCode.RUN_EVIDENCE_RAW_EXPORT_FORBIDDEN,
            context={"auth_layer": auth_layer},
        )
